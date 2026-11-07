"""Import uncertainty contracts; no pharmaceutical lookup assumptions."""
import numpy as np
import pymupdf
import pytest
from src.catalog_reader import validate_catalog_item
from src.image_table_detector import ImageTableDetector


def item(name, **extra):
    return dict(item_name=name, base_price=50.0, discount_rate=0.2, **extra)


@pytest.mark.parametrize("name", [
    "Example 1000/50 mg 28 tablets", "Example 1500/1000 mg 14 tablets",
    "Example 5/40/12.5 mg 30 tablets", "Example 40/5 mg 30 tablets",
])
def test_digital_ratios_have_no_invented_magnitude_limit(name):
    assert validate_catalog_item(item(name))[0]


@pytest.mark.parametrize("name", [
    "Example 1205/40/5 mg 30 tablets", "Example 5/40/12.5 mg 30 tablets",
    "Example 1000/50 mg 28 tablets", "Example 40/5 mg 30 tablets",
])
def test_ocr_ratios_need_source_evidence_even_when_plausible(name):
    assert validate_catalog_item(item(name, _ocr_engine_used="windows")) == (False, "unverified_ocr_strength_sequence")


def test_ambiguous_decimal_quarantined_without_touching_digital_text():
    name = "Example 2. 0 mg 30 tablets"
    assert validate_catalog_item(item(name, _ocr_engine_used="windows"))[1] == "ambiguous_ocr_decimal"
    assert validate_catalog_item(item(name))[0]


class FakeOCR:
    def extract_text_boxes(self, crop, engine):
        return [{"text": "Example 12.5/40/5 mg 30 tablets", "bbox": [0,0,100,20], "engine": "windows"}]


@pytest.mark.parametrize("name", ["Example 1205/40/5 mg 30 tablets", "Example 5/40/12.5 mg 30 tablets", "دواء 5/40/12.5 مجم 30 قرص"])
def test_retry_never_reverses_replaces_or_deletes_source_numbers(name):
    detector = ImageTableDetector.__new__(ImageTableDetector)
    detector._ocr_engine = FakeOCR()
    boxes = [{"bbox": [10,10,100,30]}]
    actual, verified = detector._recover_multi_component_strength(name, boxes, 1, img_np=np.zeros((50,150,3), dtype=np.uint8), cell_bounds_pt=(5,110))
    assert actual == name
    assert not verified  # two agreeing OCR retries are not independent source truth
    assert len(detector._last_strength_attempts) == 2
    assert all(a["bbox_pt"][0] == 5 and a["bbox_pt"][2] == 110 for a in detector._last_strength_attempts)
    assert detector._last_strength_attempts[0]["readings"][0]["text"].endswith("30 tablets")


def test_matching_digital_cell_corroborates_without_reordering():
    detector = ImageTableDetector.__new__(ImageTableDetector)
    name = "Example 1000/50 mg 28 tablets"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((20,30), name)
        actual, verified = detector._recover_multi_component_strength(name, [{"bbox": [20,15,250,35]}], 1, pdf_page=page, cell_bounds_pt=(15,270))
    assert verified
    assert actual == name


def test_defective_fallback_cannot_approve_plausible_missing_zero():
    assert validate_catalog_item(item("Example 2 mg 3 tablets", _ocr_engine_used="rapidocr")) == (False, "unverified_ocr_engine")
