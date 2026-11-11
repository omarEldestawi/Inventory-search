"""
Standalone Python Bridge for Native PowerToys OCR Worker with ±3 Row Context Windowing.

Provides:
- Persistent subprocess connection to `PowerToysOcrWorker.exe` (zero PowerShell overhead).
- `extract_target_box_with_context`: expands a target cell/row crop vertically by
  `context_rows_above` (default 3) and `context_rows_below` (default 3) blocks so
  `Windows.Media.Ocr` gets full multi-line layout context, then filters returned words
  strictly back to the target row's vertical Y band.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("WinContextOCR")

_NATIVE_WORKER_PROC: Optional[subprocess.Popen] = None
_NATIVE_WORKER_LOCK = threading.Lock()


def _discover_worker_exe() -> Optional[str]:
    """Locates the compiled PowerToysOcrWorker.exe binary."""
    here = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.normpath(os.path.join(here, "..", ".."))
    candidates = [
        os.path.join(here, "PowerToysOcrWorker.exe"),
        os.path.join(here, "bin", "PowerToysOcrWorker.exe"),
        os.path.join(base_dir, "src", "native_ocr", "PowerToysOcrWorker.exe"),
        os.path.join(base_dir, "assets", "bin", "PowerToysOcrWorker.exe"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "src", "native_ocr", "PowerToysOcrWorker.exe"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "bin", "PowerToysOcrWorker.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _get_or_start_native_worker(worker_exe_path: Optional[str] = None) -> Optional[subprocess.Popen]:
    """Starts or returns the persistent PowerToysOcrWorker.exe background process."""
    global _NATIVE_WORKER_PROC
    if os.name != "nt":
        return None

    exe_path = worker_exe_path or _discover_worker_exe()
    if not exe_path or not os.path.isfile(exe_path):
        return None

    with _NATIVE_WORKER_LOCK:
        if _NATIVE_WORKER_PROC is not None:
            if _NATIVE_WORKER_PROC.poll() is None:
                return _NATIVE_WORKER_PROC
            _NATIVE_WORKER_PROC = None

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            proc = subprocess.Popen(
                [exe_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                creationflags=creationflags,
            )

            deadline = time.time() + 6.0
            ready = False
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if "__READY__" in line:
                    ready = True
                    break

            if not ready:
                try:
                    proc.kill()
                except Exception:
                    pass
                return None

            _NATIVE_WORKER_PROC = proc
            return _NATIVE_WORKER_PROC
        except Exception as exc:
            logger.warning("Failed to start PowerToysOcrWorker.exe: %s", exc)
            return None


def _shutdown_native_worker() -> None:
    """Cleanly terminates PowerToysOcrWorker.exe on process exit."""
    global _NATIVE_WORKER_PROC
    with _NATIVE_WORKER_LOCK:
        if _NATIVE_WORKER_PROC is not None:
            try:
                if _NATIVE_WORKER_PROC.poll() is None and _NATIVE_WORKER_PROC.stdin:
                    _NATIVE_WORKER_PROC.stdin.write('{"command":"exit"}\n')
                    _NATIVE_WORKER_PROC.stdin.flush()
                    _NATIVE_WORKER_PROC.wait(timeout=1.0)
            except Exception:
                try:
                    _NATIVE_WORKER_PROC.kill()
                except Exception:
                    pass
            _NATIVE_WORKER_PROC = None


atexit.register(_shutdown_native_worker)


def _contains_arabic_char(text: str) -> bool:
    for c in text:
        if ("\u0600" <= c <= "\u06ff") or ("\u0750" <= c <= "\u077f") or ("\ufb50" <= c <= "\ufdff") or ("\ufe70" <= c <= "\ufeff"):
            return True
    return False


def _sort_words_bidi(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Orders words in BiDi reading order:
    - If any word contains Arabic script, sort Right-to-Left (descending X midpoint),
      while keeping closely-spaced non-Arabic runs (split decimals, dosages, Latin phrases)
      in Left-to-Right order.
    - Otherwise sort Left-to-Right (ascending X midpoint).
    """
    if not words:
        return []

    has_arabic = any(_contains_arabic_char(w.get("text", "")) for w in words)
    if not has_arabic:
        return sorted(words, key=lambda w: (w["bbox"][0] + w["bbox"][2]) * 0.5)

    rtl_sorted = sorted(words, key=lambda w: (w["bbox"][0] + w["bbox"][2]) * 0.5, reverse=True)
    heights = [max(1.0, float(w["bbox"][3] - w["bbox"][1])) for w in rtl_sorted]
    avg_h = max(10.0, sum(heights) / len(heights))

    i = 0
    n = len(rtl_sorted)
    while i < n:
        if _contains_arabic_char(rtl_sorted[i].get("text", "")):
            i += 1
            continue

        j = i
        while j + 1 < n and not _contains_arabic_char(rtl_sorted[j + 1].get("text", "")):
            gap = max(0.0, float(rtl_sorted[j]["bbox"][0]) - float(rtl_sorted[j + 1]["bbox"][2]))
            if gap <= 1.0 * avg_h:
                j += 1
            else:
                break

        if j > i:
            rtl_sorted[i : j + 1] = list(reversed(rtl_sorted[i : j + 1]))
        i = j + 1

    return rtl_sorted


