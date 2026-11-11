import queue
from types import SimpleNamespace
from unittest.mock import Mock

from app_gui import PharmaProcurementApp


def test_run_waits_for_existing_inspection_and_ignores_repeated_run():
    catalog = SimpleNamespace(path='selected.pdf', category='Catalog', catalog_result=None)
    app = SimpleNamespace(
        file_model=SimpleNamespace(validate=lambda _: (True, ''), files=[catalog],
                                   get_order_files=lambda: ['order.xlsx'], get_catalog_files=lambda: [catalog.path],
                                   get_avg_discounts_files=lambda: []),
        output_dir_var=Mock(), run_button=Mock(), status_label=Mock(), bridge=None,
        _catalogs_inspecting={catalog.path}, _inspection_requests={catalog.path: (1, catalog)},
        _waiting_for_inspection=False, _async_inspect_counts=Mock(),
    )
    PharmaProcurementApp._on_run_optimization(app)
    PharmaProcurementApp._on_run_optimization(app)
    assert app._waiting_for_inspection
    assert app._inspection_requests == {catalog.path: (1, catalog)}
    app._async_inspect_counts.assert_called_once_with([catalog.path])


def test_stale_inspection_error_does_not_clear_current_request():
    catalog = SimpleNamespace(path='selected.pdf', category='Catalog', catalog_result=None,
                              determine_lifecycle_state=Mock())
    app = SimpleNamespace(
        file_model=SimpleNamespace(files=[catalog]), _ocr_queue=queue.Queue(),
        _catalogs_inspecting={catalog.path}, _inspection_requests={catalog.path: (2, catalog)},
        _waiting_for_inspection=True, _latest_applied_seq={}, _pending_catalog_view=None,
        status_label=Mock(), _update_ui_state=Mock(), _update_file_card_badge=Mock(),
        _bump_catalog_generation=Mock(), _resume_waiting_optimization=Mock(), after=Mock(),
    )
    app._poll_ocr_queue = lambda: PharmaProcurementApp._poll_ocr_queue(app)
    app._ocr_queue.put(('INSPECT_FILE_ERROR', catalog.path, 'obsolete', 1))
    app._poll_ocr_queue()
    assert app._waiting_for_inspection
    assert app._inspection_requests[catalog.path][0] == 2
    app.status_label.configure.assert_not_called()

    app._ocr_queue.put(('INSPECT_FILE_ERROR', catalog.path, 'deadline expired', 2))
    app._poll_ocr_queue()
    assert not app._waiting_for_inspection
    assert not app._inspection_requests and not app._catalogs_inspecting
    assert catalog.diagnostic_summary == 'deadline expired'
    app._update_ui_state.assert_called_once()
