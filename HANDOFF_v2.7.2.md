# Handoff & Architecture Document — Version 2.7.2
**Feature:** Native PowerToys Dual-Language OCR Worker + `±3`-Row Vertical Context Windowing  
**Date:** 2026-11-08  
**Status:** Core Engine Compiled, Wired & Verified (`test_v26_arabic_ocr_pipeline.py` & `test_v25_target1_recovery.py` 23/23 Passing)

---

## 1. Overview & Motivation

In Version 2.7, single-row and single-cell image crops in `Windows.Media.Ocr` frequently failed or returned empty/garbled text when cropped tightly around a single table row, whereas **Microsoft PowerToys Text Extractor** read the exact same region cleanly.

Investigation identified four root causes:
1. **Missing Vertical Layout Context:** `Windows.Media.Ocr` relies on a layout and line-spacing analyzer before character recognition. Feeding a single tight cell/row (~25–30 px tall) deprives the recognizer of baseline and line-spacing context.
2. **Lack of Upscaling & Border Padding:** PowerToys Text Extractor upscales small crops (`HighQualityBicubic`) and adds solid white padding around the bitmap before creating the WinRT `SoftwareBitmap`.
3. **Single-Language (`ar-SA`) Limitation:** Calling `ar-SA` alone often drops decimal points or misreads Latin characters (`Panadol`, `125.50`, `24.5%`), whereas running **both `ar-SA` and `en-US` concurrently** and preferring `en-US` on pure ASCII/numeric bounding boxes preserves both Arabic script and Latin/numeric precision.
4. **PowerShell Marshal Overhead:** Calling WinRT via PowerShell `Invoke-WinRt` reflection added significant overhead compared to a compiled native C# WinRT binary.

---

## 2. What Has Been Implemented & Wired in v2.7.2

### 2.1 Standalone Native C# WinRT Binary (`src/native_ocr/PowerToysOcrWorker.cs` & `.exe`)
- **Location:**
  - Source: [`src/native_ocr/PowerToysOcrWorker.cs`](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/native_ocr/PowerToysOcrWorker.cs)
  - Compiled Binary: `src/native_ocr/PowerToysOcrWorker.exe`
