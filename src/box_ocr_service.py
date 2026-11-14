"""Read an explicitly selected Review region without accessing Tk or saving data."""

import atexit
import logging
import multiprocessing
import os
import pickle
import struct
import subprocess
import sys
import threading

from .box_ocr_parser import parse_box_words
from .native_ocr.win_context_ocr import ContextWindowOCR, _sort_words_bidi

_logger = logging.getLogger("BoxOCRService")
_HEADER_STRUCT = struct.Struct(">I")


def render_pdf_page_with_highlight(
    pdf_path: str,
    page_number: int = 1,
    bbox=None,
    dpi: int = 150,
    highlight_color: str = "#DC2626",
    highlight_width: int = 4,
):
    """
    Renders a PDF page to a PIL Image at specified DPI (default 150),
    and highlights the provided bounding box [x0, y0, x1, y1] if given.
    Returns None if file is missing, not a PDF, or rendering fails.
    """
    if not pdf_path or not os.path.isfile(pdf_path):
        return None
    if not pdf_path.lower().endswith(".pdf"):
        return None
    try:
        from PIL import Image, ImageDraw
        import pymupdf

        doc = pymupdf.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return None
        p_idx = max(0, min(page_number - 1, len(doc) - 1))
        page = doc[p_idx]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.info["pdf_page_rect"] = tuple(page.rect)
        img.info["pdf_inverse_rotation"] = tuple(page.derotation_matrix)

        if bbox and len(bbox) >= 4:
            scale_x = pix.width / max(1.0, float(page.rect.width))
            scale_y = pix.height / max(1.0, float(page.rect.height))
            rotated = pymupdf.Rect(bbox).normalize() * page.rotation_matrix
            rx0, ry0, rx1, ry1 = (
                rotated.x0 * scale_x, rotated.y0 * scale_y,
                rotated.x1 * scale_x, rotated.y1 * scale_y,
            )

            if rx1 - rx0 < 10:
                rx1 = rx0 + 10
            if ry1 - ry0 < 10:
                ry1 = ry0 + 10

            draw = ImageDraw.Draw(img)
            draw.rectangle([rx0, ry0, rx1, ry1], outline=highlight_color, width=highlight_width)
            inner_color = "#D97706" if highlight_color != "#D97706" else "#F59E0B"
            draw.rectangle([rx0 + 2, ry0 + 2, rx1 - 2, ry1 - 2], outline=inner_color, width=max(1, highlight_width // 2))

        doc.close()
        return img
    except Exception as exc:
        _logger.warning(f"Error rendering PDF page {page_number} for {pdf_path}: {exc}")
        return None


def render_pdf_row_crop(
    pdf_path: str,
    page_number: int = 1,
    bbox=None,
    dpi: int = 180,
    pad: float = 6.0,
    max_size=None,
):
    """
    Renders a cropped PIL Image of a specific row/region bounding box [x0, y0, x1, y1]
    from the source PDF page for side-by-side display next to editable fields.
    """
    if not pdf_path or not os.path.isfile(pdf_path) or not pdf_path.lower().endswith(".pdf"):
        return None
    if not bbox or len(bbox) < 4:
        return None
    try:
        from PIL import Image
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            if not len(doc):
                return None
            page = doc[max(0, min(page_number - 1, len(doc) - 1))]
            x0, y0, x1, y1 = pymupdf.Rect(bbox[:4]).normalize()
            source_clip = pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
            source_clip &= page.rect * page.derotation_matrix
            if source_clip.width < 12 or source_clip.height < 8:
                return None
            clip = source_clip * page.rotation_matrix & page.rect
            if max_size:
                scale = min(dpi / 72, max_size[0] / clip.width, max_size[1] / clip.height)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip)
            else:
                pix = page.get_pixmap(dpi=dpi, clip=clip)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        if max_size:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
        return img
    except Exception as exc:
        _logger.debug(f"Error rendering PDF row crop on page {page_number} for {pdf_path}: {exc}")
        return None


def _render(pdf_path, page_index, bbox, dpi, context_rows, column_roles):
    import numpy as np
    import pymupdf

    scale = dpi / 72.0
    with pymupdf.open(pdf_path) as document:
        if not 0 <= page_index < len(document):
            raise ValueError('The selected PDF page no longer exists')
        page = document[page_index]
        target = pymupdf.Rect(bbox) * page.rotation_matrix & page.rect
        if target.is_empty or target.width < 2 or target.height < 2:
            raise ValueError('Select a visible area on the PDF page')
        height = max(5, target.height)
        clip = pymupdf.Rect(target.x0 - 6, target.y0 - context_rows * height,
                           target.x1 + 6, target.y1 + context_rows * height) & page.rect
        pixmap = page.get_pixmap(dpi=dpi, clip=clip, alpha=False, colorspace=pymupdf.csRGB)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)

        def to_pixels(rect):
            return (rect.x0 * scale - pixmap.x, rect.y0 * scale - pixmap.y,
                    rect.x1 * scale - pixmap.x, rect.y1 * scale - pixmap.y)

        roles = {name: to_pixels(pymupdf.Rect(box) * page.rotation_matrix)
                 for name, box in (column_roles or {}).items()}
    return image, to_pixels(target), roles


