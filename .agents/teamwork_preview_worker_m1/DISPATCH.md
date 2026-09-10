# Dispatch: Worker M1 (Pipeline & Controller Bridge)

## Mission
Implement `src/pipeline.py` and `src/controller.py` to decouple the core procurement engine, provide programmatic execution with progress callbacks, and expose multi-tier file classification.

## File Ownership
- `src/pipeline.py` (Exclusive)
- `src/controller.py` (Exclusive)

## Key References
- ORIGINAL_REQUEST.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md
- PROJECT.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\PROJECT.md
- Domain Skill: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\skills\egyptian-pharma-procurement\SKILL.md
- Explorer 1 Handoff: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_survey_1\handoff.md
- Explorer 2 Handoff: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_survey_2\handoff.md

## 2026-09-10T20:57:26Z
You are Worker M1 (Pipeline & Controller Bridge).
Your working directory is: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_m1
Project root directory is: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search

MANDATORY INPUTS:
1. ORIGINAL_REQUEST.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md (Read first!)
2. PROJECT.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\PROJECT.md
3. Dispatch file: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_m1\DISPATCH.md
4. Domain Skill: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\skills\egyptian-pharma-procurement\SKILL.md
5. Explorer 1 Handoff: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_survey_1\handoff.md
6. Explorer 2 Handoff: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_survey_2\handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

EXCLUSIVE FILE OWNERSHIP:
You exclusively own and modify:
- `src/pipeline.py`
- `src/controller.py`

TASK:
1. Create `src/pipeline.py` implementing `run_procurement_pipeline(order_files: list[str], catalog_files: list[str], output_dir: str, progress_callback: callable = None) -> dict`.
   - Ingests all PDF catalogs (`PDFCatalogParser`) and Excel/CSV catalogs (`parse_excel_catalog`).
   - Ingests all purchase orders (`load_purchase_order`), combining requested items.
   - Triggers `progress_callback(percent, message)` at key steps (catalog parsing, order loading, allocation, report generation).
   - Executes `MedicineAllocator(consolidated_inventory).allocate_order(buying_list)`.
   - Generates Excel workbook using `ArabicExcelReportGenerator(results, output_dir=output_dir).generate()`.
   - Returns dict with `results`, `report_path`, `arabic_report_path`, `kpis`.
   - Catches exceptions and returns detailed diagnostics.
2. Create `src/controller.py` implementing:
   - `classify_files(file_paths: list[str]) -> dict[str, list[str]]`: 3-tier heuristic (PDF -> catalog; name regex/keywords -> order; content inspection -> order; else catalog).
   - `ProcurementEngineBridge`: Helper class for background worker threading and `queue.Queue` communication with the GUI.
3. Test your implementation by running a test script or command against the sample files in `input/catalogs` and `input/orders`. Verify the generated Excel workbook.
4. Write your completion report to:
   `c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_m1\handoff.md`
   Send a completion message back to the orchestrator referencing the handoff path and summarizing test results.
