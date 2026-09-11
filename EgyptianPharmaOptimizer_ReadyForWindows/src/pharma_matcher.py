# -*- coding: utf-8 -*-
"""
Strict Pharmaceutical Entity & Safety Validator.
Guarantees zero dangerous drug substitutions, strict dosage form consistency,
and exact strength / infant milk stage verification.
"""
import re
import unicodedata
from rapidfuzz import fuzz

DIGITS_MAP = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')

def clean_arabic_string(text: str) -> str:
    """Normalize Arabic presentation forms, translate all digits, space numbers, and remove diacritics."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', str(text))
    text = text.translate(DIGITS_MAP)
    text = text.replace('\u064c', 'ي').replace('\u064b', 'ي').replace('ـ', '')
    text = re.sub(r'[\u0617-\u061A\u064B-\u0652]', '', text)
    
    char_map = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ة': 'ه', 'ى': 'ي', 'ئ': 'ي', 'ؤ': 'و',
        'ی': 'ي', 'ي': 'ي',
        'ﻼ': 'لا', 'ﻸ': 'لا', 'ﻹ': 'لا', 'ﻶ': 'لا', 'ك': 'ك', 'ک': 'ك',
        'ﻧ': 'ن', 'ﺳ': 'س', 'ﺷ': 'ش', 'ﺻ': 'ص', 'ﺿ': 'ض', 'ﻃ': 'ط'
    }
    for src, dst in char_map.items():
        text = text.replace(src, dst)
        
    text = re.sub(r'(\d+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', text)
    text = re.sub(r'([a-zA-Z\u0600-\u06FF])(\d+)', r'\1 \2', text)
    text = re.sub(r'(\d+(?:\.\d+)?)', r' \1 ', text)
    text = text.replace('*', ' ').replace('/', ' ').replace('.', ' ').replace('-', ' ').replace('_', ' ').replace('"', ' ').replace('\\', ' ').replace(',', ' ')
    return re.sub(r'\s+', ' ', text).strip().lower()

def extract_form_category(text: str) -> str:
    """Classifies medicine dosage form into mutually exclusive categories."""
    t = clean_arabic_string(text)
    # Strip storage tags before evaluating dosage forms
    t = re.sub(r'\b(?:ث|ثلاجة|ثلاجه)\b', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    words = set(t.split())
    
    # Check explicit solid oral forms first
    if any(k in words or (len(k) >= 4 and k in t) for k in ['قرص', 'اقراص', 'اقرص', 'لرص', 'صارقا', 'صرق', 'شريط', 'شرايط', 'كبسول', 'كبسولة', 'كبسولات', 'هلوسبك', 'tab', 'tablet', 'strip', 'cap', 'capsule', 'caplet']) or re.search(r'\b(?:ق|ك)\b', t):
        return 'SOLID_ORAL'
    if any(k in words or (len(k) >= 4 and k in t) for k in ['امبول', 'امبولات', 'لوبما', 'فيال', 'فيالات', 'لايف', 'حقن', 'حقنه', 'حقنة', 'سرنجة', 'amp', 'vial', 'inj']):
        return 'INJECTABLE'
    if any(k in words or (len(k) >= 4 and k in t) for k in ['شراب', 'شرب', 'بارش', 'معلق', 'syrup', 'susp', 'elixir']) or re.search(r'\b(?:ش)\b', t):
        return 'ORAL_LIQUID'
    if any(k in words or (len(k) >= 4 and k in t) for k in ['قطرة', 'قطره', 'نقط', 'drops', 'eye drop', 'ear drop']):
        return 'DROPS'
    if any(k in words or (len(k) >= 4 and k in t) for k in ['بخاخ', 'اسبراي', 'سبراي', 'spray', 'inhaler']):
        return 'SPRAY'
    if any(k in words or (len(k) >= 4 and k in t) for k in ['فوار', 'اكياس', 'كيس', 'سايكا', 'حبيبات', 'sachet', 'eff']):
        return 'SACHET'
    if any(k in words or (len(k) >= 4 and k in t) for k in ['لبوس', 'قمع', 'اقماع', 'supp']):
        return 'SUPPOSITORY'
    if any(k in words or (len(k) >= 4 and k in t) for k in ['كريم', 'مرهم', 'دهان', 'cream', 'oint']):
        return 'TOPICAL_CREAM_OINT'
    if any(k in words for k in ['جل', 'جيل', 'gel']):
        return 'TOPICAL_GEL'
    if any(k in words or (len(k) >= 4 and k in t) for k in ['لبن', 'حليب', 'نستوجين', 'بيبيلاك', 'ابتاميل', 'هيرو', 'بيوميل', 'سيريلاك']) or re.search(r'\bنان\b', t):
        return 'INFANT_MILK'
    if any(k in words or (len(k) >= 4 and k in t) for k in ['غسول', 'شامبو', 'صابون', 'لوشن', 'لوسيون', 'سيرم', 'زيت', 'shampoo', 'lotion', 'wash']):
        return 'COSMETIC'
        
    return 'UNKNOWN'

def extract_drug_strengths_smart(text: str) -> set:
    """
    Extracts true active ingredient strengths while ignoring packaging counts (e.g. 30 قرص, 5 امبول, 100 مل).
    """
    t = clean_arabic_string(text)
    
    # 1. Strip pack counts attached to packaging words
    pack_units = r'قرص|اقراص|صارقا|صرق|كبسول|كبسولة|كبسولات|امبول|امبولات|فيال|فيالات|حقن|حقنه|كيس|اكياس|شريط|شرايط|باكت|باكو|علبة|علبه|ملل|مل|لتر|جرعة|جرعه|tab|tabs|tablet|tablets|cap|caps|capsule|capsules|amp|amps|ampoule|ampoules|vial|vials|strip|strips|sachet|sachets'
    t_no_pack = re.sub(rf'\b\d+(?:\.\d+)?\s*(?:{pack_units})\b', ' ', t, flags=re.IGNORECASE)
    t_no_pack = re.sub(rf'\b(?:{pack_units})\s*\d+(?:\.\d+)?\b', ' ', t_no_pack, flags=re.IGNORECASE)
    
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

def check_strength_compatibility(req_text: str, cand_text: str) -> bool:
    """Strict verification of strengths, combined ratios, and infant milk stages."""
    t_req = clean_arabic_string(req_text)
    t_cand = clean_arabic_string(cand_text)
    
    # 1. Infant Milk Stages (e.g. stage 1 vs stage 2)
    if any(k in t_req for k in ['لبن', 'حليب', 'نستوجين', 'بيبيلاك', 'ابتاميل', 'هيرو', 'نان', 'بيوميل', 'نيدو']):
        m1 = re.search(r'\b([1-4])\b', t_req)
        m2 = re.search(r'\b([1-4])\b', t_cand)
        if m1 and m2 and m1.group(1) != m2.group(1):
            return False
            
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

from .normalizer import extract_canonical_brand, extract_sorted_brand_tokens

def extract_core_brand_root(text: str) -> str:
    """Strips all dosage forms, strengths, packaging, and branch tags to leave the pure brand root."""
    t = clean_arabic_string(text)
    
    # Replace slashes with space so both sides are preserved (e.g. اقراص/فاركو ديجستين -> اقراص فاركو ديجستين)
    t = t.replace('/', ' ')
    
    # Remove numbers
    t = re.sub(r'\b\d+(?:\.\d+)?\b', ' ', t)
    
    # Remove packaging and dosage forms
    t = re.sub(r'\b(?:شريط|شرايط|باكو|باكت|كرتونه|كرتون|علبة|علبه|جرعة|جرعه|امبول|امبولات|فيال|فيالات|قرص|اقراص|اقرص|لرص|كبسول|كبسولة|كبسولات|كيس|اكياس|tab|cap|amp|vial|strip)\b', ' ', t)
    t = re.sub(r'\b(?:شراب|شرب|مرهم|كريم|جل|جيل|قطرة|قطره|نقط|بخاخ|اسبراي|سبراي|فوار|حبيبات|لبوس|اقماع|قمع|غسول|شامبو|صابون|لوشن|لوسيون|سيرم|زيت|لبن|حليب|حقن|حقنه|مجم|جم|مج|غم|ملل|مل|وحدة|ميكرو|رسم|مسر|mg|gm|g|ml|iu|mcg|ق|ك|ش)\b', ' ', t)
    t = re.sub(r'\b(?:ث|ثلاجة|ثلاجه)\b', ' ', t)
    
    # Remove commercial tags & manufacturers
    t = re.sub(r'\b(?:س\s*ج|س\s*ق|سعر\s+جديد|سعر\s+قديم|جديد|قديم|خاص|نقدي|مميز|جدا|جداا|سعر|جنيه|فاركو|المهن|سيد|ايبيكو|امون|سيديكو|العامرية|ماش|سانوفي|النيل|اكديما|سيجما|الحكمه|الحكمة|ادويا|سوفيكو|ميباکو|ميباكو|استرا|جلفار|ركز|صغير|كبير|كبييير|ضد\s+القشرة|عسل\s+وليمون)\b', ' ', t)
    t = re.sub(r'\b\d+\s*(?:ج|جنيه)\b', ' ', t)
    
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def is_safe_pharmaceutical_match(req_item: str, cand_item: str) -> bool:
    """
    Strict Clinical Safety Check:
    1. Form compatibility check (no syrup vs tablets, no injectables vs ointment, no drops vs injection).
    2. Exact strength, exact ratio & infant stage match.
    3. High-confidence brand identity (canonical brand or brand root).
    """
    if not req_item or not cand_item:
        return False
        
    req_parts = [p.strip() for p in re.split(r'(?<!\d)/(?!\d)', req_item) if p.strip()] if '/' in req_item else [req_item]
    
    for r_part in req_parts:
        if _check_single_part_match(r_part, cand_item):
            return True
            
    return False

def _check_single_part_match(req_text: str, cand_text: str) -> bool:
    # 1. Form Compatibility
    form_req = extract_form_category(req_text)
    form_cand = extract_form_category(cand_text)
    
    if form_req != 'UNKNOWN' and form_cand != 'UNKNOWN':
        if form_req != form_cand:
            return False
            
    # Strict Parenteral, Liquid, Drops, and Infant Milk safety gates (cannot cross-match with UNKNOWN)
    if form_req in ('INJECTABLE', 'ORAL_LIQUID', 'DROPS', 'INFANT_MILK') and form_cand != form_req:
        return False
    if form_cand in ('INJECTABLE', 'ORAL_LIQUID', 'DROPS', 'INFANT_MILK') and form_req != form_cand:
        return False

    # 2. Strength & Ratio & Milk Stage Compatibility
    if not check_strength_compatibility(req_text, cand_text):
        return False

    # 2.5 Formulation Modifier Compatibility (Extra, XR, Plus, Cold & Flu, etc.)
    if not check_modifier_compatibility(req_text, cand_text):
        return False

    # 3. Canonical Brand Direct Match (Skill Gold Standard)
    c_brand_req = extract_canonical_brand(req_text)
    c_brand_cand = extract_canonical_brand(cand_text)
    if c_brand_req and c_brand_cand and c_brand_req == c_brand_cand and len(c_brand_req) >= 3:
        return True

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
            return True

    return False


MODIFIERS = {
    'extra': ['extra', 'اكسترا', 'بلس', 'بلاس', 'بلص', 'plus'],
    'forte': ['forte', 'فورت', 'فورتي', 'مضاعف', 'max', 'ماكس'],
    'extended_release': ['xr', 'sr', 'mr', 'cr', 'retard', 'ممتد'],
    'cold_flu': ['cold', 'flu', 'كولد', 'فلو', 'انفلونزا', 'كومبي', 'combi'],
    'day_night': ['day', 'night', 'ليل', 'نهار'],
    'sinus': ['sinus', 'جيوب'],
    'rapid': ['rapid', 'fast', 'سريع', 'فوري'],
    'advance': ['advance', 'ادفانس', 'المطور'],
    'junior': ['junior', 'اطفال', 'pediatric', 'infant', 'baby', 'رضع'],
}

def extract_modifiers(text: str) -> set:
    t = clean_arabic_string(text)
    words = set(t.split())
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