def _rapid_loop(connection):
    engine = None
    try:
        from .ocr_engine import ArabicOCREngine

        while True:
            try:
                render_args = connection.recv()
            except EOFError:
                break
            if render_args is None:
                break
            try:
                image, target, roles = _render(*render_args)
                if engine is None:
                    engine = ArabicOCREngine()
                    if not engine.is_available():
                        raise RuntimeError('RapidOCR models are unavailable')
                boxes = engine.extract_text_boxes(image, engine='rapidocr')
                connection.send({'status': 'ok', 'words': boxes[:256], 'target': target, 'roles': roles})
            except Exception as exc:
                connection.send({'status': 'error', 'error': str(exc)})
    finally:
        try:
            connection.close()
        except Exception:
            pass


class _PersistentRapidWorker:
    """Lazily spawned, reusable RapidOCR subprocess guarded by a Windows Job Object."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._conn = None
        self._job = None
        self._registered = False

    def _ensure_locked(self):
        if not self._registered:
            atexit.register(self.close)
            self._registered = True
        if self._proc is not None and self._proc.is_alive() and self._conn is not None:
            return
        self._close_locked()
        context = multiprocessing.get_context('spawn')
        parent_conn, child_conn = context.Pipe(duplex=True)
        process = context.Process(target=_rapid_loop, args=(child_conn,), daemon=True)
        process.start()
        child_conn.close()
        job = None
        if os.name == 'nt':
            try:
                from .native_ocr.windows_job import WorkerJob
                job = WorkerJob(process._popen)
            except Exception:
                job = None
        self._proc = process
        self._conn = parent_conn
        self._job = job

    def request(self, render_args, timeout_s=20.0):
        with self._lock:
            self._ensure_locked()
            try:
                self._conn.send(render_args)
                if not self._conn.poll(timeout_s):
                    raise TimeoutError('RapidOCR exceeded its deadline')
                return self._conn.recv()
            except Exception:
                self._close_locked()
                raise

    def _close_locked(self):
        conn, self._conn = self._conn, None
        proc, self._proc = self._proc, None
        job, self._job = self._job, None
        if conn is not None:
            try:
                conn.send(None)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
        if job is not None:
            try:
                job.close()
            except Exception:
                pass
        if proc is not None:
            try:
                if proc.is_alive():
                    proc.join(timeout=0.3)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=0.5)
            except Exception:
                pass
            try:
                proc.close()
            except Exception:
                pass

    def close(self):
        with self._lock:
            self._close_locked()


_RAPID_WORKER = None
_RAPID_WORKER_LOCK = threading.Lock()


def _get_rapid_worker():
    global _RAPID_WORKER
    with _RAPID_WORKER_LOCK:
        if _RAPID_WORKER is None:
            _RAPID_WORKER = _PersistentRapidWorker()
        return _RAPID_WORKER


def _rapid_fallback(render_args, timeout_s=20.0):
    return _get_rapid_worker().request(render_args, timeout_s=timeout_s)


def run_box_ocr(pdf_path, page_index, bbox_pt, *, dpi=180, context_rows=3, column_roles=None):
    """Return transient field suggestions for a single selected PDF box."""
    render_args = (pdf_path, page_index, bbox_pt, dpi, context_rows, column_roles)
    try:
        if os.environ.get("EPO_FORCE_RAPID_FALLBACK") == "1":
            native_result = {'status': 'error', 'error': 'forced_fallback'}
            result = _rapid_fallback(render_args)
            backend = 'RapidOCR'
            if result.get('status') == 'error':
                return {'ok': False, 'error': f'{native_result.get("error")} / {result.get("error")}'}
            target = result.get('target')
            roles = result.get('roles')
            if target is None or roles is None:
                _, target, roles = _render(*render_args)
        else:
            image, target, roles = _render(*render_args)
            native = ContextWindowOCR()
            native_result = native.extract_target_box_with_context(image, target, context_rows, context_rows)
            backend = 'Windows OCR'
            result = native_result
            if result.get('status') == 'error':
                result = _rapid_fallback(render_args)
                backend = 'RapidOCR'
                if result.get('status') == 'error':
                    return {'ok': False, 'error': f'{native_result.get("error")} / {result.get("error")}'}
        x0, y0, x1, y1 = target
        words = []
        for word in result.get('words', []):
            left, top, right, bottom = word['bbox']
            if x0 <= (left + right) / 2 <= x1 and y0 <= (top + bottom) / 2 <= y1:
                words.append(word)
        if not words:
            return {'ok': False, 'error': 'No text detected in the selected box'}
        sort_bidi = _sort_words_bidi if backend == 'Windows OCR' else None
        return {'ok': True, 'parse': parse_box_words(words, column_roles=roles, sort_bidi=sort_bidi),
                'backend': backend}
    except (EOFError, OSError, RuntimeError, ValueError, TimeoutError) as exc:
        return {'ok': False, 'error': str(exc)}


_ORIGINAL_RUN_BOX_OCR = run_box_ocr


def _write_frame(stream, payload):
    data = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(_HEADER_STRUCT.pack(len(data)) + data)
    stream.flush()


def _read_exact(stream, size):
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError('Worker pipe closed unexpectedly')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _read_frame(stream):
    header = _read_exact(stream, _HEADER_STRUCT.size)
    (length,) = _HEADER_STRUCT.unpack(header)
    if length <= 0 or length > 128 * 1024 * 1024:
        raise ValueError(f'Invalid frame size: {length}')
    return pickle.loads(_read_exact(stream, length))


def run_review_worker_stdio():
    """Serve PDF preview rendering, Box OCR, and fingerprint validation over binary stdio."""
    from PIL import Image

    req_in = sys.stdin.buffer
    stdout_fd = sys.__stdout__.fileno() if sys.__stdout__ is not None else 1
    resp_out = os.fdopen(os.dup(stdout_fd), "wb", buffering=0)
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, 1)
        finally:
            os.close(devnull_fd)
    except OSError:
        pass
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except OSError:
        pass

    try:
        while True:
            try:
                msg = _read_frame(req_in)
            except EOFError:
                break
            cmd = msg[0]
            if cmd == "shutdown":
                _write_frame(resp_out, ("ok", True))
                break
            if cmd == "ping":
                _write_frame(resp_out, ("pong", True))
                continue
            if cmd == "preview":
                try:
                    _, (path, page, bbox), row_request, highlight_color, page_scale, row_scale = msg
                    pscale = max(1.0, float(page_scale or 1.0))
                    rscale = max(1.0, float(row_scale or 1.0))
                    img = render_pdf_page_with_highlight(path, page, bbox, highlight_color=highlight_color)
                    psize = None
                    pbytes = None
                    info = {}
                    disp_size = (0, 0)
                    if img is not None:
                        disp_h = max(1, round(520 * img.height / img.width))
                        disp_size = (520, disp_h)
                        scaled_w = max(1, round(520 * pscale))
                        scaled_h = max(1, round(disp_h * pscale))
                        rgb = img.convert("RGB").resize((scaled_w, scaled_h), Image.Resampling.BILINEAR)
                        psize = rgb.size
                        pbytes = rgb.tobytes()
                        info = {
                            "pdf_page_rect": img.info.get("pdf_page_rect"),
                            "pdf_inverse_rotation": img.info.get("pdf_inverse_rotation"),
                        }
                    rsize = None
                    rbytes = None
                    if row_request:
                        row_path, row_page, row_bbox, _ = row_request
                        target_rw = max(1, round(460 * rscale))
                        target_rh = max(1, round(110 * rscale))
                        crop = render_pdf_row_crop(row_path, row_page, row_bbox, max_size=(target_rw, target_rh))
                        if crop is not None:
                            canvas = Image.new("RGB", (target_rw, target_rh), (240, 240, 240))
                            crop_rgb = crop.convert("RGB")
                            ox = max(0, (target_rw - crop_rgb.width) // 2)
                            oy = max(0, (target_rh - crop_rgb.height) // 2)
                            canvas.paste(crop_rgb, (ox, oy))
                            rsize = canvas.size
                            rbytes = canvas.tobytes()
                    _write_frame(resp_out, ("ok", (psize, pbytes, info, disp_size, rsize, rbytes)))
                except Exception as exc:
                    _write_frame(resp_out, ("error", str(exc)))
                continue
            if cmd == "ocr":
                try:
                    _, pdf_path, page_idx, bbox, roles, fingerprint, force_fallback = msg
                    if force_fallback:
                        os.environ["EPO_FORCE_RAPID_FALLBACK"] = str(force_fallback)
                    else:
                        os.environ.pop("EPO_FORCE_RAPID_FALLBACK", None)
                    outcome = run_box_ocr(pdf_path, page_idx, bbox, column_roles=roles)
                    fp_ok = bool(fingerprint and fingerprint.is_current(pdf_path))
                    _write_frame(resp_out, ("ok", (outcome, fp_ok)))
                except Exception as exc:
                    _write_frame(resp_out, ("error", str(exc)))
                continue
            _write_frame(resp_out, ("error", f"Unknown review worker command: {cmd}"))
    finally:
        shutdown_review_workers()
        try:
            resp_out.close()
        except Exception:
            pass


class ReviewProcessWorker:
    """Persistent out-of-process worker for Review PDF preview, Box OCR, and fingerprint hashing."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._job = None
        self._registered = False

    def _ensure_locked(self):
        if not self._registered:
            atexit.register(self.close)
            self._registered = True
        if self._proc is not None and self._proc.poll() is None:
            return
        self._close_locked()
        frozen = getattr(sys, "frozen", False)
        cmd = (
            [sys.executable, "--review-worker"]
            if frozen
            else [sys.executable, "-m", "src.box_ocr_service", "--review-worker"]
        )
        cwd = None if frozen else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        job = None
        if os.name == "nt":
            try:
                from .native_ocr.windows_job import WorkerJob
                job = WorkerJob(proc)
            except Exception:
                job = None
        self._proc = proc
        self._job = job

    def call(self, payload):
        with self._lock:
            self._ensure_locked()
            try:
                _write_frame(self._proc.stdin, payload)
                return _read_frame(self._proc.stdout)
            except Exception:
                self._close_locked()
                raise

    def _close_locked(self):
        proc, self._proc = self._proc, None
        job, self._job = self._job, None
        if proc is not None:
            try:
                if proc.stdin:
                    try:
                        _write_frame(proc.stdin, ("shutdown",))
                    except Exception:
                        pass
                    proc.stdin.close()
            except Exception:
                pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
            try:
                if proc.poll() is None:
                    proc.wait(timeout=2.0)
            except Exception:
                pass
        if job is not None:
            try:
                job.close()
            except Exception:
                pass
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except Exception:
                pass

    def close(self):
        with self._lock:
            self._close_locked()


_REVIEW_WORKER = None
_REVIEW_WORKER_LOCK = threading.Lock()


def get_review_process_worker():
    global _REVIEW_WORKER
    with _REVIEW_WORKER_LOCK:
        if _REVIEW_WORKER is None:
            _REVIEW_WORKER = ReviewProcessWorker()
        return _REVIEW_WORKER


def shutdown_review_workers():
    global _RAPID_WORKER, _REVIEW_WORKER
    if _REVIEW_WORKER is not None:
        _REVIEW_WORKER.close()
    if _RAPID_WORKER is not None:
        _RAPID_WORKER.close()
    try:
        from .native_ocr.win_context_ocr import _shutdown_native_worker
        _shutdown_native_worker()
    except Exception:
        pass


if __name__ == "__main__" and "--review-worker" in sys.argv:
    run_review_worker_stdio()
