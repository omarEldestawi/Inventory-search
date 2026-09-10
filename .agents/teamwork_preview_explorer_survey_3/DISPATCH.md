# Dispatch: Explorer 3 (Packaging, PyInstaller & Installer Tooling)

## Mission
Investigate PyInstaller packaging requirements, standalone build dependencies, Windows installer compilers (Inno Setup / NSIS / WiX), environment capabilities, and packaging verification.

## Working Directory
c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_survey_3

## Authoritative Inputs
- ORIGINAL_REQUEST.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md
- Domain Skill: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\skills\egyptian-pharma-procurement\SKILL.md
- Existing Codebase: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search

## 2026-09-10T20:44:40Z
Investigate packaging and installer compilation in the current Windows environment:
1. Python environment and dependencies: check python version, installed packages (customtkinter, pyinstaller, pymupdf/fitz, pandas, openpyxl, rapidfuzz, etc.).
2. PyInstaller packaging configuration: spec file requirements, data files (customtkinter theme JSONs/assets, fonts, icons), hidden imports, hooks, whether onedir or onefile is best suited for installer distribution.
3. Windows installer compilers availability: Check what tools are installed or available on this system (Inno Setup `ISCC.exe`, NSIS `makensis.exe`, WiX, or whether Inno Setup / NSIS is in Program Files / PATH / portable, or if an installer script can be compiled via chocolatey/winget/portable binaries or Python-based installer generators).
4. Installer specifications: Installation directory (e.g. `%LocalAppData%\Programs\...` or Program Files), Desktop & Start Menu shortcuts, icon integration, uninstaller in Windows Add/Remove Programs, silent install options.
5. Automated build & verification pipeline: How to verify the built `.exe` runs and processes catalogs in an automated test.

