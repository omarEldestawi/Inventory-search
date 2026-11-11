import queue
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest
from PIL import Image

import app_gui

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


def test_drag_maps_scaled_preview_without_starting_ocr():
    label = SimpleNamespace(_apply_widget_scaling=lambda size: size * 2,
                            winfo_width=lambda: 400, winfo_height=lambda: 500)
    window = SimpleNamespace(
        _current_rendered_dims=(100, 200, (0, 0, 100, 200), (1, 0, 0, 1, 0, 0)),
        page_image_lbl=label, _invalidate_box_ocr=Mock(), _render_pdf_page=Mock(), _execute_box_ocr=Mock(),
    )
    CatalogReviewWindow._ocr_custom_preview_box(window, 120, 70, 160, 110)
    assert window._custom_drag_bbox == [10, 10, 30, 30]
    window._invalidate_box_ocr.assert_called_once()
    window._execute_box_ocr.assert_not_called()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_row_preview_crops_rotated_source_bounds(tmp_path, rotation):
    path = tmp_path / "rotated.pdf"
    bbox = (45, 390, 185, 410)
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=500)
        page.draw_rect(pymupdf.Rect(bbox), color=None, fill=(0, 0, 0))
        page.set_rotation(rotation)
        document.save(path)

    image = app_gui.render_pdf_row_crop(str(path), bbox=bbox, dpi=72, pad=0)
    assert image is not None
    assert image.size == ((20, 140) if rotation in (90, 270) else (140, 20))
    assert image.getpixel((image.width // 2, image.height // 2)) == (0, 0, 0)
    region = app_gui.render_pdf_row_crop(str(path), bbox=(0, 0, 300, 500), max_size=(460, 110))
    assert region is not None and region.width <= 460 and region.height <= 110


def test_preview_renders_off_tk_and_only_displays_latest_request(monkeypatch):
    release_first = threading.Event()
    first_started = threading.Event()
    main_thread = threading.get_ident()
    calls = []

    def render(path, page, bbox, **kwargs):
        calls.append(("page", page, threading.get_ident()))
        img = Image.new("RGB", (100, 200))
        img.info.update(pdf_page_rect=(0, 0, 100, 200), pdf_inverse_rotation=(1, 0, 0, 1, 0, 0))
        return img

    def render_crop(path, page, bbox, **kwargs):
        calls.append(("crop", page, threading.get_ident()))
        if page == 1:
            first_started.set()
            assert release_first.wait(5)
        return Image.new("RGB", (100, 20), (page, 0, 0))

    def issue(page):
        return SimpleNamespace(source_id=f"p{page}_t0_r1", bbox=(10, 20, 90, 40),
                               identity=SimpleNamespace(page=page))

    monkeypatch.setattr(app_gui, "render_pdf_page_with_highlight", render)
    monkeypatch.setattr(app_gui, "render_pdf_row_crop", render_crop)
    window = SimpleNamespace(
        catalog_path="catalog.pdf", current_page=1, total_pages=3, selected_issue=issue(1),
        page_info_lbl=Mock(), page_image_lbl=Mock(), row_crop_lbl=Mock(), after=Mock(),
        _current_ctk_image=None, _preview_request=None, _preview_results=queue.Queue(1),
        _preview_running=False, _preview_drag=(10, 20),
    )
    window._launch_pdf_preview = lambda request: CatalogReviewWindow._launch_pdf_preview(window, request)
    window._poll_pdf_preview = lambda: CatalogReviewWindow._poll_pdf_preview(window)

    CatalogReviewWindow._render_pdf_page(window)
    try:
        assert first_started.wait(5)
        for page in (2, 3):
            window.current_page = page
            window.selected_issue = issue(page)
            CatalogReviewWindow._render_pdf_page(window)
        assert window._current_rendered_dims is None
        assert window._preview_drag is None
        assert [(kind, page) for kind, page, _ in calls] == [("page", 1), ("crop", 1)]
    finally:
        release_first.set()

    first = window._preview_results.get(timeout=5)
    window._preview_results.put(first)
    window._poll_pdf_preview()
    assert window._current_ctk_image is None
    window.row_crop_lbl.configure.assert_called_with(image="")
    latest = window._preview_results.get(timeout=5)
    window._preview_results.put(latest)
    window._poll_pdf_preview()
    assert [(kind, page) for kind, page, _ in calls] == [
        ("page", 1), ("crop", 1), ("page", 3), ("crop", 3),
    ]
    assert all(thread != main_thread for _, _, thread in calls)
    assert window._current_rendered_dims[:2] == (520, 1040)
    window.page_image_lbl.configure.assert_called_with(image=window._current_ctk_image, text="")
    crop = window.row_crop_lbl.configure.call_args.kwargs["image"]
    assert crop.cget("light_image").getpixel((0, 0)) == (3, 0, 0)


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
