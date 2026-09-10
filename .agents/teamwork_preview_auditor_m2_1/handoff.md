# Forensic Audit Report: Milestone M2 — CustomTkinter Windows 11 GUI

**Date**: 2026-09-11T01:26:30Z  
**Auditor**: Forensic Auditor (Milestone M2)  
**Working Directory**: `c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_auditor_m2_1`  
**Target File**: `c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_auditor_m2_1\handoff.md`  
**Work Product Audited**:
- `app_gui.py` (Modern CustomTkinter Windows 11 Desktop Application)
- `tests/test_gui.py` (Automated Test Suite covering Tiers 1-4)
- User Constraints: `ORIGINAL_REQUEST.md` (Integrity Mode: `development`)

---

## Forensic Audit Report

**Work Product**: `app_gui.py` and `tests/test_gui.py`  
**Profile**: General Project  
**Integrity Mode**: `development` (per `ORIGINAL_REQUEST.md`)  
**Verdict**: **CLEAN**

### Phase Results
- **Hardcoded Test Results Check**: PASS — Zero hardcoded expected outputs, constant returns, or simulated results in `app_gui.py`.
- **Facade Implementation Check**: PASS — Genuine CustomTkinter desktop interface (1,036 lines), comprehensive layout, active widget hierarchy, real Segoe UI font styling, thread-safe asynchronous worker bridge, and Windows shell launchers.
- **Fabricated Verification Outputs Check**: PASS — All test runs executed fresh; no pre-cached fake logs or mocked completion indicators.
- **Binding to ProcurementEngineBridge**: PASS — Clicking Run (`_on_run_optimization`) instantiates `ProcurementEngineBridge` and runs `run_procurement_pipeline` on a background daemon thread with thread-safe queue polling every 50ms.
- **KPI Binding Verification**: PASS — Live engine output dictionary (`total_items`, `matched_items`, `deterministic_matches`, `out_of_stock`, `avg_discount`, `total_savings`, `allocation_counts`) dynamically bound to UI metric cards and winner badges.
- **Automated Test Suite Authenticity**: PASS — All 25 tests in `tests/test_gui.py` assert concrete structural and behavioral properties with zero trivial passes (`assert True` absent).
- **Headless Self-Test CLI Switch**: PASS — `python app_gui.py --self-test` cleanly executes, validates widget trees, and exits 0.

---

## 1. Observation

### 1.1 Static Analysis of Source Files
1. **`app_gui.py`**:
   - Lines 19–25: Genuine imports of `classify_files`, `ProcurementEngineBridge`, `run_procurement_pipeline`, and `PipelineExecutionError`.
   - Lines 30–53: Modern Windows 11 styling via `customtkinter` with Deep Navy accent (`#1F4E79`), emerald green order badges (`#059669`), sky blue catalog badges (`#0284C7`), and native `Segoe UI` fonts.
   - Lines 56–111: Native Windows shell hooks: `os.startfile(norm_path)` and `subprocess.run(["explorer", f"/select,{target_path}"])`.
   - Lines 113–228: `FileListModel` manages `FileItem` objects, invokes `classify_files` on ingest, tracks manual overrides (`set_override`), and enforces validation gating requiring $\ge 1$ order, $\ge 1$ catalog, and valid output path.
   - Lines 229–601: `PharmaProcurementApp(ctk.CTk)` builds left sidebar (branding, folder destination picker, optimization run button, theme menu) and main area (toolbar, scrollable file cards with remove button and override dropdown, progress bar, status label, 5 KPI cards, winning wholesaler pill badges, and report/folder open buttons).
   - Lines 803–864: `_on_run_optimization` validates inputs, creates `self.bridge = ProcurementEngineBridge()`, dispatches `self.bridge.start(...)` in a daemon background thread, and schedules `self.after(50, self.poll_queue)` to consume messages without freezing the GUI.
   - Lines 865–904: `_on_pipeline_completed` binds actual dictionary values from `results['kpis']` directly to `card_req`, `card_alloc`, `card_oos`, `card_disc`, `card_sav`, and `wholesalers_pills_label`, and enables report opening buttons.
   - Lines 981–1022: CLI switch `--self-test` invokes `run_headless_self_test()` which withdraws the window, validates component presence, and returns 0.
   - Zero occurrences of dummy mock keywords (`mock`, `fake`, `dummy`, `simulate`, `sleep`) found in `app_gui.py`.

2. **`tests/test_gui.py`**:
   - Contains 25 comprehensive unit and integration tests across Tiers 1-4.
   - Genuine assertions covering headless initialization, theme switching, typography, deduplication, auto-classification, manual override toggle, file removal, destination directory setting, validation gating, async queue message consumption (`PROGRESS`, `DONE`, `ERROR`), Windows shell launching, boundary values (0 B, KB, MB formatting, empty paths, zeroed KPIs), and real domain file ingestion (`طلبية_اليوم.xlsx` and `الشركة_المتحدة.pdf`).

