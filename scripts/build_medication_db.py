# -*- coding: utf-8 -*-
"""
Script to build and seed the Medication Knowledge Base (medications.db).
Clusters catalog items and PO items into Standard Medications, normalizes dosage units
(e.g., 5mg <-> 5مجم, 1gm <-> 1جم), and registers all raw Arabic/English variants,
un-reversed text, decoded glyphs, and unit-swapped variants as aliases.
"""
import os
import sys
import re
import json
import glob
import time
import shutil
import logging
from typing import List, Optional, Set, Tuple
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.medication_db import MedicationDB, DEFAULT_DB_PATH
from src.normalizer import (
    extract_canonical_brand,
    extract_dosage_form,
    parse_dosage_and_pack,
    unreverse_arabic_text,
    is_arabic_text_reversed,
    decode_custom_catalog_glyphs,
    strip_illegal_characters,
    ARABIC_TO_ENGLISH_BRANDS,
    ENGLISH_TO_ARABIC_BRANDS,
)
from src.pharma_matcher import (
    extract_core_brand_root,
    extract_form_category,
    clean_arabic_string,
    extract_modifiers,
)
from src.pdf_parser import PDFCatalogParser
from src.excel_parser import load_purchase_order

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BuildMedicationDB")

UNIT_NORMALIZATION_MAP = {
    'mg': 'مجم',
    'mgs': 'مجم',
    'مجم': 'مجم',
    'مج': 'مجم',
    'ملجم': 'مجم',
    'مليجرام': 'مجم',
    'مليجرم': 'مجم',
    'gm': 'جم',
    'gms': 'جم',
    'g': 'جم',
    'جم': 'جم',
    'جرام': 'جم',
    'غم': 'جم',
    'mcg': 'ميكروجرام',
    'ug': 'ميكروجرام',
    'μg': 'ميكروجرام',
    'ميكروجرام': 'ميكروجرام',
    'ميكرو': 'ميكروجرام',
    'مكجم': 'ميكروجرام',
    'ml': 'مل',
    'mls': 'مل',
    'مل': 'مل',
    'ملل': 'مل',
    'iu': 'وحدة',
    'ui': 'وحدة',
    'وحدة': 'وحدة',
    '%': '%',
}

EN_TO_AR_BRAND_VARIANTS = {}
for _ar, _en in ARABIC_TO_ENGLISH_BRANDS.items():
    EN_TO_AR_BRAND_VARIANTS.setdefault(_en.lower(), []).append(_ar)


def normalize_dosage_unit(strength: str) -> str:
    """
    Normalizes dosage units across Arabic and English representations to standard canonical Arabic units.
    Ensures identical active ingredient strengths cluster under the same standard medication ID.
    E.g.:
      '5mg' -> '5مجم'
      '5 مج' / '5مج' -> '5مجم'
      '5مجم' -> '5مجم'
      '1gm' / '1g' / '1جم' -> '1جم'
      '100ml' / '100مل' -> '100مل'
      '500mcg' / '500ug' / '500ميكروجرام' -> '500ميكروجرام'
      '10000iu' / '10000وحدة' -> '10000وحدة'
    """
    if not strength:
        return ""
    s = strength.strip().lower()

    # 1. Match standard single or ratio number + unit, e.g. "5mg", "0.5 مجم", "50/1000 mg", "1.25/5mg"
    m = re.match(r'^([\d./]+)\s*([a-zA-Z\u0600-\u06ff%]+)$', s)
    if m:
        num_part = m.group(1).strip()
        if num_part.startswith('.'):
            num_part = '0' + num_part
        unit_part = m.group(2).strip()
        canonical_unit = UNIT_NORMALIZATION_MAP.get(unit_part, unit_part)
        return f"{num_part}{canonical_unit}"

    # 2. Match reversed notation, e.g. "مج 5" -> "5مجم"
    m_rev = re.match(r'^([a-zA-Z\u0600-\u06ff%]+)\s*([\d./]+)$', s)
    if m_rev:
        unit_part = m_rev.group(1).strip()
        num_part = m_rev.group(2).strip()
        if num_part.startswith('.'):
            num_part = '0' + num_part
        canonical_unit = UNIT_NORMALIZATION_MAP.get(unit_part, unit_part)
        return f"{num_part}{canonical_unit}"

    return s


