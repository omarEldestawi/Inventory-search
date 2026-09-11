# -*- coding: utf-8 -*-
"""
Arabic text normalization, entity extraction, and vendor resolver.
"""
import os
import re
import unicodedata

EASTERN_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

ARABIC_CHAR_MAP = {
    'أ': 'ا',
    'إ': 'ا',
    'آ': 'ا',
    'ٱ': 'ا',
    'ة': 'ه',
    'ى': 'ي',
    'ئ': 'ي',
    'ؤ': 'و',
    'ی': 'ي',
    'ي': 'ي',
    'ك': 'ك',
    'ک': 'ك',
    'ﻼ': 'لا',
    'ﻸ': 'لا',
    'ﻹ': 'لا',
    'ﻶ': 'لا',
    'ﻧ': 'ن',
    'ﺳ': 'س',
    'ﺷ': 'ش',
    'ﺻ': 'ص',
    'ﺿ': 'ض',
    'ﻃ': 'ط',
}

GREEK_ARABIC_MAP = {
    'ϳ': 'ي',
    'ϛ': 'ك',
    'Ύ': 'ا',
    'Α': 'ب',
    'ϗ': 'ق',
    'Ϡ': 'ل',
    'ϼ': 'لا',
    'ϻ': 'لا',
    'Λ': 'ث',
    'Ο': 'ج',
    'Δ': 'ة',
    'Η': 'ت',
    'ϣ': 'ش',
    'Χ': 'خ',
    '΋': 'ئ',
    'ϓ': 'ف',
    'ϊ': 'ع',
    'Ϫ': 'غ',
    'ϰ': 'ذ',
    'Σ': 'س',
    '́': '',
    'ـ': '',
}

def decode_greek_arwasoft(text: str) -> str:
    """Decodes custom ArwaSoft Greek glyph font encodings back into standard Arabic letters."""
    if not text or not isinstance(text, str):
        return ""
    t = str(text)
    for greek_char, arabic_char in GREEK_ARABIC_MAP.items():
        t = t.replace(greek_char, arabic_char)
    return t

def normalize_vendor_name(filename_or_raw_name: str) -> str:
    """Standardizes raw catalog filename into a clean entity label."""
    if not filename_or_raw_name:
        return ""
    name = os.path.splitext(os.path.basename(filename_or_raw_name))[0].replace('\u200e','').replace('\u2068','').replace('\u2069','').replace('EX','')
    name_clean = name.replace('ـ', '').replace('-', ' ').replace('_', ' ').strip()
    
    # Strip day names, version tags, and commercial noise
    name_clean = re.sub(r'\b(?:السبت|الاحد|الأحد|الاثنين|الإثنين|الثلاثاء|الاربعاء|الأربعاء|الخميس|الجمعة|الجمعه)\b', ' ', name_clean)
    name_clean = re.sub(r'\b(?:نقدي|نقدى|كاش|خاص|جملة|جمله|عروض|تحديث|سعر|جديد|ش|ج)\b', ' ', name_clean)
    name_clean = re.sub(r'[\(\)\[\]0-9]', ' ', name_clean)
    name_clean = re.sub(r'\s+', ' ', name_clean).strip()
    
    # Wholesaler canonical mappings
    if 'الحجاز' in name_clean:
        return 'الحجاز فارما'
    if 'اكتف' in name_clean:
        return 'نيو اكتف طنطا'
    if 'القاضي' in name_clean or 'القاضى' in name_clean:
        return 'القاضي فارما'
    if 'سبيشيال' in name_clean:
        return 'سبيشيال فارما'
    if 'ستروكا' in name_clean:
        return 'شركة ستروكا الجيزة'
    if 'الفارس' in name_clean:
        return 'الفارس طنطا'
    if 'الايمان' in name_clean or 'الإيمان' in name_clean:
        return 'مخزن الإيمان'
    if 'ياسين' in name_clean:
        return 'شركة ال ياسين المنوفيه'
    if 'صيادلة المستقبل' in name_clean:
        return 'صيادلة المستقبل'
    if 'سينا تريد' in name_clean:
        return 'سينا تريد'
    if 'القمة' in name_clean or 'القمة' in name_clean:
        return 'مخزن القمة'
    if 'وائل سمير' in name_clean:
        return 'مخزن وائل سمير'
    if 'زيدان' in name_clean or 'زيدااان' in name_clean:
        return 'مميز زيدان'
    if 'احمد عبد الله' in name_clean or 'أحمد عبد الله' in name_clean:
        return 'مخزن د أحمد عبد الله'
    if 'انفينتي' in name_clean or 'انفينتى' in name_clean:
        return 'مخزن انفينتي'
    if 'فريندس' in name_clean:
        return 'فريندس تو ام'
    if 'الدولية' in name_clean or 'الدوليه' in name_clean:
        return 'الدولية فارما'
    if 'الرؤى' in name_clean or 'النور' in name_clean or 'الروى' in name_clean:
        return 'شركة الرؤى والنور'
    if 'ميجا' in name_clean or 'ميجـا' in name_clean:
        return 'ميجا فارم'
    if 'الوجيه' in name_clean or 'الوجيـه' in name_clean:
        return 'مخزن الوجيه فارم'
    if 'السلطان' in name_clean:
        return 'مخزن السلطان'
    if 'المكرومي' in name_clean:
        return 'مخزن المكرومي'
    if 'الحياه' in name_clean or 'الحياة' in name_clean:
        return 'مخزن الحياه فارم'
    if 'فالكون' in name_clean:
        return 'مخزن فالكون فارم'
    if 'فارما تو جو' in name_clean or 'فارما توجو' in name_clean:
        return 'فارما تو جو'
    if 'نيو الفا' in name_clean or 'نيو ألفا' in name_clean or 'الفا فارم' in name_clean:
        return 'نيو ألفا فارم'
    if 'السلام' in name_clean:
        return 'مخزن السلام فارم'
    if 'ثقه' in name_clean or 'ثقة' in name_clean:
        return 'الثقة فارما طنطا'
    if 'العمرو' in name_clean:
        return 'مخزن العمرو فارما'
    if 'مصر' in name_clean:
        return 'مصر لتجارة الأدوية'
    if 'كيور' in name_clean:
        return 'كيور فارما'
    if 'الهضبه' in name_clean or 'الهضبة' in name_clean:
        return 'مخزن الهضبة فارم'
    if 'النجوم' in name_clean:
        return 'مخزن النجوم'
    if 'هنا' in name_clean:
        return 'مخزن هنا جملة'
    if 'عروض' in name_clean or 'مميز' in name_clean:
        return 'عروض مميز'
    if 'اوائل' in name_clean or 'أوائل' in name_clean or 'اوائل' in name_clean:
        return 'الاوائل فارم'
    if 'جمل' in name_clean:
        return 'مخزن جمل'
    
    return name_clean.strip() if name_clean else name.strip()

