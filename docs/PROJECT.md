# Project: Egyptian Pharmaceutical Procurement Engine Desktop App

## Architecture
The application consists of a layered desktop architecture:
1. **Core Domain & Allocation Engine (`src/`)**:
   - `allocator.py`: Two-pass deterministic and AI-assisted medicine procurement optimizer.
   - `pdf_parser.py`: PyMuPDF catalog extraction with Arabic RTL/Bidi correction and multi-column bucketing.
   - `excel_parser.py`: Order file ingestion with dynamic header discovery and quantity aggregation.
   - `normalizer.py`: Drug name cleaning, dosage extraction, and vendor normalization.
   - `pharma_matcher.py`: Clinical safety verification (dosage form, strength ratio, modifiers).
   - `report_generator.py`: Multi-sheet Right-to-Left (RTL) Arabic Excel workbook generator.
2. **Pipeline & Controller Layer (`src/pipeline.py` & `src/controller.py`)**:
   - `classify_files()`: Multi-tier file classification into daily purchase orders vs wholesaler catalogs.
   - `run_procurement_pipeline()`: Headless, progress-notifying execution harness.
3. **User Interface Layer (`app_gui.py` & `src/gui/`)**:
   - CustomTkinter Windows 11 styled GUI with dark/light mode and `Segoe UI` typography.
   - File & folder pickers, visual badges, override dropdowns, and remove buttons.
   - Asynchronous worker thread communicating via thread-safe `queue.Queue` with 50ms polling.
   - Post-run KPI summary dashboard and direct Windows Shell launch handlers (`os.startfile`, `explorer /select`).
   - Built-in `--self-test` CLI switch for headless verification.
4. **Distribution & Packaging**:
   - PyInstaller `.spec` packaging in `onedir` mode bundling all assets, fonts, and C-extension DLLs.
   - Inno Setup script (`installer.iss`) compiling non-elevated (`PrivilegesRequired=lowest`) `Setup.exe` with desktop/start menu shortcuts and Windows Add/Remove Programs registration.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Pipeline Decoupling | Expose programmatic pipeline API with progress reporting hooks | M1 | ORIGINAL_REQUEST §R2 |
| 2 | Auto-Categorization | 3-tier heuristic (ext, regex/keyword, content scan) separating orders from catalogs | M1 | ORIGINAL_REQUEST §R2 |
| 3 | Modern CustomTkinter UI | Dark/light Windows 11 responsive interface with Segoe UI typography | M2 | ORIGINAL_REQUEST §R1 |
| 4 | File Management UI | Scrollable card list with badges, item counts, remove buttons, and manual override | M2 | ORIGINAL_REQUEST §R1 |
| 5 | Directory Picker | Folder selection dialog for output report destination | M2 | ORIGINAL_REQUEST §R1 |
| 6 | Anti-Freeze Async Engine | Background worker thread with queue.Queue polling to prevent Windows "Not Responding" | M2 | ORIGINAL_REQUEST §R2 |
| 7 | Progress & Status Display | Determinate progress bar (0%-100%) and localized status descriptions | M2 | ORIGINAL_REQUEST §R1 |
| 8 | KPI Summary Dashboard | Post-run metrics cards (items requested, allocated, OOS, avg discount %, savings) | M2 | ORIGINAL_REQUEST §R1 |
| 9 | Windows Shell Integration | One-click actions to launch Excel report (`os.startfile`) and open folder in Explorer | M2 | ORIGINAL_REQUEST §R1 |
| 10 | Headless Self-Test Switch | CLI `--self-test` argument enabling automated GUI validation | M2 | Acceptance Criteria |
| 11 | App Icon & Assets | Multi-resolution Windows icon (`assets/app.ico`) and packaging resources | M3 | ORIGINAL_REQUEST §R4 |
| 12 | PyInstaller Spec & Build | Complete `onedir` build bundling customtkinter, pymupdf, rapidfuzz, openpyxl | M3 | ORIGINAL_REQUEST §R3 |
| 13 | Standalone Binary Verification | Automated test verifying `PharmaProcurement.exe` runs and executes `--self-test` | M3 | Acceptance Criteria |
| 14 | Inno Setup Script | `.iss` configuration for non-elevated user-space installation to LocalAppData | M4 | ORIGINAL_REQUEST §R4 |
| 15 | Shortcuts & Uninstaller | Start Menu, Desktop shortcuts, and Windows Add/Remove Programs registration | M4 | ORIGINAL_REQUEST §R4 |
| 16 | Installer Compilation | Compile standalone `Setup.exe` via Inno Setup Command-Line Compiler (`ISCC.exe`) | M4 | ORIGINAL_REQUEST §R4 |
| 17 | Silent Install Verification | Automated verification of silent install (`/VERYSILENT`), run, and clean uninstall | M4 | Acceptance Criteria |
| 18 | E2E Acceptance & Robustness | 100% test suite pass across Tiers 1-4 and Tier 5 adversarial hardening | Final | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Pipeline & Controller Bridge | `src/pipeline.py`, `src/controller.py`, file classification & progress callback | none | DONE |
| M2 | CustomTkinter GUI Desktop App | `app_gui.py`, Windows 11 dark/light UI, async thread queue, KPI cards, shell actions | M1 | IN_PROGRESS |
| M3 | PyInstaller Standalone Packaging | `assets/app.ico`, `PharmaProcurement.spec`, `dist/PharmaProcurement/` executable | M2 | PLANNED |
| M4 | Inno Setup Windows Installer | `installer.iss`, `Setup.exe`, shortcuts, uninstaller, silent lifecycle test | M3 | PLANNED |
| E2E | E2E Testing Track | `TEST_INFRA.md`, automated test suite (Tiers 1-4), `TEST_READY.md` | M1 | DONE |
| Final | Full Acceptance & Hardening | Pass 100% E2E tests, Tier 5 adversarial coverage hardening, audit verification | M4, E2E | PLANNED |

