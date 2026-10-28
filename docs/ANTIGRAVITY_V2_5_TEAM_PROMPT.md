# Teamwork Project Prompt — PDF Recovery and Correction, v2.5

Status: Revised handoff, ready for implementation planning and team launch in Antigravity.

Implement, verify, and package Version 2.5 of Egyptian Pharma Optimizer: an end-to-end PDF recovery, inspection, and persistent correction workflow that resolves digital PDF catalog extraction failures instead of merely reporting them.

Working directory: `C:\Users\omart\Desktop\Inventory-search-PC`

Reported baseline: v2.4, commit `1d7e6ad26802ad85ee61ea335f97d3d4a8426f07`. Verify the current checkout and working tree; preserve existing user changes. Do not assume this report proves the current repository state.

## 1. Scope and required outcome

Users must be able to import a digital PDF, benefit from automatic recovery of unambiguous extraction failures, review unresolved entries beside the original PDF, correct fields or column mappings, and use validated results in procurement. Corrections must survive restart for the exact source file.

- Digital PDFs only in this iteration. Keep the archived RapidOCR implementation disabled. Do not add a new OCR engine, cloud uploads, or external AI processing.
- Scanned/image-only pages receive a clear unsupported-extraction explanation and a page preview. Manual entry remains possible, but does not establish verified page completeness.
- Corrections apply only to the exact source file, bound to canonical path and SHA-256 digest. No reusable vendor templates or automatic transfer to newer catalogs.
- Preserve downstream pharmaceutical identity, strength, form, and matching safeguards. Never invent missing names, prices, discounts, or stock values.
- Read applicable repository instructions and `.agents/skills/egyptian-pharma-procurement/SKILL.md` before implementation.
- Prepare and verify local v2.5 installer and portable artifacts. Do not publish, push, or tag a release.

## 2. Team and integration rules

Launch a full team with these responsibilities:

| Role | Responsibilities |
|---|---|
| Lead / Integration | Verify baseline, define shared contracts, assign file ownership, integrate inspection and procurement, review changes, own final acceptance. |
| Extraction | Extend source traceability and diagnostics across parser paths; implement bounded deterministic recovery. |
| Persistence | Implement correction storage, validation/replay, fingerprints, cache revision tracking, and atomic writes. |
| UI | Implement review screen, PDF preview, edits, mapping previews, progress, cancellation, and stale-worker protection. |
| Independent QA | Develop independent adversarial fixtures, verify regressions and integrity, and test packaged Windows artifacts. |

Before parallel implementation, the lead must establish diagnostics types, source identity rules, service contracts, and file ownership. Avoid concurrent edits to shared files; route cross-cutting integration through the lead. If concurrency is limited, queue roles. QA must assess behavior against this specification and source evidence, not merely mirror implementation logic.

## 3. Requirements

### R1. Shared diagnostics and service contracts

- Extend existing diagnostics rather than building a separate import system.
- Every reviewable issue retains a stable, table-distinguishing source identity, page, table/group, row or region, raw extracted cells/text, available PDF coordinates, rejection reason, recovery attempts, and resolution provenance.
- Distinguish original extraction, automatic recovery, and manual correction; retain original failure history after resolution.
- Keep the existing eight-column procurement DataFrame schema. Store provenance and resolution details in metadata.
- Provide a shared service for listing unresolved issues, bounded automatic recovery, previewing column mappings, applying validated edits/mappings, resetting corrections, and returning refreshed `CatalogResult` objects.
- Use that service in both GUI inspection and direct procurement, including procurement without a populated GUI cache.
- Give additive metadata fields safe defaults. Reparse incompatible caches rather than silently accepting them.

### R2. Comprehensive extraction accountability

