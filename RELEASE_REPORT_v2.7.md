# Release Report — Version 2.7 (Pre-Release / In Preparation)

**Date:** 2026-11-07  
**Build Status:** Built & Verified Locally (Pre-Release Staged — **NOT PUSHED**)  
**Platform:** Windows 10 / 11 (64-bit)  

---

## 1. Executive Summary

Release 2.7 consolidates critical OCR strength source-fidelity safeguards, column-boundary coordinate token assignment, unknown-discount lifecycle preservation, and performance optimizations (persistent OCR worker process) into a unified standalone desktop package.

**Crucial Constraints & Guarantees**:
- **Zero Search Algorithm Modification**: Search, matching, ranking, and clinical allocation logic in `src/allocator.py` and `src/pharma_matcher.py` remain **strictly untouched (0 diff)**.
- **Pre-Release Status**: All artifacts, tests, and configuration files are prepared and staged locally. As requested, this release is **not published or pushed to origin**.
- **Scope Limitation**: Tested scope covers digital PDF/Excel catalogs and generated raster benchmark pages. Physical paper scans remain classified as **unverified**.

---

## 2. Artifacts & Cryptographic Verification

| Artifact | Path | Size | SHA-256 Hash |
| :--- | :--- | :--- | :--- |
| **Standalone Executable** | `dist/EgyptianPharmaOptimizer/EgyptianPharmaOptimizer.exe` | 23,511,774 B | `5FCAA7145FC61629F3A838DE9B698EEC3E7E621BC0696AAC68DEE336BB0146BE` |
| **Windows Setup Installer** | `dist_installer/EgyptianPharmaOptimizer_Setup_v2.7.exe` | 115,204,612 B | `E5812FDB8B066B8C4CEFB5B5E18DCEFB5505ECC63A15225FE55FADC46675A592` |
| **Core Normalizer** | `src/normalizer.py` | 89,848 B | `9EEA7A21C10015393DDA39DDAA47E42166D17BB10A1857E2DFC81E6F60317C6B` |
| **Clinical Allocator** | `src/allocator.py` | 33,074 B | `83298CF61E35A772F7BBE0380C850E08FF930C5E35F47CBF575AD834DFB5E42A` |
| **Pharma Matcher** | `src/pharma_matcher.py` | 31,529 B | `D1549DBAC26685690DA2897AA361809A643394A4F17451F4D951AE52EA9B36E4` |

*Note*: `src/allocator.py` and `src/pharma_matcher.py` match the pristine base repository byte-for-byte.

---

## 3. Key Enhancements in Version 2.7

### 3.1 OCR Strength Source-Fidelity Safeguards
- Removed speculative strength limits, unconditional ratio reversal, and trailing-digit truncation.
- Multi-component strengths (e.g. `5/40/12.5`) are not altered to conform to speculative drug ratios.
- Uncertain combination strengths and ambiguous spaced decimals are quarantined as unresolved review issues rather than guessed or fabricated.
- The known-defective RapidOCR engine is prohibited from independently validating or approving ambiguous critical fields.

### 3.2 Coordinate-Driven Token Assignment
- In `src/catalog_recovery.py`, OCR token routing strictly observes source table cell and column bounding boxes ($X_{\min}, X_{\max}$).
- Prevents price/discount token collision when values are identical (e.g., price `20.00` and discount `20%`).
- Retains non-numeric Arabic annotations (e.g., `ثلاجة` / cold chain) in product metadata without polluting price fields.

### 3.3 Unknown-Discount Lifecycle Preservation
- Preserves empty or unreadable discounts as `None`/unknown across extraction, caching, and procurement.
- Does not default missing discounts to `0.0`.
- In allocation and GUI reporting, distinguishes "offer found, discount unverified" from "out of stock", preventing underpriced or unjustified procurement decisions.

### 3.4 Persistent OCR Worker Architecture
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
