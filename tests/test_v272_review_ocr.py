import queue
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf

from app_gui import CatalogReviewWindow
from src.box_ocr_parser import BoxParseResult
from src.box_ocr_service import _render


def test_clean_import_does_not_load_ocr_dependencies():
    command = ('import app_gui,sys; '
               'assert not {"cv2", "onnxruntime", "rapidocr_onnxruntime", "src.ocr_engine"} & sys.modules.keys()')
    subprocess.run([sys.executable, '-c', command], check=True, timeout=20)


def test_rotated_pdf_crop_keeps_source_target_and_roles_in_same_pixels(tmp_path):
    path = tmp_path / 'rotated.pdf'
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=500)
        page.insert_text((50, 100), '12.50')
        page.set_rotation(90)
        document.save(path)
    source = (40, 85, 85, 110)
    image, target, roles = _render(path, 0, source, 180, 3, {'price': source})
    assert target == roles['price']
    assert target[0] >= 0 and target[1] >= 0
    assert target[2] <= image.shape[1] and target[3] <= image.shape[0]
    left, top, right, bottom = map(int, target)
    assert image[top:bottom, left:right].min() < 100


def test_stale_review_result_cannot_change_editor_or_publish_suggestions():
    current = ('catalog.pdf', 1, 1, 'p1_t0_r2', 2)
    old = ('catalog.pdf', 1, 1, 'p1_t0_r1', 1)
    window = SimpleNamespace(
        _box_results=queue.Queue(), _box_running=True, _box_pending=None, _box_suggestion=None,
        _box_editor_context=lambda: current, catalog_path='catalog.pdf',
        name_var=Mock(), price_var=Mock(), disc_var=Mock(),
        box_suggestions_lbl=Mock(), use_box_suggestions_btn=Mock(),
    )
    fingerprint = Mock()
    result = {'ok': True, 'backend': 'test OCR', 'parse': BoxParseResult('name', 12.50, 25)}
    window._box_results.put((old, fingerprint, result, True))
    CatalogReviewWindow._poll_box_ocr(window)
    assert window._box_suggestion is None
    window.box_suggestions_lbl.configure.assert_not_called()
    window._box_results.put((current, fingerprint, result, True))
    CatalogReviewWindow._poll_box_ocr(window)
    assert window._box_suggestion == (current, result['parse'])
    for field in (window.name_var, window.price_var, window.disc_var):
        field.set.assert_not_called()
