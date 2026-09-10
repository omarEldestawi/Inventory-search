# Dispatch: Worker M2 (CustomTkinter Windows 11 GUI Desktop App)

## Mission
Implement `app_gui.py` providing a modern Windows 11 CustomTkinter desktop GUI for the Egyptian Pharmaceutical Procurement Engine, fully integrated with `src/pipeline.py` and `src/controller.py`, alongside automated headless tests in `tests/test_gui.py`.

## Exclusive File Ownership
- `app_gui.py` (Exclusive)
- `tests/test_gui.py` (Exclusive)

## Authoritative Inputs
- ORIGINAL_REQUEST.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md
- PROJECT.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\PROJECT.md
- Explorer 2 Handoff: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_survey_2\handoff.md
- Explorer 1 Handoff: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_survey_1\handoff.md
- Approved Pipeline: `c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\src\pipeline.py`
- Approved Controller: `c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\src\controller.py`

## 2026-09-10T21:14:31Z
You are Worker M2 (CustomTkinter Windows 11 GUI Desktop App).
Your working directory is: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_m2
Project root directory is: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search

MANDATORY INPUTS:
1. ORIGINAL_REQUEST.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md (Read first!)
2. PROJECT.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\PROJECT.md
3. Dispatch file: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_m2\DISPATCH.md
4. Explorer 2 Handoff: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_survey_2\handoff.md
5. Approved Core Engine Bridge: `src/pipeline.py` and `src/controller.py`

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

EXCLUSIVE FILE OWNERSHIP:
You exclusively own and modify:
- `app_gui.py`
- `tests/test_gui.py`

TASK:
1. Create `app_gui.py` implementing the complete modern Windows 11 CustomTkinter desktop GUI:
   - System/Dark/Light theme support via `customtkinter.set_appearance_mode("System")` and a theme selector.
   - High-contrast bilingual typography (Arabic & English) using `Segoe UI` fonts.
   - Left Sidebar / Action Panel:
     - Branding header: "نظام المشتريات الصيدلانية / Egyptian Pharma Optimizer".
     - Destination directory picker with Browse button and text entry (defaulting to `./output`).
     - Primary Action Button: "بدء التحسين والتوزيع / Run Optimization" (accent color `#1F4E79`), with validation guard enabling it only when at least 1 order file and 1 catalog file are selected.
     - Dark/Light/System theme toggle switch.
   - Right Main Panel:
     - Multi-file selection toolbar ("+ إضافة ملفات / Add Files", "+ إضافة مجلد / Add Folder", "مسح الكل / Clear All") with file counter badge.
     - Scrollable file list (`CTkScrollableFrame`) displaying selected files with:
       - File type badges (`[PDF]`, `[XLSX]`, `[CSV]`)
       - File basename and size
       - Auto-classification status badges (`[📋 أمر شراء / Order]` or `[🏷️ كتالوج مخزن / Catalog]`)
       - Manual Category Override dropdown (`CTkOptionMenu`) allowing the user to switch categories in 1 click
       - Delete button (`✕`) to remove individual files
     - Active progress bar (`CTkProgressBar`) and live localized status label.
     - Post-Run Summary KPI Card / Section:
       - Displays: Total requested items, allocated items, out-of-stock count, average discount %, total savings, and winning wholesalers pills.
       - "📄 فتح التقرير / Open Report" action using `os.startfile(report_path)` on Windows.
       - "📁 فتح المجلد / Open Containing Folder" action using `explorer /select,...` on Windows.
   - Asynchronous execution pattern:
     - Uses `ProcurementEngineBridge` from `src.controller` in a daemon background thread.
     - UI thread polls queue every 50ms (`root.after(50, self.poll_queue)`), updating progress and UI without freezing.
     - Clean error popup/dialog on failure.
   - Headless CLI flag support:
     - If `--self-test` in `sys.argv`, instantiate GUI with `app.withdraw()`, verify all components and dependencies load cleanly, and exit with code 0.
2. Create `tests/test_gui.py` covering:
   - Headless instantiation test (`app.withdraw()`).
   - File list addition, deduplication, auto-classification, manual override, and removal.
   - Validation gate enabling/disabling the Run button.
   - Bridge message queue handling (`PROGRESS`, `DONE`, `ERROR`).
   - Post-run KPI display card binding.
3. Run tests via `python tests/test_gui.py` and `python app_gui.py --self-test` to verify clean headless execution.
4. Write your completion report to:
   `c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_worker_m2\handoff.md`
   Send a completion message back referencing the handoff path and summarizing test results.