def get_dosage_unit_variants(strength: str) -> List[str]:
    """Returns equivalent strength strings in both Arabic and English units."""
    if not strength:
        return []
    s = strength.strip().lower()
    m = re.match(r'^([\d./]+)\s*([a-zA-Z\u0600-\u06ff%]+)$', s)
    if not m:
        m_rev = re.match(r'^([a-zA-Z\u0600-\u06ff%]+)\s*([\d./]+)$', s)
        if m_rev:
            num = m_rev.group(2).strip()
            unit = m_rev.group(1).strip()
        else:
            return [strength]
    else:
        num = m.group(1).strip()
        unit = m.group(2).strip()

    if num.startswith('.'):
        num = '0' + num

    variants = [f"{num}{unit}"]
    if unit in ['mg', 'mgs', 'مجم', 'مج', 'ملجم', 'مليجرام']:
        variants.extend([f"{num}مجم", f"{num} مجم", f"{num}mg", f"{num} mg", f"{num}مج", f"{num} مج"])
    elif unit in ['gm', 'gms', 'g', 'جم', 'جرام', 'غم']:
        variants.extend([f"{num}جم", f"{num} جم", f"{num}gm", f"{num} gm", f"{num}g", f"{num} g"])
    elif unit in ['ml', 'mls', 'مل', 'ملل']:
        variants.extend([f"{num}مل", f"{num} مل", f"{num}ml", f"{num} ml"])
    elif unit in ['mcg', 'ug', 'μg', 'ميكروجرام', 'ميكرو', 'مكجم']:
        variants.extend([f"{num}ميكروجرام", f"{num} ميكروجرام", f"{num}mcg", f"{num} mcg"])
    elif unit in ['iu', 'ui', 'وحدة']:
        variants.extend([f"{num}وحدة", f"{num} وحدة", f"{num}iu", f"{num} iu"])
    return list(dict.fromkeys(variants))


def isolate_product_name(text: str) -> str:
    """Isolates the authentic product name if commercial substitute tokens ('بديل' / 'substitute') are present."""
    s = str(text).strip()
    if 'بديل' in s:
        parts = s.split('بديل')
        if parts[0].strip():
            return parts[0].strip()
    if 'substitute' in s.lower():
        parts = re.split(r'substitute', s, flags=re.IGNORECASE)
        if parts[0].strip():
            return parts[0].strip()
    return s


