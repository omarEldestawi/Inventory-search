## 2026-09-10T23:17:07Z

You are Worker M1 (Catalog Inspection & RapidOCR + RapidTable Implementation Worker).
Your agent working directory: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_m1_ocr
Project root: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search
Authoritative user request: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md
Scope document: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\orchestrator_2\SCOPE.md
Domain skill: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\skills\egyptian-pharma-procurement\SKILL.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

URGENT DIRECTIVE FROM USER:
1. Minimize shell run_command calls. Perform all code modifications, inspections, and file operations directly using file tools (view_file, write_to_file, replace_file_content, grep_search, find_by_name) rather than terminal commands like cat, ls, or python -c.
2. Do not call ask_question under any circumstances.
3. When testing Python code, batch tests together into single test runs rather than multiple separate commands.
4. Auto-approve all subagent steps internally. Proceed without hesitation.

FILE WRITE OWNERSHIP:
You exclusively own and may edit:
- `src/pdf_parser.py`
- `src/controller.py`
- `src/pipeline.py` (only for adding optional catalog_cache parameter)
- `app_gui.py`
- `tests/test_ocr_parser.py` or updates to existing test files in `tests/`

YOUR MISSION (Milestone 1):
Implement Deliverable 1: Catalog Inspection & On-Demand Arabic OCR Re-read.
CRITICAL USER DIRECTIVE: Use RapidOCR + RapidTable (NOT upstream PaddleOCR, NOT Surya).
1. PyMuPDF (fitz) rasterizes PDF pages at 300 DPI (page.get_pixmap(dpi=300))
2. RapidOCR (from rapidocr_onnxruntime import RapidOCR) extracts Arabic text via ONNX CPU
3. RapidTable (from rapid_table import RapidTable) detects table column boundaries (اسم الصنف, سعر الجمهور, الخصم) and outputs clean pandas.DataFrame
4. Feed DataFrame rows into existing normalizer/matcher pipeline
5. Show medication count detected per catalog file in GUI (app_gui.py)
6. On-demand "Re-read with OCR" action per catalog running asynchronously in background thread without freezing GUI, then update count.

## 2026-09-10T23:17:27Z
Explorer 3 technical discoveries:
1. pd.read_html requires lxml which is NOT installed. Use standard library HTMLParser/regex converter.
2. RapidTable input: batch_ocr = [(np.array([x[0] for x in ocr_res]), [x[1] for x in ocr_res], [float(x[2]) for x in ocr_res])]
3. Lazy initialization of RapidOCR and RapidTable singletons.
4. Weights slanet-plus.onnx ready in site-packages.