def unreverse_arabic_text(text: str) -> str:
    """Detects reversed Arabic text inside PDF-extracted text and restores natural reading order without corrupting digits."""
    if not text or not isinstance(text, str):
        return ""
    
    # Decode ArwaSoft Greek glyphs if present
    if any(k in text for k in GREEK_ARABIC_MAP):
        text = decode_greek_arwasoft(text)
    
    # Normalize unicode presentation forms (e.g. ﺹﺍﺮﻗﺍ -> اقراص)
    text = unicodedata.normalize('NFKD', str(text))
    text = text.translate(EASTERN_ARABIC_DIGITS)
    text = text.replace('\u064c', 'ي').replace('\u064b', 'ي')
    text = text.replace('ـ', '')
    
    # Protect numbers from being reversed with attached words (e.g. 100مجم -> 100 مجم)
    text = re.sub(r'([a-zA-Z\u0600-\u06FF])(\d+)', r'\1 \2', text)
    text = re.sub(r'(\d+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', text)
    
    words = text.split()
    unreversed_words = []
    
    for w in words:
        # Don't reverse pure numbers or punctuation
        if re.fullmatch(r'[\d.,/%\-_]+', w):
            unreversed_words.append(w)
            continue
        arabic_chars = [c for c in w if '\u0600' <= c <= '\u06FF']
        if len(arabic_chars) > len(w) * 0.5:
            unreversed_words.append(w[::-1])
        else:
            unreversed_words.append(w)
            
    return ' '.join(unreversed_words[::-1])

def normalize_drug_text(text: str) -> str:
    """Canonical text normalizer based on medicine-price-comparator-new skill."""
    if not text:
        return ""
    t = unicodedata.normalize('NFKD', str(text)).translate(EASTERN_ARABIC_DIGITS)
    for src, dst in ARABIC_CHAR_MAP.items():
        t = t.replace(src, dst)
    t = t.replace('/', ' ').replace('٫', '.').replace('،', ',').replace('٪', '%')
    t = re.sub(r'[\u0640]', '', t)
    t = re.sub(r'([a-zA-Z\u0600-\u06FF])(\d)', r'\1 \2', t)
    t = re.sub(r'(\d)([a-zA-Z\u0600-\u06FF])', r'\1 \2', t)
    t = re.sub(r'[إأآاٱ]', 'ا', t)
    t = re.sub(r'ة', 'ه', t)
    t = re.sub(r'[ىيئیی]', 'ي', t)
    t = re.sub(r'[كک]', 'ك', t)
    t = re.sub(r'[ؤ]', 'و', t)
    return t.lower()

