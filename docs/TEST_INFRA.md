# E2E Test Infra: Egyptian Pharmaceutical Procurement Desktop App

## Test Philosophy
- Opaque-box, requirement-driven. Derives from ORIGINAL_REQUEST.md.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial + Real-World Workload Testing.
- Progressive testability: Verification mechanism does not depend on implementation details.

## Feature Inventory & Test Matrix
| # | Feature | Source | Tier 1 (Coverage) | Tier 2 (BVA/Corner) | Tier 3 (Pairwise) | Tier 4 (Real-World) |
|---|---------|--------|:-----------------:|:-------------------:|:-----------------:|:-------------------:|
| 1 | Pipeline Decoupling & Execution | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 2 | File Auto-Categorization | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 3 | Windows 11 GUI Initialization & Theme | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 4 | Multi-File Selection & UI Management | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 5 | Output Destination Selector | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 6 | Asynchronous Execution & Anti-Freeze | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 7 | Progress Bar & Status Reporting | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 8 | KPI Summary Dashboard Display | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 9 | Windows Shell File/Folder Launch | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 10 | Headless CLI Self-Test Flag | Acceptance Criteria | 5 | 5 | ✓ | ✓ |
| 11 | Application Icon & Assets | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 12 | PyInstaller Standalone Executable Build | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 13 | Standalone Binary Self-Test Execution | Acceptance Criteria | 5 | 5 | ✓ | ✓ |
| 14 | Inno Setup Installer Script | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 15 | Shortcuts & Uninstaller Creation | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 16 | Setup.exe Installer Compilation | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 17 | Silent Install & Uninstall Lifecycle | Acceptance Criteria | 5 | 5 | ✓ | ✓ |
| 18 | Arabic Multi-Sheet Excel Verification | Acceptance Criteria | 5 | 5 | ✓ | ✓ |

## Test Architecture
- Test Runner: `pytest`
- Test suite location: `tests/`
  - `tests/test_pipeline.py`: Tests pipeline execution, callbacks, and file classification.
  - `tests/test_gui.py`: Headless CustomTkinter GUI tests (`app.withdraw()`), events, queue polling, state transitions.
  - `tests/test_packaging.py`: Standalone binary execution, installer compilation, silent install/uninstall.
  - `tests/test_e2e_procurement.py`: End-to-end integration tests with real catalogs, Arabic text, Bidi numbers, and Excel workbook checks.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Standard Daily Order Run | F1, F2, F3, F4, F5, F6, F7, F8, F18 | High |
| 2 | Large Multi-Catalog Optimization (3000+ items) | F1, F2, F6, F7, F8, F18 | High |
| 3 | File Permission Conflict & Fallback Handling | F1, F6, F8, F18 | Medium |
| 4 | Headless Distribution Self-Test | F10, F12, F13 | Medium |
| 5 | Full User Installer Deployment Lifecycle | F14, F15, F16, F17 | High |

## Coverage Thresholds
- Tier 1: Feature Coverage (>=5 per feature)
- Tier 2: Boundary & Corner Cases (>=5 per feature)
- Tier 3: Cross-Feature Combinations (pairwise coverage of major feature pairs)
- Tier 4: Real-World Application Scenarios (>=5 realistic application scenarios)
