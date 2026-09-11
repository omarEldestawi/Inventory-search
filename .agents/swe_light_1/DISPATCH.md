## 2026-09-11T11:10:48Z

You are teamwork_preview_swe, the orchestrator for SWE Light.
Your working directory is: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\swe_light_1
Project workspace: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search
Authoritative user request: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md

Task:
Fix the output directory write permission error in packaged Windows builds and ensure robust RapidOCR / RapidTable catalog extraction.

Requirements:
1. R1. Safe User-Writable Default Output Directory:
   The application must never default to writing output inside the application installation path (`_internal` or `Program Files`). It must default to a user-writable directory (e.g., `~/Desktop/Pharma_Output` or user Documents folder) with automatic fallback if the configured directory is not writable.
2. R2. OCR Engine Reliability & Frozen Build Packaging:
   Ensure `RapidOCR` and `RapidTable` work seamlessly both in development and in PyInstaller packaged builds (`.spec` / `build_exe.py`), with descriptive error logging and fallbacks for scanned PDFs.

Acceptance Criteria:
- Running pipeline with default settings never fails with `[WinError 5] Access is denied` in `Program Files`.
- Directory creation validates write permissions before executing pipeline stages.
- `PDFCatalogParser.parse_ocr()` succeeds on test PDF files without missing ONNX runtime assets.
- Error messages for missing OCR dependencies or corrupted files are surfaced clearly in the UI without crashing the worker thread.

Execute the SWE Light workflow: run an implementer on the task, followed by reviewer rounds, establishing correctness with tests. When finished, send a completion report back to parent.