CANONICAL_NOISE_WORDS = [
    'س ج', 'س ق', 'سعر جديد', 'سعر قديم', 'س.ج', 'س.ق', 'جديد', 'قديم', 'سعر', 'جنيه',
    'باكو', 'باكت', 'كرتونه', 'كرتون', 'علبه', 'علبة', 'شريط', 'شرايط', 'شريطين',
    'ثلاجة', 'ثلاجه', 'ث', 'محلي', 'مستورد', 'عرض', 'كبير', 'صغير', 'عادي',
    'فاركو', 'العامرية', 'ميباكو', 'النيل', 'ايبيكو', 'سانوفي', 'سيديكو', 'ماش',
    'الحكمه', 'المهن', 'ممفيس', 'فرعونية', 'اكديما', 'سيجما', 'امون', 'ادويا',
    'اقراص', 'قرص', 'اقرص', 'لرص', 'ق', 'tab', 'tablet', 'كبسول', 'كبسولة', 'ك', 'cap', 'capsule',
    'شراب', 'شرب', 'ش', 'syr', 'syrup', 'حقن', 'امبول', 'فيال', 'inj', 'amp', 'vial',
    'كريم', 'cream', 'مرهم', 'oint', 'جل', 'جيل', 'gel', 'لوشن', 'lotion',
    'نقط', 'قطرة', 'drops', 'بخاخ', 'اسبراي', 'spray', 'فوار', 'اكياس', 'sachet',
    'مجم', 'مج', 'mg', 'جم', 'جرام', 'g', 'gm', 'مكجم', 'mcg', 'مل', 'ملل', 'ml', 'ج', 'س'
]

def extract_canonical_brand(text: str) -> str:
    """Canonical brand extraction matching medicine-price-comparator-new skill."""
    t = normalize_drug_text(text)
    for w in sorted(CANONICAL_NOISE_WORDS, key=len, reverse=True):
        t = re.sub(rf'\b{w}\b', ' ', t)
    t = re.sub(r'\b\d+(?:\.\d+)?\b', ' ', t)
    t = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', t)
    return t


def normalize_arabic_text(text: str) -> str:
    """Normalize Arabic string for fuzzy matching."""
    if not text or not isinstance(text, str):
        return ""
    
    # Normalize unicode presentation forms
    text = unicodedata.normalize('NFKD', str(text))
    # Translate digits
    text = text.translate(EASTERN_ARABIC_DIGITS)
    
    # Remove tashkeel & tatweel
    text = re.sub(r'[\u0617-\u061A\u064B-\u0652\u0640]', '', text)
    
    # Normalize characters
    for src, dst in ARABIC_CHAR_MAP.items():
        text = text.replace(src, dst)
        
    # Remove price update tags & noise
    text = re.sub(r'\bس\s*[.\-_]?\s*[جق]\b', '', text)
    text = re.sub(r'\bسعر\s+(?:جديد|قديم)\b', '', text)
    text = re.sub(r'\b\d+\s*ج\b', '', text)
    text = re.sub(r'\b(?:خاص|نقدي|مميز|جدا|جديد|قديم|باكو|علبة|شريط|شرايط|قرص|اقراص|اقرص|لرص|صارقا|صرق|كبسول|كبسولة|امبول|فيال|نقط|قطرة|شراب|شرب|مرهم|كريم|جل|جيل)\b', '', text)
    
    # Space between digits & letters
    text = re.sub(r'(\d+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', text)
    text = re.sub(r'([a-zA-Z\u0600-\u06FF])(\d+)', r'\1 \2', text)

    # Clean whitespace & lowercase
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text

