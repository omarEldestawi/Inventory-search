## 2026-09-11T11:50:41Z
Implement the requested single self-contained fix:
# Teamwork Project Prompt — Half 1: Output Directory & Permission Safety
Goal: Fix PermissionError / Access is denied on Program Files and ensure safe user-writable output directories

Scope:
- src/pipeline.py
- src/controller.py
- app_gui.py
- tests/test_pipeline.py / tests/test_gui.py

Requirements:
1. R1. Safe User-Writable Default Output Directory: Never default to writing output inside installation paths (_internal, Program Files, /Applications). Default to user-writable directory (e.g. user Desktop/Pharma_Output or Documents/Pharma_Output) across both Windows and macOS platforms.
2. R2. Proactive Write Permission Validation & Automatic Fallback: Validate write permissions with a probe before executing pipeline stages. If write permission is denied (PermissionError, [WinError 5] Access is denied), automatically log a warning and fallback to a guaranteed user-writable location (~/Desktop/Pharma_Output or ~/Documents/Pharma_Output).
3. R3. GUI Output Path Protection & Non-Crashing Error Handling: Output directory picker defaults to safe user directory, warns or disallows protected installation directories, and cleanly catches and surfaces any permission errors in the UI without crashing the background worker thread.

Acceptance Criteria:
- Running pipeline with default settings never fails with [WinError 5] Access is denied in Program Files or permission errors on macOS/Linux.
- Directory creation validates write permissions with probe before executing pipeline stages.
- If an unwritable directory is supplied to run_procurement_pipeline(), it falls back cleanly to a writable user directory without raising an unhandled PermissionError.
- GUI initializes output destination to a user-writable directory and worker thread handles permission issues gracefully.
- Pipeline and GUI unit tests pass.

Follow your SWE Light loop: dispatch implementer, run tests, adversarial review rounds, verify all tests pass.
When finished, send a handoff report back to your parent.

## 2026-09-11T11:55:58Z
IMPORTANT ENVIRONMENT CONSTRAINT: Git is NOT installed or enabled on this Mac. Do NOT use any git commands (git diff, git status, git commit, git log, etc.). They will all fail. Work directly with files — read them, edit them, check modification times — but no git operations whatsoever. Ensure all subagents (implementers, reviewers) are instructed accordingly.