## Interface Contracts

### `src/pipeline.py` & `src/controller.py`
```python
def classify_files(file_paths: list[str]) -> dict[str, list[str]]:
    """Returns {'orders': [...], 'catalogs': [...], 'unknown': [...]}"""

def run_procurement_pipeline(
    order_files: list[str],
    catalog_files: list[str],
    output_dir: str,
    progress_callback: callable = None,  # callback(percent: float, message: str)
) -> dict:
    """Executes catalog parsing, allocation, report generation.
    Returns:
    {
        'results': dict,         # Allocator output dict with 'kpis', 'master_comparison', etc.
        'report_path': str,      # Absolute path to primary generated Excel workbook
        'arabic_report_path': str# Absolute path to Arabic alias workbook
    }
    Raises Exception with detailed diagnostics on failure.
    """
```

### `app_gui.py` (CLI & Headless Contract)
```bash
python app_gui.py               # Launches interactive CustomTkinter desktop GUI
python app_gui.py --self-test   # Headless self-test: loads CTK, verifies dependencies, exits 0
```

### `PharmaProcurement.exe`
```bash
PharmaProcurement.exe --self-test  # Headless self-test verifying frozen executable integrity
```

### Inno Setup Installer (`Setup.exe`)
```bash
Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="<target_dir>"
```

## Code Layout
```
Inventory-search/
├── assets/
│   ├── app.ico                     # Multi-res application icon
│   └── app_icon.png                # PNG source icon
├── src/
│   ├── __init__.py
│   ├── allocator.py                # MedicineAllocator
│   ├── pdf_parser.py               # PDFCatalogParser
│   ├── excel_parser.py             # Purchase order parser
│   ├── normalizer.py               # Arabic text & discount normalizer
│   ├── pharma_matcher.py           # Clinical safety rules
│   ├── report_generator.py         # Multi-sheet RTL Arabic Excel generator
│   ├── gemini_matcher.py           # Optional AI transliteration
│   ├── pipeline.py                 # Core execution pipeline
│   └── controller.py               # File classification & thread-safe controller
├── app_gui.py                      # CustomTkinter Windows 11 GUI entry point
├── PharmaProcurement.spec          # PyInstaller packaging spec
├── installer.iss                   # Inno Setup compilation script
├── tests/
│   ├── test_pipeline.py            # Headless pipeline unit tests
│   ├── test_gui.py                 # Headless CustomTkinter GUI unit & integration tests
│   ├── test_packaging.py          # PyInstaller & installer lifecycle tests
│   └── test_e2e_procurement.py     # E2E test suite (Tiers 1-4)
├── PROJECT.md                      # Project master index
├── TEST_INFRA.md                   # E2E test infra index
└── TEST_READY.md                   # E2E test suite completion signal
```