def parse_discount(val) -> float:
    """Parse discount string or number into float between 0.0 and 1.0."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        v = float(val)
        if v > 1.0:
            return round(v / 100.0, 4)
        return round(v, 4)
    
    val_str = str(val).strip().replace('%', '').replace(',', '.').translate(EASTERN_ARABIC_DIGITS)
    match = re.search(r'[-+]?\d*\.?\d+', val_str)
    if match:
        try:
            num = float(match.group())
            if num > 1.0:
                return round(num / 100.0, 4)
            return round(num, 4)
        except ValueError:
            return 0.0
    return 0.0

def parse_dosage_and_pack(item_name: str):
    """Extract dosage strengths and pack sizes from item name."""
    normalized = normalize_arabic_text(item_name)
    
    strength_pattern = r'(\d+(?:\.\d+)?\s*(?:mg|gm|g|ml|mcg|iu|مجم|جم|مل|ميكروجرام|وحدة))'
    strength_match = re.search(strength_pattern, normalized, re.IGNORECASE)
    dosage = strength_match.group(1).replace(' ', '') if strength_match else ''
    
    pack_pattern = r'(\d+\s*(?:tab|cap|amp|vial|strip|bottle|قرص|كبسولة|امبول|فيال|شريط|زجاجة|شرايط))'
    pack_match = re.search(pack_pattern, normalized, re.IGNORECASE)
    pack_size = pack_match.group(1).replace(' ', '') if pack_match else ''
    
    return dosage, pack_size

def extract_dosage_form(item_name: str) -> str:
    """Classifies medicine pharmaceutical dosage form / formulation."""
    if not item_name:
        return "غير محدد"
    
    name_clean = item_name.lower().strip()
    words = set(name_clean.split())
    
    if any(k in words or (len(k) >= 4 and k in name_clean) for k in ['قرص', 'اقراص', 'اقرص', 'لرص', 'صارقا', 'صرق', 'شريط', 'شرايط', 'tab', 'tablet', 'strip']):
        return "قرص"
    elif any(k in words or (len(k) >= 4 and k in name_clean) for k in ['كبسول', 'كبسولة', 'هلوسبك', 'cap', 'capsule']):
        return "كبسول"
    elif any(k in words or (len(k) >= 4 and k in name_clean) for k in ['امبول', 'لوبما', 'فيال', 'لايف', 'amp', 'vial', 'حقن', 'سرنجة', 'inj', 'injection']):
        return "حقن/امبول"
    elif any(k in words or (len(k) >= 4 and k in name_clean) for k in ['شراب', 'شرب', 'بارش', 'سائل', 'معلق', 'syrup', 'susp', 'suspension', 'elixir']):
        return "شراب"
    elif any(k in words for k in ['جل', 'جيل', 'gel']):
        return "جل"
    elif any(k in words or (len(k) >= 4 and k in name_clean) for k in ['كريم', 'مرهم', 'cream', 'oint']):
        return "كريم"
    elif any(k in words or (len(k) >= 4 and k in name_clean) for k in ['نقط', 'قطرة', 'drops', 'drop', 'eye drop', 'ear drop']):
        return "نقط/قطرة"
    elif any(k in words or (len(k) >= 4 and k in name_clean) for k in ['كيس', 'اكياس', 'سايكا', 'فوار', 'sachet', 'eff', 'granules', 'حبيبات']):
        return "فوار/اكياس"
    elif any(k in words or (len(k) >= 4 and k in name_clean) for k in ['بخاخ', 'اسبراي', 'spray', 'inhaler', 'aerosol']):
        return "بخاخ"
    elif any(k in words or (len(k) >= 4 and k in name_clean) for k in ['غسول', 'شامبو', 'صابون', 'لوشن', 'سيرم', 'ماسك', 'زيت', 'معجون', 'shampoo', 'lotion', 'serum', 'soap', 'wash']):
        return "تجميل/عناية"
        
    return "غير محدد"

MODIFIER_NOISE = {'ادفانس', 'فورت', 'بلس', 'بلاس', 'بلص', 'اكسترا', 'كبار', 'اطفال', 'مساج', 'رجال', 'نساء', 'تريو', 'كومبي', 'سريع', 'فوري', 'مطور'}

def extract_sorted_brand_tokens(text: str) -> str:
    """Extracts sorted core brand tokens, invariant to word reordering in warehouse catalogs."""
    if not text:
        return ""
    t = normalize_drug_text(text)
    t = t.replace('/', ' ')
    for w in sorted(CANONICAL_NOISE_WORDS, key=len, reverse=True):
        t = re.sub(rf'\b{w}\b', ' ', t)
    t = re.sub(r'\b\d+(?:\.\d+)?\b', ' ', t)
    words = [w for w in re.sub(r'[^a-z0-9\u0600-\u06FF\s]', ' ', t).split() if len(w) >= 2]
    brand_words = [w for w in words if w not in MODIFIER_NOISE]
    if not brand_words:
        brand_words = words
    clean_words = [w[2:] if w.startswith('ال') and len(w) > 4 else w for w in brand_words]
    return ''.join(sorted(clean_words))

def fix_arwasoft_arabic_numbers(text: str) -> str:
    """
    Reverses visually inverted Eastern Arabic digits rendered by ArwaSoft accounting software
    (e.g. ٥٢٦ -> 625, ٠٠٦ -> 600, ٠٦١ -> 160, ٥٫٢١ -> 12.5, ٠٤ -> 40, ٠٣ -> 30, ٠٢ -> 20, ٠١ -> 10, ٠٥ -> 50, ٠٠٥ -> 500).
    """
    if not text:
        return ""
    def _rev_num(m):
        num_str = m.group(0)
        clean_num = num_str.replace('٫', '.').replace(',', '.')
        return clean_num[::-1].translate(EASTERN_ARABIC_DIGITS)
    
    return re.sub(r'[٠-٩]+(?:[٫.,][٠-٩]+)?', _rev_num, text)

