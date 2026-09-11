## Task Assignment: Explorer 2 (GUI & Async Architecture Explorer)
- Workspace: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search
- Your agent dir: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_m1_2
- Milestone: Milestone 1 (Catalog Inspection & On-Demand Arabic OCR Re-read)
- Scope Document: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\orchestrator_2\SCOPE.md
- User Request: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md
- Domain Skill: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\skills\egyptian-pharma-procurement\SKILL.md

## 2026-09-10T23:00:00Z
Mission: Investigate `app_gui.py` and `src/controller.py` for catalog inspection and on-demand OCR re-read.
User Mandate:
- In `app_gui.py` and `src/pdf_parser.py`: show medication count detected per catalog file in GUI.
- On-demand "Re-read with OCR" action per catalog.
- Must run asynchronously in background thread without freezing GUI, then update count.

Investigate and document in your `analysis.md` and `handoff.md`:
1. How files are selected, classified, and rendered in the GUI file list (`app_gui.py`).
2. How medication counts can be computed upon initial file addition / classification (or cached) and where the count label/badge should appear on each catalog card.
3. How and where the "Re-read with OCR" button should be placed on each catalog item in the file list.
4. How the background thread should be spawned (e.g. using `threading.Thread` or existing worker queue) so the GUI remains 100% responsive without freezing.
5. What progress/loading feedback should be shown while OCR is running (e.g. spinner / text "Running OCR...").
6. How the controller (`src/controller.py`) or pipeline should cache or store the re-read results so subsequent procurement runs use the OCR-parsed items instead of standard-parsed items.
7. Any bilingual (Arabic/English) labels needed for the inspect/re-read buttons and count badges.
