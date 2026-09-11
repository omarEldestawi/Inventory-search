## 2026-09-11T02:59:36Z
You are Explorer 1 (Codebase & Parser Explorer).
Your agent working directory: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_m1_1
Project root: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search
Authoritative user request: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md
Scope document: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\orchestrator_2\SCOPE.md
Domain skill: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\skills\egyptian-pharma-procurement\SKILL.md

Mission: Investigate the catalog parsing implementation in `src/pdf_parser.py` and the OCR stack.
User Mandate:
- Use RapidOCR + RapidTable (NOT upstream PaddleOCR, NOT Surya).
- PyMuPDF (fitz) rasterizes PDF pages at 300 DPI (`page.get_pixmap(dpi=300)`).
- RapidOCR (`from rapidocr_onnxruntime import RapidOCR`) extracts Arabic text via ONNX CPU.
- RapidTable (`from rapid_table import RapidTable`) detects table column boundaries (`اسم الصنف`, `سعر الجمهور`, `الخصم`) and outputs clean pandas.DataFrame.
- Feed DataFrame rows into existing normalizer/matcher (`clean_drug_name`, `normalize_vendor_name`, etc.).

Investigate and document in your `analysis.md` and `handoff.md`:
1. Current `src/pdf_parser.py` structure, classes, and methods (e.g. `PDFCatalogParser`, how items/medications are parsed and returned).
2. Exact design for adding `parse_catalog_ocr(pdf_path: str) -> list[dict]` or an OCR mode to `PDFCatalogParser`.
3. How to rasterize pages at 300 DPI using `fitz.open(pdf_path)` and convert pixmaps to images/bytes for RapidOCR and RapidTable.
4. How RapidOCR and RapidTable interact: check exact library signatures, whether RapidTable takes images and/or OCR results, and return formats.
5. How table columns (e.g. Arabic column names for drug name, public price, discount, etc.) should be detected and mapped to dictionary records matching the existing parser output format.
6. Error handling, fallback mechanisms if OCR or table detection encounters non-tabular pages, and performance considerations.

Write `analysis.md` and `handoff.md` in your agent directory. Once complete, notify orchestrator via send_message with handoff path and summary.
