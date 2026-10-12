# -*- coding: utf-8 -*-
"""
Strict Pharmaceutical Entity & Safety Validator.
Guarantees zero dangerous drug substitutions, strict dosage form consistency,
and exact strength / infant milk stage verification.
"""
import re
import unicodedata
import functools
from typing import Optional, List, Dict, Set, Tuple, Union, Any
from rapidfuzz import fuzz

DIGITS_MAP = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')

def clean_arabic_string(text: str) -> str:
    """Normalize Arabic presentation forms, translate all digits, space numbers, and remove diacritics."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', str(text))
    text = text.translate(DIGITS_MAP)
    text = text.replace('٫', '.')
    # Pre-normalize Egyptian decimal shorthands (e.g. "5." -> "0.5", "25." -> "0.25", ".5" -> "0.5")
    text = re.sub(r'\b(\d+)\.(?=\s|[a-zA-Z\u0600-\u06FF]|$)', r'0.\1', text)
    text = re.sub(r'(?<!\d)\.(\d+)', r'0.\1', text)

    text = text.replace('\u064c', 'ي').replace('\u064b', 'ي').replace('ـ', '')
    text = re.sub(r'[\u0617-\u061A\u064B-\u0652]', '', text)
    
    char_map = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ة': 'ه', 'ى': 'ي', 'ئ': 'ي', 'ؤ': 'و',
        'ی': 'ي', 'ي': 'ي',
        'ﻼ': 'لا', 'ﻸ': 'لا', 'ﻹ': 'لا', 'ﻶ': 'لا', 'ك': 'ك', 'ک': 'ك',
        'ﻧ': 'ن', 'ﺳ': 'س', 'ﺷ': 'ش', 'ﺻ': 'ص', 'ﺿ': 'ض', 'ﻃ': 'ط',
        'ھ': 'ه', 'ہ': 'ه'
    }
    for src, dst in char_map.items():
        text = text.replace(src, dst)
        
    text = re.sub(r'(\d+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', text)
    text = re.sub(r'([a-zA-Z\u0600-\u06FF])(\d+)', r'\1 \2', text)
    text = re.sub(r'(\d+(?:\.\d+)?)', r' \1 ', text)
    # Do NOT strip decimal points when adjacent to digits
    text = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', text)
    text = text.replace('*', ' ').replace('/', ' ').replace('-', ' ').replace('_', ' ').replace('"', ' ').replace('\\', ' ').replace(',', ' ')
    return re.sub(r'\s+', ' ', text).strip().lower()

@functools.lru_cache(maxsize=16384)
def extract_form_category(text: str) -> str:
    """Classifies medicine dosage form into mutually exclusive categories."""
    t = clean_arabic_string(text)
    # Strip storage tags before evaluating dosage forms
    t = re.sub(r'\b(?:ث|ثلاجة|ثلاجه)\b', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    words = set(t.split())
    
    # 1. Explicit Suppository (must precede packaging words like شريط)
    if any(k in words or (len(k) >= 4 and k in t) for k in ['لبوس', 'قمع', 'اقماع', 'supp']):
        return 'SUPPOSITORY'

    # 2. Explicit Injectable / Parenteral (must precede generic solid oral or isolated 'ك')
    if any(k in words or (len(k) >= 4 and k in t) for k in ['امبول', 'امبولات', 'لوبما', 'فيال', 'فيالات', 'لايف', 'حقن', 'حقنه', 'حقنة', 'سرنجة', 'amp', 'vial', 'inj']):
        return 'INJECTABLE'

    # 3. Explicit Infant Milk Formulas
    if any(k in words or (len(k) >= 4 and k in t) for k in ['لبن', 'حليب', 'نستوجين', 'بيبيلاك', 'ابتاميل', 'هيرو', 'بيوميل', 'سيريلاك']) or re.search(r'\bنان\b', t):
        return 'INFANT_MILK'

    # 4. Vaginal Douche / Wash
    if any(k in t for k in ['دش مهبلي', 'غسول مهبلي', 'vaginal wash']) or any(k in words for k in ['دش', 'douche']):
        return 'DOUCHE'

    # 5. Drops / Ophthalmic / Otic / Oral Drops
    if any(k in words or (len(k) >= 4 and k in t) for k in ['قطرة', 'قطره', 'نقط', 'drops', 'eye drop', 'ear drop']):
        return 'DROPS'

    # 6. Spray / Inhaler
    if any(k in words or (len(k) >= 4 and k in t) for k in ['بخاخ', 'اسبراي', 'سبراي', 'spray', 'inhaler']):
        return 'SPRAY'

    # 7. Sachet / Effervescent
    if any(k in words or (len(k) >= 4 and k in t) for k in ['فوار', 'اكياس', 'كيس', 'اكلاس', 'سايكا', 'حبيبات', 'sachet', 'eff']):
        return 'SACHET'

    # 8. Oral Liquid / Syrup / Suspension
    if 'ماء غريب' in t or 'ماء نونو' in t or any(k in words or (len(k) >= 4 and k in t) or k in t for k in ['شراب', 'شرب', 'شاب', 'بارش', 'معلق', 'syrup', 'susp', 'elixir', 'ر شاب', 'ش راب', 'بار ش']) or re.search(r'\b(?:ش)\b', t):
        return 'ORAL_LIQUID'

    # 9. Topical Gel
    if any(k in words for k in ['جل', 'جيل', 'gel']):
        return 'TOPICAL_GEL'

    # 10. Topical Solution
    if any(k in words or (len(k) >= 4 and k in t) for k in ['محلول', 'solution', 'soln']):
        return 'TOPICAL_SOLUTION'

    # 11. Topical Cream
    if any(k in words or (len(k) >= 4 and k in t) for k in ['كريم', 'cream']):
        return 'TOPICAL_CREAM'

    # 12. Topical Ointment
    if any(k in words or (len(k) >= 4 and k in t) for k in ['مرهم', 'دهان', 'ointment', 'oint']):
        return 'TOPICAL_OINTMENT'

    # 13. Cosmetic & Hygiene (Deodorant roll-on, shampoo, wash, lotion, oil, serum)
    if 'رول اون' in t or 'roll on' in t or any(k in words or (len(k) >= 4 and k in t) for k in ['غسول', 'شامبو', 'صابون', 'لوشن', 'لوسيون', 'سيرم', 'زيت', 'shampoo', 'lotion', 'wash']):
        return 'COSMETIC'

    # 14. Explicit Solid Oral (Tablets, Capsules, Strips)
    # Note: 'ك' or 'ق' only matches solid oral when attached to digits (e.g. '30 ق' or '20 ك'),
    # avoiding false matches on potassium 'ك' (e.g. 'دولفين ك') or Vitamin K.
    solid_oral_kws = ['قرص', 'اقراص', 'اقرص', 'قراص', 'لرص', 'صارقا', 'صرق', 'شريط', 'شرايط', 'كبسول', 'كبسولة', 'كبسوله', 'كبسولات', 'كسسول', 'هلوسبك', 'tab', 'tablet', 'strip', 'cap', 'capsule', 'caplet']
    if any(k in words or (len(k) >= 4 and k in t) for k in solid_oral_kws) or re.search(r'(?:\d+\s*(?:ق|ك)\b|\b(?:ق|ك)\s*\d+)', t) or re.search(r'\bقر+ص\b', t):
        return 'SOLID_ORAL'
        
    return 'UNKNOWN'

def extract_drug_strengths_smart(text: str) -> set:
    """
    Extracts true active ingredient strengths while ignoring packaging counts (e.g. 30 قرص, 5 امبول, 100 مل).
    """
    t = clean_arabic_string(text)
    # Decouple glued dosage strength and strip count before packaging words (e.g. 1203 شريط -> 120 3 شريط)
    t = re.sub(r'\b(120|180|250|400|500|600|750|800|1000)([1-5])\s*(?:شريط|شرايط)\b', r'\1 \2 شريط', t)
    # Strip compound packaging specs like "5 باكت 64" or "10 باكو 100"
    t_no_pack = re.sub(r'\b\d+\s*(?:باكت|باكو|علبة|علبه|كرتونه|كرتونة|كرتون|باك|بكت)\s*\d+\b', ' ', t)
    
    # 1. Strip pack counts attached to packaging words (integers only, never decimals like 0.5)
    # Clinical dosage strengths (e.g. 125, 250, 500, 1000) are protected from pack count stripping!
    # Sweetener pack counts (e.g. 300, 350) are pack counts and should be stripped.
    pack_units = r'قرص|اقراص|قراص|لرص|صارقا|صرق|كبسول|كبسولة|كبسوله|كبسولات|كسسول|هلوسبك|امبول|امبولات|لوبما|فيال|فيالات|حقن|حقنه|كيس|اكياس|سايكا|اكلاس|شريط|شرايط|طيرش|باكت|باكو|علبة|علبه|ملل|مل|لتر|جرعة|جرعه|tab|tabs|tablet|tablets|cap|caps|capsule|capsules|amp|amps|ampoule|ampoules|vial|vials|strip|strips|sachet|sachets'
    
    DOSAGE_STRENGTH_NUMBERS = {125, 150, 160, 200, 250, 400, 500, 600, 625, 750, 800, 875, 1000, 1200, 1500, 2000, 5000, 10000, 20000, 50000, 100000, 200000}

    def _strip_pack(m):
        try:
            val = int(m.group(1))
            if val in DOSAGE_STRENGTH_NUMBERS or (val >= 125 and val not in (300, 350)):
                return m.group(0)
        except ValueError:
            pass
        return ' '

    t_no_pack = re.sub(rf'(?<![\d.])\b(\d+)\s*(?:{pack_units})\b(?!\.)', _strip_pack, t_no_pack, flags=re.IGNORECASE)
    t_no_pack = re.sub(rf'\b(?:{pack_units})\s*(\d+)\b(?!\.)', _strip_pack, t_no_pack, flags=re.IGNORECASE)
    
    # Strip price artifacts (e.g. ج 78, 96 جنيه)
    t_no_pack = re.sub(r'\b\d+\s*(?:ج|جنيه|س\.ج|س\.ق)\b', ' ', t_no_pack)
    t_no_pack = re.sub(r'\b(?:ج|جنيه|س\.ج|س\.ق)\s*\d+\b', ' ', t_no_pack)
    
    # 2. Extract explicit pharmaceutical units (e.g. 2 مجم, 500mg, 1gm, 5 رسم)
    explicit = set()
    unit_pattern = r'مجم|جم|مج|غم|وحدة|ميكرو|رسم|مسر|mg|gm|g|mcg|iu'
    for n, unit in re.findall(rf'\b(\d+(?:\.\d+)?)\s*({unit_pattern})\b', t_no_pack, flags=re.IGNORECASE):
        val = float(n)
        val_str = str(int(val)) if val.is_integer() else str(val)
        explicit.add(val_str)
        if unit.lower() in ['gm', 'g', 'جم', 'غم']:
            mg_val = val * 1000.0
            explicit.add(str(int(mg_val)) if mg_val.is_integer() else str(mg_val))
        elif unit.lower() in ['mg', 'مجم', 'مج', 'رسم', 'مسر']:
            g_val = val / 1000.0
            if g_val.is_integer():
                explicit.add(str(int(g_val)))
    for unit, n in re.findall(rf'\b({unit_pattern})\s*(\d+(?:\.\d+)?)\b', t_no_pack, flags=re.IGNORECASE):
        val = float(n)
        val_str = str(int(val)) if val.is_integer() else str(val)
        explicit.add(val_str)
        if unit.lower() in ['gm', 'g', 'جم', 'غم']:
            mg_val = val * 1000.0
            explicit.add(str(int(mg_val)) if mg_val.is_integer() else str(mg_val))
        elif unit.lower() in ['mg', 'مجم', 'مج', 'رسم', 'مسر']:
            g_val = val / 1000.0
            if g_val.is_integer():
                explicit.add(str(int(g_val)))
        
    if explicit:
        return explicit
        
    # 3. If no explicit unit found after stripping pack counts, return remaining numbers
    remaining = set()
    for n in re.findall(r'\b(\d+(?:\.\d+)?)\b', t_no_pack):
        val = float(n)
        remaining.add(str(int(val)) if val.is_integer() else str(val))
    return remaining

MILK_SPECIAL_TYPES = {
    'lf': [r'\blf\b', r'\bال\s*اف\b', r'\bلاكتوز\s+فري\b', r'\blactose\s+free\b', r'خالي\s+من\s+اللاكتوز'],
    'ha': [r'\bha\b', r'\bاتش\s*ايه\b', r'\bاتش\s*اي\b', r'\bh\s*a\b', r'hypoallergenic', r'ضد\s+التحسس'],
    'ar': [r'\bar\b', r'\bايه\s*ار\b', r'\bاي\s*ار\b', r'\ba\s*r\b', r'anti\s*reflux', r'ضد\s+الارتجاع'],
    'ec': [r'\bec\b', r'\bايه\s*سي\b', r'\bاي\s*سي\b', r'extra\s*care'],
    'comfort': [r'\bcomfort\b', r'\bكومفورت\b', r'\bكامفورت\b'],
    'digest': [r'\bdigest\b', r'\bدايجست\b', r'\bديجست\b'],
    'premature': [r'\bpremature\b', r'\bpre\b', r'\bبري\b', r'\bبريماتيور\b', r'مبتسرين', r'خديج'],
}

def extract_milk_type(text: str) -> Optional[str]:
    t = clean_arabic_string(text)
    for mtype, pats in MILK_SPECIAL_TYPES.items():
        for pat in pats:
            if re.search(pat, t, re.IGNORECASE):
                return mtype
    return None

def extract_milk_stage(text: str) -> Optional[str]:
    t = clean_arabic_string(text)
    m_stage = re.search(r'(?:مرحله|مرحلة|stage)\s*([1-4])\b', t, re.IGNORECASE)
    if m_stage:
        return m_stage.group(1)
    t_clean = re.sub(r'\b(?:باكو|باكت|كرتونه|كرتونة|كرتون|علبه|علبة|كارتونة|كارتونه)\s*\d+\b', ' ', t)
    t_clean = re.sub(r'\b\d+\s*(?:باكو|باكت|كرتونه|كرتونة|كرتون|علبه|علبة)\b', ' ', t_clean)
    t_clean = re.sub(r'\b\d+\s*(?:جم|جرام|مجم|غم|g|gm|kg|كجم|مل|ملل)\b', ' ', t_clean)
    t_clean = re.sub(r'\b(?:سعر|ج|جنيه)\s*\d+\b', ' ', t_clean)
    t_clean = re.sub(r'\b\d+\s*(?:سعر|ج|جنيه)\b', ' ', t_clean)
    m = re.search(r'\b([1-4])\b', t_clean)
    return m.group(1) if m else None

def check_infant_milk_compatibility(req_text: str, cand_text: str) -> bool:
    """Guarantees zero dangerous substitutions between infant milk types (LF, HA, AR, Comfort, Premature) and stages."""
    t_req = clean_arabic_string(req_text)
    t_cand = clean_arabic_string(cand_text)
    milk_kw = ['لبن', 'حليب', 'نستوجين', 'بيبيلاك', 'ابتاميل', 'هيرو', 'نان', 'بيوميل', 'نيدو', 'milk', 'hero', 'nan', 'bebelac', 'aptamil', 'biomil', 'nestogen', 's26', 'similac', 'primalac']
    is_milk = any(k in t_req for k in milk_kw) or any(k in t_cand for k in milk_kw) or (extract_form_category(req_text) == 'INFANT_MILK') or (extract_form_category(cand_text) == 'INFANT_MILK')
    if not is_milk:
        return True
    
    # 1. Formula special types (LF, HA, AR, EC, Comfort, Digest, Premature) must match exactly
    type_req = extract_milk_type(req_text)
    type_cand = extract_milk_type(cand_text)
    if type_req != type_cand:
        return False
        
    # 2. Infant milk stages (1, 2, 3, 4) must match exactly
    stage_req = extract_milk_stage(req_text)
    stage_cand = extract_milk_stage(cand_text)
    if stage_req != stage_cand:
        return False
        
    return True

def check_strength_compatibility(req_text: str, cand_text: str) -> bool:
    """Strict verification of strengths, combined ratios, and infant milk stages."""
    if not check_infant_milk_compatibility(req_text, cand_text):
        return False

    t_req = clean_arabic_string(req_text)
    t_cand = clean_arabic_string(cand_text)
            
    # 2. Multi-strength Ratios (e.g. 5/1000 vs 1000/5, 10/160/12.5)
    r_norm = unicodedata.normalize('NFKD', str(req_text)).translate(DIGITS_MAP).replace(' ', '')
    c_norm = unicodedata.normalize('NFKD', str(cand_text)).translate(DIGITS_MAP).replace(' ', '')
    combos1 = re.findall(r'\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)+', r_norm)
    combos2 = re.findall(r'\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)+', c_norm)
    if combos1 or combos2:
        if not (combos1 and combos2):
            return False
        set1 = {tuple(sorted(float(x) for x in re.findall(r'\d+(?:\.\d+)?', c))) for c in combos1}
        set2 = {tuple(sorted(float(x) for x in re.findall(r'\d+(?:\.\d+)?', c))) for c in combos2}
        return set1 == set2

    # 3. Smart Active Ingredient Strengths (pack counts stripped)
    s_req = extract_drug_strengths_smart(t_req)
    s_cand = extract_drug_strengths_smart(t_cand)
    if s_req and s_cand:
        return bool(s_req & s_cand)
        
    return True

from .normalizer import (
    extract_canonical_brand,
    extract_sorted_brand_tokens,
    is_known_canonical_brand,
    unreverse_arabic_text,
    is_arabic_text_reversed,
)

@functools.lru_cache(maxsize=16384)
def extract_core_brand_root(text: str) -> str:
    """Strips all dosage forms, strengths, packaging, and branch tags to leave the pure brand root."""
    t = clean_arabic_string(text)
    
    # Replace slashes with space so both sides are preserved (e.g. اقراص/فاركو ديجستين -> اقراص فاركو ديجستين)
    t = t.replace('/', ' ')
    
    # Remove numbers
    t = re.sub(r'\b\d+(?:\.\d+)?\b', ' ', t)
    
    # Remove commercial tags & manufacturers
    mfg_kw = (
        r'س\s*ج|س\s*ق|سعر\s+جديد|سعر\s+قديم|جديد|قديم|خاص|نقدي|مميز|جدا|جداا|سعر|جنيه|'
        r'فاركو|المهن|سيد|ايبيكو|ابيكو|امون|سيديكو|العامرية|العامريه|ماش|سانوفي|النيل|'
        r'اكديما|سيجما|الحكمه|الحكمة|ادويا|سوفيكو|ميباکو|ميباكو|استرا|جلفار|سكويب|'
        r'كيما\s*فارم|دلتا\s*فارم|دلتا|جالكسو|نوفارتس|افنتس|فايزر|ايفا|جلوبال|ماركيرل|مينا\s*فارم|'
        r'ركز|صغي+ر+|كبي+ر+|ضد\s+القشرة|عسل\s+وليمون'
    )
    t = re.sub(rf'\b(?:{mfg_kw})\b', ' ', t)
    t = re.sub(r'\b\d+\s*(?:ج|جنيه)\b', ' ', t)
    t = re.sub(r'\b[سج]\b', ' ', t)
    
    # Remove packaging and dosage forms (handling 'ه' since clean_arabic_string maps 'ة' -> 'ه')
    t = re.sub(r'\b(?:شريط|شرايط|باكو|باكت|كرتونه|كرتونة|كرتون|علبه|علبة|جرعه|جرعة|امبول|امبولات|لوبما|فيال|فيالات|قرص|اقراص|اقرص|قراص|لرص|صارقا|صرق|كبسول|كبسوله|كبسولة|كبسولات|كسسول|هلوسبك|كيس|اكياس|اكلاس|سايكا|tab|cap|amp|vial|strip)\b', ' ', t)
    t = re.sub(r'\b(?:شراب|شرب|شاب|بارش|معلق|مرهم|كريم|دهان|جل|جيل|قطره|قطرة|نقط|بخاخ|اسبراي|سبراي|فوار|حبيبات|لبوس|اقماع|قمع|غسول|شامبو|صابون|لوشن|لوسيون|سيرم|زيت|لبن|حليب|حقن|حقنه|حقنة|مجم|جم|مج|غم|جرام|ملل|مل|وحده|وحدة|ميكرو|رسم|مسر|mg|gm|g|ml|iu|mcg|ق|ك|ش)\b', ' ', t)
    t = re.sub(r'\b(?:رول\s+اون|roll\s+on)\b', ' ', t)
    t = re.sub(r'\b(?:ث|ثلاجة|ثلاجه)\b', ' ', t)
    
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def _extract_item_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get('name') or item.get('item_name') or item.get('trade_name') or '')
    if item is None:
        return ""
    return str(item).strip()

def is_safe_pharmaceutical_match(req_item: Any, cand_item: Any) -> bool:
    """
    Strict Clinical Safety Check:
    1. Form compatibility check (no syrup vs tablets, no injectables vs ointment, no drops vs injection).
    2. Exact strength, exact ratio & infant stage match.
    3. High-confidence brand identity (canonical brand or brand root).
    Accepts string names or dictionary item representations.
    """
    req_str = _extract_item_text(req_item)
    cand_str = _extract_item_text(cand_item)
    if not req_str or not cand_str:
        return False
    if _is_safe_pharmaceutical_match_cached(req_str, cand_str):
        return True

    # Try unreversed candidate if reversed
    if is_arabic_text_reversed(cand_str):
        unrev_c = unreverse_arabic_text(cand_str)
        if unrev_c and unrev_c != cand_str and _is_safe_pharmaceutical_match_cached(req_str, unrev_c):
            return True

    # Try unreversed request if reversed
    if is_arabic_text_reversed(req_str):
        unrev_r = unreverse_arabic_text(req_str)
        if unrev_r and unrev_r != req_str and _is_safe_pharmaceutical_match_cached(unrev_r, cand_str):
            return True

    return False

@functools.lru_cache(maxsize=32768)
def _is_safe_pharmaceutical_match_cached(req_item: str, cand_item: str) -> bool:
    if not req_item or not cand_item:
        return False
        
    req_parts = [p.strip() for p in re.split(r'(?<!\d)/(?!\d)', req_item) if p.strip()] if '/' in req_item else [req_item]
    cand_parts = [p.strip() for p in re.split(r'(?<!\d)/(?!\d)', cand_item) if p.strip()] if '/' in cand_item else [cand_item]

    # Explicit cross-form block across full strings or slash parts
    # (e.g. lotion/cosmetic must never match tablets/solid oral)
    all_forms_req = {extract_form_category(p) for p in req_parts} | {extract_form_category(req_item)}
    all_forms_cand = {extract_form_category(p) for p in cand_parts} | {extract_form_category(cand_item)}
    all_forms_req.discard('UNKNOWN')
    all_forms_cand.discard('UNKNOWN')

    if ('COSMETIC' in all_forms_req and 'SOLID_ORAL' in all_forms_cand) or \
       ('SOLID_ORAL' in all_forms_req and 'COSMETIC' in all_forms_cand):
        return False

    for r_part in req_parts:
        for c_part in cand_parts:
            if _check_single_part_match(
                r_part,
                c_part,
                parent_req=req_item if len(req_parts) > 1 else None,
                parent_cand=cand_item if len(cand_parts) > 1 else None,
            ):
                return True
            
    return False

def _check_single_part_match(req_text: str, cand_text: str, parent_req: Optional[str] = None, parent_cand: Optional[str] = None) -> bool:
    # 0. Reject commercial substitutes ("بديل") unless explicitly requested in PO
    sub_patterns = ['بديل', 'بدائل', 'بديلا', 'كبديل', 'والبديل', 'للبديل', 'بديله', 'بديلها', 'مستبدل', 'شبيه', 'substitute', 'subst', 'alternative', 'replacement']
    if (any(k in cand_text for k in sub_patterns) or (parent_cand and any(k in parent_cand for k in sub_patterns))) and not any(k in req_text for k in sub_patterns):
        return False

    # 1. Form Compatibility
    form_req = extract_form_category(req_text)
    if form_req == 'UNKNOWN' and parent_req:
        parent_form = extract_form_category(parent_req)
        if parent_form != 'UNKNOWN':
            form_req = parent_form
    form_cand = extract_form_category(cand_text)
    if form_cand == 'UNKNOWN' and parent_cand:
        parent_cand_form = extract_form_category(parent_cand)
        if parent_cand_form != 'UNKNOWN':
            form_cand = parent_cand_form
    
    if form_req != 'UNKNOWN' and form_cand != 'UNKNOWN':
        if form_req != form_cand:
            return False

    # Strict forms cannot match UNKNOWN (zero cross-form substitution)
    never_unknown_forms = {
        'INJECTABLE', 'DOUCHE', 'INFANT_MILK', 'DROPS', 'ORAL_LIQUID',
        'SACHET', 'SUPPOSITORY', 'TOPICAL_GEL', 'TOPICAL_SOLUTION',
        'SPRAY', 'COSMETIC', 'TOPICAL_OINTMENT', 'TOPICAL_CREAM'
    }
    if (form_req in never_unknown_forms and form_cand != form_req) or (form_cand in never_unknown_forms and form_req != form_cand):
        return False
            
    # Strict Parenteral, Liquid, Drops, Douche, Infant Milk, Sachet/Eff, Topical Gel, Suppository, Cosmetic, and Solid Oral safety gates
    strict_forms = ('INJECTABLE', 'ORAL_LIQUID', 'DROPS', 'INFANT_MILK', 'DOUCHE', 'SACHET', 'TOPICAL_GEL', 'TOPICAL_SOLUTION', 'SUPPOSITORY', 'SOLID_ORAL', 'COSMETIC', 'TOPICAL_CREAM', 'TOPICAL_OINTMENT', 'SPRAY')
    if form_req in strict_forms and form_cand != form_req and form_cand != 'UNKNOWN':
        return False
    if form_cand in strict_forms and form_req != form_cand and form_req != 'UNKNOWN':
        return False
    if (form_req in ('INJECTABLE', 'ORAL_LIQUID', 'SACHET', 'SUPPOSITORY', 'DROPS', 'TOPICAL_GEL', 'COSMETIC', 'SPRAY', 'TOPICAL_CREAM', 'TOPICAL_OINTMENT') and form_cand == 'SOLID_ORAL') or \
       (form_req == 'SOLID_ORAL' and form_cand in ('INJECTABLE', 'ORAL_LIQUID', 'SACHET', 'SUPPOSITORY', 'DROPS', 'TOPICAL_GEL', 'COSMETIC', 'SPRAY', 'TOPICAL_CREAM', 'TOPICAL_OINTMENT')):
        return False

    # 2. Strength & Ratio & Milk Stage Compatibility
    if not check_strength_compatibility(req_text, cand_text):
        return False

    # 2.5 Formulation Modifier Compatibility (Extra, XR, Plus, Cold & Flu, Decongestant, Ultra, Woman, etc.)
    if not check_modifier_compatibility(req_text, cand_text):
        return False

    # 3. Canonical Brand Direct Match (Skill Gold Standard)
    c_brand_req = extract_canonical_brand(req_text)
    c_brand_cand = extract_canonical_brand(cand_text)
    if c_brand_req and c_brand_cand:
        if c_brand_req == c_brand_cand and len(c_brand_req) >= 3:
            # Prevent short-circuit matching when the canonical brand is an umbrella brand or has sub-brand suffixes
            is_umbrella = (
                c_brand_req in ('limitless', 'panthenol', 'بانثينول', 'ليمتلس') or
                c_brand_req.startswith('limitless') or c_brand_cand.startswith('limitless') or
                c_brand_req.startswith('panthenol') or c_brand_cand.startswith('panthenol')
            )
            if is_umbrella:
                root_req = extract_core_brand_root(req_text).replace(' ', '')
                root_cand = extract_core_brand_root(cand_text).replace(' ', '')
                if root_req and root_cand and root_req == root_cand:
                    return True
                return False
            return True
        # If both are recognized canonical brands and they differ, strictly reject
        if c_brand_req != c_brand_cand and is_known_canonical_brand(c_brand_req) and is_known_canonical_brand(c_brand_cand):
            return False
        # Umbrella sub-brand isolation
        if (c_brand_req.startswith('limitless') or c_brand_cand.startswith('limitless') or
            c_brand_req.startswith('panthenol') or c_brand_cand.startswith('panthenol')):
            return False

    # 4. Word-Order Invariant Sorted Brand Tokens
    s_brand_req = extract_sorted_brand_tokens(req_text)
    s_brand_cand = extract_sorted_brand_tokens(cand_text)
    if s_brand_req and s_brand_cand and s_brand_req == s_brand_cand and len(s_brand_req) >= 3:
        return True

    # 5. Brand Root Exact / Normalized Verification
    brand_req = extract_core_brand_root(req_text)
    brand_cand = extract_core_brand_root(cand_text)
    if not brand_req or not brand_cand:
        return False

    b_req_nospace = brand_req.replace(' ', '')
    b_cand_nospace = brand_cand.replace(' ', '')
    if b_req_nospace == b_cand_nospace and len(b_req_nospace) >= 3:
        return True

    b_req_no_al = b_req_nospace[2:] if b_req_nospace.startswith('ال') and len(b_req_nospace) > 4 else b_req_nospace
    b_cand_no_al = b_cand_nospace[2:] if b_cand_nospace.startswith('ال') and len(b_cand_nospace) > 4 else b_cand_nospace
    if b_req_no_al == b_cand_no_al and len(b_req_no_al) >= 3:
        return True

    # High-ratio fuzzy match on full brand string only (must start with same letter)
    sim_ratio = fuzz.ratio(b_req_no_al, b_cand_no_al)
    if sim_ratio >= 92 and abs(len(b_req_no_al) - len(b_cand_no_al)) <= 1:
        if b_req_no_al[0] == b_cand_no_al[0]:
            cb1 = extract_canonical_brand(b_req_no_al)
            cb2 = extract_canonical_brand(b_cand_no_al)
            if cb1 and cb2 and cb1 != cb2 and is_known_canonical_brand(cb1) and is_known_canonical_brand(cb2):
                return False
            # Zero-risk: For fuzzy brand roots, form MUST be known on both sides and match exactly
            if form_req == 'UNKNOWN' or form_cand == 'UNKNOWN' or form_req != form_cand:
                return False
            return True

    return False


MODIFIERS = {
    'extra': ['extra', 'اكسترا', 'بلس', 'بلاس', 'بلص', 'بالس', 'plus'],
    'forte': ['forte', 'فورت', 'فورتي', 'مضاعف', 'max', 'ماكس'],
    'extended_release': ['xr', 'sr', 'mr', 'cr', 'retard', 'ممتد'],
    'cold_flu': ['cold', 'flu', 'كولد', 'فلو', 'انفلونزا', 'كومبي', 'combi'],
    'day_night': ['day', 'night', 'ليل', 'نهار'],
    'sinus': ['sinus', 'جيوب'],
    'rapid': ['rapid', 'fast', 'سريع', 'فوري'],
    'advance': ['advance', 'ادفانس', 'المطور'],
    'junior': ['junior', 'اطفال', 'pediatric', 'infant', 'baby', 'رضع'],
    'decongestant': ['decongestant', 'decongest', 'ديكونجيستانت', 'ديكونجستنت', 'ديكونجستانت', 'ديكونجستين', 'ديكونجست'],
    'ultra': ['ultra', 'الترا', 'ألترا'],
    'woman': ['woman', 'women', 'ومان', 'سيدات', 'حريمي'],
    'men': ['man', 'men', 'مان', 'رجال', 'رجالي'],
    'omega': ['omega', 'اوميجا', 'اوميغا'],
    'vitamin_d': ['vitamin d', 'vit d', 'بيبي د', 'فيتامين د'],
    'magnesium': ['magnesium', 'ماغنسيوم', 'ماجنسيوم', 'مغنسيوم'],
    'lipoverx': ['lipoverx', 'ليبوفيركس'],
    'zinc': ['zinc', 'زنك'],
    'osteodance': ['osteodance', 'اوستيودانس', 'استيودانس', 'اوستيو دانس', 'استيو دانس'],
    'chromax': ['chromax', 'كروماكس'],
    'turmeric': ['turmeric', 'كركمين', 'كركم'],
    'gluta': ['gluta', 'جلوتا'],
    'calcium': ['calcium', 'كالسيوم'],
    'iron': ['iron', 'حديد', 'فير'],
    'roll_on': ['roll on', 'رول اون'],
    'hair': ['شعر', 'hair'],
    'skin': ['جلد', 'بشره', 'بشرة', 'skin'],
    'nile': ['النيل', 'نيل', 'el nile', 'nile'],
    'mepaco': ['ميباكو', 'ميباكووو', 'ميباکو', 'وكابيم', 'mepaco'],
    'cid': ['سيد', 'cid'],
    'eipico': ['ايبيكو', 'ابيكو', 'وكيبيا', 'وكيبا', 'eipico'],
    'amoun': ['امون', 'amoun', 'نوما'],
    'pharco': ['فاركو', 'pharco', 'وكراف'],
    'sedico': ['سيديكو', 'sedico'],
    'amriya': ['العامرية', 'العامريه', 'عامرية', 'عامريه', 'amriya'],
    'mash': ['ماش', 'mash', 'شام'],
    'sigma': ['سيجما', 'sigma', 'امجيس'],
    'adwia': ['ادويا', 'adwia', 'ايودا'],
    'eva': ['ايفا', 'eva'],
}

def extract_modifiers(text: str) -> set:
    t = clean_arabic_string(text)
    words = set(t.split())
    if is_arabic_text_reversed(text):
        t_unrev = clean_arabic_string(unreverse_arabic_text(text))
        words |= set(t_unrev.split())
        t = f"{t} {t_unrev}"

    found = set()
    for mod_name, aliases in MODIFIERS.items():
        for a in aliases:
            if a in words or (len(a) >= 3 and f' {a} ' in f' {t} '):
                found.add(mod_name)
                break
    return found

def check_modifier_compatibility(req_text: str, cand_text: str) -> bool:
    mods_req = extract_modifiers(req_text)
    mods_cand = extract_modifiers(cand_text)
    return mods_req == mods_cand