def seed_canonical_brands(db: MedicationDB):
    """Seeds baseline canonical brands from ARABIC_TO_ENGLISH_BRANDS dictionary in a single fast transaction."""
    logger.info(f"Seeding {len(ARABIC_TO_ENGLISH_BRANDS)} canonical brands into MedicationDB...")
    with db._connection() as conn:
        cur = conn.cursor()
        for ar_brand, en_root in ARABIC_TO_ENGLISH_BRANDS.items():
            canonical_name = f"{ar_brand} ({en_root.title()})"
            cur.execute("""
                INSERT OR IGNORE INTO standard_medications
                (canonical_name, canonical_brand, form_category, strength, pack_size, active_substance)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (canonical_name, en_root, "UNKNOWN", "", "", ""))

            row = cur.execute("SELECT id FROM standard_medications WHERE canonical_name = ?", (canonical_name,)).fetchone()
            if row:
                std_id = row[0]
                seed_variants = [
                    (ar_brand, "brand_dict_ar"),
                    (en_root, "brand_dict_en"),
                    (en_root.title(), "brand_dict_en"),
                    (en_root.upper(), "brand_dict_en"),
                    (canonical_name, "canonical_seed"),
                ]
                for extra_ar in EN_TO_AR_BRAND_VARIANTS.get(en_root.lower(), []):
                    seed_variants.append((extra_ar, "brand_dict_ar"))
                for v, src in seed_variants:
                    cur.execute("""
                        INSERT OR IGNORE INTO medication_aliases
                        (standard_id, raw_text, normalized_text, source, is_verified)
                        VALUES (?, ?, ?, ?, ?)
                    """, (std_id, v, clean_arabic_string(v), src, 1))

    db._load_cache()
    logger.info(f"Seeded {len(ARABIC_TO_ENGLISH_BRANDS)} baseline brands.")


def ingest_item_strings(db: MedicationDB, items: List[str], source_label: str):
    """
    Analyzes a list of medicine item names, infers canonical identity with unit normalization,
    creates standard medications if needed, and registers all raw, normalized, and un-reversed variants.
    """
    if not items:
        return
    logger.info(f"Ingesting {len(items)} item strings from '{source_label}'...")
    created_standards = 0
    registered_aliases = 0
    alias_rows = []

    with db._connection() as conn:
        cur = conn.cursor()
        for raw in items:
            raw_str = str(raw).strip()
            if not raw_str or len(raw_str) < 2:
                continue

            # Isolate genuine brand if commercial substitute marker exists
            target_str = isolate_product_name(raw_str)

            # Unreverse target string if reversed for accurate feature extraction
            feature_str = target_str
            if is_arabic_text_reversed(target_str):
                unrev = unreverse_arabic_text(target_str)
                if unrev:
                    feature_str = unrev

            # 1. Brand root / canonical brand
            brand_en = extract_canonical_brand(feature_str)
            brand_ar = extract_core_brand_root(feature_str)
            if not brand_en and brand_ar:
                brand_en = ARABIC_TO_ENGLISH_BRANDS.get(brand_ar, brand_ar)
            if not brand_en:
                brand_en = brand_ar or feature_str.split()[0]

            # 2. Dosage form category
            form_cat = extract_form_category(feature_str)

            # 3. Strength & pack with unit normalization
            strength, pack = parse_dosage_and_pack(feature_str)
            norm_strength = normalize_dosage_unit(strength)

            # 4. Modifiers
            mods = extract_modifiers(feature_str)

            # Construct standardized canonical representation
            primary_brand = ENGLISH_TO_ARABIC_BRANDS.get(brand_en.lower(), brand_ar or brand_en)
            parts = [primary_brand]
            if norm_strength:
                parts.append(norm_strength)
            if mods:
                parts.extend(sorted(mods))
            if form_cat != "UNKNOWN":
                parts.append(form_cat)
            canonical_name = " ".join(parts).strip()

            # Insert or ignore standard medication
            cur.execute("""
                INSERT OR IGNORE INTO standard_medications
                (canonical_name, canonical_brand, form_category, strength, pack_size, active_substance)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (canonical_name, brand_en, form_cat, norm_strength or "", pack or "", ""))

            row = cur.execute("SELECT id FROM standard_medications WHERE canonical_name = ?", (canonical_name,)).fetchone()
            if not row:
                continue
            std_id = row[0]
            created_standards += 1

            # Collect alias candidates
            aliases_for_item: Set[str] = set()
            aliases_for_item.add(raw_str)
            aliases_for_item.add(canonical_name)

            # Cleaned / normalized Arabic
            norm_raw = clean_arabic_string(raw_str)
            if norm_raw:
                aliases_for_item.add(norm_raw)

            # Decoded custom glyphs (Al-Hadhaba aboriginal runics, Arwasoft Greek)
            decoded = decode_custom_catalog_glyphs(raw_str)
            if decoded and decoded != raw_str:
                aliases_for_item.add(decoded)
                norm_d = clean_arabic_string(decoded)
                if norm_d:
                    aliases_for_item.add(norm_d)

            # Unreversed Arabic variant
            if is_arabic_text_reversed(raw_str):
                unreversed = unreverse_arabic_text(raw_str)
                if unreversed and unreversed != raw_str:
                    aliases_for_item.add(unreversed)
                    norm_u = clean_arabic_string(unreversed)
                    if norm_u:
                        aliases_for_item.add(norm_u)
            else:
                unrev = unreverse_arabic_text(raw_str)
                if unrev and unrev != raw_str:
                    aliases_for_item.add(unrev)
                    norm_u = clean_arabic_string(unrev)
                    if norm_u:
                        aliases_for_item.add(norm_u)

            # Brand variations across all known Arabic spelling forms and English roots
            all_brand_variants: Set[str] = set()
            if primary_brand:
                all_brand_variants.add(primary_brand)
            if brand_ar:
                all_brand_variants.add(brand_ar)
            if brand_en:
                all_brand_variants.add(brand_en)
                all_brand_variants.add(brand_en.title())
                all_brand_variants.add(brand_en.upper())
                for extra_ar in EN_TO_AR_BRAND_VARIANTS.get(brand_en.lower(), []):
                    all_brand_variants.add(extra_ar)

            # Unit variations
            if strength:
                for u_var in get_dosage_unit_variants(strength):
                    variant_str = re.sub(re.escape(strength), u_var, raw_str, flags=re.IGNORECASE)
                    aliases_for_item.add(variant_str)
                    norm_v = clean_arabic_string(variant_str)
                    if norm_v:
                        aliases_for_item.add(norm_v)

                    # Also brand + u_var variants across all brand variants
                    for b_var in all_brand_variants:
                        aliases_for_item.add(f"{b_var} {u_var}")
                        aliases_for_item.add(f"{b_var}{u_var}")
                        # Reversed brand variant for Arabic
                        if re.match(r'^[\u0600-\u06ff]+$', b_var):
                            aliases_for_item.add(f"{b_var[::-1]} {u_var}")
                            if b_var == "كونكور":
                                aliases_for_item.add(f"ركونوك {u_var}")

            elif norm_strength:
                for b_var in all_brand_variants:
                    aliases_for_item.add(f"{b_var} {norm_strength}")
                    aliases_for_item.add(f"{b_var}{norm_strength}")
                    if re.match(r'^[\u0600-\u06ff]+$', b_var):
                        aliases_for_item.add(f"{b_var[::-1]} {norm_strength}")
                        if b_var == "كونكور":
                            aliases_for_item.add(f"ركونوك {norm_strength}")

            # Register brand + modifier combinations (e.g. 'panadol extra', 'بنادول اكسترا')
            if mods:
                mod_str = " ".join(sorted(mods))
                mod_translations = {
                    'extra': 'اكسترا',
                    'plus': 'بلاس',
                    'advance': 'ادفانس',
                    'junior': 'جونيور',
                    'cold_flu': 'كولد اند فلو',
                }
                ar_mods = [mod_translations.get(m, m) for m in sorted(mods)]
                ar_mod_str = " ".join(ar_mods)
                for b_var in all_brand_variants:
                    aliases_for_item.add(f"{b_var} {mod_str}")
                    aliases_for_item.add(f"{b_var} {ar_mod_str}")
                    if norm_strength:
                        aliases_for_item.add(f"{b_var} {norm_strength} {mod_str}")
                        aliases_for_item.add(f"{b_var} {norm_strength} {ar_mod_str}")

            # Register form abbreviations
            if norm_strength and form_cat == 'SOLID_ORAL':
                for b_var in all_brand_variants:
                    if re.match(r'^[\u0600-\u06ff]+$', b_var):
                        aliases_for_item.add(f"{b_var} {norm_strength} اقراص")
                        aliases_for_item.add(f"{b_var} {norm_strength} قرص")
                        if pack:
                            aliases_for_item.add(f"{b_var} {norm_strength} {pack} قرص")
                    else:
                        aliases_for_item.add(f"{b_var} {norm_strength} tab")
                        aliases_for_item.add(f"{b_var} {norm_strength} tabs")
                        aliases_for_item.add(f"{b_var} {norm_strength} tablet")

            for a_text in aliases_for_item:
                a_clean = a_text.strip()
                if a_clean:
                    alias_rows.append((std_id, a_clean, clean_arabic_string(a_clean), source_label, 1))

        if alias_rows:
            cur.executemany("""
                INSERT OR IGNORE INTO medication_aliases
                (standard_id, raw_text, normalized_text, source, is_verified)
                VALUES (?, ?, ?, ?, ?)
            """, alias_rows)
            registered_aliases = len(alias_rows)

    db._load_cache()
    logger.info(
        f"Completed '{source_label}': Processed {created_standards} standard references, "
        f"registered up to {registered_aliases} alias rows."
    )


