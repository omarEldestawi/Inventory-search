# Scope: Egyptian Pharmaceutical Procurement Engine - Final Deliverables

## Architecture
- Core Engine: `src/allocator.py`, `src/normalizer.py`, `src/pharma_matcher.py`, `src/pdf_parser.py`, `src/excel_parser.py`, `src/report_generator.py`
- Pipeline & Controller: `src/pipeline.py`, `src/controller.py`
- GUI: `app_gui.py` (CustomTkinter)
- OCR Engine: PyMuPDF (`fitz`), RapidOCR (`rapidocr_onnxruntime`), RapidTable (`rapid_table`)
- Packaging: `PharmaProcurement.spec`, PyInstaller, `installer.iss`, Inno Setup (`ISCC.exe`)
- Git Remote: `git@github.com:omarEldestawi/Inventory-search.git`

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Medication Count Display | Show detected medication count per catalog file in GUI | M1_OCR | ORIGINAL_REQUEST §R1 |
| 2 | On-Demand Arabic OCR Re-read | Asynchronous background OCR re-parsing using RapidOCR + RapidTable | M1_OCR | ORIGINAL_REQUEST §R1 |
| 3 | PyMuPDF 300 DPI Rasterization | Render PDF pages at 300 DPI (`page.get_pixmap(dpi=300)`) | M1_OCR | ORIGINAL_REQUEST §R1 |
| 4 | RapidOCR Arabic Text Extraction | ONNX CPU extraction of Arabic medication text | M1_OCR | ORIGINAL_REQUEST §R1 |
| 5 | RapidTable Column Detection | Detect table boundaries (`اسم الصنف`, `سعر الجمهور`, `الخصم`) to DataFrame | M1_OCR | ORIGINAL_REQUEST §R1 |
| 6 | PyInstaller Packaging | Standalone `.exe` bundling all dependencies, onnxruntime, CTK assets | M2_PyInstaller | ORIGINAL_REQUEST §R2 |
| 7 | Windows Installer Wizard | Inno Setup `.iss` compiled via `ISCC.exe` producing `Setup.exe` with shortcuts | M3_InnoSetup | ORIGINAL_REQUEST §R3 |
| 8 | GitHub Repository Backup | Initialize/verify repo `omarEldestawi/Inventory-search`, commit and push to main | M4_Git | ORIGINAL_REQUEST §R4 |
| 9 | Full Verification Suite | Self-test, pytest, binary execution, Setup.exe, git push | Final | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Catalog Inspection & OCR | `src/pdf_parser.py`, `src/controller.py`, `app_gui.py` | none | IN_PROGRESS |
| M2 | PyInstaller Standalone Executable | `PharmaProcurement.spec`, `dist/PharmaProcurement/` | M1 | PLANNED |
| M3 | Windows Installer Setup.exe | `installer.iss`, `Setup.exe` via `ISCC.exe` | M2 | PLANNED |
| M4 | Git Backup to GitHub | Remote `git@github.com:omarEldestawi/Inventory-search.git` push | M3 | PLANNED |
| Final | Acceptance & Verification | `--self-test`, pytest, standalone exe, Setup.exe, git | M1, M2, M3, M4 | PLANNED |

## Interface Contracts
### PDF Parser RapidOCR & RapidTable Integration
- `PDFCatalogParser.parse_catalog_ocr(pdf_path: str) -> list[dict]`
- Uses `fitz.open(pdf_path)`, renders `page.get_pixmap(dpi=300)`
- Calls `RapidOCR()` on image
- Calls `RapidTable()` on image / OCR results to reconstruct table DataFrame
- Maps detected columns to normalized fields (`name`, `price`, `discount_rate`, `category`, `vendor`)
- Feeds into existing `normalize_vendor_name`, `clean_drug_name`, and medicine matcher

### GUI Inspection & Background Async Contract
- File item card displays detected medication count badge (e.g. "245 items")
- "Re-read with OCR" button per catalog item card
- Runs background thread via controller / executor without freezing CTK GUI
- On completion, updates UI badge with new count and refreshes catalog cache

### Packaging & Installer Contracts
- PyInstaller: `dist/PharmaProcurement/PharmaProcurement.exe --self-test` passes
- Inno Setup: `Output/Setup.exe` compiles via `ISCC.exe installer.iss`
