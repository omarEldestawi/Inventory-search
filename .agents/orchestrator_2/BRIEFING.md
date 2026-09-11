# BRIEFING — 2026-09-11T03:19:25Z

## Mission
Deliver the Egyptian Pharmaceutical Procurement Engine Windows 11 desktop application with Arabic OCR catalog inspection, PyInstaller standalone packaging, Inno Setup wizard, and GitHub repository backup.

## 🔒 My Identity
- Archetype: orchestrator
- Roles: orchestrator, user_liaison, human_reporter, successor
- Working directory: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\orchestrator_2
- Original parent: parent
- Original parent conversation ID: 8cbfc06a-671f-4a3d-a49a-781054c51fd9

## 🔒 My Workflow
- **Pattern**: Project
- **Scope document**: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\orchestrator_2\SCOPE.md
1. **Decompose**: 4 clear milestones corresponding to user deliverables:
   - Milestone 1 (M1_OCR): Catalog Inspection & On-Demand Arabic OCR Re-read (RapidOCR + RapidTable in fitz/pdf_parser/app_gui)
   - Milestone 2 (M2_PyInstaller): Standalone Windows executable build via PyInstaller (.spec bundling all dependencies, CTK assets)
   - Milestone 3 (M3_InnoSetup): Windows Installer Wizard Setup.exe via Inno Setup script (.iss and ISCC.exe compilation, shortcuts, uninstaller)
   - Milestone 4 (M4_Git): Git backup to GitHub omarEldestawi/Inventory-search via git@github.com:omarEldestawi/Inventory-search.git
2. **Dispatch & Execute**:
   - For each milestone: Explorer investigation -> Worker implementation -> Reviewers/Challengers/Auditor gating.
3. **On failure**:
   - Retry, Replace, Skip, Redistribute, Redesign.
4. **Succession**:
   - At 16 spawns, write handoff.md, cancel crons, spawn successor.
- **Work items**:
  1. Milestone 1: Catalog Inspection & On-Demand Arabic OCR Re-read [in-progress]
  2. Milestone 2: PyInstaller Standalone Executable [pending]
  3. Milestone 3: Windows Installer Wizard Setup.exe [pending]
  4. Milestone 4: Git Backup to GitHub [pending]
- **Current phase**: Milestone 1 Implementation
- **Current focus**: Milestone 1: Catalog Inspection & On-Demand Arabic OCR Re-read

## 🔒 Key Constraints
- NEVER write, modify, or create source code files directly.
- NEVER run build/test commands yourself — require workers to do so.
- NEVER investigate or explore the problem at the code level — dispatch Explorers for technical investigation.
- Use RapidOCR + RapidTable (NOT upstream PaddleOCR, NOT Surya).
- PyMuPDF rasterizes PDF pages at 300 DPI (`page.get_pixmap(dpi=300)`).
- RapidOCR extracts Arabic text via ONNX CPU.
- RapidTable detects table column boundaries (اسم الصنف, سعر الجمهور, الخصم) and outputs clean pandas.DataFrame.
- Must run asynchronously in background thread without freezing GUI, then update count.
- Binary veto on integrity violations from Forensic Auditor.
- Never reuse a subagent after it has delivered its handoff.
- URGENT DIRECTIVE: Minimize shell run_command calls. Perform all inspections/file operations directly using file tools. Do not call ask_question. Batch tests together into single runs. Auto-approve all subagent steps.
- SECURITY DIRECTIVE: All downloads/tools/models must originate strictly from verified trusted sources (PyPI, official GitHub release assets, winget, JRSoftware) with verified SHA-256 checksums. No unverified third-party binaries permitted.

## Current Parent
- Conversation ID: 8cbfc06a-671f-4a3d-a49a-781054c51fd9
- Updated: 2026-09-11T03:19:25Z

## Key Decisions Made
- Decompose into 4 sequential milestones: M1 (OCR & inspection), M2 (PyInstaller), M3 (Inno Setup), M4 (Git Backup).
- Explorers 1, 2, and 3 completed investigations, proving RapidOCR + RapidTable pipeline, in-memory 300 DPI rasterization, GUI 2-row layout with async queue, and `CatalogCache` in controller.
- Shared Explorer 3's critical discoveries with Worker M1 (standard library regex HTML converter, (N, 4, 2) batch format for RapidTable, lazy initialization).
- Enforced security directive on trusted sources and cryptographic verification across team.

## Team Roster
| Agent | Type | Work Item | Status | Conv ID |
|-------|------|-----------|--------|---------|
| explorer_m1_1 | teamwork_preview_explorer | PDF Parser & RapidOCR/RapidTable Analysis | completed | 3f9c8225-7c93-46a3-bf17-be8f7169418a |
| explorer_m1_2 | teamwork_preview_explorer | GUI Count & Async Architecture Analysis | completed | 90d2561a-a8fd-4b9a-a31b-e69c6ff96406 |
| explorer_m1_3 | teamwork_preview_explorer | Dependencies & Verification Strategy | completed | f6d0dfd1-ecb0-4b44-8dee-b5d9a2d6421c |
| worker_m1 | teamwork_preview_worker | RapidOCR + RapidTable & GUI Inspection Integration | in-progress | de13ae31-b1c0-4f30-9cf0-8111883c0fe5 |

## Succession Status
- Succession required: no
- Spawn count: 4 / 16
- Pending subagents: de13ae31-b1c0-4f30-9cf0-8111883c0fe5
- Predecessor: orchestrator_1
- Successor: not yet spawned

## Active Timers
- Heartbeat cron: 3b92a196-eb1c-46f3-8ecb-542eb14e48e6/task-20
- Safety timer: none

## Artifact Index
- SCOPE.md — Milestone definitions & interface contracts
- ORIGINAL_REQUEST.md — Authoritative user requirements
