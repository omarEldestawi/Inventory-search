# Egyptian Pharma Optimizer Version 2.5 — Test Verification Report

Final local release verification, rebuilt artifacts, the completed 23-catalog audit,
and the strengthened procurement test are documented in
[V25_LOCAL_ACCEPTANCE.md](docs/current/V25_LOCAL_ACCEPTANCE.md). The results below
describe the earlier QA run.

**Date**: 2026-10-28  
**Author**: Independent QA Test Engineer (`qa_m2d_e2e`)  
**Status**: TEST READY (All 33 New Verification Tests Passed, 268 Baseline Tests Passing, 0 Regressions)

---

## 1. Quick Test Runner Commands

### Run Full Milestone 2D Test Suite (Targets 1, 2, and 3):
```powershell
python -m pytest tests/test_v25_target1_recovery.py tests/test_v25_target2_corrections.py tests/test_v25_target3_procurement_e2e.py -v
```

### Run by Specific Verification Target:
```powershell
# Verification Target 1: Extraction & Recovery Suite (15 tests)
python -m pytest tests/test_v25_target1_recovery.py -v

# Verification Target 2: Correction Integrity & Persistence Suite (12 tests)
python -m pytest tests/test_v25_target2_corrections.py -v

# Verification Target 3: Procurement E2E & Local Packaging Suite (6 tests)
python -m pytest tests/test_v25_target3_procurement_e2e.py -v
```

### Run Full Regression Suite:
```powershell
python -m pytest tests/test_v23_diagnostics_cache.py tests/test_v23_pdf_table_groups.py tests/test_m1_contracts_service.py tests/test_adversarial_challenger_m1.py tests/test_v25_target1_recovery.py tests/test_v25_target2_corrections.py tests/test_v25_target3_procurement_e2e.py
```

---

## 2. Test Execution Results Summary

| Target Suite | Test File | Tests | Status | Duration |
|---|---|:---:|:---:|:---:|
| **Target 1: Extraction & Recovery** | `tests/test_v25_target1_recovery.py` | 15 | **PASS (100%)** | ~18s |
| **Target 2: Correction & Persistence** | `tests/test_v25_target2_corrections.py` | 12 | **PASS (100%)** | ~21s |
| **Target 3: Procurement E2E & Packaging** | `tests/test_v25_target3_procurement_e2e.py` | 6 | **PASS (100%)** | ~12s |
| **Combined M2D Suite** | All 3 Target Suites | **33** | **PASS (100%)** | **71.26s** |
| **Core Baseline Regression** | Diagnostics, Groups, M1 Contracts | **268** | **PASS (100%)** | **4.23s** |
| **Total Verified Test Count** | Full Integration Suite | **301** | **PASS (100%)** | **~75s** |

---

## 3. Comprehensive Verification Coverage Checklist

### Verification Target 1: Extraction and Recovery Suite (`tests/test_v25_target1_recovery.py`)
- [x] **Coordinate Re-extraction**: Verified that cell values dropped or truncated during initial table border extraction are recovered directly from the vector PDF text stream (`page.get_text("words")` / `page.get_textbox(bbox)`) at row coordinates.
- [x] **Wrapped Arabic & Mixed Content**: Verified that multi-line wrapped Arabic medication names (e.g. `كونكور 5 مجم\n30 قرص`) and mixed Arabic/Latin names (`أوجمنتين 1 جم\nAugmentin 1g\n14 قرص`) reconstruct cleanly into canonical clinical identities with proper strength (`5مجم`, `1جم`) and unit pack (`30قرص`, `14قرص`) without reversing Latin letters or mangling Arabic characters.
- [x] **Headerless Continuations & Swapped Columns**: Verified that swapped price and discount columns (e.g. Price column containing `20%` and Discount column containing `180.00`) resolve deterministically when bounds are unambiguous (`0 < price < 10000`, `0 <= discount <= 0.85`). Verified headerless continuation rows map successfully against established table geometry.
- [x] **Multiple Tables Distinct Source Identity**: Verified that identical row indices across different tables or pages (`p1_t0_r2`, `p1_t1_r2`, `p2_t0_r2`) produce unique source identities, and updates to one never overwrite colliding row indices in another table.
- [x] **Unidentified Table Layouts**: Verified that unmapped table layouts emit region-level issues (`source_id="pX_tY_region"`, `row=None`, `is_region_issue=True`) without hallucinating candidate row counts (`candidate_rows=0`, `expected_count_known=False`), properly incrementing `unresolved_region_count`.
- [x] **Ambiguous / Contradictory Interpretations**: Verified that ambiguous interpretations (e.g. two numeric values in price range without percent indicator) remain strictly unresolved for human review without guessed or hallucinated values.
- [x] **Recovery Idempotency**: Verified that executing `run_bounded_automatic_recovery()` repeatedly produces identical row counts, identical DataFrame values, identical unresolved issue counts, and zero duplicate rows.
- [x] **Baseline Preservation**: Verified that 100% of baseline valid records are preserved unchanged across all benchmark catalogs:
  - Hayah Shibin (`tests/fixtures/hayah_shibin.pdf`): Exactly **571** valid items preserved.
  - Dawlia (`input/catalogs/شركة مخزن الدولية الحديثة للادوية.pdf`): Exactly **529** valid items preserved.
  - Zahra (`input/catalogs/تحديث زهره.pdf`): Exactly **1,167** valid items preserved.

