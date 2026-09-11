# User Permissions & Operational Directive

- **Date**: 2026-09-11
- **Status**: ACTIVE & MANDATORY (ENFORCED ACROSS ALL SUBAGENTS)

The user has explicitly instructed:
"allow everything without my permission, automatically approve and proceed"

1. **Full Command & Build Authorization**: All commands (pip install, builds, test runners, PyInstaller, Inno Setup compiler ISCC.exe, git operations) are 100% pre-authorized.
2. **Zero Halts / Zero Prompts**: No agent or subagent is permitted to stop, wait, or ask the user for confirmation or manual execution. 
3. **Total Autonomous Flow**: Execute all steps consecutively from Milestone 1 through Milestone 4 and final verification.
4. **Minimize `run_command`**: Use file tools (`view_file`, `write_to_file`, `replace_file_content`, `grep_search`, `find_by_name`) for all inspections, readings, edits, and file operations to prevent IDE permission popups. Only invoke shell commands when strictly necessary (e.g. running test batches, PyInstaller, ISCC, git).
5. **No `ask_question`**: Never call `ask_question`.
6. **Batch Test Runs**: Consolidate test executions into single comprehensive runs rather than multiple fragmented commands.
7. **Auto-Approve Internally**: Auto-approve all subagent steps internally and proceed without pause.
8. **Cryptographic Integrity & Trusted Sources Only**: Any downloaded dependency, tool, or model MUST strictly originate from official upstream repositories (official Python PyPI, official GitHub release assets of vetted open-source projects, Microsoft winget, JRSoftware). Any binary or model file must have its cryptographic SHA-256 checksum strictly verified before inclusion. No unverified third-party binaries or unknown sources are permitted.


