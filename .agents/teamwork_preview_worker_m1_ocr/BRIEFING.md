# BRIEFING — 2026-09-10T23:17:07Z

## Mission
Implement Milestone 1: Catalog Inspection & On-Demand Arabic OCR Re-read using RapidOCR and RapidTable in src/pdf_parser.py, src/controller.py, src/pipeline.py, and app_gui.py, verified with unit tests.

## 🔒 My Identity
- Archetype: implementer, qa, specialist
- Roles: implementer, qa, specialist
- Working directory: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_m1_ocr
- Original parent: 3b92a196-eb1c-46f3-8ecb-542eb14e48e6
- Milestone: M1_OCR

## 🔒 Key Constraints
- Use RapidOCR + RapidTable (NOT upstream PaddleOCR, NOT Surya).
- Minimize shell run_command calls. Perform all code modifications, inspections, and file operations directly using file tools.
- Do not call ask_question under any circumstances.
- Batch python test commands into single runs.
- File write ownership: src/pdf_parser.py, src/controller.py, src/pipeline.py (optional catalog_cache), app_gui.py, tests/test_ocr_parser.py (and existing test files).
- Keep CustomTkinter UI completely responsive during OCR background threads.

## Current Parent
- Conversation ID: 3b92a196-eb1c-46f3-8ecb-542eb14e48e6
- Updated: not yet

## Task Summary
- **What to build**:
  1. PDF 300 DPI rasterization (page.get_pixmap(dpi=300)) in src/pdf_parser.py.
  2. RapidOCR ONNX Arabic extraction + RapidTable table structure parsing to DataFrame.
  3. Clean/map columns (اسم الصنف, سعر الجمهور, الخصم, etc.) to canonical schema.
  4. 3-tier degradation fallback: RapidTable -> RapidOCR line clustering -> PyMuPDF digital text.
  5. In-memory catalog cache in src/controller.py & pipeline pass-through in src/pipeline.py.
  6. GUI catalog file card count badges + "Re-read with OCR" async daemon thread in app_gui.py.
  7. Comprehensive unit and GUI self-test verification.
- **Success criteria**:
  - `parse_catalog_ocr` works and parses catalogs cleanly.
  - `inspect_catalog_counts` and `reread_catalog_with_ocr` in controller.
  - UI shows item count badge and asynchronous OCR button with responsive UI.
  - All tests pass (`pytest` and `app_gui.py --self-test`).
- **Interface contracts**: SCOPE.md § Interface Contracts
- **Code layout**: src/ for core logic, tests/ for tests, app_gui.py for GUI.

## Change Tracker
- **Files modified**: none yet
- **Build status**: pending initial inspection
- **Pending issues**: none

## Quality Status
- **Build/test result**: pending
- **Lint status**: clean
- **Tests added/modified**: tests/test_ocr_parser.py (planned)

## Loaded Skills
- **Source**: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\skills\egyptian-pharma-procurement\SKILL.md
- **Local copy**: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_m1_ocr\egyptian-pharma-procurement.md
- **Core methodology**: Wholesaler catalog ingestion, 2-column accounting format detection, Arabic name normalization, drug strength/form safety checks, optimal allocation.

## Key Decisions Made
- Lazy initialization of RapidOCR and RapidTable singletons to avoid startup lag.
- Convert PyMuPDF pixmap buffer directly into numpy BGR array without touching disk.
- HTML table output from RapidTable converted via pandas read_html with regex/string fallback.

## Artifact Index
- .agents/teamwork_preview_worker_m1_ocr/DISPATCH.md — Assignment instructions
- .agents/teamwork_preview_worker_m1_ocr/BRIEFING.md — Situational awareness
- .agents/teamwork_preview_worker_m1_ocr/progress.md — Heartbeat and step log
