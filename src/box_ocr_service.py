"""Read an explicitly selected Review region without accessing Tk or saving data."""

import multiprocessing
import os

from .box_ocr_parser import parse_box_words
from .native_ocr.win_context_ocr import ContextWindowOCR, _sort_words_bidi


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


def _rapid_worker(connection, render_args):
    try:
        from .ocr_engine import ArabicOCREngine

        image, _, _ = _render(*render_args)
        engine = ArabicOCREngine()
        if not engine.is_available():
            raise RuntimeError('RapidOCR models are unavailable')
        boxes = engine.extract_text_boxes(image, engine='rapidocr')
        connection.send({'status': 'ok', 'words': boxes[:256]})
    except Exception as exc:
        connection.send({'status': 'error', 'error': str(exc)})
    finally:
        connection.close()


def _rapid_fallback(render_args, timeout_s=12):
    context = multiprocessing.get_context('spawn')
    incoming, outgoing = context.Pipe(duplex=False)
    with incoming, outgoing:
        process = context.Process(target=_rapid_worker, args=(outgoing, render_args), daemon=True)
        process.start()
        outgoing.close()
        job = None
        try:
            if os.name == 'nt':
                from .native_ocr.windows_job import WorkerJob

                job = WorkerJob(process._popen)
            if not incoming.poll(timeout_s):
                raise TimeoutError('RapidOCR exceeded its deadline')
            return incoming.recv()
        finally:
            if job is not None:
                job.close()
            if process.is_alive():
                process.kill()
            process.join(timeout=0.5)
            if not process.is_alive():
                process.close()


def run_box_ocr(pdf_path, page_index, bbox_pt, *, dpi=180, context_rows=3, column_roles=None):
    """Return transient field suggestions for a single selected PDF box."""
    render_args = (pdf_path, page_index, bbox_pt, dpi, context_rows, column_roles)
    try:
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
    except (EOFError, OSError, RuntimeError, ValueError) as exc:
        return {'ok': False, 'error': str(exc)}
