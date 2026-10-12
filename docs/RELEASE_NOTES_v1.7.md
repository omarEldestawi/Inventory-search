# 🏥 Egyptian Pharma Procurement Optimizer v1.7

### 🌟 What's New in Version 1.7 / الجديد في هذا التحديث

- 🎯 **100% Deterministic Parity & Reversed Arabic Resolution**: Fully resolves items from catalogs containing reversed Arabic letter streams (e.g. El-Salam warehouse items like *Davalindi* and *Seloken ZOK*), achieving 100% allocation matching across all wholesalers.
- 🗄️ **Resilient Read-Only SQLite & AppData Ingestion**: Seamless fallback to read-only URI mode (`PRAGMA query_only = ON;`) and automatic `%LOCALAPPDATA%` caching for execution inside protected directories like `C:\Program Files` without administrative write permissions.
- 🛡️ **Hardened Pharmaceutical Strength Protection**: Guarded active strengths ($\ge 125$ mg) against pack-count stripping in fallback fuzzy matching, strictly preventing dosage mismatches (e.g. Flumox 1g vs 500mg).
- 🔄 **Modern In-Place Update Flow**: Supports direct in-place upgrading over existing installations without modifying saved orders or history.

---

### 📥 Download & Installation / التحميل والتثبيت

1. Download **`EgyptianPharmaOptimizer_Setup_v1.7.exe`** from the Assets below.
2. Run the installer. If you have an earlier version installed, it will automatically update it in place.
3. Launch **Egyptian Pharma Optimizer** from your desktop or start menu.
