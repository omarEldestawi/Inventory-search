# Egyptian Pharmaceutical Procurement Skill

## Procedure:
1. **Catalog Ingestion**:
   - Map filenames dynamically using normalize_vendor_name.
   - Detect 2-column accounting formats and parse both columns independently.
   - Decouple glued numbers and normalize NFKD characters.
2. **Order Reconciliation**:
   - Parse order requests (0910.xlsx or daily order pattern).
   - Filter requested items against the candidate index.
3. **Safety Gate Verification**:
   - Run is_safe_pharmaceutical_match checking Form Compatibility, Active Strength / Ratio Compatibility, and Canonical Brand Root.
4. **Optimal Allocation**:
   - Pick highest discount rate among available stock suppliers.
   - Generate multi-sheet workbook (Procurement_Order_Optimized_YYYY-MM-DD.xlsx).
