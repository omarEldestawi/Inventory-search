from pathlib import Path
from unittest.mock import Mock

import pymupdf
import pandas as pd
import pytest

from src import catalog_recovery, controller, image_table_detector, pdf_parser
from src.catalog_diagnostics import CatalogResult, ImportDiagnostics, ReviewIssue
from src.catalog_service import CatalogCorrectionService, STANDARD_COLUMNS
from src.pipeline import PipelineExecutionError, run_procurement_pipeline


FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def ocr_calls(monkeypatch):
    detector = Mock(side_effect=AssertionError('raster OCR invoked during import'))
    row_ocr = Mock(side_effect=AssertionError('row OCR invoked during import'))
    region_ocr = Mock(side_effect=AssertionError('region OCR invoked during import'))
    monkeypatch.setattr(image_table_detector, 'ImageTableDetector', detector)
    monkeypatch.setattr(catalog_recovery, 'recover_by_ocr_ladder', row_ocr)
    monkeypatch.setattr(catalog_recovery, 'recover_region_by_ocr', region_ocr)
    yield
    for mock in (detector, row_ocr, region_ocr):
        mock.assert_not_called()


def test_raster_import_defers_with_stable_review_geometry(ocr_calls):
    path = str(FIXTURES / 'test_scanned_page1.pdf')
    parser = pdf_parser.PDFCatalogParser(path)
    result = CatalogResult.from_dataframe(parser.parse())
    assert result is not None and result.dataframe.empty
    assert result.status == 'failed'
    assert result.diagnostics.unresolved_region_count == 1
    issue, = result.review_issues
    assert issue.source_id == 'p1_t0_region'
    assert issue.page_number == 1 and issue.bbox
    assert issue.rejection_reason == 'image_only_page_requires_review'


def test_inspection_refresh_and_corrections_reload_defer_raster(ocr_calls, monkeypatch, tmp_path):
    monkeypatch.setenv('EPO_CORRECTIONS_DIR', str(tmp_path))
    path = str(FIXTURES / 'test_scanned_page1.pdf')
    first = controller.inspect_catalog(path, refresh=True)
    reloaded = CatalogCorrectionService(path).get_refreshed_catalog_result(refresh=True)
    assert first.dataframe.empty and reloaded.dataframe.empty
    assert first.review_issues[0].source_id == reloaded.review_issues[0].source_id


def test_procurement_fallback_blocks_scanned_only_catalog_without_ocr(ocr_calls, monkeypatch, tmp_path):
    monkeypatch.setenv('EPO_CORRECTIONS_DIR', str(tmp_path / 'corrections'))
    order = tmp_path / 'order.csv'
    order.write_text('item_name,quantity\nExample tablet,1\n', encoding='utf-8')
    path = str(FIXTURES / 'test_scanned_page1.pdf')
    with pytest.raises(PipelineExecutionError, match='catalog'):
        run_procurement_pipeline([str(order)], [path], output_dir=str(tmp_path), catalog_cache={})
    assert not list(tmp_path.glob('*.xlsx'))


def test_save_one_verified_row_leaves_the_scanned_page_in_review(ocr_calls, monkeypatch, tmp_path):
    monkeypatch.setenv('EPO_CORRECTIONS_DIR', str(tmp_path))
    path = str(FIXTURES / 'test_scanned_page1.pdf')
    service = CatalogCorrectionService(path)
    before = service.get_refreshed_catalog_result()
    issue, = before.review_issues
    saved = service.apply_region_row_correction(issue, [20, 20, 180, 35], {
        'item_name': 'Verified sample tablet', 'base_price': 12.50, 'discount_rate': 0.25,
    })
    assert len(saved.dataframe) == 1
    assert saved.diagnostics.requires_acknowledgment
    assert not saved.issues_by_source_id[issue.source_id].resolved
    reloaded = CatalogCorrectionService(path).get_refreshed_catalog_result(refresh=True)
    assert list(reloaded.dataframe['base_price']) == [12.50]


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotated_scanned_region_accepts_row_in_source_coordinates(ocr_calls, monkeypatch, tmp_path, rotation):
    monkeypatch.setenv("EPO_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    path = tmp_path / "rotated.pdf"
    with pymupdf.open(FIXTURES / "test_scanned_page1.pdf") as source, pymupdf.open() as document:
        page = document.new_page(width=300, height=500)
        page.insert_image(page.rect, pixmap=source[0].get_pixmap())
        page.set_rotation(rotation)
        document.save(path)

    service = CatalogCorrectionService(str(path))
    issue, = service.get_refreshed_catalog_result().review_issues
    assert list(issue.bbox) == [0, 0, 300, 500]
    saved = service.apply_region_row_correction(issue, [40, 390, 185, 410], {
        "item_name": "Verified sample tablet", "base_price": 12.50, "discount_rate": 0.25,
    })
    assert list(saved.dataframe["base_price"]) == [12.50]


def test_name_digit_crossing_arwasoft_column_boundary_stays_out_of_price():
    page = Mock()
    page.get_drawings.return_value = [
        {'rect': pymupdf.Rect(401.4, y, 583.08, y + 14.16)} for y in (504.6, 522.6, 540.6)
    ]
    row = [(561.94, 506.41, 581.61, 516.46, 'فاكيشن'),
           (547.2, 506.41, 559.49, 516.46, 'صن'),
           (531.34, 506.41, 544.7, 516.46, 'بلوك'),
           (509.74, 506.41, 528.83, 516.46, 'سبراى'),
           (493.2, 506.41, 507.29, 516.46, '٠٠٢'),
           (485.02, 506.41, 493.12, 516.46, 'مل'),
           (467.88, 506.41, 472.61, 516.46, '١'),
           (472.56, 506.41, 477.81, 516.46, '+'),
           (477.87, 506.41, 482.6, 516.46, '١'),
           (441.36, 505.19, 457.92, 516.3, '550'),
           (411.48, 505.19, 422.5, 516.3, '29')]
    page.get_text.return_value = [(x0, y0 + dy, x1, y1 + dy, text)
                                  for dy in (0, 18, 36) for x0, y0, x1, y1, text in row]
    parser = pdf_parser.PDFCatalogParser(warehouse_name='Sample Catalog')
    parser._doc_first_num_is_price = False
    items = parser._extract_arwasoft_3col_rects(page)
    assert len(items) == 3
    assert all(item['base_price'] == 550 and item['discount_rate'] == 0.29 for item in items)
    assert all('1 + 1' in item['item_name'] for item in items)


def test_digital_recovery_preserves_schema_and_source_provenance(ocr_calls, monkeypatch):
    issue = ReviewIssue(source_id='p1_t0_r1', rejection_reason='missing_discount')
    original = CatalogResult(pd.DataFrame(columns=STANDARD_COLUMNS), ImportDiagnostics(), None, [issue])
    recovered = {'item_name': 'Verified sample tablet', 'base_price': 12.50, 'discount_rate': 0.25}
    monkeypatch.setattr(catalog_recovery, 'recover_by_coordinates', Mock(return_value=recovered))
    result = catalog_recovery.run_automatic_recovery(original)
    assert list(result.dataframe.columns) == STANDARD_COLUMNS
    assert list(result.dataframe['discount_rate']) == [0.25]
    assert result.issues_by_source_id[issue.source_id].extraction_method == 'coordinate_reextraction'
