# Original User Request

## 2026-09-10T20:40:22Z

Build a modern Windows 11 desktop GUI application (using CustomTkinter) for the Egyptian Pharmaceutical Procurement Engine, and package it into a standalone Windows installer wizard (`Setup.exe`) for distribution to other laptops.

Working directory: c:/Users/omart/.gemini/antigravity/scratch/Inventory-search
Integrity mode: development

## Requirements

### R1. Modern Windows 11 Graphical Interface (CustomTkinter)
Create an intuitive, modern desktop interface supporting Arabic and English:
- **Input 1 (Files Selection)**: Browse and multi-select input files (order list `.xlsx` and wholesaler catalogs `.pdf`, `.xlsx`, `.csv`), with a clean list widget displaying selected files and allowing items to be added or removed.
- **Input 2 (Output Destination)**: Browse and select the destination directory where the resulting procurement report will be saved.
- **Run & Feedback**: An action button to start optimization with an active progress bar and a post-run summary card showing key KPIs (matched items, average discount, winning wholesalers, and a direct button to open the generated Excel file / folder).

### R2. Core Procurement Engine Integration
Connect the GUI controller to the existing local deterministic engine (`src/allocator.py`, `src/pdf_parser.py`, `src/normalizer.py`, `src/pharma_matcher.py`, `src/report_generator.py`):
- Automatically categorize selected files into daily orders vs wholesaler catalogs based on file content and naming patterns.
- Execute allocation asynchronously in a background thread to keep the GUI responsive and prevent "Not Responding" freezes.
- Generate the final multi-sheet Arabic procurement Excel report directly in the user-selected output directory.

### R3. Standalone Executable Packaging (PyInstaller)
Package the desktop application and its dependencies (`pymupdf`, `pandas`, `openpyxl`, `rapidfuzz`, `customtkinter`) into a standalone Windows executable.

### R4. Windows Installer Wizard (Setup.exe)
Create an automated Windows installation wizard (`Setup.exe` via Inno Setup or NSIS script):
- Installs the application to standard Windows user directories (`AppData` or `Program Files`).
- Automatically creates Desktop and Start Menu shortcuts with an application icon.
- Includes a clean uninstaller accessible via Windows Settings / Add or Remove Programs.
- Runs on any Windows 10/11 laptop without requiring Python or manual configuration.

## Acceptance Criteria

### GUI Functionality & Usability
- [ ] Application launches cleanly into a modern Windows 11 styled window with dark/light mode support.
- [ ] File picker dialog allows selecting multiple `.pdf` and `.xlsx` files, displayed in a scrollable list with item counts.
- [ ] Folder picker dialog allows selecting any valid output destination path.
- [ ] Execution runs smoothly with a progress indicator and finishes without UI freezing.
- [ ] Generates the exact multi-sheet procurement workbook in the chosen folder.
- [ ] Completion modal displays summary KPIs and offers a "Open Output File" button.

### Packaging & Distribution
- [ ] PyInstaller build script/spec cleanly compiles the application without missing module errors.
- [ ] An installer setup script (Inno Setup `.iss` / NSIS) compiles a standalone `Setup.exe`.
- [ ] Installing `Setup.exe` on a clean Windows machine installs the software, creates Start Menu / Desktop shortcuts, and launches the app successfully.

## Verification Plan
1. **Automated GUI & Engine Test**: Execute an automated headless or integration test feeding sample files and verifying output report creation at target path.
2. **Build Verification**: Compile executable via PyInstaller and verify that the output binary launches and processes sample catalogs.
3. **Installer Compilation**: Verify that the installer compiler outputs `Setup.exe` ready for distribution.

## Follow-up — 2026-09-10T20:48:10Z

The user has provided the following directive: "can u give the agents full perrmission, no need to ask me to run any commands". Full permission has been granted across the entire multi-agent hierarchy for all commands, scripts, builds, and tool runs. Proceed autonomously without pausing for manual command approvals.