### 1.2 Verbatim Tool Commands and Outputs

#### Check 1: Headless Self-Test CLI Switch
- **Command**: `python app_gui.py --self-test`
- **Output**:
  ```
  [SELF-TEST] Launching headless CustomTkinter GUI self-test...
  [SELF-TEST] CustomTkinter Windows 11 GUI initialized, validated, and verified cleanly.
  ```
- **Exit Code**: `0`

#### Check 2: Automated GUI Test Suite (Tiers 1-4)
- **Command**: `python -m pytest tests/test_gui.py -v`
- **Output**:
  ```
  ============================= test session starts =============================
  platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\omart\AppData\Local\Python\pythoncore-3.14-64\python.exe
  cachedir: .pytest_cache
  rootdir: C:\Users\omart\.gemini\antigravity\scratch\Inventory-search
  plugins: anyio-4.14.2
  collecting ... collected 25 items

  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f3_headless_instantiation PASSED [  4%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f3_theme_switching PASSED [  8%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f3_bilingual_typography PASSED [ 12%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f4_file_addition_and_deduplication PASSED [ 16%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f4_auto_classification PASSED [ 20%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f4_manual_category_override PASSED [ 24%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f4_file_removal_and_clear PASSED [ 28%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f5_destination_directory_picker PASSED [ 32%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f6_validation_gate PASSED [ 36%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f6_async_bridge_progress_queue PASSED [ 40%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f6_async_bridge_done_queue PASSED [ 44%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f6_async_bridge_error_queue PASSED [ 48%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f9_windows_shell_actions PASSED [ 52%]
  tests/test_gui.py::TestTier1GUIFeatureCoverage::test_f10_headless_self_test_function PASSED [ 56%]
  tests/test_gui.py::TestTier2BoundaryAndCornerCases::test_format_file_size_boundaries PASSED [ 60%]
  tests/test_gui.py::TestTier2BoundaryAndCornerCases::test_empty_and_whitespace_paths PASSED [ 64%]
  tests/test_gui.py::TestTier2BoundaryAndCornerCases::test_empty_output_directory_validation PASSED [ 68%]
  tests/test_gui.py::TestTier2BoundaryAndCornerCases::test_override_flip_multiple_times PASSED [ 72%]
  tests/test_gui.py::TestTier2BoundaryAndCornerCases::test_remove_nonexistent_path_no_crash PASSED [ 76%]
  tests/test_gui.py::TestTier2BoundaryAndCornerCases::test_kpi_binding_with_empty_or_zero_values PASSED [ 80%]
  tests/test_gui.py::TestTier2BoundaryAndCornerCases::test_shell_open_missing_file_handled_gracefully PASSED [ 84%]
  tests/test_gui.py::TestTier3PairwiseCombinations::test_file_addition_then_override_then_validation PASSED [ 88%]
  tests/test_gui.py::TestTier3PairwiseCombinations::test_disable_controls_during_run_and_re_enable_on_done PASSED [ 92%]
  tests/test_gui.py::TestTier4RealWorldScenarios::test_real_sample_files_ingestion_and_classification PASSED [ 96%]
  tests/test_gui.py::TestTier4RealWorldScenarios::test_real_full_catalog_batch_ingestion PASSED [100%]

  ============================= 25 passed in 9.01s ==============================
  ```
- **Exit Code**: `0`

