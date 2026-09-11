# Handoff Report — Explorer 2 (GUI & Async Architecture Explorer)

**Date**: 2026-09-11  
**Working Directory**: `c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_m1_2`  
**Milestone**: Milestone 1 (Catalog Inspection & On-Demand Arabic OCR Re-read)  
**Status**: Complete (Hard Handoff)

---

## 1. Observation

1. **File Selection & Ingestion Lifecycle**:
   - In `app_gui.py` (lines 618-656), files are added via `_on_add_files()` (file dialog) or `_on_add_folder()` (directory traversal) and routed to `add_files(paths)`.
   - `FileListModel.add_paths(file_paths)` (lines 139-173) invokes `classify_files(candidates)` from `src.controller`.
   - In `src/controller.py` (lines 24-129), `classify_files()` executes a 3-tier heuristic: Tier 1 (extension check, where `.pdf` is unconditionally categorized as catalog), Tier 2 (regex pattern for date codes and order/catalog keywords), and Tier 3 (first 15 rows content peek).
   - In `app_gui.py` (lines 681-765), `_render_file_list()` iterates through `self.file_model.files` and instantiates a single-row `ctk.CTkFrame` per file item containing extension badge (col 0), name/size (col 1), category badge (col 2), override dropdown menu (col 3), and delete button (col 4).
   - In `app_gui.py` (lines 113-132), `FileItem` tracks `path`, `filename`, `ext`, `category`, `auto_category`, `is_override`, `size_bytes`, and `size_str`. **It does not store detected medication counts, parsed DataFrames, or OCR status flags.**

2. **Catalog Parsing & Ingestion in Pipeline**:
   - In `src/pipeline.py` (lines 213-228), `run_procurement_pipeline()` receives `catalog_files: list[str]`. Inside the ingestion loop, it parses PDF catalogs via `parser_inst = PDFCatalogParser(cat_file, warehouse_name=w_name)` and `df_cat = parser_inst.parse()`.
   - There is currently **no mechanism in `run_procurement_pipeline()` or `ProcurementEngineBridge` to receive pre-parsed or OCR-parsed DataFrames**. If a catalog is re-read with OCR in the GUI, running the pipeline would discard the OCR results and re-parse from scratch using standard parsing.

3. **Threading & Concurrency Model**:
   - In `src/controller.py` (lines 132-235), `ProcurementEngineBridge` spawns a daemon `threading.Thread` (`ProcurementEngineWorker`) executing `run_procurement_pipeline()`.
   - Communication with the GUI is handled exclusively through `queue.Queue` using tuples: `("PROGRESS", pct, msg)`, `("DONE", results)`, and `("ERROR", msg, tb)`.
   - In `app_gui.py` (lines 830-864), `poll_queue()` polls the bridge queue every 50ms using `self.after(50, self.poll_queue)` without blocking the Tkinter event loop.

4. **Test Suite Baseline & Self-Test**:
   - Running `python app_gui.py --self-test` exits with code 0:
     ```
     [SELF-TEST] Launching headless CustomTkinter GUI self-test...
     [SELF-TEST] CustomTkinter Windows 11 GUI initialized, validated, and verified cleanly.
     ```
   - Running `pytest tests/test_gui.py` passed 44 of 48 tests (failures observed: `NameError: ctk is not defined` on lines 1064/1119 of `tests/test_gui.py` due to missing import in test module; and `results.get("kpis")` returning `None` causing `'NoneType' object has no attribute 'get'` in `_on_pipeline_completed`).
   - Sample catalogs in `input/catalogs/` parsed via `PDFCatalogParser.parse()` yield:
     - `الشركة_المتحدة.pdf`: 7 items
     - `فارما_اوفرسيز.pdf`: 5 items
     - `مخزن_ابن_سينا.pdf`: 7 items

---

## 2. Logic Chain

1. **Count Display Necessity**:
   - Based on Observation 1 and the User Mandate, operators cannot see how many items each catalog contains before running optimization.
   - To show medication counts without freezing the GUI, `FileItem` must store `item_count`, `parsed_df`, `is_ocr`, and `status`.
   - On addition, standard parsing (`PDFCatalogParser.parse()` for PDF, `parse_excel_catalog()` for spreadsheets) runs in a background thread and updates the card badge upon completion.