- Record reviewable failures across structural, legacy, and coordinate extraction paths.
- Capture bounding regions before early validation exits, including missing-name failures. Fall back to table or page context when precise coordinates are unavailable.
- Create region-level issues for unmappable tables or unenumerated rows without inventing candidate counts.
- Separate confirmed non-product headers/footers from unresolved product candidates.
- Preserve unknown completeness where coverage cannot be established. Resolving known issues must not turn unknown coverage into a complete import.
- Maintain consistent accepted, rejected, unprocessed, and duplicate accounting. Resolved rows become accepted; recovery/correction counts are provenance, not additional candidate rows.

### R3. Deterministic automatic recovery

Automatically run recovery after initial extraction and before summary display, using applicable strategies in this order:

1. Re-extract text by cell/row coordinates.
2. Reconstruct wrapped text within the same source row.
3. Resolve column roles using explicit headers or an established geometrically compatible layout.

- Attempt each strategy at most once per issue in a recovery pass. Repeated passes must be idempotent.
- Automatically accept only a single unambiguous interpretation supported by source evidence. Conflicting or ambiguous interpretations remain unresolved.
- Never borrow values from adjacent products or other catalogs.
- Preserve previously accepted records during automatic recovery. Reconcile overlapping extraction attempts by source identity before normal catalog deduplication.
- Use shared catalog validation for original extraction, recovery, and manual corrections, while preserving downstream pharmaceutical matching safeguards. Catalog extraction does not itself approve a medicine match.
- Standardize numeric validation to the existing final import behavior: `0 < price < 10000`; discount from explicit zero through 85%. A blank discount is not zero. The UI uses percentages; the internal discount remains a fraction.

### R4. Asynchronous review and correction GUI

- Add **Review and fix** to catalog cards and the catalog viewer.
- Replace the warning-only confirmation with a consolidated summary offering **Review and fix**, **Continue with available items**, and **Cancel**.
- Display warehouse, page, clear Arabic/English issue explanation, extracted values, and the original PDF page with the issue region highlighted. Use existing PyMuPDF rendering and full-page fallback.
- Support editing item name, price, discount percentage, and stock status, with field-specific validation errors and no validation bypass.
- Support column mapping for a selected table/group with a preview of every affected record, including previously accepted rows. Require explicit confirmation, validate the proposed result, and apply atomically; failed validation leaves the active result unchanged.
- Permit manual entry linked to a selected PDF source region when no usable row exists. Label its provenance as manual.
- Provide **Save correction**, **Undo correction**, and **Leave unresolved**, plus a full reset action for the catalog.
- Keep extraction, rendering, and revalidation off the GUI thread. Show progress and support cancellation. Commit UI updates on the GUI thread.
- Use per-catalog operation revisions to prevent stale workers from overwriting later edits, resets, refreshes, or file changes. Cancelled operations must not partially replace active results.
- Summarize outcomes explicitly, for example: “18 automatically recovered, 4 manually corrected, 3 unresolved.”
- Continuing with unresolved product issues requires explicit partial-import acknowledgment. Catalogs with zero valid entries cannot enter procurement. Unknown completeness stays visibly unverified.

### R5. Atomic, fingerprinted correction persistence

Store versioned corrections under:

`%LOCALAPPDATA%/EgyptianPharmaOptimizer/data/catalog_corrections`

Each record includes canonical path, source SHA-256 digest, extraction schema version, stable source identity, original and corrected values or column mapping, timestamp, provenance, and correction revision.

- Use atomic writes and serialize updates per catalog to avoid lost edits.
- Validate corrections again on restart or refresh through the shared service.
- Never silently replay corrections against changed contents, incompatible source identities, or incompatible extraction schemas. Explain why review is required.
- Handle malformed or corrupt storage without crashing or applying invalid data. Surface a clear warning.
- Verify the PDF fingerprint before committing background results.
- Include correction revision in cache freshness checks; fingerprint checks alone do not detect a newer correction to an unchanged PDF.
- Recompute diagnostics and acknowledgment tokens after correction, undo, or reset. Invalidate stale cache entries and prior acknowledgments.
- Reset removes saved corrections and rebuilds the catalog through current extraction and automatic recovery. Undo restores the preceding correction state and updates its revision.
- A persistence failure must be visible; do not claim a correction was saved. Keep the prior committed result available.

