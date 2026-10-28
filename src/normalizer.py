# -*- coding: utf-8 -*-
"""
Arabic text normalization, entity extraction, and vendor resolver.
"""
import os
import re
import unicodedata
import functools
from typing import Optional, Dict, List, Tuple, Any, Sequence

# XML 1.0 illegal characters regex for openpyxl safety
# Prohibits ASCII control characters (0-8, 11-12, 14-31) and surrogate/non-character code points
ILLEGAL_CHARACTERS_RE = re.compile(
    r'[\000-\010]|[\013-\014]|[\016-\037]|[\ud800-\udfff]|[\ufffe-\uffff]'
)


def strip_illegal_characters(text: str) -> str:
    """Removes non-printable ASCII control characters and surrogate code points."""
    if not text:
        return ""
    return ILLEGAL_CHARACTERS_RE.sub("", str(text))

EASTERN_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

ARABIC_CHAR_MAP = {
    # Alif variants & Presentation Forms
    'أ': 'ا',
    'إ': 'ا',
    'آ': 'ا',
    'ٱ': 'ا',
    'ﺎ': 'ا',  # U+FE8E Final Alef
    'ﺍ': 'ا',  # U+FE8D Isolated Alef
    'ﺄ': 'ا',  # U+FE84 Final Alef with Hamza Above
    'ﺃ': 'ا',  # U+FE83 Isolated Alef with Hamza Above
    'ﺈ': 'ا',  # U+FE88 Final Alef with Hamza Below
    'ﺇ': 'ا',  # U+FE87 Isolated Alef with Hamza Below
    'ﺂ': 'ا',  # U+FE82 Final Alef with Madda Above
    'ﺁ': 'ا',  # U+FE81 Isolated Alef with Madda Above

    # Taa Marbuta & Haa Presentation Forms
    'ة': 'ه',
    'ﺔ': 'ه',  # U+FE94 Final Teh Marbuta
    'ﺓ': 'ه',  # U+FE93 Isolated Teh Marbuta
    'ﮫ': 'ه',  # U+FBAB Heh Initial Form
    'ﮪ': 'ه',  # U+FBAA Heh Isolated Form
    'ﮬ': 'ه',  # U+FBAC Heh Medial Form
    'ﮭ': 'ه',  # U+FBAD Heh Medial Form
    'ﻪ': 'ه',  # U+FEEA Final Heh
    'ﻫ': 'ه',  # U+FEEB Initial Heh
    'ﻬ': 'ه',  # U+FEEC Medial Heh
    'ﻩ': 'ه',  # U+FEE9 Isolated Heh
    'ھ': 'ه',  # U+06BE Arabic Letter Heh Doachashmee
    'ہ': 'ه',  # U+06C1 Arabic Letter Heh Goal

    # Yaa & Alef Maksura Presentation Forms
    'ى': 'ي',
    'ئ': 'ي',
    'ؤ': 'و',
    'ی': 'ي',
    'ي': 'ي',
    'ﻰ': 'ي',  # U+FEF0 Final Alef Maksura
    'ﻯ': 'ي',  # U+FEEF Isolated Alef Maksura
    'ﻲ': 'ي',  # U+FEF2 Final Yeh
    'ﯾ': 'ي',  # U+FBFE Yeh Initial Form
    'ﻳ': 'ي',  # U+FEF3 Initial Yeh
    'ﻴ': 'ي',  # U+FEF4 Medial Yeh
    'ﻱ': 'ي',  # U+FEF1 Isolated Yeh
    'ﺊ': 'ي',  # U+FE8A Final Yeh with Hamza Above
    'ﺋ': 'ي',  # U+FE8B Initial Yeh with Hamza Above
    'ﺌ': 'ي',  # U+FE8C Medial Yeh with Hamza Above
    'ﺉ': 'ي',  # U+FE89 Isolated Yeh with Hamza Above

    # Waw Presentation Forms
    'ﻮ': 'و',  # U+FEEE Final Waw
    'ﻭ': 'و',  # U+FEED Isolated Waw
    'ﺆ': 'و',  # U+FE86 Final Waw with Hamza Above
    'ﺅ': 'و',  # U+FE85 Isolated Waw with Hamza Above

    # Kaf Presentation Forms
    'ك': 'ك',
    'ک': 'ك',
    'ﻚ': 'ك',  # U+FEDA Final Kaf
    'ﻛ': 'ك',  # U+FEDB Initial Kaf
    'ﻜ': 'ك',  # U+FEDC Medial Kaf
    'ﻙ': 'ك',  # U+FED9 Isolated Kaf

    # Lam-Alef Ligatures
    'ﻼ': 'لا',  # U+FEFC Final Lam with Alef
    'ﻻ': 'لا',  # U+FEFB Isolated Lam with Alef
    'ﻸ': 'لا',  # U+FEF8 Final Lam with Alef with Hamza Above
    'ﻷ': 'لا',  # U+FEF7 Isolated Lam with Alef with Hamza Above
    'ﻹ': 'لا',  # U+FEF9 Isolated Lam with Alef with Hamza Below
    'ﻺ': 'لا',  # U+FEFA Final Lam with Alef with Hamza Below
    'ﻶ': 'لا',  # U+FEF6 Final Lam with Alef with Madda Above
    'ﻵ': 'لا',  # U+FEF5 Isolated Lam with Alef with Madda Above

    # Beh Presentation Forms
    'ﺐ': 'ب',  # U+FE90 Final Beh
    'ﺑ': 'ب',  # U+FE91 Initial Beh
    'ﺒ': 'ب',  # U+FE92 Medial Beh
    'ﺏ': 'ب',  # U+FE8F Isolated Beh

    # Teh Presentation Forms
    'ﺖ': 'ت',  # U+FE96 Final Teh
    'ﺗ': 'ت',  # U+FE97 Initial Teh
    'ﺘ': 'ت',  # U+FE98 Medial Teh
    'ﺕ': 'ت',  # U+FE95 Isolated Teh

    # Theh Presentation Forms
    'ﺚ': 'ث',  # U+FE9A Final Theh
    'ﺛ': 'ث',  # U+FE9B Initial Theh
    'ﺜ': 'ث',  # U+FE9C Medial Theh
    'ﺙ': 'ث',  # U+FE99 Isolated Theh

    # Jeem Presentation Forms
    'ﺞ': 'ج',  # U+FE9E Final Jeem
    'ﺟ': 'ج',  # U+FE9F Initial Jeem
    'ﺠ': 'ج',  # U+FEA0 Medial Jeem
    'ﺝ': 'ج',  # U+FE9D Isolated Jeem

    # Hah Presentation Forms
    'ﺢ': 'ح',  # U+FEA2 Final Hah
    'ﺣ': 'ح',  # U+FEA3 Initial Hah
    'ﺤ': 'ح',  # U+FEA4 Medial Hah
    'ﺡ': 'ح',  # U+FEA1 Isolated Hah

    # Khah Presentation Forms
    'ﺦ': 'خ',  # U+FEA6 Final Khah
    'ﺧ': 'خ',  # U+FEA7 Initial Khah
    'ﺨ': 'خ',  # U+FEA8 Medial Khah
    'ﺥ': 'خ',  # U+FEA5 Isolated Khah

    # Dal Presentation Forms
    'ﺪ': 'د',  # U+FEAA Final Dal
    'ﺩ': 'د',  # U+FEA9 Isolated Dal

    # Thal Presentation Forms
    'ﺬ': 'ذ',  # U+FEAC Final Thal
    'ﺫ': 'ذ',  # U+FEAB Isolated Thal

    # Reh Presentation Forms
    'ﺮ': 'ر',  # U+FEAE Final Reh
    'ﺭ': 'ر',  # U+FEAD Isolated Reh

    # Zain Presentation Forms
    'ﺰ': 'ز',  # U+FEB0 Final Zain
    'ﺯ': 'ز',  # U+FEAF Isolated Zain

    # Seen Presentation Forms
    'ﺲ': 'س',  # U+FEB2 Final Seen
    'ﺳ': 'س',  # U+FEB3 Initial Seen
    'ﺴ': 'س',  # U+FEB4 Medial Seen
    'ﺱ': 'س',  # U+FEB1 Isolated Seen

    # Sheen Presentation Forms
    'ﺶ': 'ش',  # U+FEB6 Final Sheen
    'ﺷ': 'ش',  # U+FEB7 Initial Sheen
    'ﺸ': 'ش',  # U+FEB8 Medial Sheen
    'ﺵ': 'ش',  # U+FEB5 Isolated Sheen

    # Sad Presentation Forms
    'ﺺ': 'ص',  # U+FEBA Final Sad
    'ﺻ': 'ص',  # U+FEBB Initial Sad
    'ﺼ': 'ص',  # U+FEBC Medial Sad
    'ﺹ': 'ص',  # U+FEB9 Isolated Sad

    # Dad Presentation Forms
    'ﺾ': 'ض',  # U+FEBE Final Dad
    'ﺿ': 'ض',  # U+FEBF Initial Dad
    'ﻀ': 'ض',  # U+FEC0 Medial Dad
    'ﺽ': 'ض',  # U+FEBD Isolated Dad

    # Tah Presentation Forms
    'ﻂ': 'ط',  # U+FEC2 Final Tah
    'ﻃ': 'ط',  # U+FEC3 Initial Tah
    'ﻄ': 'ط',  # U+FEC4 Medial Tah
    'ﻁ': 'ط',  # U+FEC1 Isolated Tah

    # Zah Presentation Forms
    'ﻆ': 'ظ',  # U+FEC6 Final Zah
    'ﻈ': 'ظ',  # U+FEC8 Medial Zah
    'ﻅ': 'ظ',  # U+FEC5 Isolated Zah

    # Ain Presentation Forms
    'ﻊ': 'ع',  # U+FECA Final Ain
    'ﻋ': 'ع',  # U+FECB Initial Ain
    'ﻌ': 'ع',  # U+FECC Medial Ain
    'ﻉ': 'ع',  # U+FEC9 Isolated Ain

    # Ghain Presentation Forms
    'ﻎ': 'غ',  # U+FECE Final Ghain
    'ﻏ': 'غ',  # U+FECF Initial Ghain
    'ﻐ': 'غ',  # U+FED0 Medial Ghain
    'ﻍ': 'غ',  # U+FECD Isolated Ghain

    # Feh Presentation Forms
    'ﻒ': 'ف',  # U+FED2 Final Feh
    'ﻓ': 'ف',  # U+FED3 Initial Feh
    'ﻔ': 'ف',  # U+FED4 Medial Feh
    'ﻑ': 'ف',  # U+FED1 Isolated Feh

    # Qaf Presentation Forms
    'ﻖ': 'ق',  # U+FED6 Final Qaf
    'ﻗ': 'ق',  # U+FED7 Initial Qaf
    'ﻘ': 'ق',  # U+FED8 Medial Qaf
    'ﻕ': 'ق',  # U+FED5 Isolated Qaf

    # Lam Presentation Forms
    'ﻞ': 'ل',  # U+FEDE Final Lam
    'ﻟ': 'ل',  # U+FEDF Initial Lam
    'ﻠ': 'ل',  # U+FEE0 Medial Lam
    'ﻝ': 'ل',  # U+FEDD Isolated Lam

    # Meem Presentation Forms
    'ﻢ': 'م',  # U+FEE2 Final Meem
    'ﻣ': 'م',  # U+FEE3 Initial Meem
    'ﻤ': 'م',  # U+FEE4 Medial Meem
    'ﻡ': 'م',  # U+FEE1 Isolated Meem

    # Noon Presentation Forms
    'ﻦ': 'ن',  # U+FEE6 Final Noon
    'ﻧ': 'ن',  # U+FEE7 Initial Noon
    'ﻨ': 'ن',  # U+FEE8 Medial Noon
    'ﻥ': 'ن',  # U+FEE5 Isolated Noon
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

CUSTOM_CATALOG_LIGATURE_MAP = {
    'ᣂᢕﺘᜧﻻ': 'الاكتيز',
    'ᣂᢕﺘᜧلا': 'الاكتيز',
    'ﻻᜧﺘᢕᣂ': 'الاكتيز',
    'لاᜧﺘᢕᣂ': 'الاكتيز',
    'ᣂᢕ': 'ير',
    'ᢕᣂ': 'ري',
    'ᜧᣂᢕ': 'كير',
    'ᢕᣂᜧ': 'ريك',
    'ᡧᢕᣂﻻᜧﺘ': 'الاكتيز',
    'وᣂ ᢔﻴﺳ': 'سيبرو',
    'وᣂᢔﻴﺳ': 'سيبرو',
    'ﻟᣌᢔᡧ': 'لبن',
    'لᣌᢔᡧ': 'لبن',
    'ᣃᡫ اب': 'شراب',
    'ᣃᡫاب': 'شراب',
    'ᣃᡫ': 'شريط',
    'ᣌᢕᡧ': 'ين',
    'ᡧᢕᣌ': 'ين',
    ' ᣌن': 'ن',
    'ᣌن': 'ين',
    'ᗷᜧᘭ': 'بكي',
}

AL_HADABA_FONT_MAP = {
    'ᗷ': 'ب', 'ᜧ': 'ك', 'ᘭ': 'ي', 'ᗫ': 'ي', 'ᣂ': 'ر', 'ᢕ': 'و', 'ᘌ': 'ي', 'ᡧ': 'ن',
    'ᖁ': 'ر', 'ᛞ': 'ب', 'ᢔ': 'ب', 'ᘘ': 'ب', 'ᡫ': 'ر', 'ᣃ': 'ش', 'ᗖ': 'ب', 'ᖔ': 'و',
    'ᒯ': 'ه', 'ᡨ': 'ر', 'ᛳ': 'ي', 'ᚏ': 'ي', 'ᙬ': 'ن', 'ᚱ': 'ي', 'ᜓ': 'و', 'ᣍ': 'ي',
    'ᣎ': 'ي', 'ᙏ': 'ن', 'ᙫ': 'ب', 'ᣒ': 'ي', 'ᣄ': 'ش', 'ᝏ': 'ك', 'ᝣ': 'ك', 'ᣠ': 'ي',
    'ᛒ': 'ب', '᙭': 'ث', 'ᚽ': 'ب', 'ᣢ': 'لي', 'ᣚ': 'نا', 'ᡵ': 'ر', 'ᘻ': 'ت', 'ᢝ': 'ي',
    '᚜': 'ي', 'ᣤ': 'ي', '\u16ff': 'ك',
    'ᣌ': 'ي', 'ᖂ': 'ز', 'ᣐ': 'ي', 'ᣓ': 'س', 'ᣛ': 'ي', 'ᣥ': 'ي', 'ᣑ': 'ي', 'ᣆ': 'ض'
}

CUSTOM_CATALOG_GLYPH_MAP = {**GREEK_ARABIC_MAP, **AL_HADABA_FONT_MAP}
CUSTOM_CATALOG_GLYPH_MAP['ᛞ'] = 'ب'
CUSTOM_CATALOG_GLYPH_MAP['ᘭ'] = 'ي'
CUSTOM_CATALOG_GLYPH_MAP['ᢔ'] = 'ب'
CUSTOM_CATALOG_GLYPH_MAP['\u16ff'] = 'ك'

def normalize_ocr_split_medication_names(text: str) -> str:
    """Normalize OCR-split multi-word Arabic medication names into unified canonical forms."""
    if not text or not isinstance(text, str):
        return ""
    t = str(text)
    # E.g. 'سباز موبير الجين' / 'سبازموبي رالجي ني' / 'سبازموبي رالجين' -> 'سبازموبيرالجين'
    t = re.sub(r'سباز\s*م[وُ]?\s*بي\s*ر\s*ال\s*جي\s*ن(?:[يى]|\b)', 'سبازموبيرالجين', t)
    t = re.sub(r'سباز\s*مو\s*ديجستين', 'سبازموديجستين', t)
    t = re.sub(r'سباز\s*مو\s*كيور', 'سبازموكيور', t)
    t = re.sub(r'سباز\s*مو\s*فري', 'سبازموفري', t)
    t = re.sub(r'هاي\s+بيوتك', 'هايبيوتك', t)
    t = re.sub(r'ميجا\s+موكس', 'ميجاموكس', t)
    t = re.sub(r'ما\s*مي\s*كير', 'مامي كير', t)
    t = re.sub(r'در\s*موكالم', 'درموكالم', t)
    t = re.sub(r'بيكو\s*لاكس', 'بيكولاكس', t)
    t = re.sub(r'ادو\s*يفلام', 'ادويفلام', t)
    t = re.sub(r'ادو\s*يفالم', 'ادويفلام', t)
    t = re.sub(r'از\s*اثيوبرين', 'ازاثيوبرين', t)
    t = re.sub(r'بريفا\s*كوند', 'بريفاكوند', t)
    t = re.sub(r'سيكو\s*برام', 'سيكوبرام', t)
    t = re.sub(r'جلي\s*مبا\s*كير|جليم\s*با\s*كير', 'جليمباكير', t)
    t = re.sub(r'بيتا\s*لليرج|بيتا\s*ليرج', 'بيتاليرج', t)
    t = re.sub(r'تيرا\s*ميسن|تيرا\s*ميسين', 'تيراميسين', t)
    t = re.sub(r'دور\s*ميفال', 'دورميفال', t)
    t = re.sub(r'زيثرو\s*دوز', 'زيثرودوز', t)
    t = re.sub(r'لينا\s*تراج', 'ليناتراج', t)
    t = re.sub(r'فور\s*كيدز', 'فوركيدز', t)
    return t

def decode_custom_catalog_glyphs(text: str) -> str:
    """Decodes custom ERP font encodings (ArwaSoft Greek, Al-Hadaba/OrgaSoft Aboriginal/Runic) back into standard Arabic letters."""
    if not text or not isinstance(text, str):
        return ""
    t = str(text)
    for lig, rep in CUSTOM_CATALOG_LIGATURE_MAP.items():
        if lig in t:
            t = t.replace(lig, rep)
    for glyph, arabic_char in CUSTOM_CATALOG_GLYPH_MAP.items():
        if glyph in t:
            t = t.replace(glyph, arabic_char)
    t = normalize_ocr_split_medication_names(t)
    return t

def decode_greek_arwasoft(text: str) -> str:
    """Backward compatibility alias for decode_custom_catalog_glyphs."""
    return decode_custom_catalog_glyphs(text)

def normalize_vendor_name(filename_or_raw_name: str) -> str:
    """Standardizes raw catalog filename into a clean entity label."""
    if not filename_or_raw_name:
        return ""
    name = os.path.splitext(os.path.basename(filename_or_raw_name))[0].replace('‎','').replace('⁨','').replace('⁩','').replace('EX','')
    name_clean = name.replace('ـ', '').replace('-', ' ').replace('_', ' ').strip()
    
    # Strip day names, version tags, and commercial noise anywhere in string
    name_clean = re.sub(r'\b(?:السبت|الاحد|الأحد|الاثنين|الإثنين|الثلاثاء|الاربعاء|الأربعاء|الخميس|الجمعة|الجمعه)\b', ' ', name_clean)
    name_clean = re.sub(r'\b(?:نقدي|نقدى|كاش|خاص|عروض|تحديث|سعر|جديد|ش|ج)\b', ' ', name_clean)
    name_clean = re.sub(r'[\(\)\[\]0-9]', ' ', name_clean)
    name_clean = re.sub(r'\s+', ' ', name_clean).strip()
    
    # Wholesaler canonical mappings (specific vendors prioritized to avoid collisions)
    if 'ادم' in name_clean or 'آدم' in name_clean:
        return 'مخزن ادم جملة'
    if 'محجوب' in name_clean:
        return 'مخزن محجوب السنبلاوين'
    if 'انفينتي' in name_clean or 'انفنتي' in name_clean or 'انفينتى' in name_clean:
        return 'مخزن انفينتي'
    if 'كيان' in name_clean:
        return 'نيو كيان المنصورة'
    if 'بيرفكت' in name_clean:
        return 'بيرفكت فارم المنوفية'
    if 'دار الفؤاد' in name_clean or 'الفؤاد' in name_clean:
        return 'دار الفؤاد'
    if 'رافال' in name_clean:
        return 'مخزن رافال فارم'
    if 'الرواد' in name_clean or 'رواد كفر الدوار' in name_clean:
        return 'الرواد'
    if 'رواد' in name_clean or 'الدوااا' in name_clean or 'رواد الدواء' in name_clean:
        return 'شركة رواد الدواء'
    if 'سينا' in name_clean:
        return 'سينا تريد'
    if 'لايف كير' in name_clean or 'تروفي' in name_clean or 'تروفى' in name_clean:
        return 'لايف كير تروفي'
    if 'العربيه للصيادله' in name_clean or 'العربية للصيادلة' in name_clean or 'العربيه' in name_clean or 'العربية' in name_clean:
        return 'الشركة العربية للصيادلة'
    if 'الفرسان' in name_clean:
        if 'اسكندريه' in name_clean or 'اسكندرية' in name_clean:
            return 'الفرسان اسكندرية'
        if 'بنها' in name_clean:
            return 'الفرسان بنها'
        return 'مخزن الفرسان'
        
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
    if 'القمة' in name_clean:
        return 'مخزن القمة'
    if 'وائل سمير' in name_clean:
        return 'مخزن وائل سمير'
    if 'زيدان' in name_clean or 'زيدااان' in name_clean:
        return 'مميز زيدان'
    if 'احمد عبد الله' in name_clean or 'أحمد عبد الله' in name_clean:
        return 'مخزن د أحمد عبد الله'
    if 'فريندس' in name_clean:
        return 'فريندس تو ام'
    if 'الدولية الحديثة' in name_clean or 'الدوليه الحديثه' in name_clean:
        return 'مخزن الدولية الحديثة'
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
    if 'الحياه' in name_clean or 'الحياة' in name_clean or 'hayah_shibin' in name.lower() or 'hayah' in name_clean.lower():
        return 'مخزن الحياة فارم'
    if 'فالكون' in name_clean:
        return 'مخزن فالكون فارم'
    if 'فارما تو جو' in name_clean or 'فارما توجو' in name_clean:
        return 'فارما تو جو'
    if 'نيو الفا' in name_clean or 'نيو ألفا' in name_clean or 'الفا فارم' in name_clean:
        return 'نيو ألفا فارم'
    if 'نيو فارم' in name_clean:
        return 'نيو فارم شبين الكوم'
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
    if 'زهرة' in name_clean or 'زهره' in name_clean:
        return 'زهرة فارم'
    
    # Disambiguate جملة vs جمل: strip wholesale indicator before matching Gamal Warehouse
    name_no_gomla = re.sub(r'\b(?:جملة|جمله)\b', '', name_clean).strip()
    if 'جمل' in name_no_gomla:
        return 'مخزن جمل'
    
    return name_clean.strip() if name_clean else name.strip()

REVERSED_PHARMA_TOKENS = {
    'صارقا', 'صرق', 'لوسبك', 'هلوسبك', 'ةلوسبك', 'ميرك', 'لوبما', 'تلاوبما', 'لوبمإ',
    'بارش', 'تكاب', 'وكاب', 'ةنوترك', 'هنوترك', 'ةبلع', 'هبلع', 'طيرش', 'طیرش', 'طیررش',
    'راوف', 'طقن', 'طاقن', 'رعس', 'مصخ', 'فنصلا', 'فنص', 'ديدج', 'ميدق', 'يفاص',
    'لوسغ', 'لولحم', 'نوباص', 'سوبل', 'عاقما', 'نحق', 'ليدب', 'لیدب', 'خيرات', 'خیرات',
    'ةدحتملا', 'هدحتملا', 'ةكرشلا', 'هكرشلا', 'ةيلودلا', 'هيلودلا', 'ةيرماعلا', 'هيرماعلا',
    'ةيمسر', 'هيمسر', 'ةيبنا', 'هيبنا', 'ناهدم', 'سايكا', 'سايكأ', 'ليج', 'يلج', 'خاخم', 'ياربسا',
    'نشول', 'كيرا', 'يجلرد', 'نيتسكوباد', 'اتكرنومايد', 'ماجلوياب', 'اتيفويب', 'شام', 'لم', 'للم',
    'كولب', 'نص', 'سلب', 'ريغص', 'ريبك', 'اتكرياف', 'ملافولكيد', 'وبماش', 'لدناد', 'نويسول',
    'مويسلاكيد', 'لوزاتسيجناب'
}

FORWARD_PHARMA_TOKENS = {
    'اقراص', 'قرص', 'كبسول', 'كبسولة', 'كريم', 'امبول', 'امبولات', 'إمبول',
    'شراب', 'باكت', 'باكو', 'كرتونة', 'علبة', 'شريط',
    'فوار', 'نقط', 'نقاط', 'سعر', 'خصم', 'الصنف', 'صنف', 'جديد', 'قديم', 'صافي',
    'غسول', 'محلول', 'صابون', 'لبوس', 'اقماع', 'حقن', 'بديل', 'تاريخ',
    'المتحدة', 'الشركة', 'الدولية', 'العامرية', 'رسمية', 'انبوبة', 'مدهان', 'اكياس', 'جل', 'جيل', 'بخاخ', 'سبراي',
    'لوشن', 'اريك', 'درلجي', 'دابوكستين', 'دياموكرون', 'بايوجليم', 'بيوفيت', 'ماش', 'مل', 'ملل',
    'بلوك', 'صن', 'صن بلوك', 'بلس', 'صغير', 'كبير', 'فايركتا', 'ديكلوفلام', 'شامبو', 'داندل', 'لوسيون',
    'ديكالسيوم', 'بانجستازول'
}

REVERSED_TOKEN_MAP = {
    'صرق': 'قرص',
    'صارقا': 'اقراص',
    'طيرش': 'شريط',
    'طیرش': 'شريط',
    'طیررش': 'شريط',
    'نشول': 'لوشن',
    'ديدج': 'جديد',
    'كيرا': 'اريك',
    'يجلرد': 'درلجي',
    'نيتسكوباد': 'دابوكستين',
    'اتكرنومايد': 'دياموكرون',
    'ماجلوياب': 'بايوجليم',
    'اتيفويب': 'بيوفيت',
    'شام': 'ماش',
    'لم': 'مل',
    'للم': 'ملل',
    'ميرك': 'كريم',
    'سلب': 'بلس',
    'اتكرياف': 'فايركتا',
    'ملافولكيد': 'ديكلوفلام',
    'لوسبك': 'كبسول',
    'هلوسبك': 'كبسوله',
    'ةلوسبك': 'كبسولة',
    'لوبما': 'امبول',
    'تلاوبما': 'امبولات',
    'بارش': 'شراب',
    'تكاب': 'باكت',
    'وكاب': 'باكو',
    'راوف': 'فوار',
    'طقن': 'نقط',
    'طاقن': 'نقاط',
    'سوبل': 'لبوس',
    'عاقما': 'اقماع',
    'ريغص': 'صغير',
    'ريبك': 'كبير',
    'رعس': 'سعر',
    'مصخ': 'خصم',
    'ليدب': 'بديل',
    'ميدق': 'قديم',
    'يفاص': 'صافي',
    'لوسغ': 'غسول',
    'لولحم': 'محلول',
    'نوباص': 'صابون',
    'نحق': 'حقن',
    'ناهدم': 'مدهان',
    'سايكا': 'اكياس',
    'سايكأ': 'اكياس',
    'خاخم': 'بخاخ',
    'ياربسا': 'سبراي',
    'خيرات': 'تاريخ',
    'ةدحتملا': 'المتحدة',
    'هدحتملا': 'المتحدة',
    'ةكرشلا': 'الشركة',
    'هكرشلا': 'الشركة',
    'ةيلودلا': 'الدولية',
    'هيلودلا': 'الدولية',
    'ةيرماعلا': 'العامرية',
    'هيرماعلا': 'العامرية',
    'ةيمسر': 'رسمية',
    'هيمسر': 'رسمية',
    'ةيبنا': 'انبوبة',
    'هيبنا': 'انبوبة',
    'فنصلا': 'الصنف',
    'فنص': 'صنف',
    'وبماش': 'شامبو',
    'لدناد': 'داندل',
    'نويسول': 'لوسيون',
    'مويسلاكيد': 'ديكالسيوم',
    'لوزاتسيجناب': 'بانجستازول',
}

REVERSED_PHRASE_PATTERNS = [
    (r'\bكولب\s+نص\b', 'صن بلوك'),
    (r'\bبلوك\s+صن\b', 'صن بلوك'),
    (r'\bنص\s+كولب\b', 'صن بلوك'),
    (r'\bص\s+رق\b', 'قرص'),
    (r'\bط\s+يرش\b', 'شريط'),
    (r'\bريه\s+بوت\b', 'توب هير'),
    (r'\bبوت\s+ريه\b', 'توب هير'),
    (r'\bكليم\s+يدب\b', 'بدي ميلك'),
    (r'\bيدب\s+كليم\b', 'بدي ميلك'),
    (r'\bمسجلل\b', 'للجسم'),
    (r'\bدنا\s+تسيوت\b', 'تويست اند'),
    (r'\bتسيوت\s+دنا\b', 'تويست اند'),
    (r'\bريه\s+وج\b', 'جو هير'),
    (r'\bمريس\b', 'سيرم'),
    (r'\bلافطلل\s+ءام\s+يبيب\s+وسناس\b', 'سانسو بيبي ماء للاطفال'),
    (r'\bسلب\s+اتكرياف\b', 'فايركتا بلس'),
    (r'\bق\s+ملافولكيد\b', 'ديكلوفلام ق'),
]

def fix_spaced_and_reversed_digits(text: str) -> str:
    """Fixes digit spacing and reversed digit patterns from catalog print streams."""
    if not text:
        return ""
    t = text
    t = re.sub(r'\b0\s+0\s*/\s*3\s+5\b', '35/500', t)
    t = re.sub(r'\b0\s+0\s+1\b', '100', t)
    t = re.sub(r'\b0\s+0\s+2\b', '200', t)
    t = re.sub(r'\b0\s+0\s+3\b', '300', t)
    t = re.sub(r'\b0\s+0\s+4\b', '400', t)
    t = re.sub(r'\b0\s+0\s+5\b', '500', t)
    t = re.sub(r'\b0\s+0\s+6\b', '600', t)
    t = re.sub(r'\b0\s+0\s+8\b', '800', t)
    t = re.sub(r'\b0\s+5\s+2\b', '250', t)
    t = re.sub(r'\b0\s+4\s+2\b', '240', t)
    t = re.sub(r'\b0\s+6\s+1\b', '160', t)
    t = re.sub(r'\b4\s+4\s+1\b', '144', t)
    t = re.sub(r'\b0\s+10\b', '100', t)

    # Inverted word order streams (e.g. 0 0 1 word-reversed to 1 0 0)
    t = re.sub(r'\b1\s+0\s+0\b', '100', t)
    t = re.sub(r'\b2\s+0\s+0\b', '200', t)
    t = re.sub(r'\b5\s+0\s+0\b', '500', t)

    for d, val in [('2', '20'), ('3', '30'), ('4', '40'), ('5', '50'), ('6', '60'), ('7', '70'), ('8', '80'), ('9', '90')]:
        t = re.sub(rf'\b0\s+{d}\b', val, t)

    # Lookahead and preceding unit rules for pack sizes (12 and 14)
    pack_units = r'(?:قرص|اقراص|صرق|صارقا|tab|strip|شريط|طيرش|مجم|مج|كبسول|هلوسبك)'
    t = re.sub(rf'\b2\s+1\s*(?={pack_units})', '12 ', t)
    t = re.sub(rf'(\b{pack_units})\s*2\s+1\b', r'\1 12', t)
    t = re.sub(rf'\b4\s+1\s*(?={pack_units})', '14 ', t)
    t = re.sub(rf'(\b{pack_units})\s*4\s+1\b', r'\1 14', t)

    # Iteratively collapse remaining spaces between digits
    while re.search(r'(?<=\d)\s+(?=\d)', t):
        t = re.sub(r'(?<=\d)\s+(?=\d)', '', t)
    return t

def is_arabic_text_reversed(text: str) -> bool:
    """Evaluates whether an Arabic string has reversed letter stream order."""
    if not text:
        return False
    t_clean = strip_illegal_characters(str(text))
    t_clean = decode_custom_catalog_glyphs(t_clean)
    for src, dst in ARABIC_CHAR_MAP.items():
        t_clean = t_clean.replace(src, dst)
    norm = unicodedata.normalize('NFKD', t_clean)
    # Unify Persian/Urdu variants before checking tokens
    norm = norm.replace('ی', 'ي').replace('ک', 'ك').replace('ہ', 'ه')
    rev_score = 0
    fwd_score = 0

    # Unit position heuristics (count all occurrences)
    rev_unit_matches = re.findall(r'(?:^|\s)(?:ق|مجم|جم|مل|سم|صرق|طيرش|طیرش|لوسبك)\s+\d+', norm)
    rev_score += len(rev_unit_matches) * 4
    
    fwd_unit_matches = re.findall(r'\d+\s+(?:ق|مجم|جم|مل|سم|قرص|شريط|كبسول)(?:\s|$)', norm)
    fwd_score += len(fwd_unit_matches) * 4

    words = re.findall(r'[\u0600-\u06ff]+', norm)
    for w in words:
        if w in REVERSED_PHARMA_TOKENS:
            rev_score += 6
        elif w in FORWARD_PHARMA_TOKENS:
            fwd_score += 6
        if w.startswith('ة') and len(w) > 1:
            rev_score += 5
        elif w.endswith('ة') and len(w) > 1:
            fwd_score += 3
        if w.startswith('ى') and len(w) > 1:
            rev_score += 5
        elif w.endswith('ى') and len(w) > 1:
            fwd_score += 3
        if w.endswith('لا') and len(w) >= 4 and not w.startswith('ال'):
            rev_score += 4
        elif w.startswith('ال') and len(w) >= 4 and not w.endswith('لا'):
            fwd_score += 3
        if w.endswith(('لأ', 'لإ', 'لآ')):
            rev_score += 4
        elif w.startswith(('أل', 'إل', 'آل')):
            fwd_score += 3
    return rev_score > fwd_score

def unreverse_arabic_text(text: str, force_reverse: Optional[bool] = None) -> str:
    """Detects reversed Arabic text inside PDF-extracted text and restores natural reading order without corrupting digits or forward text."""
    if not text or not isinstance(text, str):
        return ""
    
    text = strip_illegal_characters(text)
    
    # Decode custom ERP font encodings (ArwaSoft Greek, Al-Hadaba Aboriginal/Runic)
    text = decode_custom_catalog_glyphs(text)
    
    # Normalize Arabic decimal separator (٫) between digits before word splitting so decimals like 41٫5 stay intact
    text = re.sub(r'(?<=[\d\u0660-\u0669])٫(?=[\d\u0660-\u0669])', '.', text)
    text = text.translate(EASTERN_ARABIC_DIGITS)
    
    # Decouple punctuation attached to letters
    text = re.sub(r'([)\]}>(])([a-zA-Z\u0600-\u06ff])', r'\1 \2', text)
    text = re.sub(r'([a-zA-Z\u0600-\u06ff])([)\]}>(])', r'\1 \2', text)
    text = re.sub(r'([a-zA-Z\u0600-\u06ff])([/\-])', r'\1 \2', text)
    text = re.sub(r'([/\-])([a-zA-Z\u0600-\u06ff])', r'\1 \2', text)

    # Protect numbers from being reversed with attached words (e.g. 100مجم -> 100 مجم)
    text = re.sub(r'([a-zA-Z\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufeff])(\d+)', r'\g<1> \g<2>', text)
    text = re.sub(r'(\d+)([a-zA-Z\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufeff])', r'\g<1> \g<2>', text)
    
    # Pre-replace known multi-word reversed phrases before splitting
    for pat, rep in REVERSED_PHRASE_PATTERNS:
        text = re.sub(pat, rep, text)

    if force_reverse is True:
        should_reverse = True
    elif force_reverse is False:
        should_reverse = False
    else:
        should_reverse = is_arabic_text_reversed(text)

    if should_reverse:
        latin_chars = len(re.findall(r'[a-zA-Z]', text))
        arabic_chars_count = len(re.findall(r'[\u0600-\u06FF\ufb50-\ufdff\ufe70-\ufeff]', text))
        is_mixed_predominantly_latin = latin_chars > 0 and (latin_chars >= arabic_chars_count or latin_chars >= 4)
        
        words = text.split()
        unreversed_words = []
        known_forward_tokens = FORWARD_PHARMA_TOKENS.union({'الاكتيز', 'اكتيز', 'سيبرو'})
        
        for w in words:
            # Don't reverse pure numbers or punctuation
            if re.fullmatch(r'[\d.,/%\-_]+', w):
                unreversed_words.append(w)
                continue
            w_clean = re.sub(r'^[^\w]+|[^\w]+$', '', w)
            if w_clean in REVERSED_TOKEN_MAP:
                rep = REVERSED_TOKEN_MAP[w_clean]
                unreversed_words.append(w.replace(w_clean, rep))
                continue
            if w in known_forward_tokens or w_clean in known_forward_tokens or normalize_arabic_text(w_clean) in known_forward_tokens:
                unreversed_words.append(w)
                continue
            arabic_chars = [c for c in w if ('؀' <= c <= 'ۿ') or ('\ufb50' <= c <= '\ufeff')]
            if len(arabic_chars) > len(w) * 0.5:
                if is_mixed_predominantly_latin:
                    unreversed_words.append(w)
                else:
                    unreversed_words.append(w[::-1])
            else:
                unreversed_words.append(w)
        
        if is_mixed_predominantly_latin:
            text = ' '.join(unreversed_words)
        else:
            text = ' '.join(unreversed_words[::-1])

    # Un-reverse individual known reversed tokens even if full string was forward or mixed
    words = text.split()
    fixed_words = []
    for w in words:
        w_clean = re.sub(r'^[^\w]+|[^\w]+$', '', w)
        if w_clean in REVERSED_TOKEN_MAP:
            rep = REVERSED_TOKEN_MAP[w_clean]
            fixed_words.append(w.replace(w_clean, rep))
        else:
            fixed_words.append(w)
    text = ' '.join(fixed_words)

    # Apply phrase replacements once more
    for pat, rep in REVERSED_PHRASE_PATTERNS:
        text = re.sub(pat, rep, text)

    # Fix digit spacing & reversed digit quirks
    text = fix_spaced_and_reversed_digits(text)

    # Normalize unicode presentation forms AFTER reversing word characters so ligatures (like Lam-Alef) preserve correct letter order
    for src, dst in ARABIC_CHAR_MAP.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize('NFKD', str(text))
    text = text.translate(EASTERN_ARABIC_DIGITS)
    text = text.replace('ی', 'ي').replace('ک', 'ك').replace('ہ', 'ه')
    text = text.replace('ٌ', 'ي').replace('ً', 'ي')
    text = text.replace('ـ', '')

    # Final cleanup of any un-reversed tokens exposed after presentation form normalization
    post_words = text.split()
    cleaned_post = []
    for w in post_words:
        wc = re.sub(r'^[^\w]+|[^\w]+$', '', w)
        if wc in REVERSED_TOKEN_MAP:
            cleaned_post.append(w.replace(wc, REVERSED_TOKEN_MAP[wc]))
        else:
            cleaned_post.append(w)
    text = ' '.join(cleaned_post)
    return re.sub(r'\s+', ' ', text).strip()



def resolve_group_arabic_direction(rows: Sequence[Sequence[Any]], name_col: int) -> str:
    """
    Establishes group-level Arabic reading direction from multiple clear examples within the group.
    Returns 'reversed', 'forward', or 'unknown'.
    """
    if name_col is None or not rows:
        return "unknown"

    rev_votes = 0
    fwd_votes = 0

    for r in rows:
        if name_col >= len(r) or r[name_col] is None:
            continue
        val = str(r[name_col]).strip()
        if not val or len(val) < 2 or val.isdigit():
            continue
        decoded = decode_custom_catalog_glyphs(val)
        if is_catalog_noise(decoded):
            continue

        if is_arabic_text_reversed(decoded):
            rev_votes += 1
        elif any(w in decoded for w in FORWARD_PHARMA_TOKENS):
            fwd_votes += 1

    if rev_votes >= 2 and rev_votes > fwd_votes * 1.5:
        return "reversed"
    if fwd_votes >= 2 and fwd_votes > rev_votes * 1.5:
        return "forward"
    return "unknown"


def pre_tokenize_pharma_string(text: str) -> str:
    """
    Decouples glued numbers, dosage units, and packaging forms in pharmaceutical names.
    E.g.: 'ابيزيثرو500مجم3قرص' -> 'ابيزيثرو 500 مجم 3 قرص'
          'اتراكون14كبسوله' -> 'اتراكون 14 كبسوله'
          'Augmentin1g14tab' -> 'Augmentin 1 g 14 tab'
    """
    if not text or not isinstance(text, str):
        return ""
    t = strip_illegal_characters(str(text))
    t = decode_custom_catalog_glyphs(t)
    t = t.translate(EASTERN_ARABIC_DIGITS)
    for src, dst in ARABIC_CHAR_MAP.items():
        t = t.replace(src, dst)
    
    # Decouple punctuation attached to letters/digits
    t = re.sub(r'([)\]}>(])([a-zA-Z\u0600-\u06ff])', r'\1 \2', t)
    t = re.sub(r'([a-zA-Z\u0600-\u06ff])([)\]}>(])', r'\1 \2', t)
    t = re.sub(r'([a-zA-Z\u0600-\u06ff])([/\-])', r'\1 \2', t)
    t = re.sub(r'([/\-])([a-zA-Z\u0600-\u06ff])', r'\1 \2', t)

    # Decouple commercial abbreviations & suffixes (س 144 ج, س ج, ش ج, باكو 160)
    t = re.sub(r'\bسج\b', 'س ج', t)
    t = re.sub(r'\bشج\b', 'ش ج', t)
    t = re.sub(r'\bسق\b', 'س ق', t)
    t = re.sub(r'\bشق\b', 'ش ق', t)
    t = re.sub(r'(\bس)\s*(\d+)\s*(ج\b)', r'\1 \2 \3', t)
    
    # 1. Decouple letters and digits
    t = re.sub(r'([a-zA-Z\u0600-\u06FF])(\d+)', r'\1 \2', t)
    t = re.sub(r'(\d+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', t)
    
    # 1b. Decouple glued Latin letters and Arabic letters
    t = re.sub(r'([a-zA-Z])([\u0600-\u06FF])', r'\1 \2', t)
    t = re.sub(r'([\u0600-\u06FF])([a-zA-Z])', r'\1 \2', t)
    
    # 2. Decouple glued dosage units & packaging forms from adjacent digits
    units = (
        r'(?:مجم|جم|مج|غم|جرام|مكجم|ميكروجرام|ميكرو|ملل|مل|سم|وحدة|'
        r'اقراص|قرص|اقرص|لرص|صارقا|صرق|كبسولات|كبسولة|كبسول|هلوسبك|'
        r'امبولات|امبول|لوبما|فيال|شريطين|شرايط|شريط|طيرش|طیرش|طیررش|شراب|شرب|بارش|'
        r'نقط|قطرة|قطره|فوار|اكياس|كيس|باكت|باكو|علبة|علبه|بخاخ|مرهم|كريم|جل|جيل|لوشن|لبوس|حقن|'
        r'mg|gm|g|ml|mcg|iu|tab|tabs|tablet|tablets|cap|caps|capsule|capsules|amp|amps|ampoule|ampoules|'
        r'vial|vials|strip|strips|syr|syrup|sachet|sachets|cream|gel|oint|spray|drop|drops)'
    )
    t = re.sub(rf'(\d+(?:\.\d+)?)\s*({units})\b', r'\1 \2 ', t, flags=re.IGNORECASE)
    t = re.sub(rf'\b({units})\s*(\d+(?:\.\d+)?)', r' \1 \2 ', t, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', t).strip()


def normalize_drug_text(text: str) -> str:
    """Canonical text normalizer based on medicine-price-comparator-new skill with pre-tokenization."""
    if not text:
        return ""
    text = pre_tokenize_pharma_string(text)
    text = strip_illegal_characters(text)
    t = unicodedata.normalize('NFKD', str(text)).translate(EASTERN_ARABIC_DIGITS)
    for src, dst in ARABIC_CHAR_MAP.items():
        t = t.replace(src, dst)
    t = t.replace('/', ' ').replace('٫', '.').replace('،', ',').replace('٪', '%')
    t = re.sub(r'[ـ]', '', t)
    t = re.sub(r'([a-zA-Z؀-ۿ])(\d)', r'\\g<1> \\g<2>', t)
    t = re.sub(r'(\d)([a-zA-Z؀-ۿ])', r'\\g<1> \\g<2>', t)
    t = re.sub(r'[إأآاٱ]', 'ا', t)
    t = re.sub(r'ة', 'ه', t)
    t = re.sub(r'[ىيئیی]', 'ي', t)
    t = re.sub(r'[كک]', 'ك', t)
    t = re.sub(r'[ؤ]', 'و', t)
    return t.lower()


CANONICAL_NOISE_WORDS = [
    'س ج', 'س ق', 'سعر جديد', 'سعر قديم', 'س.ج', 'س.ق', 'ش ج', 'ش.ج', 'شريط جديد', 'س 144 ج', 'جديد', 'قديم', 'سعر', 'جنيه',
    'باكو', 'باكت', 'كرتونه', 'كرتون', 'علبه', 'علبة', 'شريط', 'شرايط', 'شريطين',
    'ثلاجة', 'ثلاجه', 'ث', 'محلي', 'مستورد', 'عرض', 'كبير', 'صغير', 'عادي',
    'فاركو', 'العامرية', 'ميباكو', 'النيل', 'ايبيكو', 'سانوفي', 'سيديكو', 'ماش',
    'الحكمه', 'المهن', 'ممفيس', 'فرعونية', 'اكديما', 'سيجما', 'امون', 'ادويا',
    'اقراص', 'قرص', 'اقرص', 'لرص', 'ق', 'tab', 'tablet', 'tablets', 'كبسول', 'كبسولة', 'كبسولات', 'ك', 'cap', 'capsule', 'capsules',
    'شراب', 'شرب', 'ش', 'syr', 'syrup', 'حقن', 'امبول', 'امبولات', 'فيال', 'فيالات', 'inj', 'amp', 'ampoule', 'vial',
    'كريم', 'cream', 'مرهم', 'oint', 'جل', 'جيل', 'gel', 'لوشن', 'lotion',
    'نقط', 'قطرة', 'قطره', 'drops', 'drop', 'eye drop', 'ear drop', 'بخاخ', 'اسبراي', 'سبراي', 'spray', 'فوار', 'اكياس', 'كيس', 'sachet', 'sachets',
    'لبوس', 'لبوسة', 'اقماع', 'قمع', 'خرطوشه', 'خرطوشة', 'فيلم', 'لزقه', 'لزقة', 'بودره', 'بودرة', 'شامبو', 'غسول', 'محلول', 'صابون', 'معجون',
    'شاور', 'استحلاب', 'وريدي', 'عضل', 'فوم', 'سولوستار', 'فليكس', 'قلم',
    'مجم', 'مج', 'mg', 'جم', 'جرام', 'g', 'gm', 'مكجم', 'mcg', 'مل', 'ملل', 'ml', 'ج', 'س'
]

ARABIC_TO_ENGLISH_BRANDS = {
    'ماي كري': 'mami care',
    'مامي كير': 'mami care',
    'جليمباكري': 'glimpacare',
    'جليمباكير': 'glimpacare',
    'بيلاسنيجيك': 'bilastigic',
    'بيلاستيجيك': 'bilastigic',
    'بيتالليرج': 'betalerg',
    'بيتاليرج': 'betalerg',
    'مو روكسنوريك': 'miroxenuric',
    'موروكسنوريك': 'miroxenuric',
    'ميروكسنوريك': 'miroxenuric',
    'ادويفالم': 'adwiflam',
    'ادويفلام': 'adwiflam',
    'فو روديب': 'ferrodeep',
    'فوروديب': 'ferrodeep',
    'فيروديب': 'ferrodeep',
    'تيراميسن': 'terramycin',
    'تيراميسين': 'terramycin',
    'يونيلوكسام': 'uniloxam',
    'سيكوبرام': 'secopram',
    'زيثرودوز': 'zithrodose',
    'زيثرو دوز': 'zithrodose',
    'ليناتراج': 'linatrag',
    'لينا تراج': 'linatrag',
    'دورميفال': 'dormival',
    'دور ميفال': 'dormival',
    'بريفاكوند': 'prevabond',
    'بريفا كوند': 'prevabond',
    'السيكس': 'lasix',
    'الكتيز': 'lactase',
    'لاكتيز': 'lactase',
    'الكتيفينور': 'lactiferon',
    'لاكتيفينور': 'lactiferon',
    'لوالويست': 'lola west',
    'تسيولاول': 'lola west',
    'لولاويست': 'lola west',
    'التراكايين': 'ultracaine',
    'ارومالوك': 'aromaloc',
    'ديبروساليك': 'diprosalic',
    'سبازموبيرالجين': 'spasmopyralgin',
    'جينتازون': 'gentazone',
    'اليكا ام': 'elica m',
    'وصايا': 'wasaya',
    'اورلي': 'orly',
    'اورلى': 'orly',
    'اورليسمارت': 'orlysmart',
    'اورليستات': 'orlistat',
    'سنترافيتا': 'centravita',
    'نازوفلوتين': 'nasoflutin',
    'كويك سلم': 'quick slim',
    'فاستاريل': 'vastarel',
    'ابيماج': 'epimag',
    'باروفين': 'parophen',
    'بانادول': 'panadol',
    'بنادول': 'panadol',
    'اوجمنتين': 'augmentin',
    'اوجمانتين': 'augmentin',
    'كتافلام': 'cataflam',
    'كتاافلم': 'cataflam',
    'كونكور': 'concor',
    'بروفين': 'brufen',
    'فلاجيل': 'flagyl',
    'نيكسيوم': 'nexium',
    'فولتارين': 'voltaren',
    'انتينال': 'antinal',
    'اماريل': 'amaryl',
    'كاربامازيبين': 'carbamazepine',
    'كابوتن': 'capoten',
    'سيبرازول': 'ciprazole',
    'سبرالكس': 'cipralex',
    'اتور': 'ator',
    'كريستور': 'crestor',
    'جلوكوفاج': 'glucophage',
    'كوزار': 'cozaar',
    'زانتاك': 'zantac',
    'لانتوس': 'lantus',
    'كلارينيز': 'clarinase',
    'تلفاست': 'telfast',
    'زيرتك': 'zyrtec',
    'اوترفين': 'otrivin',
    'موبيك': 'mobic',
    'سيردالود': 'sirdalud',
    'كولونا': 'colona',
    'دوفاستون': 'duphaston',
    'سيلدينافيل': 'sildenafil',
    'سياليس': 'cialis',
    'فياجرا': 'viagra',
    'ليبيتور': 'lipitor',
    'بلافيكس': 'plavix',
    'دافلون': 'daflon',
    'دورميكوم': 'dormicum',
    'لاسيكس': 'lasix',
    'داونيل': 'daonil',
    'داياميكرون': 'diamicron',
    'جانوفيا': 'januvia',
    'جالفوس': 'galvus',
    'فورسيجا': 'forxiga',
    'جاردينس': 'jardiance',
    'سوبرافيت': 'supravit',
    'كيروفيت': 'kerovit',
    'بيتادين': 'betadine',
    'ميبو': 'mebo',
    'كتافاست': 'catafast',
    'سيبتازول': 'septazole',
    'كلافيموكس': 'klavimox',
    'هاي بيوتك': 'hibiotic',
    'هايبيوتك': 'hibiotic',
    'كيورام': 'curam',
    'ميجا موكس': 'megamox',
    'ميجاموكس': 'megamox',
    'زيثروماكس': 'zithromax',
    'زيثرون': 'zithron',
    'ازيثروسين': 'azithrocin',
    'سيبروفلوكساسين': 'ciprofloxacin',
    'سيبروفار': 'ciprofar',
    'سيبروسين': 'ciprocin',
    'تارجوسيد': 'targocid',
    'يوناسين': 'unasyn',
    'افيل': 'avil',
    'اتينولول': 'atenolol',
    'بلوكيم': 'blokium',
    'كابوزيد': 'capozide',
    'كاردورا': 'cardura',
    'ديلتيازم': 'diltiazem',
    'الداكتون': 'aldactone',
    'اندرال': 'inderal',
    'موديوريتيك': 'moduretic',
    'نورفاسك': 'norvasc',
    'تنورمين': 'tenormin',
    'تريتاس': 'tritace',
    'موتيفال': 'motival',
    'نيوروتون': 'neuroton',
    'نيوروبيون': 'neurobion',
    'ميلجا': 'milga',
    'ثيروجلوبين': 'thyroglobulin',
    'التروكسين': 'eltroxin',
    'يوريفين': 'urivin',
    'راني': 'rani',
    'جاست ريج': 'gastreg',
    'ديجستين': 'digestin',
    'سبازموفري': 'spasmofree',
    'سبازمو فري': 'spasmofree',
    'سبازمو ديجستين': 'spasmodigestin',
    'سبازموديجستين': 'spasmodigestin',
    'سبازمودايجستين': 'spasmodigestin',
    'سبازمو دايجستين': 'spasmodigestin',
    'سبازموكيور': 'spasmocure',
    'سبازمو كيور': 'spasmocure',
    'سبازموبيرالجين': 'spasmopyralgin',
    'سبازمو بيرالجين': 'spasmopyralgin',
    'سبازموبي رالجين': 'spasmopyralgin',
    'سبازموفين': 'spasmofen',
    'سبازمو فين': 'spasmofen',
    'سيتالو': 'citalo',
    'سيتالوبرام': 'citalopram',
    'اسيتالوبرام': 'escitalopram',
    'كولشيسين': 'colchicine',
    'ايفورين': 'evorine',
    'افوريند': 'evorind',
    'درافوكال': 'drafocal',
    'اوستيوكير': 'osteocare',
    'ماء غريب': 'gripe water',
    'ابيزيثرو': 'epizithro',
    'افالوكس': 'avelox',
    'ايموكسكلاف': 'emoxclav',
    'ماجناسيف': 'magnacef',
    'زينات': 'zinnat',
    'سيفوتاكس': 'cefotax',
    'سيفترين': 'ceftriaxone',
    'سيفترياكسون': 'ceftriaxone',
    'كلافوران': 'claforan',
    'يونيكتام': 'unictam',
    'دالاسين': 'dalacin',
    'كلاسيد': 'klacid',
    'سيفازون': 'cefazone',
    'سيفاكسون': 'cefaxone',
    'سيفيبم': 'cefepime',
    'سيفيكسيم': 'cefixime',
    'سيكلور': 'ceclor',
    'ماكسيبيم': 'maxipime',
    'افروزوليد': 'averozolid',
    'لينزوليد': 'linezolid',
    'نيوزوليد': 'newzolid',
    'فوكسازوليدين': 'foxazolidine',
    'تاريفيد': 'tarivid',
    'تاريفان': 'tarifun',
    'تافانيك': 'tavanic',
    'موكساسين': 'moxacin',
    'ليفوفلوكساسين': 'levofloxacin',
    'ليفانيك': 'levanic',
    'ليفوتافين': 'levotavin',
    'ليفوفيروز': 'levoferoz',
    'ازجوفلوكس': 'azgoflox',
    'فلوكسيبسي': 'floxepci',
    'فاتروكسيم': 'vatroxim',
    'فلافيسيف': 'flavicef',
    'سالبين': 'sulbin',
    'بكتيكلور': 'bactichlor',
    'ديوراسيف': 'duricef',
    'ابيدروكسيل': 'ibidroxil',
    'راميسفتراكس': 'ramiceftrax',
    'زوراكسون': 'zoraxon',
    'ميراج': 'merag',
    'تريكسوتاز': 'trixotaz',
    'تريامريكان': 'triamecan',
    'جاستروبيوتك': 'gastrobiotic',
    'اواديست': 'awadist',
    'اوجرام': 'augram',
    'كلينداسول': 'clindasol',
    'كليندا فيرت': 'clindavert',
    'جاراميسين': 'garamycin',
    'زوفيراكس': 'zovirax',
    'اسيكلوفير': 'acyclovir',
    'فالتريكس': 'valtrex',
    'اتراكون': 'itracon',
    'اترانوكس': 'itranox',
    'ديفلوكان': 'diflucan',
    'فلوكورال': 'flucoral',
    'فانجيكان': 'fungican',
    'دكتاكورت': 'daktacort',
    'دكتارين': 'daktarin',
    'ميكوناز': 'miconaz',
    'ترافوديرمال': 'travodermal',
    'ديرموفكس': 'dermofix',
    'جينوزول': 'gynozol',
    'جينوكونازول': 'gynoconazol',
    'كانديكيور': 'candicure',
    'لاميفين': 'lamifen',
    'لاميزيل': 'lamisil',
    'ويلوفنج': 'welofung',
    'تيربينافين': 'terbinafine',
    'امريزول': 'amrizole',
    'دياكس': 'diax',
    'بارازوكسانيد': 'parazoxanide',
    'نيتازود': 'nitazode',
    'نانازوكسيد': 'nanazoxid',
    'سيكيندازول': 'secnidazole',
    'اورنيداز': 'ornidaz',
    'بنداكس': 'bendax',
    'فيرميزول': 'vermizole',
    'اسبرين بروتكت': 'aspirin protect',
    'اسبروتكت': 'asprotect',
    'اسبوسيد': 'aspocid',
    'جوسبرين': 'jusprin',
    'ايزاكارد': 'ezacard',
    'ابيمول': 'abimol',
    'بارامول': 'paramol',
    'سيتال': 'cetal',
    'بيرال': 'pyral',
    'ادول': 'adol',
    'دوليبران': 'doliprane',
    'نوفالدول': 'novaldol',
    'نوفالجين': 'novalgin',
    'تمبرا': 'tempra',
    'روتابيرتك': 'rotapirtec',
    'اولفن': 'olfen',
    'ديكلوفين': 'diclofen',
    'ديكلوبرو': 'diclopro',
    'دولفين': 'dolphin',
    'ادويفلام': 'adwiflam',
    'ابيفيناك': 'epifenac',
    'فيلدين': 'felden',
    'فلدين': 'felden',
    'كيتوفان': 'ketofan',
    'باي كيتوفان': 'bi-ketofan',
    'كيتولاك': 'ketolac',
    'كيتوبريك': 'ketoprek',
    'كيتاديل': 'ketadyl',
    'كيتوريلين': 'ketorilin',
    'انتي كوكس': 'anticox',
    'سيليبركس': 'celebrex',
    'سيلكوكس': 'celebrex',
    'اركوكسيا': 'arcoxia',
    'توريكوكس': 'toracoxib',
    'بريستافلام': 'bristaflam',
    'روكسيكام': 'roxicam',
    'لورنوكسيكام': 'lornoxicam',
    'ديسبركام': 'dispercam',
    'فليكتور': 'flector',
    'ميديكسافلام': 'medixaflam',
    'سولبادول': 'solpadol',
    'فلوتاك': 'flotac',
    'فلوادجست': 'fluadjust',
    'فلاموكونسلت': 'flamoconsult',
    'انسيلاكوكس': 'ancilacox',
    'فيوتاكوكسيب': 'viotacoxib',
    'كوكسينورين': 'coxinurin',
    'كولشيسين': 'colchicine',
    'جاوتيفيد': 'goutifid',
    'نويوريك': 'no-uric',
    'زيماكس': 'zimax',
    'ابيكوتيل': 'epicutil',
    'كونجستال': 'congestal',
    'كونجيستال': 'congestal',
    'كولد فري': 'cold free',
    'فلورست': 'flurest',
    'كومتركس': 'comtrex',
    'وان تو ثري': '123',
    'باوركابس': 'powercaps',
    'ترايمدفلو': 'trimedflu',
    'بنتاكولد': 'pentacold',
    'انتي فلو': 'anti-flu',
    'فنتولين': 'ventolin',
    'فاركولين': 'farcolin',
    'اتروفنت': 'atrovent',
    'بيرودوال': 'berodual',
    'كومبيفنت': 'combivent',
    'سبيريفا': 'spiriva',
    'سمبيكورت': 'symbicort',
    'سيريتيد': 'seretide',
    'فوستر': 'foster',
    'بالميكورت': 'pulmicort',
    'بالموكورت': 'pulmicort',
    'فليكسوتيد': 'flixotide',
    'فنتال': 'fental',
    'فوراديل': 'foradil',
    'متروهيلر': 'metrohaler',
    'فياسالمول': 'viasalmol',
    'برونكولين': 'broncholin',
    'بامبيديل': 'bambedil',
    'اوتريفين': 'otrivin',
    'نازوكورت': 'nasacort',
    'نازونكس': 'nasonex',
    'فليكسونيز': 'flixonase',
    'افاميس': 'avamys',
    'نازوبيكترا': 'nasopectra',
    'نازوستوب': 'nasostop',
    'نودي': 'nodi',
    'بوليمير': 'polymere',
    'اسيتيل سيستايين': 'acetylcysteine',
    'اسيتايل سستايين': 'acetylcysteine',
    'اسيتيل سستايين': 'acetylcysteine',
    'ميكوسولفان': 'mucosolvan',
    'بيسلفون': 'bisolvon',
    'برونكوبرو': 'bronchopro',
    'التراسولف': 'ultrasolv',
    'برونشيكم': 'bronchicum',
    'توسيفان': 'tussivan',
    'توسكان': 'tusskan',
    'رينوتوس': 'rhinotuss',
    'رينوبرو': 'rhinopro',
    'رينومول': 'rhinomol',
    'جواياديسكا': 'guayadisca',
    'سيدابرونت': 'sedapront',
    'سيستابرونت': 'sedapront',
    'سينوبريت': 'sinupret',
    'ايفي هيرب': 'ivy herb',
    'بروسبان': 'prospan',
    'كافينتول': 'caffentol',
    'فلوب': 'flop',
    'ميوكوتك': 'mucotec',
    'ميوكتا': 'mucta',
    'ستيمولان': 'stimulan',
    'كلاريتين': 'claritine',
    'ايريوس': 'aerius',
    'ديسلوراتادين': 'desloratadine',
    'ليفوستات': 'levostat',
    'هيستازين': 'histazine',
    'الليرجيل': 'allergyl',
    'اليرجوليبر': 'allergoliber',
    'اليرزون': 'allerzone',
    'اليفو': 'alevo',
    'زالتيك': 'zaltec',
    'فنستيل': 'fenistil',
    'لورين': 'lorine',
    'لوراز': 'loraz',
    'ازيلاست': 'azelast',
    'كوكاست': 'kocast',
    'ايروفاست': 'aerofast',
    'مونتيلوراما': 'montelorama',
    'سينجولير': 'singulair',
    'كنترولوك': 'controloc',
    'كونترولوك': 'controloc',
    'بانتازول': 'pantazol',
    'زوركال': 'zurcal',
    'بروتولوك': 'protoloc',
    'بانتروجلوب': 'pantroglobe',
    'داونوبرازول': 'downoprazole',
    'دوكسيرازول': 'doxirazole',
    'بيورازو': 'purazo',
    'نيكسكيور': 'nexicure',
    'تريتوالس': 'tritouls',
    'انتودين': 'antodine',
    'فاموتاك': 'famotac',
    'فاموتيفلكس': 'famotiflex',
    'موتيليوم': 'motilium',
    'جاستروموتيل': 'gastromotil',
    'فاركوتيليام': 'farcotilium',
    'موتيل فاست': 'motil fast',
    'جاناتون': 'ganaton',
    'ايتوبرايد': 'itopride',
    'موسابرايد': 'mosapride',
    'دوسباتالين': 'duspatalin',
    'كولوفيرين': 'coloverin',
    'كولوسبازمين': 'colospasmin',
    'سبازموفين': 'spasmofen',
    'سباسكولون': 'spascolon',
    'بوسكوبان': 'buscopan',
    'فيسرالجين': 'visceralgine',
    'ترايتون': 'tritone',
    'جاستروليف': 'gastroliv',
    'ميكوجيل': 'mucogel',
    'مالوكس': 'maalox',
    'ريوبانوكس': 'riopanox',
    'جليكودال': 'glycodal',
    'اورسوفالك': 'ursofalk',
    'اورسوجال': 'ursogall',
    'هيباميرز': 'hepamerc',
    'هيبامارين': 'hepamarine',
    'سيلين': 'silymarin',
    'ليفاجول': 'livagol',
    'ليفانوكس': 'levanox',
    'رواكول': 'rowachol',
    'رواتينكس': 'rowatinex',
    'يورينكس': 'urinex',
    'بروكسيمول': 'proximol',
    'يوريكول': 'uricol',
    'يوروكنترول': 'eurocontrol',
    'باولوكير': 'paulocare',
    'بيكولاكس': 'picolax',
    'مينالاكس': 'menalax',
    'ايجيكوستات': 'egycostat',
    'لاكسيول': 'laxiol',
    'موفيكول': 'movicol',
    'لاكتيول': 'lacteol',
    'لاكتوماكس': 'lactomax',
    'انتروجيرمينا': 'enterogermina',
    'اتموسالازين': 'atmosalazine',
    'كولوسلازين': 'colosalazine',
    'سلازوبيرين': 'salazopyrin',
    'بنتازا': 'pentasa',
    'كوليك اوف': 'colic off',
    'سانسو بيبى': 'sanso baby',
    'سانسو بيبي': 'sanso baby',
    'ماء غريب': 'gripe water',
    'كالمابيبي': 'calmababy',
    'كالمينال': 'calminal',
    'كارمينكس': 'carminex',
    'كلكسان': 'clexane',
    'اينوهيب': 'innohep',
    'زاريلتو': 'xarelto',
    'ريفاروكسابان': 'rivaroxaban',
    'ريفاروسبير': 'rivarospire',
    'فاكساتو': 'vaxato',
    'اليكويس': 'eliquis',
    'اليمبوسيس': 'elimbosis',
    'براداكسا': 'pradaxa',
    'ماريفان': 'marevan',
    'وارفارين': 'warfarin',
    'اتاكاند': 'atacand',
    'كانديسارتان': 'candesartan',
    'اكسفورج': 'exforge',
    'سيلوكين': 'seloken',
    'نيبيليت': 'nebilet',
    'نيبليت': 'nebilet',
    'نيبيفولول': 'nebivolol',
    'بيسولوك': 'bisoloc',
    'بيتاكور': 'betacor',
    'تريبليكسام': 'triplixam',
    'كوفرسيل': 'coversyl',
    'ناتريلكس': 'natrilix',
    'الكابرس': 'alcapress',
    'بلينديل': 'plendil',
    'بلوكاديبين': 'blocadipine',
    'بليتال': 'pletal',
    'تارغ': 'tareg',
    'دايسارتان': 'diysartan',
    'فالساتينس': 'valsatens',
    'شارتوريج': 'chartoreg',
    'افيروثيازيد': 'averothiazide',
    'لوزازيد': 'losazide',
    'جيوكاند': 'geocand',
    'البيوستكس': 'albiostix',
    'براديبيكت': 'bradipect',
    'كوراسور': 'corasore',
    'تورسامولكس': 'torsamolex',
    'دايسينون': 'dicynone',
    'كابرون': 'capron',
    'هيموستوب': 'hemostop',
    'فليبوتون': 'phlebotone',
    'فليبوفينال': 'phlebofenal',
    'ريباريل': 'reparil',
    'الفينترن': 'alphintern',
    'امبيزيم': 'ambezym',
    'الفا اميلاز': 'alpha amylase',
    'الفاثرومب': 'alphathromb',
    'روزوكوليست': 'rosucolist',
    'نوفيستوريك': 'novestoric',
    'كوليروز': 'cholerose',
    'كولوناك': 'colonac',
    'ليبانتيل': 'lipanthyl',
    'ليبتروجين': 'liptrogen',
    'ليبوكومب': 'lipocomb',
    'ليبونا': 'lipona',
    'ريفافلوفا': 'rivaflova',
    'اتورفارم': 'atorpharm',
    'جانيوميت': 'janumet',
    'جانوميت': 'janumet',
    'تراجينتا': 'trajenta',
    'جينتادوتو': 'jentadueto',
    'امباكوزا': 'empacoza',
    'ايمباكوزا': 'empacoza',
    'سينجاردي': 'synjardy',
    'زيجدو': 'xigduo',
    'ديافانس': 'diavance',
    'ديبافالي': 'depavali',
    'جليبوفين': 'glybophen',
    'جليمباكير': 'glimpacare',
    'جليماكس': 'glimax',
    'جلوكوليبتين': 'glucoliptin',
    'جلوكان': 'glucan',
    'شوجارلو': 'sugarlo',
    'سيدوفاج': 'cidophage',
    'ميتفورمين': 'metformin',
    'اماجلوست': 'amaglost',
    'دولسيل': 'dulcil',
    'بريفاجليب': 'brivaglipt',
    'ليناتراج': 'linatrag',
    'ليناجينتا': 'linagenta',
    'فيوتافيلديكس': 'viotavildix',
    'زانوجليد': 'zanoglide',
    'اكترابد': 'actrapid',
    'ميكستارد': 'mixtard',
    'هومالوج': 'humalog',
    'تويجيو': 'toujeo',
    'تريسبا': 'tresiba',
    'ابيدرا': 'apidra',
    'فيكتوزا': 'victoza',
    'اوزمبيك': 'ozempic',
    'يوثيروكس': 'euthyrox',
    'ثيروكاربين': 'thyrocarpine',
    'كاربيمازول': 'carbimazole',
    'اندوسيد': 'indocid',
    'سبرام': 'cipram',
    'استيكان': 'estikan',
    'اسيتابرام': 'ecitalopram',
    'سيرباس': 'serpass',
    'سيرليفت': 'serlift',
    'لوسترال': 'lustral',
    'زولفت': 'zoloft',
    'بروزاك': 'prozac',
    'فلوزاك': 'fluzac',
    'سيروكسات': 'seroxat',
    'فافيرين': 'faverin',
    'سيمباتكس': 'symbatex',
    'سيمبالتا': 'cymbalta',
    'افيكسور': 'effexor',
    'فالدوكسان': 'valdoxan',
    'تريتيكو': 'trittico',
    'ريميرون': 'remeron',
    'انافرانيل': 'anafranil',
    'لانتانون': 'lantanon',
    'تجريتول': 'tegretol',
    'ديباكين': 'depakine',
    'لاميكتال': 'lamictal',
    'لاموترين': 'lamotrene',
    'كيبرا': 'keppra',
    'ترايلبتال': 'trileptal',
    'جابتن': 'gaptin',
    'كونفنتين': 'conventin',
    'نيورونتين': 'neurontin',
    'ليريكا': 'lyrica',
    'ليرولين': 'lyrolin',
    'بريجابالين': 'pregabalin',
    'اندوبنتين': 'endopentin',
    'جراليبنتين': 'gralipentin',
    'ريفوتريل': 'rivotril',
    'ليكسوتانيل': 'lexotanil',
    'زاناكس': 'xanax',
    'كالمابام': 'calmepam',
    'سيروكويل': 'seroquel',
    'كويتابكس': 'quitapex',
    'كويتابين': 'quetiapine',
    'زيبركسا': 'zyprexa',
    'اولانزابين': 'olanzapine',
    'ريسبردال': 'risperdal',
    'ريسبي ديب': 'respidip',
    'ابليفاي': 'abilify',
    'دوجماتيل': 'dogmatil',
    'هالوبريدول': 'haloperidol',
    'هالونيز': 'halonez',
    'اميبريد': 'amipride',
    'سيكوبرام': 'secopram',
    'سيكوسيتام': 'secocetam',
    'ارموداكيور': 'armodacure',
    'ارموويك': 'armowake',
    'نايت كالم': 'night calm',
    'دونازيل': 'donazil',
    'اريسبت': 'aricept',
    'اكسيلون': 'exelon',
    'ميميكسا': 'memixa',
    'ميمكسا': 'memixa',
    'ايبيكسا': 'ebixa',
    'نوتروبيل': 'nootropil',
    'كافينتون': 'cavinton',
    'سيرفيتام': 'cervitam',
    'ستوجيرون': 'stugeron',
    'سيناريزين': 'cinnarizine',
    'بيتاسيرك': 'betaserc',
    'بيتاهستين': 'betahistine',
    'تريفستال': 'trivastal',
    'سينمت': 'sinemet',
    'سيريبروليسن': 'cerebrolysin',
    'برين اوكس': 'brain ox',
    'تيبوفورتين': 'tebofortin',
    'ستاركوبينا': 'startcopina',
    'كونفاجران': 'confagran',
    'كونتروليبسي': 'controlepsy',
    'سوبرانيل': 'supranil',
    'بوسبار': 'buspar',
    'ميودريل': 'myodril',
    'ميوفين': 'myofen',
    'ميولجين': 'myolgin',
    'ميوريلاكس': 'myorelax',
    'ميثوريلاكس': 'methorelax',
    'ديمرا': 'dimra',
    'ريلاكس': 'relax',
    'ريلاكومب': 'relacomb',
    'برينو ريلاكس': 'preno relax',
    'اتوموريلاكس': 'atomorelax',
    'نورجيسك': 'norgesic',
    'نيرهافلكس': 'nerhaflex',
    'ديب فريز': 'deep freeze',
    'الجيزال': 'algisal',
    'الجازال': 'algisal',
    'بنتافليكس': 'pentaflex',
    'فليكسال': 'flexal',
    'سايبريك': 'cybrex',
    'هاي كول': 'high cool',
    'موڤ': 'moov',
    'موف': 'moov',
    'راديساج': 'radisage',
    'هيموكلار': 'hemoclar',
    'اكستروما': 'extroma',
    'بانثينول': 'panthenol',
    'ريتشي بانثينول': 'richy panthenol',
    'هيبتا بانثينول': 'hepta panthenol',
    'هيبتا ماكس بانثينول': 'hepta max panthenol',
    'بانثينول يوريتشي': 'panthenol urichy',
    'ين يي سفن بانثينول': 'np7 panthenol',
    'ين يي سفن': 'np7',
    'ماكرو بانثينول': 'macro panthenol',
    'بيبانثين': 'bepanthen',
    'درموفيت': 'dermovate',
    'ديرموفيت': 'dermovate',
    'بتاديرم': 'betaderm',
    'بيتابرونيت': 'betapronate',
    'تراي بيتابرونات': 'tri-betapronate',
    'ديكساميثازون': 'dexamethasone',
    'هيدروكورتيزون': 'hydrocortisone',
    'كيناكومب': 'kenacomb',
    'كوادريدرم': 'quadriderm',
    'مكسيدرم': 'mixderm',
    'اليكا': 'elica',
    'اليكاام': 'elica m',
    'بورجازون': 'borgasone',
    'توبيسونايد': 'tobisonide',
    'كيوتيفيت': 'cutivate',
    'تريتوسبوت': 'tritospot',
    'ترايملازما': 'trimelasma',
    'بلانكا': 'blanca',
    'ماربالين': 'marpalene',
    'ادابالين': 'adapalene',
    'ادا': 'ada',
    'مارفيل': 'marvel',
    'اكني اكت': 'acne act',
    'اكني ستوب': 'acne stop',
    'سكينورين': 'skinoren',
    'نت لوك': 'netlook',
    'ايزوتريتينوين': 'isotretinoin',
    'سيبانوين': 'sebanoin',
    'فيوسيدين': 'fucidin',
    'فيوسيكورت': 'fucicort',
    'فيوسيدرم': 'fuciderm',
    'فيوسيدل': 'fucidel',
    'اموكومب': 'amocomb',
    'سكنترا': 'skintra',
    'سيلفر بيرن': 'silver burn',
    'ديرمازين': 'dermazin',
    'بوباي': 'bobai',
    'صن توب': 'suntop',
    'ستارفيل': 'starville',
    'سينوبار': 'synobar',
    'مون فيس': 'moon face',
    'ستوبلي': 'stopli',
    'توليفلي': 'tolifly',
    'كابيلو': 'capello',
    'هيرباك': 'hairback',
    'مينوكسيديل': 'minoxidil',
    'اليجون': 'alijon',
    'سيروبيب': 'seropep',
    'ليسيد': 'licid',
    'ايفرزين': 'iverzine',
    'مويست': 'moist',
    'سولو': 'solo',
    'ستيرالاين': 'steraline',
    'هيالو فور سكين': 'hyalo 4 skin',
    'هيالو فور كونترول': 'hyalo 4 control',
    'كيرباي كير': 'carebycare',
    'سنسوديرم': 'sensoderm',
    'وايت شادو': 'white shadow',
    'كلوسول': 'closol',
    'بيدرو': 'pedro',
    'لجنوكايين': 'lignocaine',
    'مانوفيبركين': 'manoviprcaine',
    'بريلوكايين': 'prilocaine',
    'بيدالكين': 'pedalkine',
    'رونكس': 'ronex',
    'كيه ال واي': 'kly',
    'ميلجا ماكس': 'milga max',
    'بي كوم': 'b com',
    'باور بي': 'power b',
    'ديبوفيت': 'depovit',
    'ليفابيون': 'livabion',
    'بيسويفت': 'biswift',
    'بيوتين فورت': 'biotin forte',
    'ال كارنتين': 'l-carnitine',
    'كارنيتول': 'carnitol',
    'كارنيفيتا': 'carnivita',
    'دافاليندي': 'davalindi',
    'ديفارول': 'devarol',
    'فيدروب': 'vidrop',
    'دي ثري': 'vitamin d3',
    'فيتا دي': 'vita d',
    'ليبوزوم دي': 'liposomal d',
    'كوليكالسيتال': 'cholecalciferol',
    'بون كير': 'bone care',
    'بونوفورت': 'bonoforte',
    'الفابونيد': 'alphabonid',
    'كالسي ديب': 'calci dep',
    'اوستيوكير': 'osteocare',
    'كالترات': 'caltrate',
    'كالسيترون': 'calcitron',
    'سانسوفيت': 'sansovit',
    'سي اتش الفا': 'ch-alpha',
    'جوينت جارد': 'joint guard',
    'جانوجوينت': 'ganojoint',
    'زادو جوينت': 'zado joint',
    'دورفين': 'dorfen',
    'فرافيرو': 'phrafero',
    'فيروترون': 'ferrotron',
    'فيراميكس': 'ferramix',
    'فيروديب': 'ferrodep',
    'فيروديونال': 'ferrodional',
    'هيموجيت': 'haemojet',
    'امبوفير': 'ampover',
    'سكروفير': 'sacrofer',
    'ايرون ليبوزومال': 'liposomal iron',
    'فوليك اسيد': 'folic acid',
    'زنكترون': 'zinctron',
    'زنك اوريجين': 'zinc origin',
    'اوكتافارون': 'octavaron',
    'اميونو فار': 'immuno pharm',
    'سانسو سي': 'sanso c',
    'سانسو بي': 'sanso b',
    'سي ريتارد': 'c-retard',
    'فيتاسترس': 'vitastress',
    'فيتارون': 'vitaron',
    'فيتونكس': 'vitonex',
    'يونايتد فيت': 'united vit',
    'بريجناكير': 'pregnacare',
    'بروفيت': 'provit',
    'بروكير': 'procair',
    'اوميجا في': 'omega v',
    'اوميجال': 'omegal',
    'يوميجا': 'u-mega',
    'ايفاليكس': 'efalex',
    'برايم روز': 'prime rose',
    'رويال كير': 'royal care',
    'رويال ريجيم': 'royal regime',
    'توب جنج': 'top ging',
    'ليمتلس اوستيودانس': 'limitless osteodance',
    'ليمتلس استيودانس': 'limitless osteodance',
    'ليمتلس اوستيو دانس': 'limitless osteodance',
    'ليمتلس استيو دانس': 'limitless osteodance',
    'ليمتلس كروماكس': 'limitless chromax',
    'ليمتلس كروماكس كت': 'limitless chromax',
    'ليمتلس اوميجا': 'limitless omega',
    'ليمتلس اوميجا 3': 'limitless omega',
    'ليمتلس ماغنسيوم': 'limitless magnesium',
    'ليمتلس ماجنسيوم': 'limitless magnesium',
    'ليمتلس مغنسيوم': 'limitless magnesium',
    'ليمتلس زنك': 'limitless zinc',
    'ليمتلس زينك': 'limitless zinc',
    'ليمتلس كركمين': 'limitless turmeric',
    'ليمتلس بيبي د': 'limitless baby d',
    'ليمتلس ليبوفيركس': 'limitless lipoferix',
    'ليمتلس بي كومبلكس': 'limitless b-complex',
    'ليمتلس جلوتا': 'limitless gluta',
    'ليمتلس مان': 'limitless man',
    'ليمتلس ومان': 'limitless woman',
    'ليمتلس كو انزيم': 'limitless co-enzyme',
    'ليمتلس لاكتوفرين': 'limitless lactoferrin',
    'ليمتلس ناتشورالز': 'limitless naturals',
    'ليمتلس فورتي': 'limitless forte',
    'اوستيودانس': 'osteodance',
    'استيودانس': 'osteodance',
    'اوستيو دانس': 'osteodance',
    'استيو دانس': 'osteodance',
    'كروماكس': 'chromax',
    'كروماكس كت': 'chromax',
    'ليمتلس': 'limitless',
    'سيديرال': 'sideral',
    'اينوكال': 'enocal',
    'ايجي ترون': 'egytron',
    'فورتيفيروم': 'fortiferrum',
    'لبن ابتاميل': 'aptamil',
    'ابتاميل': 'aptamil',
    'لبن بيبيلاك': 'bebelac',
    'بيبيلاك': 'bebelac',
    'لبن نان': 'nan',
    'نان': 'nan',
    'لبن هيرو بيبي': 'hero baby',
    'هيرو بيبي': 'hero baby',
    'هيرو نوتراسينس': 'hero nutrasense',
    'هيرو نيوتري سينس': 'hero nutrasense',
    'نوتراسينس': 'hero nutrasense',
    'نيوتري سينس': 'hero nutrasense',
    'هيرو نوتراديفنس': 'hero nutradefense',
    'نوتراديفنس': 'hero nutradefense',
    'بروجرس جولد': 'progress gold',
    'بروميل جولد': 'promil gold',
    'اس ام ايه جولد': 'sma gold',
    'لبن اس 26': 's-26',
    'اس 26': 's-26',
    'لبن سيميلاك': 'similac',
    'سيميلاك': 'similac',
    'لبن بيوميل': 'biomil',
    'بيوميل': 'biomil',
    'لبن بيديا ستارت': 'pediastart',
    'بيديا ستارت': 'pediastart',
    'لبن بيدياميل': 'pediamil',
    'بيدياميل': 'pediamil',
    'لبن نيدو': 'nido',
    'نيدو': 'nido',
    'سيريلاك': 'cerelac',
    'بليميل': 'blemil',
    'بريماليك': 'primalac',
    'اريك': 'erec',
    'باوريكتا': 'powerecta',
    'سيلدافا': 'sildava',
    'فيافاج': 'viavag',
    'اريكتاماكس': 'erectamax',
    'فايركتا': 'virecta',
    'رومانتيجرا': 'romantigra',
    'ديسباتيجرا': 'dispatigra',
    'نيرهاسيلدا': 'nerhasilda',
    'فاروفيجا': 'faroviga',
    'انداجرا': 'andagra',
    'سيالونج': 'tadalong',
    'تادالونج': 'tadalong',
    'تاداليسبي': 'tadalasp',
    'تادانيرفي': 'tadanerfi',
    'سنافى': 'snafi',
    'سنافي': 'snafi',
    'ديامونريكتا': 'diamonrecta',
    'فاردينوريكت': 'vardinorect',
    'فاردينوديب': 'vardinodep',
    'ريكتلونج': 'rectalong',
    'تامسولين': 'tamsulin',
    'اومنيك': 'omnic',
    'ديودارت': 'duodart',
    'افودارت': 'avodart',
    'بروسكار': 'proscar',
    'بروستاكيور': 'prostacure',
    'بروستانورم': 'prostanorm',
    'جيو بروست': 'geo prost',
    'دابوكستارد': 'dapoxitard',
    'دابوكستين': 'dapoxetine',
    'سيرازيت': 'cerazette',
    'سيكلوبروجينوفا': 'cycloprogynova',
    'نورجيستادول': 'norgestadol',
    'نوريجنسين': 'norigynon',
    'ميزوسيبت': 'mizosept',
    'بريمولوت': 'primolut',
    'كلوميد': 'clomid',
    'فيمارا': 'femara',
    'نولفادكس': 'nolvadex',
    'اوفيوتروز': 'oviotroz',
    'اوفيونهيبيتا': 'ovionhibita',
    'فيمابينت': 'femapent',
    'لينتوجيستون': 'lentogest',
    'اوكيوميثيل': 'ocumethyl',
    'اوكيوفنيكول': 'ocufenicol',
    'اوكيوسيليرج': 'ocucellerg',
    'اولوهيستين': 'olohistin',
    'تافلوبرو': 'taflopro',
    'تيرز جارد': 'tears guard',
    'سيستان': 'systane',
    'بوليفريش': 'polyfresh',
    'سولوفريش': 'solofresh',
    'هاي فريش': 'hyfresh',
    'ارتيلاك': 'artelac',
    'اوبتك سالين': 'optic saline',
    'اوبتي فري': 'opti-free',
    'توبراكس': 'tobrex',
    'توبرادكس': 'tobradex',
    'ديكساتوبرين': 'dexatobrin',
    'فيجاموكس': 'vigamox',
    'موكسيسيارو': 'moxiciaro',
    'مونودكسين': 'monodoxin',
    'سيانارو': 'cyanaro',
    'كونجي كلير': 'congi-clear',
    'زولامول': 'zolamol',
    'ازارجا': 'azarga',
    'بريموندين': 'brimonidine',
    'بريميليرجي': 'primellergy',
    'بينوكس': 'benox',
    'لوتيرانول': 'lotiranol',
    'نيوبول': 'neopol',
    'جانفير': 'ganvir',
    'اوتيكس': 'otex',
    'ريموواكس': 'remowax',
    'فيوتك': 'viotic',
    'اورامكس': 'oramax',
    'بي بي سي': 'bbc',
    'استربسلز': 'strepsils',
    'برادوزين': 'pradozin',
    'ابينيفرين': 'epinephrine',
    'ادرينالين': 'adrenaline',
    'اترابكس': 'atrabex',
    'اتلا دي كي': 'atla dk',
    'اتينو': 'ateno',
    'ادرينوكورتين': 'adrenocortin',
    'اربيجي': 'rbg',
    'ازاثيوبرين': 'azathioprine',
    'ازانيا': 'azania',
    'افاندروكس': 'afandrox',
    'اكسبتو برو': 'excepto pro',
    'اكستريم': 'extreme',
    'اكسيبشن': 'exception',
    'الزيبيزل': 'alzepizil',
    'اميوتريكسات': 'ameotrexate',
    'انترستو': 'entresto',
    'اندوفيت': 'endovit',
    'انسولين ايجيبت': 'insulin egypt',
    'انكان دي': 'incan d',
    'انوفا': 'anova',
    'اوزد': 'ozed',
    'اوميكاربيكس': 'omecarpix',
    'اونسيد': 'onsid',
    'اي يست': 'e yeast',
    'ايبانتين': 'ibantine',
    'ايبياكتو': 'epiacto',
    'ايكاندرا': 'icandra',
    'اينوفاجار': 'enovagar',
    'باروفين': 'parofen',
    'بايولجام': 'biolgam',
    'بريدسول': 'predsol',
    'بريفا': 'briva',
    'بلاكونيل': 'plaquenil',
    'بوتاسيوم': 'potassium',
    'بيتافوس': 'betafos',
    'بيدرامين': 'pedramine',
    'بينجرايد': 'pingride',
    'ترانسو كسير': 'transocuir',
    'ترانسيديا': 'transidia',
    'تروزاكروم': 'trozacrom',
    'تريندو': 'trendo',
    'توب فلام': 'topflam',
    'تينورمين': 'tenormin',
    'جلينسيرت': 'glincert',
    'جلينوساليك': 'glynosalic',
    'جولدن فير': 'golden fer',
    'جيرما': 'germa',
    'جيوبوتا ك': 'geopota k',
    'جيوبوتا': 'geopota',
    'خميره اونست': 'honest yeast',
    'خميره': 'yeast',
    'دال دروب': 'dal drop',
    'دلزوسين': 'delzocine',
    'دورا': 'dora',
    'دوزين': 'dozin',
    'دوكسي بروكت': 'doxyproct',
    'ديسبرودرم': 'disproderm',
    'ديكابرينو': 'decapreno',
    'ديكساجلوب': 'dexaglobe',
    'ديكسافين': 'dexaphen',
    'ديمانكورتيل': 'demancortil',
    'راميكسول': 'ramixol',
    'راميلاكت': 'ramilact',
    'رانديل': 'randil',
    'ريبايون': 'rebaion',
    'ريستيبرو': 'restipro',
    'ريلاترولين': 'relatrolin',
    'زاكاجلون': 'zacaglon',
    'زانسيستوب': 'xancistop',
    'زوكوزيت': 'zocozet',
    'زولمسولان': 'zolmesolan',
    'زوندكس': 'zondex',
    'زيستريل': 'zestril',
    'زيموريند': 'zimorind',
    'سافيبليد': 'safibleed',
    'سانوبلكس': 'sanoplex',
    'سبلفكت': 'splefect',
    'سبيراز': 'spiraz',
    'سترونج فيل': 'strongville',
    'ستلاسيل': 'stelacil',
    'سكاي كيور': 'sky cure',
    'سوبراكس': 'suprax',
    'سوليوبريد': 'solupred',
    'سويز': 'swisse',
    'سي لايت': 'c-light',
    'سيالس': 'cialis',
    'سيبازول': 'septazole',
    'سيتافين': 'cetafen',
    'سيترونوميت': 'citronomit',
    'سيداميكس': 'cidamex',
    'سيرفيتولكا': 'cervitolca',
    'سيستون': 'cystone',
    'سيستينول': 'cystinol',
    'سينتروباكس': 'centropax',
    'سينوبريل': 'sinopril',
    'فاركوفيت': 'farcovit',
    'فاستر': 'faster',
    'فاسكون': 'vascon',
    'فاكتو': 'faktu',
    'فانج رير': 'fung rare',
    'فلازاكور': 'flazacor',
    'فلوتن': 'flutin',
    'فوار فروت': 'fruit eff',
    'فورتامايند': 'fortamind',
    'فورتير': 'fortair',
    'فورجيناب': 'forgenab',
    'في اند': 'v and',
    'فيتا بوينت': 'vitapoint',
    'فيرنيلار': 'vernelar',
    'فيفيدول': 'vividol',
    'فيلكسوفان': 'flexovan',
    'فيورازول': 'furazole',
    'فيوسيست': 'fucicyst',
    'قرفة بالجنزبيل': 'cinnamon ginger',
    'قرفه بالجنزبيل': 'cinnamon ginger',
    'كابوتريل': 'capotril',
    'كادي': 'cadi',
    'كارتي تون': 'cartitone',
    'كالوبين': 'kalobin',
    'كحول': 'alcohol',
    'كركدية': 'hibiscus',
    'كركديه': 'hibiscus',
    'كلوزابكس': 'clozapex',
    'كلوزابين': 'clozapine',
    'كوافازير': 'coavazir',
    'كوتراي ميكسازول': 'cotrimoxazole',
    'كورتكس': 'cortex',
    'كورفيبيك': 'corvepique',
    'كورفيزيم': 'corvizem',
    'كوفي زنك': 'coffi zinc',
    'كوللوماك': 'collomak',
    'كومبليت': 'complete',
    'لوبيكونت': 'lubeconte',
    'لوسيدريل': 'lucidril',
    'لوفازا': 'lovaza',
    'لولا ويست': 'lola west',
    'ليبراكس': 'librax',
    'ليزبيرج': 'lizberg',
    'مافو': 'mavo',
    'ماي تونكس': 'my tonex',
    'ماي سويت بيبي': 'my sweet baby',
    'منتوبلكس': 'mentoplex',
    'موبينورم': 'mobinorm',
    'موكسين': 'moxine',
    'ميباكوجرين تي': 'mepacogreen tea',
    'ميتابسين': 'metabsin',
    'ميرتي ماش': 'merti mash',
    'ميرتي': 'merti',
    'ناريدريكس': 'naridrix',
    'نت كلين': 'net clean',
    'نورموتيرز': 'normotears',
    'نيتروماك': 'nitromac',
    'نيليكس': 'nilex',
    'نيوتري ترو': 'nutritro',
    'نيوروفيت': 'neurovit',
    'نيوكاربون': 'eucarbon',
    'هانزو': 'hanzo',
    'هيدرو لوسيون': 'hydro lotion',
    'هيدروفيرين': 'hydroferin',
    'هيدروكين': 'hydroquin',
    'هيلاريوم': 'hilarium',
    'وينديبن': 'windipine',
    'ينسون': 'anise',
    'يورونيميا': 'euronemia',
    'يونيلوكسام': 'uniloxam',
    'اريثركس': 'erythrex',
    'سيتابرونكس': 'cetapronex',
}

ENGLISH_TO_ARABIC_BRANDS = {v: k for k, v in ARABIC_TO_ENGLISH_BRANDS.items()}

_SORTED_ARABIC_BRANDS = []
_UNIQUE_ENGLISH_BRANDS = []
_MULTI_WORD_ARABIC_BRANDS = []
_SINGLE_WORD_ARABIC_BRANDS = {}
_LONG_ARABIC_BRANDS = []
_ENGLISH_BRANDS_MAP = {}
_ENGLISH_BRANDS_REGEX = None

def _refresh_brand_indexes():
    global _SORTED_ARABIC_BRANDS, _UNIQUE_ENGLISH_BRANDS, ENGLISH_TO_ARABIC_BRANDS
    global _MULTI_WORD_ARABIC_BRANDS, _SINGLE_WORD_ARABIC_BRANDS, _LONG_ARABIC_BRANDS, _ENGLISH_BRANDS_MAP, _ENGLISH_BRANDS_REGEX
    _SORTED_ARABIC_BRANDS = sorted(ARABIC_TO_ENGLISH_BRANDS.items(), key=lambda x: len(x[0]), reverse=True)
    _UNIQUE_ENGLISH_BRANDS = sorted(set(ARABIC_TO_ENGLISH_BRANDS.values()), key=len, reverse=True)
    ENGLISH_TO_ARABIC_BRANDS = {v: k for k, v in ARABIC_TO_ENGLISH_BRANDS.items()}
    
    _MULTI_WORD_ARABIC_BRANDS = [(k, v) for k, v in _SORTED_ARABIC_BRANDS if ' ' in k]
    _SINGLE_WORD_ARABIC_BRANDS = {k: v for k, v in _SORTED_ARABIC_BRANDS if ' ' not in k}
    _LONG_ARABIC_BRANDS = [(k, v) for k, v in _SORTED_ARABIC_BRANDS if len(k) >= 5 and ' ' not in k]
    _ENGLISH_BRANDS_MAP = {b.lower(): b for b in _UNIQUE_ENGLISH_BRANDS}
    if _UNIQUE_ENGLISH_BRANDS:
        pattern = r'\b(?:' + '|'.join(re.escape(b) for b in _UNIQUE_ENGLISH_BRANDS) + r')\b'
        _ENGLISH_BRANDS_REGEX = re.compile(pattern, re.IGNORECASE)
    else:
        _ENGLISH_BRANDS_REGEX = None

_refresh_brand_indexes()


def is_known_canonical_brand(brand: str) -> bool:
    """Checks if a string is a recognized canonical English brand name."""
    if not brand or not isinstance(brand, str):
        return False
    return brand in ENGLISH_TO_ARABIC_BRANDS or brand in _UNIQUE_ENGLISH_BRANDS or brand in _ENGLISH_BRANDS_MAP


def extract_canonical_brand(text: Any) -> str:
    """
    Extracts canonical English brand root from Arabic or English trade name.
    Matches 500+ commercial brands bidirectionally with pre-tokenization decoupling.
    Gracefully accepts string or dict representations.
    """
    if isinstance(text, dict):
        text = str(text.get('name') or text.get('item_name') or text.get('trade_name') or '')
    if not text:
        return ""
    return _extract_canonical_brand_cached(str(text))


@functools.lru_cache(maxsize=16384)
def _extract_canonical_brand_cached(text: str) -> str:
    if not text:
        return ""
    
    # 1. Pre-tokenize and normalize
    decoupled = pre_tokenize_pharma_string(text)
    t = normalize_drug_text(decoupled)
    
    # 2. Strip noise words and isolated numbers cleanly
    t_padded = f" {t} "
    for w in sorted(CANONICAL_NOISE_WORDS, key=len, reverse=True):
        t_padded = re.sub(rf'\s+{re.escape(w)}\s+', ' ', t_padded)
    t_padded = re.sub(r'\b\d+(?:\.\d+)?\b', ' ', t_padded)
    t_clean = t_padded.strip()
    
    # 3. Match against Arabic brands
    if len(_SORTED_ARABIC_BRANDS) != len(ARABIC_TO_ENGLISH_BRANDS):
        _refresh_brand_indexes()
        
    # Check multi-word Arabic brands first (e.g. "فيتامين سي", "اليكا ام")
    for ar_b, en_b in _MULTI_WORD_ARABIC_BRANDS:
        if ar_b in t_clean or ar_b in t or ar_b in text:
            return en_b
            
    words = set(t_clean.split()) | set(t.split()) | set(text.split())
    candidate_tokens = set(words)
    for w in words:
        if w.startswith(('ال', 'ب', 'و')):
            if len(w) > 1:
                candidate_tokens.add(w[1:])
            if len(w) > 2:
                candidate_tokens.add(w[2:])
        if w.startswith(('وال', 'بال', 'فال', 'كال')) and len(w) > 3:
            candidate_tokens.add(w[3:])

    # Ensure any candidate token starting with 'ال' has its bare root tok[2:] added
    candidate_tokens.update(
        {tok[2:] for tok in candidate_tokens if tok.startswith('ال') and len(tok) > 2}
    )

    # Fast O(1) dictionary lookup across candidate tokens
    for tok in candidate_tokens:
        if tok in _SINGLE_WORD_ARABIC_BRANDS:
            if tok == 'بانثينول' and any(x in t_clean for x in ['هيبتا', 'ماكرو', 'يوريتشي', 'سفن']):
                continue
            return _SINGLE_WORD_ARABIC_BRANDS[tok]
            
    # Check concatenated / OCR-split text for Arabic brand roots (e.g. سبازموبي رالجي ني -> spasmopyralgin)
    t_clean_ns = t_clean.replace(' ', '')
    if t_clean_ns in _SINGLE_WORD_ARABIC_BRANDS:
        if t_clean_ns == 'بانثينول' and any(x in t_clean for x in ['هيبتا', 'ماكرو', 'يوريتشي', 'سفن']):
            pass
        else:
            return _SINGLE_WORD_ARABIC_BRANDS[t_clean_ns]
    for ar_b, en_b in _LONG_ARABIC_BRANDS:
        if t_clean_ns.startswith((ar_b, 'ال' + ar_b, 'وال' + ar_b, 'بال' + ar_b, 'فال' + ar_b, 'كال' + ar_b)) or ar_b in t_clean.split():
            if ar_b == 'سيتال' and any(x in t_clean_ns for x in ['اسيتال', 'سيتالو', 'سيتالوب']):
                continue
            if ar_b == 'ديجستين' and 'سبازم' in t_clean_ns:
                continue
            if ar_b == 'راني' and 'جراني' in t_clean_ns:
                continue
            if ar_b == 'بانثينول' and any(x in t_clean_ns for x in ['هيبتا', 'ماكرو', 'يوريتشي', 'سفن']):
                continue
            return en_b

    # 4. Fast precompiled regex match against English brands
    if _ENGLISH_BRANDS_REGEX:
        m = _ENGLISH_BRANDS_REGEX.search(t) or _ENGLISH_BRANDS_REGEX.search(text)
        if m:
            matched_str = m.group(0).lower()
            return _ENGLISH_BRANDS_MAP.get(matched_str, matched_str)
            
    # 5. Graceful fallback for unmapped text / numeric tokens
    if t_clean:
        return t_clean
    if t.strip():
        return t.strip()
    return ""


def normalize_arabic_text(text: str) -> str:
    """Normalize Arabic string for fuzzy matching."""
    if not text or not isinstance(text, str):
        return ""
    
    text = strip_illegal_characters(text)
    
    # Normalize unicode presentation forms
    text = unicodedata.normalize('NFKD', str(text))
    # Translate digits
    text = text.translate(EASTERN_ARABIC_DIGITS)
    
    # Remove tashkeel & tatweel
    text = re.sub(r'[ؗ-ًؚ-ْـ]', '', text)
    
    # Normalize characters
    for src, dst in ARABIC_CHAR_MAP.items():
        text = text.replace(src, dst)
        
    # Remove price update tags & noise
    text = re.sub(r'س\s*[.\-_]?\s*[جق]', '', text)
    text = re.sub(r'سعر\s+(?:جديد|قديم)', '', text)
    text = re.sub(r'\d+\s*ج', '', text)
    text = re.sub(r'(?:خاص|نقدي|مميز|جدا|جديد|قديم|باكو|علبة|شريط|شرايط|قرص|اقراص|اقرص|لرص|صارقا|صرق|كبسول|كبسولة|امبول|فيال|نقط|قطرة|شراب|شرب|مرهم|كريم|جل|جيل)', '', text)
    
    # Space between digits & letters
    text = re.sub(r'(\d+)([a-zA-Z؀-ۿ])', r'\g<1> \g<2>', text)
    text = re.sub(r'([a-zA-Z؀-ۿ])(\d+)', r'\g<1> \g<2>', text)

    # Clean whitespace & lowercase
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text

def parse_discount(val) -> float:
    """Parse discount string or number into float strictly between 0.0 and 0.85 (85% max wholesale discount)."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        v = float(val)
        if v > 1.0:
            v = v / 100.0
        if 0.0 < v <= 0.85:
            return round(v, 4)
        return 0.0
        
    val_str = str(val).strip().replace('%', '').replace(',', '.').translate(EASTERN_ARABIC_DIGITS)
    match = re.search(r'[-+]?\d*\.?\d+', val_str)
    if match:
        try:
            num = float(match.group())
            if num <= 0.0:
                return 0.0
            if num > 1.0:
                num = num / 100.0
            if 0.0 < num <= 0.85:
                return round(num, 4)
            return 0.0
        except ValueError:
            return 0.0
    return 0.0

def is_catalog_noise(text: str) -> bool:
    """Detects header labels, software vendor credits, timestamps, or phone noise in catalog items."""
    if not text or not isinstance(text, str):
        return True
    t = str(text).strip()
    if len(t) < 2 or len(t) > 90:
        return True
    # Normalize presentation forms to canonical unicode first
    t_norm = unicodedata.normalize('NFKD', t)
    # Must contain at least one Arabic, Latin, Greek, Aboriginal, or Presentation Form character
    if not re.search(r'[a-zA-Z\u0600-\u06ff\u0750-\u077f\u0380-\u03ff\ufb50-\ufdff\ufe70-\ufeff\u1400-\u18af]', t_norm):
        return True
    # Explicit software vendor credits and page header/footer markers
    noise_keywords = [
        'اورجا سوفت', 'اروا سوفت', 'أورجا سوفت', 'أروا سوفت',
        'لتجارة وتوزيع', 'توزيع الادوية', 'توزيع الأدوية', 'مخزن الفارس',
        'تليفون', 'هاتف', 'موبايل', 'س.ت', 'ب.ض',
        'سجل تجاري', 'بطاقة ضريبية', 'صفحة'
    ]
    t_lower = t.lower()
    if any(k in t_lower for k in noise_keywords):
        return True
    if re.search(r'(?:^|[\s:/\-])(?:فاكس|page)(?:$|[\s:/\-\d])', t_lower):
        return True
    # Telephone / hotline numbers (e.g. 010..., 011..., 012..., 015..., 02..., 040...)
    if re.search(r'(?:01[0-9]{9}|0[2-5][0-9]{7,8})', t.translate(EASTERN_ARABIC_DIGITS)):
        return True
    # Pure timestamps (e.g. 05:02:58 or 05:02:58 م or م 05:02:58)
    if re.search(r'(?:(?:م|ص|am|pm)\s*)?\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:م|ص|am|pm))?', t, re.IGNORECASE):
        clean_no_time = re.sub(r'(?:(?:م|ص|am|pm)\s*)?\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:م|ص|am|pm))?', '', t, flags=re.IGNORECASE).strip()
        if len(clean_no_time) < 3:
            return True
    # Standalone date footers (e.g. الثلاثاء/10 سبتمبر)
    months = r'\b(?:يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\b'
    days = r'\b(?:السبت|الاحد|الأحد|الاثنين|الإثنين|الثلاثاء|الاربعاء|الأربعاء|الخميس|الجمعة)\b'
    if re.search(months, t) and (re.search(r'\d{1,2}', t) or re.search(days, t)):
        clean_no_date = re.sub(months, '', t)
        clean_no_date = re.sub(days, '', clean_no_date)
        clean_no_date = re.sub(r'[\d/\-\s:.]+', '', clean_no_date).strip()
        if len(clean_no_date) < 6:
            return True
    return False

def parse_dosage_and_pack(item_name: str):
    """Extract dosage strengths and pack sizes from item name."""
    if not item_name:
        return '', ''
    text = str(item_name).translate(EASTERN_ARABIC_DIGITS)
    for src, dst in ARABIC_CHAR_MAP.items():
        text = text.replace(src, dst)
    text = text.replace('ی', 'ي').replace('ک', 'ك').replace('ہ', 'ه')
    
    # Decouple letters and digits while preserving decimals
    text = re.sub(r'([a-zA-Z\u0600-\u06FF])(\d+)', r'\1 \2', text)
    text = re.sub(r'(\d+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', text)
    
    # Preserve decimal periods between digits while sanitizing other punctuation
    text = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', text)
    text = re.sub(r'[^\w\s\.]', ' ', text)
    normalized = re.sub(r'\s+', ' ', text).strip().lower()
    
    strength_pattern = r'(\d+(?:\.\d+)?\s*(?:mg|gm|g|ml|mcg|iu|مجم|مج|جم|مل|ميكروجرام|وحدة))'
    strength_match = re.search(strength_pattern, normalized, re.IGNORECASE)
    if strength_match:
        dosage = strength_match.group(1).replace(' ', '')
    else:
        # Check reversed/prefix unit notation (e.g. "مج 25" -> "25مج")
        strength_pattern_rev = r'((?:mg|gm|g|ml|mcg|iu|مجم|مج|جم|مل|ميكروجرام|وحدة)\s*\d+(?:\.\d+)?)'
        rev_match = re.search(strength_pattern_rev, normalized, re.IGNORECASE)
        if rev_match:
            parts = re.findall(r'\d+(?:\.\d+)?|[a-zA-Z\u0600-\u06ff]+', rev_match.group(1))
            if len(parts) == 2:
                num = parts[0] if parts[0][0].isdigit() else parts[1]
                unit = parts[1] if parts[0][0].isdigit() else parts[0]
                dosage = f"{num}{unit}"
            else:
                dosage = rev_match.group(1).replace(' ', '')
        else:
            dosage = ''
    
    pack_pattern = r'(\d+\s*(?:tab|cap|amp|vial|strip|bottle|قرص|كبسولة|كبسول|امبول|فيال|شريط|زجاجة|شرايط))'
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

@functools.lru_cache(maxsize=16384)
def extract_sorted_brand_tokens(text: str) -> str:
    """Extracts sorted core brand tokens, invariant to word reordering in warehouse catalogs."""
    if not text:
        return ""
    t = normalize_drug_text(text)
    t = t.replace('/', ' ')
    for w in sorted(CANONICAL_NOISE_WORDS, key=len, reverse=True):
        t = re.sub(rf'{w}', ' ', t)
    t = re.sub(r'\d+(?:\.\d+)?', ' ', t)
    words = [w for w in re.sub(r'[^a-z0-9؀-ۿ\s]', ' ', t).split() if len(w) >= 2]
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
