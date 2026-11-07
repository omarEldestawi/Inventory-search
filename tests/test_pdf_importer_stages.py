# -*- coding: utf-8 -*-
"""
Comprehensive stage-by-stage verification tests for the reliable PDF catalog importer.
Covers:
  Stage 1: Verified ground-truth reference dataset & regression catalogs
  Stage 2: Font-aware decoding, punctuation protection, and numeric preservation
  Stage 3: Automatic page/layout assessment, filename independence, and quality checks
  Stage 4: In-app review, PDF row crop, plain-language explanation, exclude/revert, scoped reuse
  Stage 5: Image-only / unsupported input review handling (retired OCR kept disabled)
  Stage 6: Cache protection (evaluating quality status and defects, not row count alone)
"""
from __future__ import annotations

import json
import os
import shutil
import pytest
import pandas as pd
import pymupdf

from src.pdf_font_decoder import (
    assess_pdf_page,
    extract_page_chars,
    has_suspicious_characters,
    inspect_and_repair_pdf_fonts,
    reconstruct_cell_text_from_chars,
)
from src.normalizer import (
    decode_custom_catalog_glyphs,
    fix_spaced_and_reversed_digits,
    is_catalog_noise,
    normalize_arabic_text,
    parse_dosage_and_pack,
    strip_illegal_characters,
    unreverse_arabic_text,
)
from src.catalog_diagnostics import (
    CatalogResult,
    FileFingerprint,
    GroupDiagnostics,
    ImportDiagnostics,
    PageDiagnostics,
    ReviewIssue,
    RowDiagnostic,
    explain_rejection_reason,
)
from src.catalog_reader import (
    ProductGroup,
    extract_item_from_group_row,
    validate_catalog_item,
)
from src.catalog_service import CatalogCorrectionService
from src.catalog_corrections import set_corrections_dir, load_corrections
from src.controller import (
    global_catalog_cache,
    is_replacement_quality_degraded,
    reread_catalog_with_ocr,
)
from src.pdf_parser import PDFCatalogParser
from app_gui import render_pdf_row_crop


REFERENCE_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "verified_catalog_reference.json"
)