class ContextWindowOCR:
    """
    High-speed Native Windows OCR engine using PowerToysOcrWorker.exe with
    ±3 row vertical context expansion and target-band Y filtering.
    """

    def __init__(self, worker_exe_path: Optional[str] = None) -> None:
        self._worker_exe_path = worker_exe_path or _discover_worker_exe()

    def is_available(self) -> bool:
        """Returns True if the native PowerToysOcrWorker.exe is available and responsive."""
        return _get_or_start_native_worker(self._worker_exe_path) is not None

    def recognize_image(
        self,
        img_np: np.ndarray,
        upscale: Optional[bool] = None,
        padding: int = 16,
    ) -> Dict[str, Any]:
        """
        Sends an RGB or grayscale numpy image to `PowerToysOcrWorker.exe` and returns
        the parsed JSON response `{"status": "ok", "lines": [...]}`.
        """
        if img_np is None or img_np.size == 0:
            return {"status": "ok", "lines": []}

        worker = _get_or_start_native_worker(self._worker_exe_path)
        if worker is None:
            return {"status": "error", "error": "Native OCR worker unavailable.", "lines": []}

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_f:
            tmp_path = tmp_f.name

        try:
            if len(img_np.shape) == 3 and img_np.shape[2] == 3:
                cv2.imwrite(tmp_path, cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR))
            else:
                cv2.imwrite(tmp_path, img_np)

            req_payload: Dict[str, Any] = {
                "image_path": tmp_path,
                "padding": int(padding),
            }
            if upscale is not None:
                req_payload["upscale"] = bool(upscale)

            req_str = json.dumps(req_payload, ensure_ascii=False)
            raw_out = ""

            with _NATIVE_WORKER_LOCK:
                if worker.poll() is not None or worker.stdin is None or worker.stdout is None:
                    worker = _get_or_start_native_worker(self._worker_exe_path)
                if worker is not None and worker.stdin and worker.stdout:
                    worker.stdin.write(req_str + "\n")
                    worker.stdin.flush()
                    raw_out = worker.stdout.readline().strip()

            if not raw_out:
                return {"status": "ok", "lines": []}

            return json.loads(raw_out)
        except Exception as exc:
            logger.warning("Native OCR recognize_image error: %s", exc)
            return {"status": "error", "error": str(exc), "lines": []}
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def extract_target_box_with_context(
        self,
        full_page_img: np.ndarray,
        target_bbox: Tuple[float, float, float, float],
        context_rows_above: int = 3,
        context_rows_below: int = 3,
        vertical_tolerance_ratio: float = 0.35,
    ) -> Dict[str, Any]:
        """
        Crops `target_bbox` plus `context_rows_above` blocks above and `context_rows_below`
        blocks below from `full_page_img`, runs the native PowerToys OCR worker on the
        expanded block, and returns ONLY the words/lines that belong to `target_bbox`.
        """
        if full_page_img is None or full_page_img.size == 0:
            return {"text": "", "words": [], "context_lines": [], "expanded_bbox": [0, 0, 0, 0]}

        img_h, img_w = full_page_img.shape[:2]
        x0, y0, x1, y1 = [float(v) for v in target_bbox[:4]]
        row_h = max(12.0, y1 - y0)

        exp_x0 = max(0, int(round(x0 - 8.0)))
        exp_y0 = max(0, int(round(y0 - context_rows_above * row_h)))
        exp_x1 = min(img_w, int(round(x1 + 8.0)))
        exp_y1 = min(img_h, int(round(y1 + context_rows_below * row_h)))

        if exp_x1 <= exp_x0 or exp_y1 <= exp_y0:
            return {"text": "", "words": [], "context_lines": [], "expanded_bbox": [exp_x0, exp_y0, exp_x1, exp_y1]}

        crop_img = full_page_img[exp_y0:exp_y1, exp_x0:exp_x1]
        resp = self.recognize_image(crop_img, upscale=True, padding=16)
        lines = resp.get("lines", []) if isinstance(resp, dict) else []

        band_min_y = y0 - (vertical_tolerance_ratio * row_h)
        band_max_y = y1 + (vertical_tolerance_ratio * row_h)

        kept_words: List[Dict[str, Any]] = []
        context_lines_page: List[Dict[str, Any]] = []

        for line in lines:
            l_bbox = line.get("bbox", [0.0, 0.0, 0.0, 0.0])
            page_l_bbox = [
                round(float(l_bbox[0]) + exp_x0, 2),
                round(float(l_bbox[1]) + exp_y0, 2),
                round(float(l_bbox[2]) + exp_x0, 2),
                round(float(l_bbox[3]) + exp_y0, 2),
            ]
            line_words_page: List[Dict[str, Any]] = []

            for w in line.get("words", []):
                wb = w.get("bbox", [0.0, 0.0, 0.0, 0.0])
                if len(wb) < 4:
                    continue
                pw_x0 = round(float(wb[0]) + exp_x0, 2)
                pw_y0 = round(float(wb[1]) + exp_y0, 2)
                pw_x1 = round(float(wb[2]) + exp_x0, 2)
                pw_y1 = round(float(wb[3]) + exp_y0, 2)

                w_page = {
                    "text": str(w.get("text", "")).strip(),
                    "bbox": [pw_x0, pw_y0, pw_x1, pw_y1],
                    "lang": w.get("lang", ""),
                }
                if not w_page["text"]:
                    continue
                line_words_page.append(w_page)

                word_y_mid = (pw_y0 + pw_y1) * 0.5
                inter_y0 = max(y0, pw_y0)
                inter_y1 = min(y1, pw_y1)
                inter_h = max(0.0, inter_y1 - inter_y0)
                word_h = max(1.0, pw_y1 - pw_y0)
                overlap_ratio = inter_h / min(row_h, word_h)

                if (band_min_y <= word_y_mid <= band_max_y) or (overlap_ratio >= 0.50):
                    kept_words.append(w_page)

            context_lines_page.append(
                {
                    "text": line.get("text", ""),
                    "bbox": page_l_bbox,
                    "words": line_words_page,
                }
            )

        ordered_target_words = _sort_words_bidi(kept_words)
        target_text = " ".join(w["text"] for w in ordered_target_words).strip()

        return {
            "text": target_text,
            "words": ordered_target_words,
            "context_lines": context_lines_page,
            "expanded_bbox": [exp_x0, exp_y0, exp_x1, exp_y1],
        }
