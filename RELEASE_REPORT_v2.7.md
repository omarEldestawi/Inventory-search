# Release Report — Version 2.7

**Date:** 2026-11-08  
**Build Status:** Built & Verified (Ready for Release)  
**Platform:** Windows 10 / 11 (64-bit)  

---

## 1. Executive Summary

Release 2.7 delivers the **Responsive Manual Medication-Search Window**, **Old-Price Spreadsheet Exclusion Policy (`س ق` / `ق س`)**, **OCR Strength Source-Fidelity Safeguards**, **Coordinate-Driven Token Assignment**, **Unknown-Discount Lifecycle Preservation**, and **Persistent OCR Worker Architecture** in a unified standalone desktop package and Windows installer.

**Crucial Constraints & Guarantees**:
- **Zero Search Algorithm Modification**: Search, matching, ranking, normalization, and clinical allocation logic in `src/allocator.py`, `src/pharma_matcher.py`, and `src/normalizer.py` remain **strictly untouched (0 diff)**.
- **Scope Limitation**: Tested scope covers digital PDF/Excel/CSV catalogs, orders, and generated raster benchmark pages. Physical paper scans remain classified as **unverified**.

---

## 2. Artifacts & Cryptographic Verification

| Artifact | Path | Size | SHA-256 Hash |
| :--- | :--- | :--- | :--- |
| **Standalone Executable** | `dist/EgyptianPharmaOptimizer/EgyptianPharmaOptimizer.exe` | 23,626,333 B | `D119A58026DB7AEBA988BC7F6360B6E653ADAF35F6E1CCC3E5F6AE6FF1F0DF11` |
| **Windows Setup Installer** | `dist_installer/EgyptianPharmaOptimizer_Setup_v2.7.exe` | 159,846,592 B | `B9C0B19451026D89A0814A21DF9A9022AC1282421A8A8E26D46AFEAEF170B833` |
| **Core Normalizer** | `src/normalizer.py` | 89,848 B | `9EEA7A21C10015393DDA39DDAA47E42166D17BB10A1857E2DFC81E6F60317C6B` |
| **Clinical Allocator** | `src/allocator.py` | 33,074 B | `83298CF61E35A772F7BBE0380C850E08FF930C5E35F47CBF575AD834DFB5E42A` |
| **Pharma Matcher** | `src/pharma_matcher.py` | 31,529 B | `D1549DBAC26685690DA2897AA361809A643394A4F17451F4D951AE52EA9B36E4` |

*Note*: `src/normalizer.py`, `src/allocator.py`, and `src/pharma_matcher.py` match the baseline repository byte-for-byte.

---

## 3. Key Enhancements in Version 2.7

### 3.1 Responsive Manual Medication-Search Window (`src/manual_search_window.py`, `src/manual_search_adapter.py`)
- Single reusable, non-blocking `CTkToplevel` window launched from the toolbar and sidebar (`🔍 بحث يدوي في الكتالوجات`).
- Thin adapter over existing matching entry points (`get_safe_candidate_matches`), resolving only active selected catalog files (`file_model.get_catalog_files()`) via validated cache access and rebuilding snapshots on catalog add, remove, refresh, or review edit.
- 60 ms GUI-thread input debounce, bounded background worker queue (at most 1 active job and 1 replaceable pending query) tagged with `(query_id, filter_id, catalog_generation_id)`, warehouse scope filtering, Best Match vs. Highest Discount display sort, 100-row cap, and separated reference weighted-discount display.
- In-place Treeview item recycling, scrollbar decoupling, and layout detachment achieving `7–11 ms` consecutive 100-row render latency (well within the `<= 200 ms` GUI responsiveness target).