## 4. Acceptance and verification

### Extraction and recovery

- [ ] Coordinate re-extraction recovers missing cells whose values exist in the PDF text.
- [ ] Wrapped Arabic names and mixed Arabic/Latin rows are reconstructed without corrupting identity, strength, or pack information.
- [ ] Headerless continuations and swapped price/discount layouts recover only when supported by unambiguous source evidence.
- [ ] Multiple tables with identical row indexes retain distinct source identities.
- [ ] Unmappable regions remain reviewable without invented row counts or false completeness.
- [ ] Genuinely missing values, conflicting interpretations, and invalid values remain unresolved.
- [ ] Overlapping extraction strategies do not create duplicate source records; legitimate duplicate products retain correct accounting.
- [ ] Repeated recovery produces identical values, counts, and status and preserves already accepted records.

### Correction integrity and persistence

- [ ] Field edits use shared catalog validation; downstream pharmaceutical matching checks remain intact.
- [ ] Blank discount differs from explicit zero, and numeric boundaries are consistent across paths.
- [ ] Mapping previews include accepted records; failed or cancelled application is atomic.
- [ ] Manual entries remain linked to source regions and do not falsely certify page completeness.
- [ ] Corrections survive restart and refresh for the exact source PDF.
- [ ] Changed PDFs, incompatible schemas, and incompatible source identifiers prevent stale replay.
- [ ] Corrupt files and storage write failures produce clear warnings without losing the last committed result.
- [ ] Undo and reset invalidate stale results and acknowledgment tokens.
- [ ] Cache freshness detects a changed correction revision even when the PDF is unchanged.
- [ ] Source changes or concurrent edits during worker execution cannot overwrite newer state.
- [ ] GUI inspection and direct procurement produce identical corrected catalog inputs.
- [ ] Zero-valid-item catalogs cannot proceed; partial imports require acknowledgment; unknown coverage remains unverified.

### Regression and packaged Windows verification

- [ ] Run existing parser, unit, integration, cache, diagnostic, regression, and procurement tests, including `pytest tests/`. Record actual commands and outcomes.
- [ ] Compare representative real digital catalogs before and after implementation, including successful imports that should remain unchanged.
- [ ] Independently challenge price/discount inversion and medicine-name corruption.
- [ ] Build local v2.5 portable and installer artifacts using the existing build workflow; update displayed/build version references consistently.
- [ ] Smoke-test actual packaged artifacts for PDF preview, Arabic rendering, responsiveness, cancellation, correction persistence, undo/reset, and procurement.
- [ ] Verify runtime correction storage works without elevation or writes to installation directories. This does not imply the installer itself must run without elevation.
- [ ] Demonstrate at least one automatically recovered row and one persisted manual correction reaching the final procurement input and being exercised by a matching order fixture.

Do not weaken tests to hide regressions. Record pre-existing failures separately and explain intentionally changed diagnostic semantics with replacement tests. Never report an unexecuted check as passing.

## 5. Delivery sequence and final report

1. Verify the checkout, instructions, baseline behavior, and existing test status.
2. Lead defines shared contracts and file ownership.
3. Extraction, persistence, UI, and independent QA work in parallel within those contracts.
4. Lead integrates both GUI inspection and direct procurement.
5. QA runs adversarial, integration, regression, and packaged-app checks; implementation agents resolve findings.
6. Prepare verified local installer and portable artifacts without publishing, pushing, or tagging.

Final report must contain:

- What changed and how users recover or correct entries.
- Verification commands, outcomes, remaining failures, and limitations.
- Representative before/after catalog results.
- Evidence of automatic recovery and persisted correction reaching procurement.
- Absolute paths to verified local build artifacts.
- Any incomplete requirements, explicitly marked rather than described as complete.

Passing unit tests alone is insufficient: verify the integrated user workflow and packaged Windows application.
