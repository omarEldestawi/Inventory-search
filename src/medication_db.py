# -*- coding: utf-8 -*-
"""
Medication Knowledge Base & Alias Resolution Engine.
Provides high-performance SQLite-backed storage and in-memory O(1) resolution
for standard pharmaceutical entities and all their raw, reversed, or misspelled aliases.
Decouples static clinical identity from fluctuating daily vendor discount rates.
"""
import os
import sys
import re
import shutil
import sqlite3
import logging
from typing import Optional, Dict, Any, List, Tuple

try:
    from .normalizer import (
        extract_canonical_brand,
        extract_dosage_form,
        unreverse_arabic_text,
        is_arabic_text_reversed,
        decode_custom_catalog_glyphs,
    )
    from .pharma_matcher import (
        clean_arabic_string,
        extract_core_brand_root,
        extract_form_category,
        is_safe_pharmaceutical_match,
    )
except ImportError:
    from normalizer import (
        extract_canonical_brand,
        extract_dosage_form,
        unreverse_arabic_text,
        is_arabic_text_reversed,
        decode_custom_catalog_glyphs,
    )
    from pharma_matcher import (
        clean_arabic_string,
        extract_core_brand_root,
        extract_form_category,
        is_safe_pharmaceutical_match,
    )

logger = logging.getLogger("MedicationDB")

def _resolve_default_db_path() -> str:
    """Resolves medications.db location in both dev and PyInstaller frozen runtime."""
    if getattr(sys, "frozen", False):
        # 1. User-writable directory in AppData / LocalAppData
        local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        user_db_dir = os.path.join(local_app_data, "EgyptianPharmaOptimizer", "data")
        user_db_path = os.path.join(user_db_dir, "medications.db")

        # 2. Locate bundled template database
        bundled_template = None
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p1 = os.path.join(meipass, "data", "medications.db")
            if os.path.exists(p1):
                bundled_template = p1
        if not bundled_template:
            exe_dir = os.path.dirname(sys.executable)
            p2 = os.path.join(exe_dir, "data", "medications.db")
            if os.path.exists(p2):
                bundled_template = p2
        if not bundled_template and meipass:
            bundled_template = os.path.join(meipass, "data", "medications.db")

        # 3. If user db doesn't exist, try initializing it from bundled template
        if bundled_template and os.path.exists(bundled_template):
            if not os.path.exists(user_db_path) or os.path.getsize(user_db_path) == 0:
                try:
                    os.makedirs(user_db_dir, exist_ok=True)
                    shutil.copy2(bundled_template, user_db_path)
                    logger.info(f"Initialized user medications database at: {user_db_path}")
                except Exception as exc:
                    logger.warning(f"Could not copy template to user dir: {exc}. Using bundled database.")
                    return bundled_template
            return user_db_path

        if os.path.exists(user_db_path) and os.path.getsize(user_db_path) > 0:
            return user_db_path
        if bundled_template:
            return bundled_template

    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "medications.db"
    )

DEFAULT_DB_PATH = _resolve_default_db_path()