#### Check 3: Empirical Live Execution Tracing (`verify_real_dispatch.py`)
To verify that clicking Run genuinely invokes `ProcurementEngineBridge` and binds live engine results to GUI widgets, the auditor ran an independent headless trace script using real domain inputs (`input/orders/طلبية_اليوم.xlsx` and `input/catalogs/الشركة_المتحدة.pdf`):
- **Command**: `python .agents/teamwork_preview_auditor_m2_1/verify_real_dispatch.py`
- **Output**:
  ```
  [AUDIT TRACE] Initializing headless PharmaProcurementApp...
  [AUDIT TRACE] Adding files:
    Order: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\input\orders\طلبية_اليوم.xlsx
    Catalog: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\input\catalogs\الشركة_المتحدة.pdf
  [AUDIT TRACE] Validation status: is_valid=True, reason=جاهز للبدء والتوزيع / Ready to optimize
  [AUDIT TRACE] Triggering _on_run_optimization()...
  [AUDIT TRACE] Verified ProcurementEngineBridge successfully created.
    -> Progress: 75.0% | جاري مطابقة الأصناف وتوزيعها على أعلى الخصومات... / Running allocation engine...
    [AI] Activating Gemini Flash for 2 unmatched / transliterated item(s)...
    -> Progress: 90.0% | جاري إنشاء تقرير المشتريات المجمع (RTL)... / Generating Excel report...
  [AUDIT TRACE] Execution completed in 3.23s
  [AUDIT TRACE] Engine KPIs: {'total_items': 8, 'matched_items': 6, 'deterministic_matches': 6, 'ai_assisted_matches': 0, 'out_of_stock': 2, 'avg_discount': np.float64(22.2), 'total_quantity': 70, 'total_public_value': 14305.0, 'total_purchase_cost': 11244.58, 'total_savings': 3060.42, 'savings_pct': 21.4, 'num_warehouses': 1, 'allocation_counts': {'الشركة المتحدة': 6}}
  [AUDIT TRACE] UI Widget Values:
    card_req: 8 (expected: 8)
    card_alloc: 6 (6 مؤكد) (expected: 6)
    card_oos: 2 (expected: 2)
    card_disc: 22.2% (expected: 22.2%)
    card_sav: 3,060.42 ج.م
    wholesalers: المخازن الموزع عليها: 🏆 الشركة المتحدة: 6
    open_report_btn state: normal
    open_folder_btn state: normal
  [AUDIT TRACE] Report path on disk: C:\Users\omart\AppData\Local\Temp\tmp0mze070s\Procurement_Order_Optimized_2026-09-11.xlsx
  [AUDIT TRACE] All real execution bindings verified successfully and authentically!
  ```
- **Exit Code**: `0`

---

## 2. Logic Chain

1. **User Requirement Mapping**:
   - `ORIGINAL_REQUEST.md §R1` mandates a modern Windows 11 CustomTkinter desktop app supporting Arabic and English, file selection with item counts, output directory picker, run button with active progress indicator, and post-run KPI summary card with direct open buttons.
   - Direct inspection of `app_gui.py` demonstrates exact compliance with all §R1 sub-requirements.
2. **Authenticity of Implementation vs. Prohibited Patterns**:
   - Grep search confirmed zero occurrences of mock keywords, simulated timers (`sleep`), or dummy returns.
   - Code inspection confirmed `PharmaProcurementApp` directly invokes `ProcurementEngineBridge`, receives real-time progress tuples `("PROGRESS", pct, message)` from the engine, and handles `("DONE", results)` by binding genuine metrics (`total_items`, `matched_items`, `out_of_stock`, `avg_discount`, `total_savings`).
3. **Execution Genuineness**:
   - The empirical trace script verified that triggering `_on_run_optimization` spawned the background worker thread, invoked `run_procurement_pipeline`, parsed real PDF catalog data, processed orders, handled quota fallback gracefully, generated the Excel report at the designated path, and populated all KPI cards with exact values computed by the deterministic allocator.
4. **Test Suite Validity**:
   - Review of `tests/test_gui.py` verified that all 25 tests contain substantive assertions evaluating state changes, error handling, widget states, and boundary conditions.
   - All tests pass 100% in 9.01s.

---

## 3. Caveats

- **External Uppercase Excel Writer in Python 3.14**: In `test_pipeline.py`, creating temporary test files with uppercase `.XLSX` via pandas without `engine="openpyxl"` caused a pandas internal error. In `tests/test_gui.py`, Worker M2 correctly specified `engine="openpyxl"` on all test fixtures, avoiding this issue entirely.
- **Packaging Out of Scope**: Packaging as standalone executable (`.spec` / `PharmaProcurement.exe`) and installer (`Setup.exe`) belongs to downstream Milestones M3 and M4.

---

## 4. Conclusion

Milestone M2 (`app_gui.py` and `tests/test_gui.py`) passes all forensic integrity checks under Development Mode (`ORIGINAL_REQUEST.md`).
- Verdict: **CLEAN**
- The CustomTkinter desktop application is authentic, thoroughly tested, free of facade implementations or simulated shortcuts, and genuinely connected to the core procurement engine.
- Milestone M2 is certified ready for PyInstaller packaging in Milestone M3.

---

## 5. Verification Method

To independently reproduce the forensic verification results:

1. **Verify CLI Headless Self-Test**:
   ```powershell
   python app_gui.py --self-test
   ```
   *Expected*: Returns exit code `0` with message `[SELF-TEST] CustomTkinter Windows 11 GUI initialized, validated, and verified cleanly.`

2. **Verify Full Automated Test Suite**:
   ```powershell
   python -m pytest tests/test_gui.py -v
   ```
   *Expected*: `25 passed` with exit code `0`.

3. **Verify Live Dispatch & Widget Binding**:
   ```powershell
   python .agents/teamwork_preview_auditor_m2_1/verify_real_dispatch.py
   ```
   *Expected*: Runs live pipeline on real sample files, binds matching KPIs to UI widgets, generates output report, and exits code `0`.
