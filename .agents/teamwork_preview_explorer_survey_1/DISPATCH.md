# Dispatch: Explorer 1 (Core Engine & Integration)

## Mission
Investigate the existing core procurement engine, data flow, file formats, and domain skill.

## Working Directory
c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\teamwork_preview_explorer_survey_1

## Authoritative Inputs
- ORIGINAL_REQUEST.md: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\ORIGINAL_REQUEST.md
- Domain Skill: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\.agents\skills\egyptian-pharma-procurement\SKILL.md
- Codebase src/: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\src
- Tests & Samples: c:\Users\omart\.gemini\antigravity\scratch\Inventory-search\

## 2026-09-10T20:44:40Z
Explore the existing codebase and domain rules:
1. Review `src/` modules: `allocator.py`, `pdf_parser.py`, `normalizer.py`, `pharma_matcher.py`, `report_generator.py`, and any other scripts or tests in the project.
2. Examine how inputs are currently processed: what constitutes an order list (.xlsx) vs wholesaler catalog (.pdf, .xlsx, .csv). What heuristic or inspection rules distinguish daily order files from vendor catalog files?
3. How does the allocator execute, what data structures are produced, what parameters are required, and how does the report generator produce the multi-sheet Arabic procurement Excel workbook?
4. What KPIs can be extracted post-run (matched items count, average discount, winning wholesalers, total savings, unmatched items, etc.)?
5. Review sample files or test data present in the repository, their formats, and how they can be used for end-to-end testing.
6. What error conditions or edge cases exist (e.g., missing columns, corrupted PDF, no matches, discount calculations)?