class MedicationDB:
    """
    SQLite-backed repository of standard medication items and their alias variants.
    Maintains an in-memory hot lookup table for sub-millisecond resolutions.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = _resolve_default_db_path()
        self.db_path = os.path.abspath(db_path)
        self._is_read_only = False

        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        except Exception:
            pass

        self._raw_cache: Dict[str, Dict[str, Any]] = {}
        self._norm_cache: Dict[str, Dict[str, Any]] = {}
        self._standards_cache: Dict[int, Dict[str, Any]] = {}

        self._init_db()
        self._load_cache()

    def _connection(self, read_only: bool = False):
        """Context manager that ensures connections are closed immediately on exit."""
        db_path = self.db_path
        parent_self = self

        class _ConnContext:
            def __init__(self, path, ro_requested):
                self.is_ro = ro_requested or getattr(parent_self, "_is_read_only", False)
                self.conn = None

                # Proactively detect read-only files before attempting write connection
                if not self.is_ro and os.path.exists(path) and not os.access(path, os.W_OK):
                    self.is_ro = True
                    parent_self._is_read_only = True

                if not self.is_ro:
                    try:
                        self.conn = sqlite3.connect(path, timeout=30.0)
                        self.conn.row_factory = sqlite3.Row
                        self.conn.execute("PRAGMA journal_mode = WAL;")
                        self.conn.execute("PRAGMA synchronous = NORMAL;")
                        self.conn.execute("PRAGMA foreign_keys = ON;")
                        return
                    except sqlite3.OperationalError as op_err:
                        # Falling back to read-only mode for read-only or permission-restricted locations (e.g. Program Files)
                        logger.info(f"Read-write SQLite connection failed ({op_err}). Falling back to read-only URI mode.")
                        if self.conn:
                            try:
                                self.conn.close()
                            except Exception:
                                pass
                            self.conn = None
                        self.is_ro = True
                        parent_self._is_read_only = True

                # Read-only fallback connection via URI
                norm = os.path.abspath(path).replace("\\", "/")
                if not norm.startswith("/"):
                    norm = "/" + norm
                uri = f"file://{norm}?mode=ro&immutable=1"
                self.conn = sqlite3.connect(uri, uri=True, timeout=30.0)
                self.conn.row_factory = sqlite3.Row
                try:
                    self.conn.execute("PRAGMA query_only = ON;")
                except Exception:
                    pass

            def __enter__(self):
                return self.conn

            def __exit__(self, exc_type, exc_val, exc_tb):
                if not self.is_ro:
                    if exc_type is None:
                        try:
                            self.conn.commit()
                        except Exception:
                            pass
                    else:
                        try:
                            self.conn.rollback()
                        except Exception:
                            pass
                try:
                    self.conn.close()
                except Exception:
                    pass

        return _ConnContext(db_path, read_only)

    def close(self):
        """Checkpoints WAL and clears caches."""
        self._raw_cache.clear()
        self._norm_cache.clear()
        self._standards_cache.clear()
        if not getattr(self, "_is_read_only", False):
            try:
                conn = sqlite3.connect(self.db_path, timeout=10.0)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                conn.close()
            except Exception:
                pass
        import gc
        gc.collect()

    def _init_db(self) -> None:
        """Initializes tables and indexes if they do not exist."""
        if getattr(self, "_is_read_only", False):
            return

        try:
            with self._connection(read_only=False) as conn:
                if getattr(self, "_is_read_only", False):
                    return
                # Check if standard_medications table already exists
                table_check = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='standard_medications'"
                ).fetchone()
                if table_check:
                    return

                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS standard_medications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        canonical_name TEXT UNIQUE NOT NULL,
                        canonical_brand TEXT NOT NULL,
                        form_category TEXT NOT NULL,
                        strength TEXT DEFAULT '',
                        pack_size TEXT DEFAULT '',
                        active_substance TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS medication_aliases (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        standard_id INTEGER NOT NULL REFERENCES standard_medications(id) ON DELETE CASCADE,
                        raw_text TEXT NOT NULL,
                        normalized_text TEXT NOT NULL,
                        source TEXT DEFAULT 'catalog',
                        is_verified INTEGER DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(standard_id, raw_text)
                    );

                    CREATE INDEX IF NOT EXISTS idx_aliases_raw ON medication_aliases(raw_text);
                    CREATE INDEX IF NOT EXISTS idx_aliases_norm ON medication_aliases(normalized_text);
                    CREATE INDEX IF NOT EXISTS idx_aliases_standard ON medication_aliases(standard_id);
                    CREATE INDEX IF NOT EXISTS idx_standards_brand ON standard_medications(canonical_brand);
                    CREATE INDEX IF NOT EXISTS idx_standards_form ON standard_medications(form_category);
                """)
        except sqlite3.OperationalError:
            self._is_read_only = True

    def _load_cache(self) -> None:
        """Pre-loads all standard medications and aliases into in-memory dictionaries for O(1) matching."""
        self._raw_cache.clear()
        self._norm_cache.clear()
        self._standards_cache.clear()

        try:
            with self._connection() as conn:
                standards = conn.execute("SELECT * FROM standard_medications").fetchall()
                for s in standards:
                    s_dict = dict(s)
                    self._standards_cache[s_dict["id"]] = s_dict

                aliases = conn.execute(
                    "SELECT standard_id, raw_text, normalized_text FROM medication_aliases"
                ).fetchall()
                for a in aliases:
                    std_info = self._standards_cache.get(a["standard_id"])
                    if std_info:
                        self._raw_cache[a["raw_text"]] = std_info
                        self._norm_cache[a["normalized_text"]] = std_info
        except Exception as e:
            logger.warning(f"Error pre-loading MedicationDB cache: {e}")

    def get_standard_by_id(self, standard_id: int) -> Optional[Dict[str, Any]]:
        """Returns standard medication information by standard_id."""
        return self._standards_cache.get(standard_id)

    def resolve(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Resolves an extracted drug string (Arabic, English, reversed, misspelled)
        to its canonical standard medication entity in O(1) time.
        """
        if not text or not str(text).strip():
            return None

        raw = str(text).strip()
        # 1. Exact raw text hit
        if raw in self._raw_cache:
            return self._raw_cache[raw]

        # 2. Normalized text hit
        norm = clean_arabic_string(raw)
        if norm in self._norm_cache:
            return self._norm_cache[norm]

        # 3. Unit swap fallback (e.g. 5mg <-> 5مجم, 5مج -> 5مجم, 1gm <-> 1جم)
        alt_norm = None
        if "mg" in norm:
            alt_norm = clean_arabic_string(re.sub(r'(\d+(?:\.\d+)?)\s*mg\b', r'\1 مجم', norm))
        elif "مجم" in norm:
            alt_norm = clean_arabic_string(re.sub(r'(\d+(?:\.\d+)?)\s*مجم\b', r'\1 mg', norm))
        elif "مج" in norm:
            alt_norm = clean_arabic_string(re.sub(r'(\d+(?:\.\d+)?)\s*مج\b', r'\1 مجم', norm))
        elif "gm" in norm or "g" in norm:
            alt_norm = clean_arabic_string(re.sub(r'(\d+(?:\.\d+)?)\s*(?:gm|g)\b', r'\1 جم', norm))
        elif "جم" in norm:
            alt_norm = clean_arabic_string(re.sub(r'(\d+(?:\.\d+)?)\s*جم\b', r'\1 gm', norm))

        if alt_norm and alt_norm in self._norm_cache:
            res = self._norm_cache[alt_norm]
            self._norm_cache[norm] = res
            self._raw_cache[raw] = res
            return res

        # 4. Packaging/form suffix fallback (e.g. "concor 10 mg tab", "كونكور 10 مجم 30 قرص")
        norm_stripped = re.sub(
            r'\s+(?:\d+\s+)?(?:قرص|اقراص|شريط|باكت|علبه|علبة|ك|ق|tab|tabs|tablet|tablets|cap|caps|capsule|capsules|amp|ampoule|syr|syrup|susp|suspension)\b.*$',
            '',
            norm
        ).strip()
        if norm_stripped and norm_stripped != norm and norm_stripped in self._norm_cache:
            res = self._norm_cache[norm_stripped]
            self._norm_cache[norm] = res
            self._raw_cache[raw] = res
            return res

        # 5. Unreversed Arabic fallback
        if is_arabic_text_reversed(raw):
            unrev = unreverse_arabic_text(raw)
            if unrev in self._raw_cache:
                res = self._raw_cache[unrev]
                self._raw_cache[raw] = res
                return res
            unrev_norm = clean_arabic_string(unrev)
            if unrev_norm in self._norm_cache:
                res = self._norm_cache[unrev_norm]
                self._norm_cache[norm] = res
                self._raw_cache[raw] = res
                return res

        # 6. Decoded glyphs fallback
        decoded = decode_custom_catalog_glyphs(raw)
        if decoded and decoded != raw:
            if decoded in self._raw_cache:
                res = self._raw_cache[decoded]
                self._raw_cache[raw] = res
                return res
            d_norm = clean_arabic_string(decoded)
            if d_norm in self._norm_cache:
                res = self._norm_cache[d_norm]
                self._norm_cache[norm] = res
                self._raw_cache[raw] = res
                return res

        return None

    def add_standard_medication(
        self,
        canonical_name: str,
        canonical_brand: str,
        form_category: str,
        strength: str = "",
        pack_size: str = "",
        active_substance: str = ""
    ) -> int:
        """Inserts a new standard medication entity."""
        name = canonical_name.strip()
        brand = canonical_brand.strip().lower()
        form = form_category.strip().upper()
        strength = strength.strip()
        pack = pack_size.strip()
        substance = active_substance.strip()

        if getattr(self, "_is_read_only", False):
            for existing_id, std in self._standards_cache.items():
                if std.get("canonical_name") == name:
                    std["canonical_brand"] = brand
                    std["form_category"] = form
                    std["strength"] = strength
                    std["pack_size"] = pack
                    if substance:
                        std["active_substance"] = substance
                    self.register_alias(existing_id, name, source="canonical_seed")
                    return existing_id

            standard_id = max(self._standards_cache.keys(), default=0) + 1
            record = {
                "id": standard_id,
                "canonical_name": name,
                "canonical_brand": brand,
                "form_category": form,
                "strength": strength,
                "pack_size": pack,
                "active_substance": substance
            }
            self._standards_cache[standard_id] = record
            self.register_alias(standard_id, name, source="canonical_seed")
            return standard_id

        try:
            with self._connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO standard_medications
                    (canonical_name, canonical_brand, form_category, strength, pack_size, active_substance)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_name) DO UPDATE SET
                        canonical_brand=excluded.canonical_brand,
                        form_category=excluded.form_category,
                        strength=excluded.strength,
                        pack_size=excluded.pack_size
                    RETURNING id;
                """, (name, brand, form, strength, pack, substance))
                row = cur.fetchone()
                standard_id = row[0]
        except sqlite3.OperationalError as op_err:
            logger.info(f"Write operation failed on read-only database ({op_err}). Caching standard in-memory.")
            self._is_read_only = True
            for existing_id, std in self._standards_cache.items():
                if std.get("canonical_name") == name:
                    std["canonical_brand"] = brand
                    std["form_category"] = form
                    std["strength"] = strength
                    std["pack_size"] = pack
                    if substance:
                        std["active_substance"] = substance
                    self.register_alias(existing_id, name, source="canonical_seed")
                    return existing_id

            standard_id = max(self._standards_cache.keys(), default=0) + 1
            record = {
                "id": standard_id,
                "canonical_name": name,
                "canonical_brand": brand,
                "form_category": form,
                "strength": strength,
                "pack_size": pack,
                "active_substance": substance
            }
            self._standards_cache[standard_id] = record
            self.register_alias(standard_id, name, source="canonical_seed")
            return standard_id

        record = {
            "id": standard_id,
            "canonical_name": name,
            "canonical_brand": brand,
            "form_category": form,
            "strength": strength,
            "pack_size": pack,
            "active_substance": substance
        }
        self._standards_cache[standard_id] = record
        # Register the canonical name itself as an alias
        self.register_alias(standard_id, name, source="canonical_seed")
        return standard_id

    def register_alias(
        self,
        standard_id: int,
        raw_text: str,
        source: str = "catalog",
        is_verified: bool = True
    ) -> bool:
        """Registers a name variation/alias pointing to a standard medication."""
        raw = str(raw_text).strip()
        if not raw:
            return False

        norm = clean_arabic_string(raw)
        std_info = self._standards_cache.get(standard_id)
        if not std_info:
            return False

        if getattr(self, "_is_read_only", False):
            self._raw_cache[raw] = std_info
            self._norm_cache[norm] = std_info
            return True

        try:
            with self._connection() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO medication_aliases
                    (standard_id, raw_text, normalized_text, source, is_verified)
                    VALUES (?, ?, ?, ?, ?)
                """, (standard_id, raw, norm, source, 1 if is_verified else 0))
        except sqlite3.OperationalError as op_err:
            logger.info(f"Write operation failed on read-only database ({op_err}). Caching alias in-memory.")
            self._is_read_only = True
            self._raw_cache[raw] = std_info
            self._norm_cache[norm] = std_info
            return True
        except Exception as e:
            logger.debug(f"Failed to insert alias '{raw}': {e}")
            self._raw_cache[raw] = std_info
            self._norm_cache[norm] = std_info
            return True

        self._raw_cache[raw] = std_info
        self._norm_cache[norm] = std_info
        return True

    def bulk_register_aliases(self, records: List[Tuple[int, str, str]]) -> int:
        """
        Batch registers aliases.
        records: list of (standard_id, raw_text, source)
        """
        if not records:
            return 0

        if getattr(self, "_is_read_only", False):
            for std_id, raw, src in records:
                r = str(raw).strip()
                if r:
                    std_info = self._standards_cache.get(std_id)
                    if std_info:
                        self._raw_cache[r] = std_info
                        self._norm_cache[clean_arabic_string(r)] = std_info
            return len(records)

        rows = []
        for std_id, raw, src in records:
            r = str(raw).strip()
            if r:
                rows.append((std_id, r, clean_arabic_string(r), src, 1))

        inserted = 0
        try:
            with self._connection() as conn:
                cur = conn.cursor()
                cur.executemany("""
                    INSERT OR IGNORE INTO medication_aliases
                    (standard_id, raw_text, normalized_text, source, is_verified)
                    VALUES (?, ?, ?, ?, ?)
                """, rows)
                inserted = cur.rowcount

            # Refresh cache
            self._load_cache()
            return inserted
        except sqlite3.OperationalError as op_err:
            logger.info(f"Bulk insert failed on read-only database ({op_err}). Caching aliases in-memory.")
            self._is_read_only = True
            for std_id, raw, src in records:
                r = str(raw).strip()
                if r:
                    std_info = self._standards_cache.get(std_id)
                    if std_info:
                        self._raw_cache[r] = std_info
                        self._norm_cache[clean_arabic_string(r)] = std_info
            return len(records)

    def count_standards(self) -> int:
        """Returns total number of standard medications."""
        return len(self._standards_cache)

    def count_aliases(self) -> int:
        """Returns total number of registered aliases."""
        return len(self._raw_cache)

    def stats(self) -> Dict[str, Any]:
        """Returns database statistics."""
        return {
            "db_path": self.db_path,
            "total_standards": self.count_standards(),
            "total_aliases": self.count_aliases(),
            "unique_normalized_aliases": len(self._norm_cache),
        }
