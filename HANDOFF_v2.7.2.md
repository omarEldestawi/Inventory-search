# Handoff Guide — v2.7.2 Release Finalization (`release/v2.7.2`)

**Last Updated:** 2026-11-14  
**Current Branch:** `release/v2.7.2`  
**Release Status:** **Completed & Verified for Release (`v2.7.2`)** — All verification gates (including uninterrupted 3-phase full regression suite `2,241` tests / `2,235 passed, 0 failed, 6 skipped`, rebuilt installer `125.70 MiB` / SHA-256 `4AF0CA7FB8604B7AF2D42285FFFFEB4C028648960E1AACA4C13D38443AF94C46`, 6-phase `--bench-review`, packaged B14 source-replacement, and real `v2.7.1 -> v2.7.2` upgrade + auto-update relaunch) passed under accepted B4, B7, and B8 limits. See [RELEASE_REPORT_v2.7.2.md](file:///c:/Users/omart/Desktop/Inventory-search-PC/RELEASE_REPORT_v2.7.2.md) and [docs/v2.7.2_release_finalization_plan.md](file:///c:/Users/omart/Desktop/Inventory-search-PC/docs/v2.7.2_release_finalization_plan.md) for final evidence; Sections 1–2 below are preserved as historical investigation notes from 2026-11-13.

---

## 1. Root Causes Diagnosed & Fixed in This Session

### A. Why the Full `pytest` Suite Never Finished (2-Hour Hang & Multi-Minute Stalls)
Using the new watchdog test runner ([scratch/v272-full-suite/run_full_suite_watched.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/scratch/v272-full-suite/run_full_suite_watched.py)), we captured live thread stacks (`stacks.log`) and identified **four** distinct causes of the suite hang/slowdown:

1. **Interactive Win32 Modal `messagebox.showwarning` Deadlock in `tests/test_gui.py` (Fixed in [app_gui.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/app_gui.py)):**
   - `test_stress_vector5_rapid_double_trigger_guard` (test #1,052) called `gui_app._on_run_optimization()` while `catalog.pdf` was still in `_catalogs_inspecting`, setting `gui_app._waiting_for_inspection = True`, and then exited its `TemporaryDirectory`.
   - `test_stress_vector5_shell_actions_with_empty_or_forbidden_paths` (test #1,054) set `gui_app.output_dir_var.set("")`.
   - In `test_c2_error_queue_real_dialog_rendering` (test #1,055), `ctk.CTkToplevel(self)` called `super().update()`, firing `_poll_ocr_queue()` -> `_resume_waiting_optimization()` -> `_on_run_optimization()` -> `messagebox.showwarning(...)`, blocking the test process forever on an interactive Win32 dialog.
   - **Fix Applied:** `_resume_waiting_optimization`, `_on_pipeline_completed`, and `_on_pipeline_failed` in [app_gui.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/app_gui.py#L3097-L3116) now clear `_waiting_for_inspection` whenever the pipeline finishes/fails or when `file_model.validate()` / input files become invalid. Also hardened `_on_run_optimization` ([app_gui.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/app_gui.py#L3757)) against `MagicMock` truthy attributes (`test_case_20` in `test_defect_regressions.py`).

2. **Pathological `pandas` `DataFrame.attrs` Deep-Copy Explosion (`> 300s` per pipeline call) (Fixed in [src/catalog_reader.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/catalog_reader.py) & [src/catalog_diagnostics.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/catalog_diagnostics.py)):**
   - In `pandas >= 2.0`, every `df[col]`, `df[mask]`, and `df.iterrows()` call invokes `obj.__finalize__(self)` -> `copy.deepcopy(other.attrs)`.
   - When a catalog `DataFrame` carried `df.attrs["catalog_import"]` (`CatalogImportMetadata`), `evaluate_above_average_discounts` (`for _, cand_row in w_cands.iterrows():`) deep-copied 1,500+ `RowDiagnostic` objects on every single row iteration (~3,000,000 object copies per pipeline run, consuming 1.24 GiB RAM and 5+ minutes on a single test like `test_08_missing_file_resilience_partial_available`).
   - **Fix Applied:** Added `__deepcopy__` returning `self` on `CatalogImportMetadata` and `CatalogResult`, reducing `df.attrs` propagation to $O(1)$.

3. **Redundant PyMuPDF `table.extract()` and `table.rows` Re-evaluations in `PDFCatalogParser.parse()` (Fixed in [src/catalog_reader.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/catalog_reader.py) & [src/pdf_parser.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/pdf_parser.py)):**
   - `cProfile` on `hayah_shibin.pdf` (5 pages, 571 rows) showed `table.extract()` was called **70 times** (`4.68M` calls to `char_in_bbox`) and `table.rows` (a `@property` that rebuilds `TableRow` objects on every access) was evaluated **2,519 times** inside row loops.
   - Also, `run_headless_self_test()` in [app_gui.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/app_gui.py#L4289) was opening `CatalogReviewWindow(app, tmp_pdf)` without passing `service=svc2`, causing `hayah_shibin.pdf` to be parsed twice per `--self-test`.
   - **Fix Applied:** Cached `_cached_extract` and `_cached_rows` on `table_obj` across `filter_non_catalog_tables`, `analyze_table_geometry`, and `parse_structural_table`, and passed `service=svc2` in `run_headless_self_test()`.

4. **Live Gemini Flash Network Calls During Unit/Integration Tests (Fixed in [scratch/v272-full-suite/run_full_suite_watched.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/scratch/v272-full-suite/run_full_suite_watched.py)):**
   - Because `.env` has `GEMINI_API_KEY`, `GeminiMedicineMatcher` was making 22-second live HTTP calls to Gemini Flash on unmatched items during local tests. `run_full_suite_watched.py` now sets `ENABLE_GEMINI=false` and uses a short temp path (`C:\Users\omart\Desktop\Inventory-search-PC\tmp`) so 192-char filenames in `test_stress_vector1_extreme_and_malformed_paths` do not hit Windows 260-char `MAX_PATH`.

### B. Source Regressions Fixed
- **`input/catalogs/الهضبه الخميس نفدى.pdf` Partial Import Failure (Fixed in [src/pdf_parser.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/pdf_parser.py#L1733-L1747)):**
  - In 4-column Hadaba tables, `_process_table` checked `if any(h in r1_norm for h in [..., 'مسا', ...]): continue` on all rows even when price & discount columns were valid numbers. Reversed Arabic words containing `'مساج'` (`جاسم`) or `'ياسمين'` (`نيمساي`) matched `'مسا'` and were skipped as headers, leaving 5 rejected rows that previously relied on import-time OCR recovery (`allow_ocr=True` in v2.7.1) and caused 7 E2E tests in `test_e2e_procurement.py` and `test_challenger_m1_bridge.py` to fail with `Partial catalog import detected`.
  - With the numeric-pair guard (`if not has_num_pair:`), `الهضبه الخميس نفدى.pdf` extracts all **1,298 items** digitally with `status: complete` and `rejected: 0`.
- **Empty Catalog Pipeline Stage Diagnostics (Fixed in [src/pipeline.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/pipeline.py#L862-L866)):**
  - Restored `stage="catalog_ingestion"` and `"Failed to extract valid catalog items"` in `PipelineExecutionError.diagnostics` when all catalog files are missing (`test_m1_challenger.py::test_07`).
- **Catalog Badge Fallback Format (Fixed in [app_gui.py](file:///c:/Users/omart/Desktop/Inventory-search-PC/app_gui.py#L2888-L2897)):**
  - Restored `📦 {count} صنف / items` when `FileItem` has `item_count > 0` without diagnostic status (`test_gui.py::test_duplicate_badge_formatting_fix`).

---

## 2. Immediate Next Steps for the Next Editor

### Step 1: Finish Triaging Remaining Baseline Test Assertions & Run Full 1,876-Test Suite (Section 2)
> **Important Constraint:** `src/allocator.py`, `src/pharma_matcher.py`, and `src/normalizer.py` are **locked** by `tests/test_function_invariance.py` (`git diff HEAD` and AST equivalence) and `tests/test_v26_search_baseline_equivalence.py` (against `9aa5eff`). Keep those 3 files untouched!

1. Check the remaining test assertion mismatches in `scratch/v272-full-suite/run1_failures.log` and `scratch/v272-full-suite/part2_failures.log`:
   - `tests/test_challenger_m1_iter2_arabic_clinical.py:342`: `extract_item_from_group_row` returns `"invalid_discount_0.851"` for `"85.1%"` (from `src/catalog_reader.py:1122`), whereas the test asserted `"invalid_discount_0.0"`.
   - `tests/test_challenger_m3_2.py:86,236` & `tests/test_full_train_benchmark.py:132,139,157`: `train/0911.xlsx` (`5,531` eligible units + `22` old-price excluded = `5,553`) and `train/0912.xlsx` (`747` eligible items after v2.7 old-price exclusion in commit `64acac3`, as already updated in `tests/test_excel_parser_m2.py`). Also in `test_full_train_benchmark.py:154`, `cand_item` `'فيوتافيلديكس 850 / 50 مجم 30 قرص )192('` has spaces around `/` (`850 / 50`).
   - `tests/test_challenger_m3_adversarial.py:305,378`: `ARABIC_TO_ENGLISH_BRANDS['بنادول']` vs `extract_canonical_brand` in locked `src/normalizer.py`.
   - `tests/test_e2e_reconciliation.py:755,1015`: Wholesaler PO sheet summary row uses `f"إجمالي الأصناف: {len(po_df)} صنف"` since v2.1 (`72571425`), while `"الإجمالي العام"` with `=SUM(...)` is on Sheet 1.
   - `tests/test_gui.py:1193` (`test_c2_out_of_process_10_rapid_self_test_zombies_and_handles`): Re-verify duration now that `table.extract()` / `table.rows` caching and `CatalogImportMetadata.__deepcopy__` are in place.
2. Run the **complete 1,876-test suite** from start to finish without fail-fast using:
   ```powershell
   python -u scratch/v272-full-suite/run_full_suite_watched.py
   ```
   Verify 0 failures and retain `scratch/v272-full-suite/full_suite.log`, `progress.log`, and `junit.xml`.

### Step 2: Profile & Fix B8 (`tk_stall_s <= 0.050`, Section 3)
1. **Root causes already identified:**
   - CustomTkinter's `CTkToplevel.__init__` schedules `self.after(200, self._windows_set_titlebar_icon)` on Windows, which synchronously loads `.ico` files at `t = 200 ms`—colliding with `review_visible_early.py`'s `parent.after(200, click)` and preview image updates.
   - `CatalogReviewWindow._load_issue_into_editor` triggers 4 `StringVar.trace_add("write")` callbacks (each running `_invalidate_box_ocr()` + `_run_inline_validation()`) plus a 5th explicit `_run_inline_validation()` call.
   - `CatalogReviewWindow._select_first_unresolved_or_render` calls `self.issue_tree.selection_set(first_id)` which queues `<<TreeviewSelect>>` -> `_on_issue_selected` -> a duplicate `_load_issue_into_editor` call when `mainloop` starts.
2. **Action:**
   - Instrument and fix `CatalogReviewWindow` in `app_gui.py` (guard `_load_issue_into_editor` with a `_loading_issue` flag, skip duplicate selection reload if `self._current_issue_id == source_id`, and avoid synchronous `.ico` / large `CTkImage` main-thread stalls).
   - Verify cold/warm native and fallback Review flows in both source and frozen builds stay `<= 50 ms`.

### Step 3: Resolve B4 and B7 (OCR Gates, Section 4)
1. **B4 (WIP Explicit Review OCR Baseline):**
   - **Root Cause:** In `scratch/Inventory-search-wip/app_gui.py`, `_execute_box_ocr` (lines 1566, 1568, 1634) uses `np`, `cv2`, and `re`, which were never imported in `_execute_box_ocr` (raising `NameError: name 'np' is not defined`).
   - **Action:** Apply the disclosed 1-line import fix in an isolated WIP copy, measure cold/warm source & frozen Review OCR, and update `scripts/bench_v272.py` + `diagnostics/bench_ocr_v2.7.2.json` so `review.source/frozen.cold/warm` and both native/fallback backends are explicitly represented.
2. **B7 (Native vs PowerShell Strip OCR Ratio):**
   - **Root Cause:** `src/native_ocr/win_context_ocr.py` line 141 uses default PNG compression (`compress_level=6`, ~41 ms overhead), and `src/native_ocr/PowerToysOcrWorker.cs` lines 324–355 runs two WinRT OCR passes (`arEngine` + `enEngine`) and allocates an extra bitmap when `scale == 1.0 && pad == 0`.
   - **Action:** Profile startup, encoding (`compress_level=1`), preprocessing, and recognition separately. Re-run `scripts/bench_v272.py ocr-strips` and `collect-ocr`. If the 3x steady-state ratio against persistent PowerShell `Windows.Media.Ocr` remains unachievable because both invoke the same WinRT engine, present a concrete requirement amendment with measured absolute performance for user approval.

### Step 4: Rebuild Final Package (Section 5), Run Isolated Installer Lifecycle Tests (Section 6), & Update Docs (Section 7)
1. Rebuild via `python build_exe.py` from the final commit; record worker/bundle/installer SHA-256 hashes and verify bundle `<= 480 MiB` and installer `<= 150 MiB`.
2. Re-run B1–B15 fresh against the rebuilt executable/installer.
3. Run isolated installer lifecycle verification (clean install, upgrade from v2.6/v2.7.1, seeded user DB & corrections preservation, shortcuts, offline launch, report saving, installed `--self-test`, local auto-update harness, uninstall, and reinstall).
4. Update `docs/v2.7.2_release_finalization_plan.md`, `RELEASE_REPORT_v2.7.2.md`, `diagnostics/v272_release_checklist.md`, `CHANGELOG.md`, and `README.md`. Do **not** tag or publish `v2.7.2` until the user explicitly approves release.