2. **Card Layout & Action Placement**:
   - Based on Observation 1, the file list scroll area is ~620px wide. Fitting 6 wide controls on a single row truncates filenames.
   - Adopting a 2-row card layout (Row 0: extension, filename, category dropdown, delete; Row 1: count badge, "Re-read with OCR" button, live status) provides spacious targets and prevents clipping.
   - For PDF catalogs, an action button `🔄 إعادة قراءة بـ OCR / Re-read with OCR` allows on-demand re-parsing.

3. **Background Worker & Responsiveness**:
   - Based on Observation 3, CustomTkinter requires all UI modifications to run on the main thread.
   - Spawning OCR re-read in a background daemon thread (`threading.Thread`) and posting progress to a `queue.Queue` polled via `self.after(50, ...)` ensures 100% GUI responsiveness without freezing.
   - Progress events report per-page stages (300 DPI rasterization, RapidOCR Arabic extraction, RapidTable column detection) directly to the card status label.

4. **Caching Contract**:
   - Based on Observation 2, `run_procurement_pipeline` currently re-reads catalog files from disk.
   - To ensure OCR re-read results are actually utilized during procurement optimization, a thread-safe `CatalogCache` must be implemented in `src/controller.py`.
   - `run_procurement_pipeline` and `ProcurementEngineBridge.start` must accept an optional `catalog_cache: Optional[Dict[str, pd.DataFrame]] = None`. When present, cached DataFrames bypass disk re-parsing.

---

## 3. Caveats

1. **Parser Engine Implementation**: Explorer 1 is designing the internal implementation of `PDFCatalogParser.parse_ocr()`. This report focuses on the GUI, async worker bridge, and caching integration contracts.
2. **OCR Execution Time**: RapidOCR + RapidTable on CPU takes approximately 1-3 seconds per page depending on hardware. For 10+ page PDFs, visual feedback (current page / total pages) is critical to prevent operator cancellation.
3. **No Code Written**: Per read-only explorer constraints, no source code or test files were modified during this investigation.

---

## 4. Conclusion

1. **Data Model**: Enhance `FileItem` in `app_gui.py` with `item_count: Optional[int]`, `parsed_df: Optional[pd.DataFrame]`, `is_ocr: bool`, and `status: str`.
2. **UI Layout**: Transition catalog cards in `app_gui.py` to a 2-row layout. Row 1 features a medication count badge (`📦 {count} صنف / {count} items` or `⚠️ 0 صنف (يحتاج OCR)`), an on-demand `🔄 إعادة قراءة بـ OCR / Re-read with OCR` button (height=26), and a live stage progress label.
3. **Async Bridge**: Implement a non-blocking `CatalogOCRWorker` using `threading.Thread` and `queue.Queue`. Poll updates via `self.after(50, self._poll_ocr_queue)`.
4. **Caching Pipeline**: Implement a thread-safe `CatalogCache` in `src/controller.py`. Extend `ProcurementEngineBridge.start()` and `run_procurement_pipeline()` with `catalog_cache: Optional[Dict[str, pd.DataFrame]] = None` so that subsequent optimization runs use OCR-extracted DataFrames without disk re-reading.
5. **Localization**: Apply bilingual Arabic/English strings across all count badges, action buttons, and status indicators.

---

## 5. Verification Method

1. **Headless Self-Test**:
   ```powershell
   python app_gui.py --self-test
   ```
   *Expected Output*: `[SELF-TEST] CustomTkinter Windows 11 GUI initialized, validated, and verified cleanly.` with exit code 0.
2. **GUI & Bridge Test Suite**:
   ```powershell
   python -m pytest tests/test_gui.py tests/test_challenger_m1_bridge.py
   ```
3. **Interactive Inspection Verification**:
   - Launch `python app_gui.py`.
   - Add `input/catalogs/الشركة_المتحدة.pdf`.
   - Verify card renders with badge `📦 7 صنف / 7 items`.
   - Click `🔄 إعادة قراءة بـ OCR / Re-read with OCR`.
   - Verify button disables, status displays page progress, UI remains responsive, and count updates upon completion.
   - Run optimization and verify report generates using the OCR-cached data.
