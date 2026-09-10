---
description: Technical invariants for Egyptian pharmaceutical catalog ingestion, multi-column geometry, text normalization, and clinical safety gates
globs: src/**/*.py, main.py, watcher.py
---

# Egyptian Pharmaceutical Procurement Rules

1. **Multi-Column PDF Layouts**:
   - Check page vector drawings (`get_drawings()`). If borders exist only on one side or tables are split, do not rely on default `page.find_tables()`.
   - Process pages using column clipping rectangles (`x < width/2` and `x >= width/2`) or structured block streams (`page.get_text("blocks")`).

2. **Text Normalization & Token Decoupling**:
   - Ingest all raw text through `unicodedata.normalize('NFKD', text)`.
   - Decouple attached digits from Arabic text using `re.sub(r'(\d+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', text)` prior to packaging or price extraction.
   - Do not invert Arabic strings unconditionally; verify logical reading order.

3. **Dosage Form Safety & Storage Qualifiers**:
   - Strip storage tags (`\b(?:ث|ثلاجة|ثلاجه)\b`) before dosage form evaluation.
   - Include market colloquialisms (`شرب`, `اقرص`, `لرص`) in form categorization (`ORAL_LIQUID`, `SOLID_ORAL`).
   - Mutual exclusion is strictly enforced: `INJECTABLE`, `SOLID_ORAL`, `ORAL_LIQUID`, `DROPS`, `SPRAY`, `SUPPOSITORY`, and `TOPICAL` cannot cross-match under any condition.
   - Multi-strength ratios (e.g. `5/1000` vs `500/5` or `10/5/1000` vs `25/5/1000`) and infant milk stages (`1`, `2`, `3`) must match exactly.
