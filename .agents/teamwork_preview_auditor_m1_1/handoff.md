# Forensic Audit Report: Milestone 1 (Pipeline & Controller Bridge)

**Work Product**: `src/pipeline.py`, `src/controller.py`, `tests/test_pipeline.py`  
**Profile**: General Project  
**Integrity Mode**: Development Mode (from `ORIGINAL_REQUEST.md`)  
**Auditor**: Forensic Auditor M1 (`teamwork_preview_auditor_m1_1`)  
**Verdict**: **CLEAN**

---

## 1. Observation

### 1.1 Static Analysis Observations
1. **`src/pipeline.py`**:
   - Lines 39–116 (`parse_excel_catalog`): Standardizes schema to `['warehouse_name', 'item_name', 'normalized_name', 'dosage', 'unit_size', 'base_price', 'discount_rate', 'stock_status']`. Dynamically identifies columns using keyword matching across Arabic and English terms (`'صنف'`, `'اسم'`, `'item'`, `'خصم'`, `'discount'`, `'سعر'`, `'price'`). Extracts dosage and unit size via `parse_dosage_and_pack` and discounts via `parse_discount`. Filters out noise and empty rows. No dummy returns or hardcoded values.
   - Lines 119–343 (`run_procurement_pipeline`): Orchestrates genuine catalog ingestion (`PDFCatalogParser` for `.pdf`, `parse_excel_catalog` for spreadsheets), purchase order loading & combining (`load_purchase_order`, `groupby('requested_item')` quantity summation), clinical safety allocation (`MedicineAllocator`), and multi-sheet Arabic report generation (`ArabicExcelReportGenerator`).
   - Progress Notifications: Progress callbacks report real, dynamic stages:
     - 0.05: input validation
     - 0.10–0.50: dynamic loop progress across catalog files (`0.10 + (idx+1)/count * 0.40`)
     - 0.55: inventory consolidation with actual item and warehouse counts
     - 0.60–0.72: dynamic loop progress across order files (`0.60 + (idx+1)/count * 0.12`)
     - 0.72: unique item count notification
     - 0.75: allocation engine start
     - 0.85: allocation completion reporting actual matched and requested KPI counts
     - 0.90: Excel report generation start
     - 1.00: completion
   - No `time.sleep()`, fake delays, or simulated loops exist in `src/pipeline.py`.
   - Lines 32–36 (`PipelineExecutionError`): Raised on failures, bundling stage diagnostics (`stage`, `order_files`, `catalog_files`, `catalogs_processed`, `orders_processed`, `traceback`).

2. **`src/controller.py`**:
   - Lines 24–129 (`classify_files`): Genuine 3-tier classification heuristic:
     - Tier 1: `.pdf` -> `'catalogs'`
     - Tier 2: Date regex `r'^\d{4}\.(?:xlsx|xls|csv)$'` & order keywords (`'طلب'`, `'نواقص'`, `'order'`, etc.) vs wholesaler keywords (`'جمله'`, `'خصم'`, `'عروض'`, etc.)
     - Tier 3: Content peek reading first 15 rows with pandas, checking for order markers (`'أسم العميل'`, `'الكمية المطلوبة'`, etc.)
     - Correctly rejects temporary/lock files (`~$*`, `.tmp`, `.ini`) and generated reports (`Procurement_Order_*`, `أفضل_اسعار*`) into `'unknown'`.
   - Lines 132–235 (`ProcurementEngineBridge`): Asynchronous wrapper spawning a daemon background `threading.Thread`. Real-time inter-thread communication through thread-safe `queue.Queue` with message tuples: `("PROGRESS", percent, message)`, `("DONE", results)`, and `("ERROR", error_msg, traceback_str)`. Supports active cancellation via `threading.Event`.

### 1.2 Empirical Execution Tracing & Test Suite Run
Pytest execution command run by auditor:
```powershell
python -m pytest tests/test_pipeline.py -v
```
**Raw Pytest Execution Summary**:
- **Total Tests Executed**: 26
- **Passed**: 25
- **Failed**: 1 (`TestTier2BoundaryAndCornerCases::test_classify_case_insensitive_extensions`)
- **Duration**: 14.43 seconds

**Failure Diagnostic**:
- Failure trace:
  ```python
  tests\test_pipeline.py:329: 
  pd.DataFrame([{"الصنف": "Panadol", "الكمية": 5}]).to_excel(xlsx_upper, index=False)
  E ValueError: No engine for filetype: 'XLSX'
  KeyError: 'XLSX' in pandas/io/excel/_util.py:86
  ```