def _load_reference_fixture() -> dict:
    with open(REFERENCE_FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_existing_path(candidates: list[str]) -> str | None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for c in candidates:
        if os.path.isabs(c) and os.path.isfile(c):
            return c
        rel = os.path.join(repo_root, c)
        if os.path.isfile(rel):
            return rel
    return None


# ============================================================================
# Stage 1: Verified Reference Dataset & Regression Catalogs
# ============================================================================

def test_stage1_el_abed_verified_reference_rows():
    ref = _load_reference_fixture()["catalogs"]["el_abed"]
    pdf_path = _resolve_existing_path(ref["default_paths"])
    if not pdf_path:
        pytest.skip("El-Abed PDF not present on this machine")

    parser = PDFCatalogParser(pdf_path)
    df = parser.parse()
    res = CatalogResult.from_dataframe(df)
    meta = df.attrs["catalog_import"]
    diag = meta.diagnostics

    assert res.fingerprint.sha256 == ref["sha256"]
    assert len(df) == ref["expected_total_rows"]
    assert meta.status == ref["expected_status"]
    assert diag.candidate_rows == 230
    assert diag.accepted_rows == 230
    assert diag.rejected_rows == 0
    assert len(diag.pages) == ref["expected_pages"]

    for p in diag.pages:
        assert p.font_repaired is True
        assert p.page_classification == "suspicious_encoding"
        assert p.selected_method == "digital_font_cmap_repaired"

    accepted_diag_rows = [
        r for p in diag.pages for g in p.groups for r in g.rows if r.outcome == "accepted"
    ]
    assert len(accepted_diag_rows) == 230

    for row_spec in ref["verified_rows"]:
        idx = row_spec["index"]
        actual = df.iloc[idx]
        r_diag = accepted_diag_rows[idx]
        assert actual["item_name"] == row_spec["item_name"], f"Mismatch at index {idx}"
        assert float(actual["base_price"]) == pytest.approx(row_spec["base_price"])
        assert float(actual["discount_rate"]) == pytest.approx(row_spec["discount_rate"])
        if "code" in row_spec:
            assert str(r_diag.raw_cells[0]).strip() == row_spec["code"], f"Code mismatch at index {idx}"
        if "source_id" in row_spec:
            assert r_diag.source_id == row_spec["source_id"], f"source_id mismatch at index {idx}"
        if "dosage" in row_spec:
            assert actual["dosage"] == row_spec["dosage"]
        if "unit_size" in row_spec:
            assert actual["unit_size"] == row_spec["unit_size"]
        has_susp, reasons = has_suspicious_characters(actual["item_name"])
        assert not has_susp, f"Suspicious chars in {actual['item_name']}: {reasons}"


def test_stage1_hadaba_dual_verified_reference_rows():
    ref = _load_reference_fixture()["catalogs"]["hadaba_dual"]
    pdf_path = _resolve_existing_path(ref["default_paths"])
    if not pdf_path:
        pytest.skip("Hadaba dual-column PDF not present on this machine")

    parser = PDFCatalogParser(pdf_path)
    df = parser.parse()
    res = CatalogResult.from_dataframe(df)
    meta = df.attrs["catalog_import"]
    diag = meta.diagnostics

    assert res.fingerprint.sha256 == ref["sha256"]
    assert len(df) == ref["expected_total_rows"]
    assert meta.status == ref["expected_status"]
    assert diag.candidate_rows == 1253
    assert diag.accepted_rows == 1253
    assert diag.rejected_rows == 0
    assert len(diag.pages) == ref["expected_pages"]

    all_sids = [r.source_id for p in diag.pages for g in p.groups for r in g.rows]
    assert len(all_sids) == len(set(all_sids)) == 1253

    for row_spec in ref["verified_rows"]:
        idx = row_spec["index"]
        actual = df.iloc[idx]
        assert actual["item_name"] == row_spec["item_name"], f"Mismatch at index {idx}"
        assert float(actual["base_price"]) == pytest.approx(row_spec["base_price"])
        assert float(actual["discount_rate"]) == pytest.approx(row_spec["discount_rate"])
        if "dosage" in row_spec:
            assert actual["dosage"] == row_spec["dosage"]
        has_susp, reasons = has_suspicious_characters(actual["item_name"])
        assert not has_susp, f"Suspicious chars in {actual['item_name']}: {reasons}"


def test_stage1_previously_working_regression_catalogs():
    ref_list = _load_reference_fixture()["catalogs"]["regression_catalogs"]
    for spec in ref_list:
        pdf_path = _resolve_existing_path([spec["path"]])
        if not pdf_path:
            continue
        df = PDFCatalogParser(pdf_path).parse()
        res = CatalogResult.from_dataframe(df)
        meta = df.attrs["catalog_import"]
        assert res.fingerprint.sha256 == spec["sha256"]
        assert len(df) == spec["expected_rows"], f"Regression row count mismatch on {spec['path']}"
        assert meta.status == spec["expected_status"], f"Regression status mismatch on {spec['path']}"
        assert meta.rejected_rows == 0
        sids = [r.source_id for p in meta.diagnostics.pages for g in p.groups for r in g.rows]
        assert len(sids) == len(set(sids))


def test_stage1_multi_table_multi_group_source_identity_and_legacy_compat(tmp_path):
    """
    Verifies that multiple tables on the same page, each with multiple product groups,
    produce distinct (page, table, group, row) identities without collision (e.g.,
    Table 0 Group 1 is 'p1_t0_g1_r1' while Table 1 Group 0 is 'p1_t1_g0_r1'),
    that unambiguous legacy 3-part identities ('p1_t0_r1' on a single-group page)
    migrate cleanly, and that ambiguous legacy 3-part identities ('p1_t0_r1' or
    'p1_t1_r1' when multiple (table, group) rows could match) never guess or attach
    to a product and instead require review.
    """
    from src.catalog_reader import parse_structural_table
    from src.catalog_corrections import save_corrections
    from src.catalog_diagnostics import (
        find_legacy_source_id_candidates,
        is_ambiguous_legacy_source_id,
        resolve_compatible_source_id,
    )

    class _MockCell:
        def __init__(self, bbox):
            self.bbox = bbox

    class _MockRow:
        def __init__(self, bboxes):
            self.cells = [b for b in bboxes]

    class _MockTable:
        def __init__(self, rows_data, y_offset=50.0):
            self._data = rows_data
            self.col_count = len(rows_data[0]) if rows_data else 0
            self.bbox = [20.0, y_offset, 560.0, y_offset + 80.0]
            self.rows = []
            for r_i, r in enumerate(rows_data):
                y0 = y_offset + r_i * 20.0
                bboxes = [[20.0 + c_i * 80.0, y0, 95.0 + c_i * 80.0, y0 + 18.0] for c_i in range(len(r))]
                self.rows.append(_MockRow(bboxes))

        def extract(self):
            return self._data

    # Table 0 has 2 groups (6 columns); Table 1 on the same page ALSO has 2 groups (6 columns)
    t0_data = [
        ["الخصم", "السعر", "الصنف", "الخصم", "السعر", "الصنف"],
        ["25", "100", "بانادول اكسترا اقراص", "30", "150", "كتافلام 50 مجم اقراص"],
    ]
    t1_data = [
        ["الخصم", "السعر", "الصنف", "الخصم", "السعر", "الصنف"],
        ["20", "210", "اوجمنتين 1 جم اقراص", "35", "80", "كونكور 5 مجم اقراص"],
    ]

    _, _, _, diag_t0 = parse_structural_table(_MockTable(t0_data, y_offset=50.0), page_idx=0, warehouse_name="مخزن", table_idx=0)
    _, _, _, diag_t1 = parse_structural_table(_MockTable(t1_data, y_offset=200.0), page_idx=0, warehouse_name="مخزن", table_idx=1)

    t0_sids = [r.source_id for g in diag_t0.groups for r in g.rows]
    t1_sids = [r.source_id for g in diag_t1.groups for r in g.rows]
    assert t0_sids == ["p1_t0_g0_r1", "p1_t0_g1_r1"]
    assert t1_sids == ["p1_t1_g0_r1", "p1_t1_g1_r1"]
    all_multi_sids = t0_sids + t1_sids
    assert len(set(all_multi_sids)) == 4, "Table 0 Group 1 and Table 1 Group 0 must never collide"

    # Verify ReviewIssue reconstructs all 4 components (page, table, group, row)
    iss = ReviewIssue(source_id="p1_t0_g1_r1", rejection_reason="invalid_price")
    assert iss.identity is not None
    assert (iss.identity.page, iss.identity.table, iss.identity.group, iss.identity.row) == (1, 0, 1, 1)

    # Verify ambiguity detection on multi-table / multi-group pages:
    # 'p1_t0_r1' could match p1_t0_g0_r1 or p1_t0_g1_r1; 'p1_t1_r1' could match p1_t0_g1_r1, p1_t1_g0_r1, or p1_t1_g1_r1
    assert is_ambiguous_legacy_source_id("p1_t0_r1", all_multi_sids) is True
    assert set(find_legacy_source_id_candidates("p1_t0_r1", all_multi_sids)) == {"p1_t0_g0_r1", "p1_t0_g1_r1"}
    assert resolve_compatible_source_id("p1_t0_r1", all_multi_sids) == "p1_t0_r1"
    assert is_ambiguous_legacy_source_id("p1_t1_r1", all_multi_sids) is True
    assert resolve_compatible_source_id("p1_t1_r1", all_multi_sids) == "p1_t1_r1"

    # Verify unambiguous legacy 3-part ID on a single-group page resolves uniquely
    single_group_sids = ["p1_t0_g0_r1", "p1_t0_g0_r2"]
    assert is_ambiguous_legacy_source_id("p1_t0_r1", single_group_sids) is False
    assert resolve_compatible_source_id("p1_t0_r1", single_group_sids) == "p1_t0_g0_r1"

    # Verify CatalogCorrectionService refuses to guess on a multi-group catalog (hayah_shibin.pdf has 2 groups on page 1: p1_t0_g0_r1 and p1_t0_g1_r1)
    corr_dir = tmp_path / "legacy_corr"
    set_corrections_dir(str(corr_dir))
    try:
        pdf_copy = tmp_path / "hayah_copy.pdf"
        shutil.copyfile("tests/fixtures/hayah_shibin.pdf", str(pdf_copy))
        save_corrections(
            str(pdf_copy),
            {
                "table_mappings": {},
                "field_corrections": {
                    "p1_t0_r1": {
                        "item_name": "تصحيح قديم غامض لا يجب تطبيقه تلقائيا",
                        "base_price": 99.0,
                        "discount_rate": 0.30,
                        "stock_status": True,
                    }
                },
                "excluded_rows": {"p1_t0_r2": "manual_exclusion"},
            },
            corrections_dir=str(corr_dir),
        )
        svc = CatalogCorrectionService(str(pdf_copy))
        res = svc.get_refreshed_catalog_result()

        # Ambiguous legacy IDs ('p1_t0_r1', 'p1_t0_r2') on a 2-group table must NOT modify or exclude any product
        assert "تصحيح قديم غامض لا يجب تطبيقه تلقائيا" not in res.dataframe["item_name"].values
        assert len(res.dataframe) == 571

        # Instead, they must be held as unresolved review issues and mark the catalog status as 'partial'
        ambig_issues = {i.source_id: i for i in res.issues_by_source_id.values() if i.source_id in ("p1_t0_r1", "p1_t0_r2")}
        assert set(ambig_issues.keys()) == {"p1_t0_r1", "p1_t0_r2"}
        for sid_key, amb_iss in ambig_issues.items():
            assert amb_iss.resolved is False
            assert amb_iss.rejection_reason == "ambiguous_legacy_correction_requires_review"
            assert "غامضة" in amb_iss.plain_explanation or "ambiguous" in amb_iss.plain_explanation.lower()
        assert res.diagnostics.status == "partial"
        assert res.diagnostics.requires_acknowledgment is True

        # Now verify that an explicit 4-part identity ('p1_t0_g0_r1', 'p1_t0_g0_r2') applies and reverts cleanly
        save_corrections(
            str(pdf_copy),
            {
                "table_mappings": {},
                "field_corrections": {
                    "p1_t0_g0_r1": {
                        "item_name": "صنف محدد بالهوية الرباعية الكاملة 500 مجم",
                        "base_price": 99.0,
                        "discount_rate": 0.30,
                        "stock_status": True,
                    }
                },
                "excluded_rows": {"p1_t0_g0_r2": "manual_exclusion"},
            },
            corrections_dir=str(corr_dir),
        )
        svc_exact = CatalogCorrectionService(str(pdf_copy))
        res_exact = svc_exact.get_refreshed_catalog_result()
        assert "صنف محدد بالهوية الرباعية الكاملة 500 مجم" in res_exact.dataframe["item_name"].values
        assert len(res_exact.dataframe) == 570  # 571 minus 1 unambiguously excluded row

        res_reverted = svc_exact.revert_correction("p1_t0_g0_r2")
        assert len(res_reverted.dataframe) == 571
    finally:
        set_corrections_dir(None)


# ============================================================================
# Stage 2: Font-Aware Decoding, Punctuation & Numeric Preservation
# ============================================================================

def test_stage2_ordinary_punctuation_and_digits_not_corrupted():
    text = "*# $ بلافيكس 75 مج* 28 قرص\n# اوتريفين نقط 1% 15 مل كبار"
    stripped = strip_illegal_characters(text)
    decoded = decode_custom_catalog_glyphs(stripped)
    assert "\n" in decoded
    assert "#" in decoded
    assert "*" in decoded
    assert "$" in decoded
    assert "1%" in decoded
    assert "75" in decoded
    assert "28" in decoded
    assert "ق" not in decoded[:5]  # \n was not turned into 'ق'


def test_stage2_numeric_sequences_ratios_and_decimals_preserved():
    assert fix_spaced_and_reversed_digits("ادويفلام 50 20 كبسوله") == "ادويفلام 50 20 كبسوله"
    assert fix_spaced_and_reversed_digits("زيروفازيت 10/10 30 قرص") == "زيروفازيت 10/10 30 قرص"
    assert fix_spaced_and_reversed_digits("سعر 1 4 4 ج") == "سعر 144 ج"

    d1, p1 = parse_dosage_and_pack("# اومنيك اوكاز .4 مجم 30 قرص مستورد")
    assert d1 == "0.4مجم"
    assert p1 == "30قرص"

    d2, p2 = parse_dosage_and_pack("وان الفا .25 مج اقراص / باكت 100")
    assert d2 == "0.25مج"

    d3, p3 = parse_dosage_and_pack(". #وان الفا 0.25 مكج 30 كبسوله")
    assert d3 == "0.25مكج"
    assert p3 == "30كبسول"

    d4, _ = parse_dosage_and_pack("ايموكسكلاف 642.9 مج 75 مل شراب")
    assert d4 == "642.9مج"

    # Display name retains original symbols/ratios while normalized_name is search-ready
    disp = "# كاندلكان بلس 12.5/32 مج 14 قرص"
    norm = normalize_arabic_text(disp)
    assert "12.5/32" in disp
    assert "#" in disp
    assert "12 5 32" in norm
    assert "#" not in norm


def test_stage2_tax_suffix_not_false_positive_catalog_noise():
    assert is_catalog_noise("# اميولانت ان 120 مل شراب.ض") is False
    assert is_catalog_noise("شراب.ض") is False
    assert is_catalog_noise("س.ت: 12345 ب.ض: 67890") is True


def test_stage2_font_recovery_without_system_reference_fonts(tmp_path, monkeypatch):
    """
    Verifies that font CMap repair succeeds using embedded fallback tables even when
    optional Windows system reference fonts (arial.ttf, calibri.ttf, etc.) are unavailable.
    """
    import src.pdf_font_decoder as pfd

    ref = _load_reference_fixture()["catalogs"]["el_abed"]
    pdf_path = _resolve_existing_path(ref["default_paths"])
    if not pdf_path:
        pytest.skip("El-Abed PDF not present on this machine")

    monkeypatch.setenv("WINDIR", str(tmp_path / "nonexistent_windows_dir"))
    monkeypatch.setattr(pfd, "_REF_TABLES_LOADED", False)
    monkeypatch.setattr(pfd, "_REF_HASH_TO_UNI", dict(pfd.FALLBACK_GLYF_HASH_TO_UNI))
    monkeypatch.setattr(pfd, "_REF_GID_TO_UNI", dict(pfd.FALLBACK_ARIAL_GID_TO_UNI))

    df = PDFCatalogParser(pdf_path).parse()
    meta = df.attrs["catalog_import"]
    assert len(df) == 230
    assert meta.status == "complete"
    assert meta.rejected_rows == 0
    assert df.iloc[0]["item_name"] == "# ابيدون 125 مل شراب"
    assert df.iloc[25]["item_name"] == "# اميولانت ان 120 مل شراب.ض"


# ============================================================================
# Stage 3: Page Assessment, Filename Independence & Quality Checks
# ============================================================================

def test_stage3_renaming_file_does_not_change_extraction_behavior(tmp_path):
    ref = _load_reference_fixture()["catalogs"]["hadaba_dual"]
    src_path = _resolve_existing_path(ref["default_paths"])
    if not src_path:
        pytest.skip("Hadaba dual-column PDF not present")

    renamed_path = str(tmp_path / "unfamiliar_supplier_catalog_999.pdf")
    shutil.copyfile(src_path, renamed_path)

    df_orig = PDFCatalogParser(src_path).parse()
    df_renamed = PDFCatalogParser(renamed_path).parse()

    assert len(df_renamed) == len(df_orig) == 1253
    assert df_renamed.attrs["catalog_import"].status == "complete"
    assert df_renamed["item_name"].tolist() == df_orig["item_name"].tolist()
    assert df_renamed["base_price"].tolist() == df_orig["base_price"].tolist()
    assert df_renamed["discount_rate"].tolist() == df_orig["discount_rate"].tolist()


def test_stage3_corrupted_rows_held_for_review_never_silently_accepted():
    grp = ProductGroup(group_index=0, raw_cols=[0, 1, 2], price_col=0, discount_col=1, name_col=2)
    # Row with replacement char U+FFFD
    item, reason, _ = extract_item_from_group_row(
        ["85", "25", "ابيدون \ufffd شراب"],
        group=grp,
        group_direction="forward",
        warehouse_name="مخزن اختبار",
    )
    assert item is None
    assert "suspicious_characters" in reason

    valid, v_reason = validate_catalog_item({
        "item_name": "بانادول \ufffd اقراص",
        "base_price": 50.0,
        "discount_rate": 0.20,
    })
    assert valid is False
    assert "suspicious_characters" in (v_reason or "")


def test_stage3_explicit_headers_never_swap_price_and_discount_on_outlier_row(tmp_path):
    """
    Verifies that when explicit headers establish the Price and Discount columns
    (['Disc', 'Price', 'Item Name']), an outlier row with 80.00 price and 95% discount
    is NEVER silently swapped into (price=95.0, discount=0.80). Instead, its source
    values (base_price=80.0, discount_rate=0.95) are preserved and the row is held
    for review under the documented discount validation bound (0 < discount <= 85%).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
    from reportlab.lib import colors
    from src.catalog_reader import parse_structural_table

    # 1. Structural reader path (multi-group table with explicit headers)
    class _MockRow:
        def __init__(self, ncols, y0):
            self.cells = [[20.0 + i * 80.0, y0, 95.0 + i * 80.0, y0 + 18.0] for i in range(ncols)]

    class _MockTable:
        def __init__(self, rows_data):
            self._data = rows_data
            self.col_count = len(rows_data[0])
            self.bbox = [20.0, 50.0, 500.0, 130.0]
            self.rows = [_MockRow(self.col_count, 50.0 + idx * 20.0) for idx in range(len(rows_data))]

        def extract(self):
            return self._data

    s_rows = [
        ["Disc", "Price", "Item Name", "Disc", "Price", "Item Name"],
        ["95%", "80.00", "Excessive Discount Drug", "25%", "120.00", "Normal Drug Tablets"],
    ]
    valid_items, _geom, _groups, t_diag = parse_structural_table(
        _MockTable(s_rows), page_idx=0, warehouse_name="Explicit_Header_WH", table_idx=0
    )
    assert t_diag.accepted_rows == 1
    assert sum(g.rejected_rows for g in t_diag.groups) == 1
    assert len(valid_items) == 1
    assert valid_items[0]["item_name"] == "Normal Drug Tablets"
    assert valid_items[0]["base_price"] == 120.0
    assert valid_items[0]["discount_rate"] == 0.25

    g0_row_diag = t_diag.groups[0].rows[0]
    assert g0_row_diag.source_id == "p1_t0_g0_r1"
    assert g0_row_diag.outcome == "rejected"
    assert g0_row_diag.reason == "invalid_discount_0.95"
    assert g0_row_diag.item is not None
    assert g0_row_diag.item["item_name"] == "Excessive Discount Drug"
    assert g0_row_diag.item["base_price"] == 80.0
    assert g0_row_diag.item["discount_rate"] == 0.95

    review_issue = g0_row_diag.to_review_issue()
    assert review_issue is not None
    assert review_issue.resolved is False
    assert review_issue.rejection_reason == "invalid_discount_0.95"
    assert review_issue.item["base_price"] == 80.0
    assert review_issue.item["discount_rate"] == 0.95

    # 2. Full PDFCatalogParser legacy single-group path on a real generated PDF
    pdf_path = str(tmp_path / "explicit_hdr_outlier_80_95.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    tbl = Table(
        [
            ["Disc", "Price", "Item Name"],
            ["95%", "80.00", "Excessive Discount Drug"],
            ["20%", "150.00", "Normal Drug 500mg"],
        ],
        colWidths=[60, 60, 240],
    )
    tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    doc.build([tbl])

    p = PDFCatalogParser(pdf_path, warehouse_name="Explicit_Header_WH")
    df = p.parse()

    assert len(df) == 1, "Only the valid 20% discount row may be accepted; the 95% row must be held for review"
    assert df.iloc[0]["item_name"] == "Normal Drug 500 mg"
    assert float(df.iloc[0]["base_price"]) == 150.0
    assert float(df.iloc[0]["discount_rate"]) == 0.20

    res = CatalogResult.from_dataframe(df)
    assert res.diagnostics.status == "partial"
    assert res.diagnostics.requires_acknowledgment is True
    assert res.diagnostics.rejected_rows == 1
    assert len(res.issues_by_source_id) == 1
    iss = next(iter(res.issues_by_source_id.values()))
    assert iss.rejection_reason == "invalid_discount_0.95"
    assert iss.resolved is False
    assert iss.item is not None
    assert iss.item["item_name"] == "Excessive Discount Drug"
    assert iss.item["base_price"] == 80.0
    assert iss.item["discount_rate"] == 0.95


# ============================================================================
# Stage 4: In-App Review, Crop, Plain Explanation, Exclude/Revert & Scoped Reuse
# ============================================================================

def test_stage4_review_explanations_and_reversible_scoped_corrections(tmp_path):
    corr_dir = tmp_path / "corrections"
    set_corrections_dir(str(corr_dir))
    try:
        pdf_a = tmp_path / "supplier_a.pdf"
        pdf_b = tmp_path / "supplier_b.pdf"
        shutil.copyfile("tests/fixtures/hayah_shibin.pdf", str(pdf_a))
        shutil.copyfile("input/catalogs/السلام شبين نقدي.pdf", str(pdf_b))

        svc_a = CatalogCorrectionService(str(pdf_a))
        base_res = svc_a.get_refreshed_catalog_result()
        base_count = len(base_res.dataframe)
        assert base_count == 571

        # 1. Correct a single row using unambiguous 4-part identity 'p1_t0_g0_r1'
        svc_a.apply_field_correction(
            "p1_t0_g0_r1",
            {
                "item_name": "صنف معدل تجريبي 500 مجم",
                "base_price": 123.5,
                "discount_rate": 0.25,
                "stock_status": True,
            },
        )
        res_after_edit = svc_a.get_refreshed_catalog_result()
        assert "صنف معدل تجريبي 500 مجم" in res_after_edit.dataframe["item_name"].values

        # Verify correction is NOT applied to a different catalog (scoped by SHA-256)
        svc_b = CatalogCorrectionService(str(pdf_b))
        res_b = svc_b.get_refreshed_catalog_result()
        assert "صنف معدل تجريبي 500 مجم" not in res_b.dataframe["item_name"].values

        # 2. Exclude a row using unambiguous 4-part identity 'p1_t0_g0_r2'
        res_after_excl = svc_a.exclude_row("p1_t0_g0_r2")
        assert len(res_after_excl.dataframe) == base_count - 1
        excl_issue = res_after_excl.issues_by_source_id["p1_t0_g0_r2"]
        assert excl_issue.resolved is True
        assert excl_issue.provenance == "manual_exclusion"
        assert "استبعاد" in excl_issue.plain_explanation

        # 3. Revert single row exclusion without losing p1_t0_g0_r1 edit
        res_after_revert = svc_a.revert_correction("p1_t0_g0_r2")
        assert len(res_after_revert.dataframe) == base_count
        assert "صنف معدل تجريبي 500 مجم" in res_after_revert.dataframe["item_name"].values

        # 4. Revert p1_t0_g0_r1 edit
        res_restored = svc_a.revert_correction("p1_t0_g0_r1")
        assert "صنف معدل تجريبي 500 مجم" not in res_restored.dataframe["item_name"].values

        # 5. Verify PDF crop rendering helper returns a PIL Image for valid bbox
        crop_img = render_pdf_row_crop(str(pdf_a), page_number=1, bbox=[40.0, 100.0, 520.0, 125.0])
        assert crop_img is not None
        assert crop_img.width > 20 and crop_img.height > 10
    finally:
        set_corrections_dir(None)


# ============================================================================
# Stage 5: Image-Only Page Assessment & Review Handling
# ============================================================================

def test_stage5_image_only_pdf_produces_actionable_review_not_false_success(tmp_path):
    # Create a 1-page image-only PDF by rasterizing a page with no digital text layer
    img_pdf_path = str(tmp_path / "scanned_image_only.pdf")
    src_doc = pymupdf.open("input/catalogs/السلام شبين نقدي.pdf")
    pix = src_doc[0].get_pixmap(dpi=100)
    src_doc.close()

    out_doc = pymupdf.open()
    page = out_doc.new_page(width=595, height=842)
    page.insert_image(page.rect, pixmap=pix)
    out_doc.save(img_pdf_path)
    out_doc.close()

    df = PDFCatalogParser(img_pdf_path).parse()
    meta = df.attrs["catalog_import"]
    diag = meta.diagnostics

    assert len(df) == 0
    assert meta.status in ("failed", "unverified")
    assert len(diag.pages) == 1
    assert diag.pages[0].page_classification == "image_only"
    assert diag.unresolved_region_count >= 1

    svc = CatalogCorrectionService(img_pdf_path)
    issues = svc.list_unresolved_issues()
    assert len(issues) >= 1
    assert "image_only" in issues[0].rejection_reason
    assert "صورة" in issues[0].plain_explanation


# ============================================================================
# Stage 6: Cache Protection (Quality-Based, Not Row-Count Alone)
# ============================================================================

def test_stage6_cache_protection_evaluates_quality_not_row_count_alone(tmp_path, monkeypatch):
    pdf_path = str(tmp_path / "cached_catalog.pdf")
    shutil.copyfile("input/catalogs/السلام شبين نقدي.pdf", pdf_path)

    # 1. Populate cache with known-good complete result (191 rows, 0 defects)
    good_df = PDFCatalogParser(pdf_path).parse()
    global_catalog_cache.set(pdf_path, good_df)
    good_res = CatalogResult.from_dataframe(good_df)

    # 2. A replacement with MORE rows (250) but 'partial' status and rejected rows IS degraded
    degraded_diag = ImportDiagnostics(
        pages=[
            PageDiagnostics(
                page=1,
                expected_count_known=True,
                accepted_rows=250,
                groups=[GroupDiagnostics(group=0, strategy="test", candidate_rows=260, accepted_rows=250, rejected_rows=10)],
            )
        ],
        accepted_rows=250,
        unique_records=250,
    )
    degraded_res = CatalogResult(dataframe=good_df.copy(), diagnostics=degraded_diag, fingerprint=good_res.fingerprint)
    assert is_replacement_quality_degraded(good_res, degraded_res) is True

    # 3. A replacement with FEWER rows (190, e.g. after excluding 1 row) but 'complete' status and 0 defects is NOT degraded
    clean_smaller_diag = ImportDiagnostics(
        pages=[
            PageDiagnostics(
                page=1,
                expected_count_known=True,
                accepted_rows=190,
                groups=[GroupDiagnostics(group=0, strategy="test", candidate_rows=190, accepted_rows=190, rejected_rows=0)],
            )
        ],
        accepted_rows=190,
        unique_records=190,
    )
    clean_smaller_res = CatalogResult(
        dataframe=good_df.iloc[:190].copy(),
        diagnostics=clean_smaller_diag,
        fingerprint=good_res.fingerprint,
    )
    assert is_replacement_quality_degraded(good_res, clean_smaller_res) is False