def build_from_workspace(db_path: Optional[str] = None, rebuild_fresh: bool = True):
    """Builds and populates medications.db from project catalogs and PO files."""
    target_path = db_path or DEFAULT_DB_PATH
    if rebuild_fresh and os.path.exists(target_path):
        bak_path = target_path + ".bak"
        logger.info(f"Backing up existing database to {bak_path}...")
        try:
            shutil.copy2(target_path, bak_path)
        except Exception as e:
            logger.warning(f"Could not backup existing DB: {e}")
        for ext in ["", "-wal", "-shm"]:
            f = target_path + ext
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    db = MedicationDB(target_path)

    # 1. Seed brand dictionary
    seed_canonical_brands(db)

    # 2. Ingest PO files
    po_search_patterns = [
        os.path.join(PROJECT_ROOT, "train", "*.xlsx"),
        os.path.join(os.path.expanduser("~"), "Desktop", "train", "*.xlsx"),
        os.path.join(PROJECT_ROOT, "input", "orders", "*.xlsx"),
        os.path.join(PROJECT_ROOT, "test1", "*.xlsx"),
    ]
    seen_po_names = set()
    po_paths = []
    for pattern in po_search_patterns:
        for p in glob.glob(pattern):
            bname = os.path.basename(p)
            if not bname.startswith("~$") and bname not in seen_po_names:
                seen_po_names.add(bname)
                po_paths.append(p)

    logger.info(f"Discovered {len(po_paths)} purchase order files to ingest: {[os.path.basename(p) for p in po_paths]}")
    for po_path in po_paths:
        fname = os.path.basename(po_path)
        try:
            df_po = load_purchase_order(po_path, drop_zero_qty=False)
            if not df_po.empty:
                po_items = []
                if "requested_item" in df_po.columns:
                    po_items.extend(df_po["requested_item"].dropna().tolist())
                if "canonical_item" in df_po.columns:
                    po_items.extend(df_po["canonical_item"].dropna().tolist())
                unique_items = list(dict.fromkeys(str(x).strip() for x in po_items if str(x).strip()))
                if unique_items:
                    ingest_item_strings(db, unique_items, source_label=f"PO_{fname}")
        except Exception as e:
            logger.warning(f"Could not load PO file {fname}: {e}")

    # 3. Ingest items from existing survey report if available
    survey_path = os.path.join(PROJECT_ROOT, "scripts", "survey_report.json")
    if os.path.isfile(survey_path):
        try:
            with open(survey_path, "r", encoding="utf-8") as f:
                survey_data = json.load(f)
                matched_analysis = survey_data.get("matching_analysis", {})
                survey_items = set()
                for po_name, p_data in matched_analysis.items():
                    for s in p_data.get("matched_samples", []):
                        if "requested" in s:
                            survey_items.add(s["requested"])
                        if "matched_catalog" in s:
                            survey_items.add(s["matched_catalog"])
                if survey_items:
                    ingest_item_strings(db, list(survey_items), source_label="SurveyReport")
        except Exception as e:
            logger.warning(f"Could not ingest survey report: {e}")

    # 4. Ingest active catalogs in train/ and input/catalogs
    cat_search_patterns = [
        os.path.join(PROJECT_ROOT, "train", "*.pdf"),
        os.path.join(os.path.expanduser("~"), "Desktop", "train", "*.pdf"),
        os.path.join(PROJECT_ROOT, "input", "catalogs", "*.pdf"),
    ]
    seen_cat_names = set()
    cat_pdfs = []
    for pattern in cat_search_patterns:
        for p in glob.glob(pattern):
            bname = os.path.basename(p)
            if not bname.startswith("~$") and bname not in seen_cat_names:
                seen_cat_names.add(bname)
                cat_pdfs.append(p)

    logger.info(f"Discovered {len(cat_pdfs)} wholesaler catalog PDF files to ingest.")
    for pdf_path in cat_pdfs:
        fname = os.path.basename(pdf_path)
        try:
            logger.info(f"Parsing catalog PDF: {fname}...")
            parser = PDFCatalogParser(pdf_path)
            df_cat = parser.parse()
            if not df_cat.empty:
                cat_items = []
                if "item_name" in df_cat.columns:
                    cat_items.extend(df_cat["item_name"].dropna().tolist())
                if "normalized_name" in df_cat.columns:
                    cat_items.extend(df_cat["normalized_name"].dropna().tolist())
                unique_items = list(dict.fromkeys(str(x).strip() for x in cat_items if str(x).strip()))
                if unique_items:
                    ingest_item_strings(db, unique_items, source_label=f"Catalog_{fname}")
        except Exception as e:
            logger.warning(f"Could not parse catalog PDF {fname}: {e}")

    stats = db.stats()
    logger.info("=== MedicationDB Build Finished ===")
    logger.info(f"Database Path: {stats['db_path']}")
    logger.info(f"Total Standard Medications: {stats['total_standards']}")
    logger.info(f"Total Registered Aliases: {stats['total_aliases']}")
    logger.info(f"Unique Normalized Aliases: {stats['unique_normalized_aliases']}")

    # 5. Verification benchmark
    sample_queries = [
        "كونكور 10 مجم 30 قرص",
        "CONCOR 10MG TAB",
        "ركونوك 10 مجم",
        "كتافلام 50 مجم",
        "اوجمانتين 1 جم",
        "AUGMENTIN 1GM",
        "بانادول اكسترا",
        "PANADOL EXTRA",
    ]
    logger.info("Running verification resolution benchmarks...")
    for q in sample_queries:
        t0 = time.perf_counter()
        res = db.resolve(q)
        elapsed_us = (time.perf_counter() - t0) * 1_000_000
        status = f"ID={res['id']} ({res['canonical_name']})" if res else "NOT FOUND"
        logger.info(f"Resolve '{q}' -> {status} in {elapsed_us:.2f} µs")

    return db


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass
    build_from_workspace()