### 3.2 Old-Price Spreadsheet Ingestion Exclusion Policy (`src/order_parser.py`, `src/excel_parser.py`, `src/pipeline.py`, `src/average_discounts.py`)
- Excludes spreadsheet rows ending in old-price markers (`س ق` or `ق س`, canonical regex `(?:^|\s)(?:س[\s.]*ق|ق[\s.]*س)\s*$`) across Excel and CSV purchase orders, supplier catalogs, and average-discount reference files.
- Preserves legitimate drug names (`س ج`, `اقراص`, `لاسيكس`, `زوفيراكس`) and all new-price rows.
- Tracks excluded rows via `ExcludedItem(reason="old_price_suffix")` with source file, sheet/row, raw name, and excluded quantity; prevents excluded order items from entering procurement allocations or out-of-stock sheets.
- Replaces filename-dependent row-count assertions in `load_average_discounts_file()` with schema and `[0.0, 1.0]` discount rate validation, and bumps `PARSER_REVISION = "2026.11.07.3"`.

### 3.3 OCR Strength Source-Fidelity Safeguards
- Removed speculative strength limits, unconditional ratio reversal, and trailing-digit truncation.
- Multi-component strengths (e.g. `5/40/12.5`) are not altered to conform to speculative drug ratios.
- Uncertain combination strengths and ambiguous spaced decimals are quarantined as unresolved review issues rather than guessed or fabricated.
- The known-defective RapidOCR engine is prohibited from independently validating or approving ambiguous critical fields.

### 3.4 Coordinate-Driven Token Assignment
- In `src/catalog_recovery.py`, OCR token routing strictly observes source table cell and column bounding boxes ($X_{\min}, X_{\max}$).
- Prevents price/discount token collision when values are identical (e.g., price `20.00` and discount `20%`).
- Retains non-numeric Arabic annotations (e.g., `ثلاجة` / cold chain) in product metadata without polluting price fields.

### 3.5 Unknown-Discount Lifecycle Preservation
- Preserves empty or unreadable discounts as `None`/unknown across extraction, caching, and procurement.
- Does not default missing discounts to `0.0`.
- In allocation and GUI reporting, distinguishes "offer found, discount unverified" from "out of stock", preventing underpriced or unjustified procurement decisions.

### 3.6 Persistent OCR Worker Architecture
- Replaced per-crop PowerShell / sub-process invocations with a persistent background OCR worker.
- Implements cached language recognition, bounded retries, and bounding-box result caching, significantly speeding up evaluation of image-heavy catalogs.

---

## 4. Benchmark & Test Verification

### 4.1 Untouched Raster Benchmark Accounting
On the evaluated generated raster catalog (`tests/fixtures/untouched_raster_page3.pdf`):
- **Candidate Rows Detected:** 28
- **Accepted Verified Rows:** 24
- **Quarantined / Unresolved Rows:** 4 (`p1_t0_r6`, `p1_t0_r9`, `p1_t0_r10`, `p1_t0_r16`)
- **Safety Rule Enforced:** All 4 uncertain strength/decimal rows are held outside the procurement pipeline with explicit `ReviewIssue` records. Automatic completion is intentionally bounded to preserve clinical safety.

### 4.2 Test Suite Execution
- **Targeted Regression Suite:** 83 tests passed, 14 subtests passed (including source-fidelity, coordinate bounds, discount lifecycle, and isolated search equivalence).
- **Executable Self-Test:** `dist\EgyptianPharmaOptimizer\EgyptianPharmaOptimizer.exe --self-test` executed with return code `0`.
- **Packaged Raster Verification:** Headless extraction on packaged binary verified 24 accepted / 4 quarantined items.
- **Inno Setup Compilation:** Setup launcher generated successfully with code signing / manifest integrity intact.

---

## 5. Scope & Limitations Notice
- **Digital Catalogs (PDF/Excel):** Fully supported across ArwaSoft, OrgaSoft, and standard multi-column layouts.
- **Generated Raster Fixtures:** Supported with deterministic 24/28 row verification and safe quarantining.
- **Physical Paper Scans:** **Unverified**. Real scanned paper documents with skew, low DPI, or physical artifacts require separate physical-scan benchmark fixtures before production claims can be made.