### Verification Target 2: Correction Integrity & Persistence Suite (`tests/test_v25_target2_corrections.py`)
- [x] **Manual Field Edits Validation**: Verified that user edits to name, price, discount, and stock pass through identical `validate_catalog_item` rules. Valid edits update the catalog atomically with provenance `manual_correction`; invalid edits (empty name, header token, <=0 or >=10000 price, <0 or >0.85 discount) are rejected with explicit `ValueError` and inline validation errors.
- [x] **Explicit Zero vs. Blank Discount**: Verified that explicit zero discount (`0.0` or `"0%"`) is preserved as float `0.0`, while blank discount (`None` or `""`) is preserved as `None` (distinct from zero). Verified inline validation rejection for prices `<= 0.0`, prices `>= 10000.0`, discounts `< 0.0`, and discounts `> 0.85`.
- [x] **Column Mapping Preview & Atomic Application**: Verified that `preview_table_column_mapping` displays prospective transformations for all affected rows (both previously accepted and unaccepted rows) without mutating state. Verified that `apply_table_column_mapping` applies changes atomically across the entire table upon confirmation.
- [x] **Persistence Reload & Re-validation**: Verified that corrections persisted under `%LOCALAPPDATA%/EgyptianPharmaOptimizer/data/catalog_corrections/<sha256>.json` reload cleanly after application restart and re-validate against the source PDF.
- [x] **Modified Content Hash Mismatch Prevention**: Verified that modifying file content or SHA-256 digest at the same path immediately prevents correction application, refuses to transfer saved corrections, and notifies the caller.
- [x] **Corrupt Storage & Schema Graceful Recovery**: Verified that corrupted/malformed JSON syntax and incompatible future schema versions (`schema_version != 2.x`) fail gracefully with an explicit review explanation without crashing, returning clean empty corrections.
- [x] **Pristine State Reset**: Verified that `service.reset_corrections()` removes the persistent JSON correction file on disk, clears table mappings and field edits, and restores the catalog to the pristine auto-extracted state (re-verified on Hayah 571 baseline).
- [x] **Procurement & Inspection Parity**: Verified that the headless procurement pathway and GUI inspection pathway produce 100% identical DataFrames for the same corrected catalog.

### Verification Target 3: Procurement E2E & Packaging Suite (`tests/test_v25_target3_procurement_e2e.py`)
- [x] **End-to-End Procurement Allocation**: Verified that an order request allocated against a catalog containing a pristine auto-extracted item, an automatically recovered item, and a persisted manually corrected item successfully allocates all three items into the final procurement optimization output workbook, applying the winning discounts and optimal vendor allocations.
- [x] **Non-Elevated `%LOCALAPPDATA%` Operation**: Verified that default storage resolves strictly within `%LOCALAPPDATA%/EgyptianPharmaOptimizer/data/catalog_corrections`, installation directories (`Program Files`, `_internal`) are blocked from writes via `is_in_installation_dir`, and all operations run without administrative elevation.
- [x] **Zero Valid Items Procurement Block**: Verified that catalogs producing 0 valid items (empty file, all rows noise/unmapped) cause `run_procurement_pipeline` to raise `PipelineExecutionError` / block procurement execution.

---

## 4. Test Files and Artifact Locations

| Artifact | Absolute File Path | Description |
|---|---|---|
| Target 1 Suite | `C:\Users\omart\Desktop\Inventory-search-PC\tests\test_v25_target1_recovery.py` | 15 recovery and extraction unit & integration tests |
| Target 2 Suite | `C:\Users\omart\Desktop\Inventory-search-PC\tests\test_v25_target2_corrections.py` | 12 correction integrity & persistence tests |
| Target 3 Suite | `C:\Users\omart\Desktop\Inventory-search-PC\tests\test_v25_target3_procurement_e2e.py` | 6 E2E allocation, packaging & blocking tests |
| Test Readiness Document | `C:\Users\omart\Desktop\Inventory-search-PC\TEST_READY.md` | Authoritative test report and checklist |
| QA Handoff Report | `C:\Users\omart\Desktop\Inventory-search-PC\.agents\teamwork\qa_m2d_e2e\handoff.md` | 5-component QA engineering handoff report |
