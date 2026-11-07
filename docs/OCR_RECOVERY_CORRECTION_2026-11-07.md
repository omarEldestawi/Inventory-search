# Recovery correction status — 2026-11-07

This update supersedes earlier claims that OCR strength recovery is complete.

- Removed the universal 1000-component limit, unconditional ratio reversal, and trailing-number deletion.
- Targeted retries stay inside the name-column bounds and retain readings with coordinates and resolution.
- A changed OCR ratio is not certified by numeric plausibility or repeated OCR agreement. Raster-only combination strengths remain unresolved; exact unchanged digital cell text can corroborate a reading.
- Ambiguous spaced decimals remain unresolved. Generic recovery cannot erase this state and reapprove the row.
- The known-defective RapidOCR engine cannot independently approve products, including plausible outputs with missing zeros.
- The real generated page-3 fixture yields 24 accepted rows and four unresolved strength/decimal rows. This is intentionally lower automatic completion, not an accuracy claim about all future files.
- Search, shared normalization, allocation and matching source files were unchanged during this correction.
- Parser revision 2026.11.07.2 invalidates pre-correction cached extraction results.

Remaining limitation: automatic verification of raster-only multi-component strengths requires reliable source-token geometry or another independently validated recognition path. This change does not solve general physical-scan OCR.

## Verification performed

- 17 source-fidelity and real generated-raster regression checks passed.
- 16 unknown-discount, procurement exclusion, field-boundary, and isolated search-equivalence checks passed.
- Original digital inputs still extracted 230 and 1,253 rows respectively; these counts alone are not an accuracy claim.
- normalizer.py, allocator.py and pharma_matcher.py match the byte-for-byte snapshots taken before this correction.
- A broader run including historical end-to-end GUI tests was interrupted after it stopped making observable progress; it is not reported as passed.
- Old all-rows-accepted OCR benchmarks are not a release guarantee. The source-fidelity regression explicitly requires the four uncertain rows to remain outside accepted output.

## Final targeted checks and executable

- Additional adversarial/diagnostics suites: 49 passed, 14 subtests passed.
- Parser-revision/cache invalidation check: 1 passed (24 unrelated tests deselected).
- Total targeted verification: 83 tests passed, plus 14 subtests. This is not a full-suite claim.
- PyInstaller executable rebuilt successfully.
- Packaged generated-raster check: exit 0, 28 candidates, 24 accepted, status partial. Four strength/decimal issues remain unresolved (the diagnostic history also retains a recovered price issue).
- Packaged self-test: exit 0 using a writable workspace TEMP directory. The first attempt failed due to the execution environment's temporary-folder permissions. Existing font fallback warnings were emitted; no claim of visual UI QA is made.

src/normalizer.py: SHA-256 9eea7a21c10015393dda39ddaa47e42166d17bb10a1857e2dfc81e6f60317c6b

src/allocator.py: SHA-256 83298cf61e35a772f7bbe0380c850e08ff930c5e35f47cbf575ad834dfb5e42a

src/pharma_matcher.py: SHA-256 d1549dbac26685690da2897aa361809a643394a4f17451f4d951ae52ea9b36e4

dist/EgyptianPharmaOptimizer/EgyptianPharmaOptimizer.exe: SHA-256 a21cb3b23f34b358b6599de146c4ceed60497539112906258b44602552459274

Installer compilation succeeded (exit 0). dist_installer/EgyptianPharmaOptimizer_Setup_v2.6.exe: SHA-256 ea5de938039c43cdf106be9b08d7e26076732659f0f792d4942ec9c4e3ca4727. Installer was built, not installed on a clean machine.
