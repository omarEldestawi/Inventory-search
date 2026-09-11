# Original User Request

## Initial Request — 2026-09-11T11:50:01Z

# Teamwork Project Prompt — Half 1: Output Directory & Permission Safety

> Status: Launched
> Goal: Fix PermissionError / Access is denied on Program Files and ensure safe user-writable output directories
> Requested team: Small, focused team

This is a single self-contained fix; keep it small and focused.

Ensure the Egyptian Pharmaceutical Procurement Engine application never attempts to write to restricted system paths (`_internal`, `Program Files`, `/Applications`, etc.) and always safely uses and falls back to user-writable directories across Windows and macOS.

Working directory: /Users/mariam/Desktop/Inventory-search/EgyptianPharmaOptimizer_MacMigration
Integrity mode: development

## Scope (Files to focus on):
- `src/pipeline.py`
- `src/controller.py`
- `app_gui.py`
- `tests/test_pipeline.py` / `tests/test_gui.py`

## Requirements

### R1. Safe User-Writable Default Output Directory
The application must never default to writing output inside the application installation path (`_internal`, `Program Files`, or `/Applications`). It must default to a user-writable directory (e.g., user Desktop/Pharma_Output or Documents/Pharma_Output) across both Windows and macOS platforms.

### R2. Proactive Write Permission Validation & Automatic Fallback
Before executing any pipeline processing stages, the application must actively validate write permissions on the target output directory by attempting a safe write probe. If write permission is denied (e.g., `PermissionError`, `[WinError 5] Access is denied`), it must automatically log a warning and fallback to a guaranteed user-writable location (`~/Desktop/Pharma_Output` or `~/Documents/Pharma_Output`).

### R3. GUI Output Path Protection & Non-Crashing Error Handling
In `app_gui.py`, ensure the output directory picker defaults to the safe user directory, warns or disallows choosing protected installation directories, and cleanly catches and surfaces any permission errors in the UI without crashing the background worker thread.

## Acceptance Criteria

### Execution & Permissions
- [ ] Running pipeline with default settings never fails with `[WinError 5] Access is denied` in `Program Files` or permission errors on macOS/Linux.
- [ ] Directory creation validates write permissions with probe before executing pipeline stages.
- [ ] If an unwritable directory is supplied to `run_procurement_pipeline()`, it falls back cleanly to a writable user directory without raising an unhandled `PermissionError`.
- [ ] GUI initializes output destination to a user-writable directory and worker thread handles permission issues gracefully.
- [ ] Pipeline and GUI unit tests pass.

## Follow-up — 2026-09-11T11:55:45Z

IMPORTANT: Git is NOT installed or enabled on this Mac. Do NOT use any git commands (git diff, git status, git commit, git log, etc.). They will all fail. Work directly with files — read them, edit them, check modification times — but no git operations whatsoever.
