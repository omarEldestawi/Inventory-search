"""
Local Arabic OCR Engine (v2.6) for Egyptian Pharma Procurement.

Wraps RapidOCR with local Arabic PP-OCR ONNX recognition weights (assets/models/rec.onnx
and assets/models/dict.txt) as the primary offline engine, with optional Windows.Media.Ocr
(ar-SA) native fast-path when running on a compatible Windows host.

Key Features:
- 100% offline execution; zero external or cloud API calls.
- Un-reversal of Visual RTL Arabic sequences emitted by PaddleOCR recognition models.
- Graceful degradation when weights or optional secondary engines are missing.
- Returns standardized bounding boxes [x0, y0, x1, y2], confidence scores, raw text,
  and normalized logical text.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    RapidOCR = None

try:
    from .normalizer import unreverse_arabic_text, EASTERN_ARABIC_DIGITS
except ImportError:
    try:
        from normalizer import unreverse_arabic_text, EASTERN_ARABIC_DIGITS
    except ImportError:
        def unreverse_arabic_text(t: str, force_reverse: Optional[bool] = None) -> str:
            return t[::-1] if any('\u0600' <= c <= '\u06ff' for c in t) else t
        EASTERN_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

logger = logging.getLogger("ArabicOCREngine")

# Process-wide cached state
_WINDOWS_OCR_AVAILABLE: Optional[bool] = None
_WORKER_PROC: Optional[subprocess.Popen] = None
_WORKER_LOCK = threading.Lock()
_OCR_CACHE: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
_OCR_CACHE_LOCK = threading.Lock()
_MAX_CACHE_ENTRIES = 1200
_GLOBAL_RAPID_ENGINE: Optional[Any] = None
_RAPID_INIT_LOCK = threading.Lock()


def _get_or_create_windows_worker() -> Optional[subprocess.Popen]:
    """Retrieves or creates the persistent Windows OCR PowerShell worker."""
    global _WORKER_PROC
    if os.name != "nt":
        return None

    with _WORKER_LOCK:
        if _WORKER_PROC is not None:
            if _WORKER_PROC.poll() is None:
                return _WORKER_PROC
            _WORKER_PROC = None

        ps_init = r'''
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[void][System.Reflection.Assembly]::LoadWithPartialName('System.Runtime.WindowsRuntime')
$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1

function Invoke-WinRt($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    [void]$netTask.Wait(-1)
    return ,$netTask.Result
}

[void][Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]

$lang = [Windows.Globalization.Language]::new('ar-SA')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)

function Recognize-File($path) {
    if (-not (Test-Path $path)) {
        [Console]::Out.WriteLine('[]')
        [Console]::Out.Flush()
        return
    }
    try {
        $file = (Invoke-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile]))[-1]
        $stream = (Invoke-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream]))[-1]
        $decoder = (Invoke-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder]))[-1]
        $bitmap = (Invoke-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap]))[-1]
        $result = (Invoke-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult]))[-1]

        $lines = @()
        foreach ($l in $result.Lines) {
            $words = @()
            foreach ($w in $l.Words) {
                $words += @{
                    text = $w.Text
                    x = $w.BoundingRect.X
                    y = $w.BoundingRect.Y
                    w = $w.BoundingRect.Width
                    h = $w.BoundingRect.Height
                }
            }
            $lines += @{
                text = $l.Text
                words = $words
            }
        }
        if ($lines.Count -eq 0) {
            [Console]::Out.WriteLine('[]')
        } else {
            $json = ,$lines | ConvertTo-Json -Depth 4 -Compress
            [Console]::Out.WriteLine($json)
        }
    } catch {
        [Console]::Out.WriteLine('[]')
    }
    [Console]::Out.Flush()
}
[Console]::Out.WriteLine('__READY__'); [Console]::Out.Flush()
'''
        try:
            proc = subprocess.Popen(
                ['powershell.exe', '-NoProfile', '-Command', '-'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
            )
            proc.stdin.write(ps_init + "\n")
            proc.stdin.flush()

            deadline = time.time() + 8.0
            ready = False
            while time.time() < deadline:
                line = proc.stdout.readline()
                if '__READY__' in line:
                    ready = True
                    break
            if not ready:
                try:
                    proc.kill()
                except Exception:
                    pass
                return None

            _WORKER_PROC = proc
            return _WORKER_PROC
        except Exception as exc:
            logger.warning("Failed to spawn persistent Windows OCR worker: %s", exc)
            return None


def _shutdown_windows_worker() -> None:
    """Terminates persistent Windows OCR worker upon process exit."""
    global _WORKER_PROC
    with _WORKER_LOCK:
        if _WORKER_PROC is not None:
            try:
                if _WORKER_PROC.poll() is None:
                    _WORKER_PROC.stdin.write("exit\n")
                    _WORKER_PROC.stdin.flush()
                    _WORKER_PROC.wait(timeout=1.0)
            except Exception:
                try:
                    _WORKER_PROC.kill()
                except Exception:
                    pass
            _WORKER_PROC = None


atexit.register(_shutdown_windows_worker)


class ArabicOCREngine:
    """
    Offline Arabic OCR Engine wrapping RapidOCR with custom Arabic ONNX recognition weights
    and optional secondary Windows Media OCR (ar-SA).
    """

    def __init__(self, models_dir: Optional[str] = None):
        self._models_dir = models_dir or self._discover_models_dir()
        self._rec_model_path: Optional[str] = None
        self._dict_path: Optional[str] = None
        self._rapid_engine: Optional[Any] = None
        self._windows_ocr_available: Optional[bool] = None

        if self._models_dir:
            cand_rec = os.path.join(self._models_dir, "rec.onnx")
            cand_dict = os.path.join(self._models_dir, "dict.txt")
            if os.path.isfile(cand_rec) and os.path.isfile(cand_dict):
                self._rec_model_path = cand_rec
                self._dict_path = cand_dict

        self._init_rapid_ocr()

    @staticmethod
    def _discover_models_dir() -> Optional[str]:
        """Locates the directory containing Arabic OCR weights."""
        base_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        candidates = [
            os.path.join(base_dir, "assets", "models"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "models"),
            os.path.join(os.path.dirname(sys.executable), "assets", "models") if getattr(sys, "frozen", False) else "",
            os.path.join(os.getcwd(), "assets", "models"),
            os.path.join(base_dir, ".agents", "teamwork", "explorer_ocr_v26", "models"),
            os.path.join(os.path.dirname(__file__), "models"),
        ]
        for c in candidates:
            if c and os.path.isfile(os.path.join(c, "rec.onnx")) and os.path.isfile(os.path.join(c, "dict.txt")):
                return c
        return None

    def _init_rapid_ocr(self) -> None:
        """Initializes the RapidOCR instance with local Arabic weights after verifying provenance."""
        if RapidOCR is None or not self._rec_model_path or not self._dict_path:
            self._rapid_engine = None
            return

        if not self._verify_model_dict_pairing():
            logger.warning("RapidOCR weights/dictionary pairing verification failed; disabling RapidOCR.")
            self._rapid_engine = None
            return

        global _GLOBAL_RAPID_ENGINE
        if _GLOBAL_RAPID_ENGINE is not None:
            self._rapid_engine = _GLOBAL_RAPID_ENGINE
            return

        with _RAPID_INIT_LOCK:
            if _GLOBAL_RAPID_ENGINE is not None:
                self._rapid_engine = _GLOBAL_RAPID_ENGINE
                return
            try:
                self._rapid_engine = RapidOCR(
                    rec_model_path=self._rec_model_path,
                    rec_keys_path=self._dict_path,
                )
                _GLOBAL_RAPID_ENGINE = self._rapid_engine
                logger.info("RapidOCR initialized with verified Arabic ONNX weights: %s", self._rec_model_path)
            except Exception as exc:
                logger.warning("Failed to initialize RapidOCR with Arabic weights: %s", exc)
                self._rapid_engine = None

    def _verify_model_dict_pairing(self) -> bool:
        """Verifies authentic model/dictionary pairing and character class ordering."""
        if not self._rec_model_path or not self._dict_path:
            return False
        if not os.path.isfile(self._rec_model_path) or not os.path.isfile(self._dict_path):
            return False

        try:
            with open(self._dict_path, "r", encoding="utf-8") as f:
                dict_lines = [line.strip("\r\n") for line in f if line.strip("\r\n")]

            # Official PaddleOCR arabic_dict.txt contains exactly 161 character classes
            if len(dict_lines) != 161:
                logger.warning("RapidOCR dictionary has non-standard length %d (expected 161)", len(dict_lines))
                return False

            # Verify character ordering: ASCII digits at 12-21 (lines 13-22), Arabic-Indic digits at 152-160 (lines 153-161)
            if dict_lines[12:22] != [str(i) for i in range(10)]:
                logger.warning("RapidOCR dictionary ASCII digit alignment corrupted")
                return False

            expected_arabic_indic = ["١", "٢", "٣", "٤", "٥", "٦", "٧", "٨", "٩"]
            if dict_lines[152:161] != expected_arabic_indic:
                logger.warning("RapidOCR dictionary Arabic-Indic digit alignment corrupted")
                return False

            return True
        except Exception as exc:
            logger.warning("RapidOCR model/dictionary verification error: %s", exc)
            return False

    def is_available(self) -> bool:
        """Returns True if at least one OCR engine (RapidOCR or Windows Media OCR) is operational."""
        return (self._rapid_engine is not None) or self.is_windows_ocr_available()

    def is_windows_ocr_available(self) -> bool:
        """Checks whether Windows.Media.Ocr with ar-SA is available on the current host (cached)."""
        global _WINDOWS_OCR_AVAILABLE
        if _WINDOWS_OCR_AVAILABLE is not None:
            return _WINDOWS_OCR_AVAILABLE

        if self._windows_ocr_available is not None:
            _WINDOWS_OCR_AVAILABLE = self._windows_ocr_available
            return _WINDOWS_OCR_AVAILABLE

        if os.name != "nt":
            self._windows_ocr_available = False
            _WINDOWS_OCR_AVAILABLE = False
            return False

        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null; "
                "[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag }",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            langs = proc.stdout.splitlines()
            self._windows_ocr_available = any("ar" in lang.lower() for lang in langs)
        except Exception:
            self._windows_ocr_available = False

        _WINDOWS_OCR_AVAILABLE = self._windows_ocr_available
        return _WINDOWS_OCR_AVAILABLE

    def unreverse_ocr_text(self, text: str) -> str:
        """
        Un-reverses PaddleOCR's visual left-to-right character emission for Arabic tokens
        into standard logical RTL text, while preserving Latin medication names and digits.
        """
        if not text:
            return ""

        has_arabic = any("\u0600" <= c <= "\u06ff" or "\ufb50" <= c <= "\ufeff" for c in text)
        if not has_arabic:
            return text.strip()

        # PaddleOCR character-sweeps left-to-right. For purely visual Arabic characters,
        # unreverse_arabic_text with force_reverse=True restores logical reading order.
        return unreverse_arabic_text(text, force_reverse=True).strip()

    def extract_text_boxes(
        self, img_np: np.ndarray, engine: str = "primary"
    ) -> List[Dict[str, Any]]:
        """
        Extracts detected text boxes, scores, and un-reversed logical text from an RGB image.

        Args:
            img_np: numpy array of the image (RGB or BGR).
            engine: 'primary' (RapidOCR Arabic ONNX first, then Windows OCR fallback),
                    'rapidocr' (strictly RapidOCR only; no fallback),
                    'windows' / 'secondary' (strictly Windows Media OCR only).

        Returns:
            list of dicts with 'text', 'raw_text', 'confidence', 'bbox', 'engine'.
        """
        if img_np is None or img_np.size == 0:
            return []

        clean_engine = str(engine).lower().strip()

        # Strict Single-Engine Request: RapidOCR only
        if clean_engine in ("rapidocr", "rapid"):
            if self._rapid_engine is not None:
                return self._extract_rapid_ocr(img_np)
            logger.warning("RapidOCR requested but engine is unavailable.")
            return []

        # Strict Single-Engine Request: Windows Media OCR only
        if clean_engine in ("windows", "windows_ocr", "windows_media_ocr", "secondary", "win"):
            if self.is_windows_ocr_available():
                return self._extract_windows_ocr(img_np)
            logger.warning("Windows Media OCR requested but ar-SA recognizer is unavailable.")
            return []

        # 'primary' or 'auto': Native Windows Media OCR if available on Windows,
        # with seamless local RapidOCR fallback when ar-SA pack is absent or on non-Windows.
        if self.is_windows_ocr_available():
            results = self._extract_windows_ocr(img_np)
            if results:
                return results

        if self._rapid_engine is not None:
            results = self._extract_rapid_ocr(img_np)
            if results:
                return results

        logger.warning("No operational Arabic OCR engine available.")
        return []

    def _extract_rapid_ocr(self, img_np: np.ndarray) -> List[Dict[str, Any]]:
        """Executes RapidOCR with Arabic ONNX recognition model."""
        cache_key = ("rapidocr", hashlib.sha256(img_np.tobytes()).hexdigest())
        with _OCR_CACHE_LOCK:
            if cache_key in _OCR_CACHE:
                return [dict(b) for b in _OCR_CACHE[cache_key]]

        try:
            res, _ = self._rapid_engine(img_np)
        except Exception as exc:
            logger.error("RapidOCR execution failed: %s", exc)
            return []

        if not res:
            with _OCR_CACHE_LOCK:
                if len(_OCR_CACHE) >= _MAX_CACHE_ENTRIES:
                    _OCR_CACHE.clear()
                _OCR_CACHE[cache_key] = []
            return []

        boxes: List[Dict[str, Any]] = []
        for box_pts, raw_text, score in res:
            pts = np.array(box_pts, dtype=np.float32)
            x0 = float(np.min(pts[:, 0]))
            x1 = float(np.max(pts[:, 0]))
            y0 = float(np.min(pts[:, 1]))
            y1 = float(np.max(pts[:, 1]))

            logical_text = self.unreverse_ocr_text(raw_text)

            boxes.append(
                {
                    "text": logical_text,
                    "raw_text": raw_text,
                    "confidence": float(score),
                    "bbox": [x0, y0, x1, y1],
                    "engine": "rapidocr",
                }
            )

        with _OCR_CACHE_LOCK:
            if len(_OCR_CACHE) >= _MAX_CACHE_ENTRIES:
                _OCR_CACHE.clear()
            _OCR_CACHE[cache_key] = boxes

        return boxes

    def _extract_windows_ocr(self, img_np: np.ndarray) -> List[Dict[str, Any]]:
        """
        Executes native Windows.Media.Ocr (ar-SA) on an image using persistent worker or one-shot fallback.
        
        Word tokens are emitted in LTR coordinate space; for lines containing Arabic,
        tokens are reordered right-to-left (descending X) to restore exact logical
        phrase sequence without corrupting embedded numbers or Latin terms.
        
        Note: Windows.Media.Ocr does not produce numeric per-box confidence scores.
        Confidence is explicitly represented as None and validated through separate
        structural, geometric, and domain evidence downstream.
        """
        cache_key = ("windows", hashlib.sha256(img_np.tobytes()).hexdigest())
        with _OCR_CACHE_LOCK:
            if cache_key in _OCR_CACHE:
                return [dict(b) for b in _OCR_CACHE[cache_key]]

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_f:
            tmp_path = tmp_f.name

        try:
            # OpenCV write handles BGR; if RGB, convert
            if len(img_np.shape) == 3 and img_np.shape[2] == 3:
                cv2.imwrite(tmp_path, cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR))
            else:
                cv2.imwrite(tmp_path, img_np)

            escaped_path = tmp_path.replace("'", "''")

            stdout = None
            worker = _get_or_create_windows_worker()
            if worker is not None:
                try:
                    with _WORKER_LOCK:
                        worker.stdin.write(f"Recognize-File '{escaped_path}'\n")
                        worker.stdin.flush()
                        out_line = worker.stdout.readline()
                        stdout = out_line.strip()
                except Exception as exc:
                    logger.warning("Windows worker communication failed: %s; falling back to one-shot process", exc)
                    _shutdown_windows_worker()
                    stdout = None

            if stdout is None:
                ps_script = f"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[void][System.Reflection.Assembly]::LoadWithPartialName('System.Runtime.WindowsRuntime')
$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }} | Select-Object -First 1

function Invoke-WinRt($WinRtTask, $ResultType) {{
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    [void]$netTask.Wait(-1)
    return ,$netTask.Result
}}

[void][Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]

$imagePath = '{escaped_path}'
$file = (Invoke-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imagePath)) ([Windows.Storage.StorageFile]))[-1]
$stream = (Invoke-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream]))[-1]
$decoder = (Invoke-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder]))[-1]
$bitmap = (Invoke-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap]))[-1]

$lang = [Windows.Globalization.Language]::new('ar-SA')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
$result = (Invoke-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult]))[-1]

$lines = @()
foreach ($line in $result.Lines) {{
    $words = @()
    foreach ($w in $line.Words) {{
        $words += @{{
            text = $w.Text
            x = $w.BoundingRect.X
            y = $w.BoundingRect.Y
            w = $w.BoundingRect.Width
            h = $w.BoundingRect.Height
        }}
    }}
    $lines += @{{
        text = $line.Text
        words = $words
    }}
}}
if ($lines.Count -eq 0) {{ '[]' }} else {{ ,$lines | ConvertTo-Json -Depth 4 -Compress }}
"""
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=20,
                )
                stdout = proc.stdout.strip()

            if not stdout:
                boxes = []
            else:
                lines_data = json.loads(stdout)
                if isinstance(lines_data, dict):
                    if "value" in lines_data and isinstance(lines_data["value"], list):
                        lines_data = lines_data["value"]
                    elif "words" in lines_data:
                        lines_data = [lines_data]
                    else:
                        lines_data = []

                boxes = []
                for item in lines_data:
                    raw_line_text = item.get("text", "").strip()
                    words = item.get("words", [])
                    if not words:
                        continue

                    min_x = min(w["x"] for w in words)
                    min_y = min(w["y"] for w in words)
                    max_x = max(w["x"] + w["w"] for w in words)
                    max_y = max(w["y"] + w["h"] for w in words)

                    # Windows Media OCR returns words in left-to-right bounding box order.
                    # If the line contains Arabic characters, natural reading order is RTL (rightmost word first).
                    has_arabic = any(
                        any("\u0600" <= c <= "\u06ff" or "\ufb50" <= c <= "\ufeff" for c in w.get("text", ""))
                        for w in words
                    )
                    if has_arabic:
                        # Reconstruct line according to BiDi principles:
                        # Arabic words flow right-to-left (descending X), but numeric tokens flow left-to-right (ascending X).
                        sorted_words = sorted(words, key=lambda w: w["x"], reverse=True)
                        final_tokens = []
                        num_run = []
                        for w in sorted_words:
                            w_txt = w["text"].translate(EASTERN_ARABIC_DIGITS).strip()
                            if w_txt.isdigit():
                                num_run.append(w)
                            else:
                                if num_run:
                                    num_run_sorted = sorted(num_run, key=lambda nw: nw["x"])
                                    final_tokens.append("".join(nw["text"] for nw in num_run_sorted))
                                    num_run = []
                                final_tokens.append(w["text"])
                        if num_run:
                            num_run_sorted = sorted(num_run, key=lambda nw: nw["x"])
                            final_tokens.append("".join(nw["text"] for nw in num_run_sorted))

                        line_text = " ".join(final_tokens)
                    else:
                        sorted_words = sorted(words, key=lambda w: w["x"])
                        line_text = " ".join(w["text"] for w in sorted_words)

                    line_text = line_text.translate(EASTERN_ARABIC_DIGITS).strip()

                    boxes.append(
                        {
                            "text": line_text,
                            "raw_text": raw_line_text,
                            "confidence": None,  # Windows OCR does not emit numeric per-box confidence; validated structurally
                            "bbox": [float(min_x), float(min_y), float(max_x), float(max_y)],
                            "engine": "windows_media_ocr",
                        }
                    )

            with _OCR_CACHE_LOCK:
                if len(_OCR_CACHE) >= _MAX_CACHE_ENTRIES:
                    _OCR_CACHE.clear()
                _OCR_CACHE[cache_key] = boxes

            return boxes
        except Exception as exc:
            logger.error("Windows Media OCR execution failed: %s", exc)
            return []
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                    os.remove(tmp_path)
                except Exception:
                    pass