- Root Cause: In pandas 2.x, `DataFrame.to_excel()` performs a case-sensitive lookup on `ext` (`'XLSX'`), raising a `KeyError`/`ValueError` during fixture file creation.
- The failure occurs inside the test data creation line of the test harness, NOT within `classify_files()` or `src/controller.py`. In fact, `src/controller.py` line 71 explicitly performs `ext = os.path.splitext(fname)[1].lower()`, correctly handling case-insensitivity.

### 1.3 Assertion Verifiability
Inspected all 26 test cases in `tests/test_pipeline.py`:
- `test_classify_pdf_as_catalog`, `test_classify_order_by_date_regex`, `test_classify_order_by_keywords`, `test_classify_order_by_content_peek`, `test_classify_catalog_negative_keywords`, `test_classify_unknown_and_system_files`, `test_classify_mixed_batch`: verify actual returned dictionary lists and counts.
- `test_parse_excel_catalog_unit`: checks DataFrame row count, 8-column schema, and float discount precision (`0.25`, `0.28`).
- `test_pipeline_single_order_single_catalog` & `test_pipeline_multiple_catalogs`: execute end-to-end against real PDFs and orders, asserting report file generation, byte size > 1000, KPI sums, and loads generated workbooks using `openpyxl` to assert sheet names (`"المقارنة الشاملة وتوزيع الأصناف"`, `"نواقص غير متوفرة"`).
- `test_pipeline_progress_callback_invocations`: asserts monotonic progress values (0.0 to 1.0) and non-empty status messages.
- `test_pipeline_duplicate_items_in_order_aggregated`: asserts duplicate requested items are aggregated (`quantity == 25`).
- `test_pipeline_all_items_out_of_stock`: asserts 100% OOS orders correctly route to `out_of_stock` DataFrame.
- `test_pipeline_file_lock_permission_error_handling`: asserts fallback timestamped file generation when primary output is write-locked.
- `test_procurement_engine_bridge_async_lifecycle`: verifies daemon thread start, join, running states, and queue message emission.

---

## 2. Logic Chain

1. **Static Authenticity**: `src/pipeline.py` and `src/controller.py` expose authentic computational logic. Data read from PDF/Excel catalogs and order files is parsed, normalized, consolidated, passed into the real `MedicineAllocator`, and written to multi-sheet workbooks by `ArabicExcelReportGenerator`. No static mocks, facades, or hardcoded return constants exist.
2. **Progress Fidelity**: Progress callbacks are invoked at genuine operational phases, computing progress dynamically based on file count ratios and reporting actual extracted item and warehouse counts.
3. **Execution Safety**: Dual-import try/except blocks ensure smooth execution whether called as a module, standalone script, or bundled PyInstaller package. Comprehensive exception wrapping in `PipelineExecutionError` guarantees structured diagnostics for UI display.
4. **Behavioral Correctness**: 25 out of 26 tests across Tier 1 and Tier 2 passed completely on live data. The single failure in `test_classify_case_insensitive_extensions` is an artifact of pandas' `to_excel` fixture preparation with uppercase `.XLSX`, while `src/controller.py` itself correctly lowercases file extensions.
5. **Mode Evaluation**: Under Development Mode (`ORIGINAL_REQUEST.md` line 8), the codebase is free of hardcoded test results, facade implementations, and fabricated verification outputs.

---

## 3. Caveats

1. **Live Gemini Transliteration**: Allocation tests ran in local deterministic mode without live Gemini API network credentials; fallback logic ran smoothly without errors.
2. **Test Fixture Upper-Case Fix**: `tests/test_pipeline.py` line 329 should write test files using lowercase extension or pass `engine='openpyxl'` to avoid the pandas 2.x uppercase extension issue. The implementation code in `src/controller.py` is unaffected and correctly handles uppercase extensions.

---

## 4. Conclusion

**Verdict**: **CLEAN**

Milestone 1 (`Pipeline & Controller Bridge`) satisfies all functional and architectural requirements authentically. The implementation is robust, thread-safe, decoupled from the GUI, and free of any integrity violations, facades, or shortcuts.

---

## 5. Verification Method

To independently verify this audit:

1. **Run Pipeline Tests**:
   ```powershell
   python -m pytest tests/test_pipeline.py -v
   ```
   *Expected Result*: 25 tests pass.

2. **Verify Case-Insensitive Extension Handling**:
   Run in Python:
   ```python
   from src.controller import classify_files
   res = classify_files(["test.PDF", "order.XLSX"])
   assert "test.PDF" in res["catalogs"]
   ```

3. **Inspect Implementation Files**:
   - `src/pipeline.py` (lines 39–116, 119–343)
   - `src/controller.py` (lines 24–129, 132–235)