- **How It Works:**
  - Persistent background process communicating over UTF-8 newline-delimited JSON (`stdin` / `stdout`), emitting `__READY__` on startup.
  - **PowerToys Preprocessing:** Upscales images `2.0x` via `InterpolationMode.HighQualityBicubic` (when `origH < 400` or `upscale=true` with `origH < 1000`) and adds a `16px` solid white (`#FFFFFF`) border on all 4 sides.
  - **Dual-Language Recognition:** Runs `ar-SA` and `en-US` `Windows.Media.Ocr.OcrEngine` instances concurrently (`Task.WhenAll`), un-maps word bounding boxes back to the original unpadded/unscaled crop coordinates, normalizes Eastern Arabic digits (`٠-٩` → `0-9`), and merges `en-US` ASCII/numeric tokens with `ar-SA` Arabic tokens (including single-stroke noise guards so Arabic vertical strokes aren't misread as `"1"` or `"l"`).
  - **BiDi Line & Word Reconstruction:** Orders lines top-to-bottom and words Right-to-Left (`descending X`) when Arabic is present, while keeping closely-spaced non-Arabic runs (`gap <= 1.0 * avgH`, such as split decimals `"125"` + `".50"` or dosages `"10"` + `"mg"`) in Left-to-Right order.
- **Zero-SDK Compilation Command (Built-in Windows `.NET` + `WinMetadata`):**
  ```powershell
  & "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /optimize+ /target:exe `
    /out:"src\native_ocr\PowerToysOcrWorker.exe" `
    /r:"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Runtime.WindowsRuntime.dll" `
    /r:"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Runtime.dll" `
    /r:"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Threading.Tasks.dll" `
    /r:"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Web.Extensions.dll" `
    /r:"C:\Windows\System32\WinMetadata\Windows.Foundation.winmd" `
    /r:"C:\Windows\System32\WinMetadata\Windows.Globalization.winmd" `
    /r:"C:\Windows\System32\WinMetadata\Windows.Graphics.winmd" `
    /r:"C:\Windows\System32\WinMetadata\Windows.Media.winmd" `
    /r:"C:\Windows\System32\WinMetadata\Windows.Security.winmd" `
    /r:"C:\Windows\System32\WinMetadata\Windows.Storage.winmd" `
    "src\native_ocr\PowerToysOcrWorker.cs"
  ```

### 2.2 Python Context-Window Bridge (`src/native_ocr/win_context_ocr.py`)
- **Location:** [`src/native_ocr/win_context_ocr.py`](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/native_ocr/win_context_ocr.py)
- **Key Class:** `ContextWindowOCR`
  - `recognize_image(img_np, upscale=True, padding=16)`: Sends an image array to the persistent `PowerToysOcrWorker.exe` process and returns structured lines and word-level bounding boxes.
  - `extract_target_box_with_context(full_page_img, target_bbox, context_rows_above=3, context_rows_below=3, vertical_tolerance_ratio=0.35)`:
    1. Expands `target_bbox` vertically by `3` row-heights above and `3` row-heights below (`7` rows total) so `Windows.Media.Ocr` gets full table line-spacing context.
    2. Runs `PowerToysOcrWorker.exe` on the 7-row image.
    3. Maps all recognized word bounding boxes back to `full_page_img` coordinates.
    4. **Target-Band `Y` Filter:** Retains **only** words whose vertical midpoint `(wy0 + wy1) / 2` falls within the target row's vertical band `[y0 - 0.35*H, y1 + 0.35*H]` (or vertical overlap ratio `>= 0.50`), preventing any data leakage from the 3 rows above or 3 rows below.

### 2.3 Integration into Core OCR & Recovery Pipeline
1. **[`src/ocr_engine.py`](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/ocr_engine.py):**
   - `ArabicOCREngine._extract_windows_ocr()` now uses `ContextWindowOCR` (`PowerToysOcrWorker.exe`) as its primary fast-path before falling back to PowerShell.
   - Emits individual word-level bounding boxes `[wx0, wy0, wx1, wy1]` when a line contains multiple words so [`ImageTableDetector`](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/image_table_detector.py) can cluster and assign each token to its exact column (`name`, `price`, `discount`, `code`).
2. **[`src/catalog_recovery.py`](file:///c:/Users/omart/Desktop/Inventory-search-PC/src/catalog_recovery.py):**
   - `recover_by_ocr_ladder()` now includes **Tier 2B (`±3`-Row Vertical Context Window Expansion + Target Y-Band Filter)** using `ContextWindowOCR.extract_target_box_with_context()` at `180 DPI` when single-row crops fail.

---

## 3. Remaining Tasks for the Next Agent (v2.7.2 Completion Checklist)

The next agent continuing v2.7.2 should complete the following tasks:

### Task 1: Wire Interactive "Read Highlighted Box (PowerToys OCR)" into `CatalogReviewWindow` (`app_gui.py`)
- In [`app_gui.py`](file:///c:/Users/omart/Desktop/Inventory-search-PC/app_gui.py) (`CatalogReviewWindow._load_issue_into_editor` and `_build_right_pane`), add or wire a button (or automatic pre-fill suggestion) that runs `ContextWindowOCR.extract_target_box_with_context()` on the selected `ReviewIssue`'s PDF page and `bbox` (`±3` rows above/below) and populates/suggests the extracted text into the Candidate Item Editor (`name_var`, `price_var`, `disc_var`) when the pharmacist clicks to inspect or retry an unresolved row.
- *Optional UX enhancement:* Allow the user to drag a selection box on the left-pane PDF preview (`self.page_image_lbl`) to OCR any custom rectangle via `ContextWindowOCR` directly into the editor fields.

### Task 2: Evaluate & Tune Recovery on Quarantined / Unresolved Rows
- Check whether `recover_by_ocr_ladder` Tier 2B (`±3`-row context window) can recover additional rows on real wholesaler PDFs while **strictly preserving** the v2.7 clinical safety gate in `run_automatic_recovery`:
  - **Important Constraint:** Do **not** weaken `test_v26_strength_source_fidelity.py` or `test_v26_untouched_scanned_pages.py` (which require `unverified_ocr_strength_sequence` and `ambiguous_ocr_decimal` rows like `p1_t0_r6`, `p1_t0_r9`, `p1_t0_r10`, `p1_t0_r16` on `untouched_raster_page3.pdf` to remain quarantined unless verified by source fidelity rules).

### Task 3: Bundle `PowerToysOcrWorker.exe` in PyInstaller & Inno Setup
- Update [`EgyptianPharmaOptimizer.spec`](file:///c:/Users/omart/Desktop/Inventory-search-PC/EgyptianPharmaOptimizer.spec) and [`build_exe.py`](file:///c:/Users/omart/Desktop/Inventory-search-PC/build_exe.py) so `src/native_ocr/PowerToysOcrWorker.exe` is bundled into `dist/EgyptianPharmaOptimizer/src/native_ocr/PowerToysOcrWorker.exe` (and/or `assets/bin/PowerToysOcrWorker.exe`).
- Verify that `build_exe.py` automatically compiles `PowerToysOcrWorker.cs` via `csc.exe` if `PowerToysOcrWorker.exe` is missing or older than `.cs`.

### Task 4: Full Regression & Release Packaging for v2.7.2
- Run the full regression suite to ensure zero regressions:
  ```powershell
  python -m pytest tests/test_v26_arabic_ocr_pipeline.py tests/test_v25_target1_recovery.py tests/test_v26_strength_source_fidelity.py tests/test_v26_untouched_scanned_pages.py tests/test_v26_ocr_field_bounds.py tests/test_v26_unknown_discount_lifecycle.py -v
  ```
- Verify `src/allocator.py`, `src/pharma_matcher.py`, and `src/normalizer.py` remain untouched (`git diff` = 0 on those three files).
- Build the standalone executable and installer for `v2.7.2` and run `--self-test`.
