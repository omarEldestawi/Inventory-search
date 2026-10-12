# -*- coding: utf-8 -*-
"""
Unit tests for Egyptian Pharmaceutical Canonical Brand Dictionary Expansion,
Pre-Tokenizer Decoupling, and Bidirectional Brand Matching.
"""
import pytest
from src.normalizer import (
    ARABIC_TO_ENGLISH_BRANDS,
    ENGLISH_TO_ARABIC_BRANDS,
    CANONICAL_NOISE_WORDS,
    pre_tokenize_pharma_string,
    normalize_drug_text,
    extract_canonical_brand,
    normalize_vendor_name,
    decode_custom_catalog_glyphs,
    ARABIC_CHAR_MAP,
)


class TestBrandDictionarySizeAndIntegrity:
    """Validates the expanded canonical brand dictionary size, types, and baseline coverage."""

    def test_dictionary_size_greater_than_or_equal_500(self):
        """Verifies dictionary expansion requirement: ARABIC_TO_ENGLISH_BRANDS >= 500."""
        count = len(ARABIC_TO_ENGLISH_BRANDS)
        assert count >= 500, f"Expected at least 500 brands, got {count}"
        print(f"\n[PASS] ARABIC_TO_ENGLISH_BRANDS contains {count} brand entries (target >= 500).")

    def test_all_baseline_88_brands_preserved(self):
        """Ensures 100% preservation of all original 88 baseline brands with zero regression."""
        baseline_88 = [
            'بانادول', 'بنادول', 'اوجمنتين', 'اوجمانتين', 'كتافلام', 'كونكور', 'بروفين', 'فلاجيل', 'نيكسيوم',
            'فولتارين', 'انتينال', 'اماريل', 'كاربامازيبين', 'كابوتن', 'سيبرازول', 'سبرالكس', 'اتور', 'كريستور',
            'جلوكوفاج', 'كوزار', 'زانتاك', 'لانتوس', 'كلارينيز', 'تلفاست', 'زيرتك', 'اوترفين', 'موبيك', 'سيردالود',
            'كولونا', 'دوفاستون', 'سيلدينافيل', 'سياليس', 'فياجرا', 'ليبيتور', 'بلافيكس', 'دافلون', 'دورميكوم',
            'لاسيكس', 'داونيل', 'داياميكرون', 'جانوفيا', 'جالفوس', 'فورسيجا', 'جاردينس', 'سوبرافيت', 'كيروفيت',
            'بيتادين', 'ميبو', 'كتافاست', 'سيبتازول', 'كلافيموكس', 'هاي بيوتك', 'هايبيوتك', 'كيورام', 'ميجا موكس',
            'ميجاموكس', 'زيثروماكس', 'زيثرون', 'ازيثروسين', 'سيبروفلوكساسين', 'سيبروفار', 'سيبروسين', 'تارجوسيد',
            'يوناسين', 'افيل', 'اتينولول', 'بلوكيم', 'كابوزيد', 'كاردورا', 'ديلتيازم', 'الداكتون', 'اندرال',
            'موديوريتيك', 'نورفاسك', 'تنورمين', 'تريتاس', 'موتيفال', 'نيوروتون', 'نيوروبيون', 'ميلجا',
            'ثيروجلوبين', 'التروكسين', 'يوريفين', 'راني', 'جاست ريج', 'ديجستين', 'سبازموفري', 'سبازمو ديجستين'
        ]
        missing = [b for b in baseline_88 if b not in ARABIC_TO_ENGLISH_BRANDS]
        assert not missing, f"Missing baseline brands: {missing}"

    def test_dictionary_types_and_lowercase_english(self):
        """Verifies that all keys are non-empty strings and values are clean lowercase English roots."""
        for ar_name, en_root in ARABIC_TO_ENGLISH_BRANDS.items():
            assert isinstance(ar_name, str) and len(ar_name.strip()) >= 2, f"Invalid Arabic key: {ar_name!r}"
            assert isinstance(en_root, str) and len(en_root.strip()) >= 2, f"Invalid English value: {en_root!r}"
            assert en_root == en_root.lower(), f"English root '{en_root}' is not lowercase"
            assert not any(c in en_root for c in ['`', '"', "'", '\\', ';', '{', '}']), f"Invalid char in '{en_root}'"

    def test_english_to_arabic_reverse_dictionary(self):
        """Verifies that the reverse mapping ENGLISH_TO_ARABIC_BRANDS is populated and accessible."""
        assert isinstance(ENGLISH_TO_ARABIC_BRANDS, dict)
        assert len(ENGLISH_TO_ARABIC_BRANDS) > 0
        # Spot check key brands
        assert ENGLISH_TO_ARABIC_BRANDS.get('panadol') in ('بانادول', 'بنادول')
        assert ENGLISH_TO_ARABIC_BRANDS.get('augmentin') in ('اوجمنتين', 'اوجمانتين')


class TestPreTokenizerDecoupling:
    """Validates regex pre_tokenize_pharma_string decoupling of glued digits, units, and forms."""

    @pytest.mark.parametrize("glued_input, expected_tokens", [
        ("ابيزيثرو500مجم3قرص", ["ابيزيثرو", "500", "مجم", "3", "قرص"]),
        ("اتراكون14كبسوله", ["اتراكون", "14", "كبسوله"]),
        ("اريثركس200مجم2شريط", ["اريثركس", "200", "مجم", "2", "شريط"]),
        ("اسبرين بروتكت 100مجم3شريط", ["اسبرين", "بروتكت", "100", "مجم", "3", "شريط"]),
        ("سيتال5لبوس", ["سيتال", "5", "لبوس"]),
        ("افالوكس400مجم اقراص", ["افالوكس", "400", "مجم", "اقراص"]),
        ("افروزوليد60مل شراب", ["افروزوليد", "60", "مل", "شراب"]),
        ("Augmentin1g14tab", ["Augmentin", "1", "g", "14", "tab"]),
        ("Panadol500mg24tab", ["Panadol", "500", "mg", "24", "tab"]),
        ("Brufen400mg", ["Brufen", "400", "mg"]),
    ])
    def test_pre_tokenize_splits_glued_strings(self, glued_input, expected_tokens):
        """Ensures glued numbers, units, and packaging forms are separated with spaces."""
        decoupled = pre_tokenize_pharma_string(glued_input)
        for token in expected_tokens:
            assert token in decoupled, f"Token '{token}' not found in decoupled result: '{decoupled}'"

    def test_pre_tokenize_preserves_decimals_and_ratios(self):
        """Ensures decimal doses and combination ratios are preserved without improper splitting."""
        decoupled = pre_tokenize_pharma_string("افيروثيازيد20/12.5/5مجم 30قرص")
        assert "12.5" in decoupled
        assert "30" in decoupled
        assert "قرص" in decoupled

    def test_pre_tokenize_handles_eastern_arabic_digits(self):
        """Translates Eastern Arabic numerals (٥٠٠ -> 500) and decouples."""
        decoupled = pre_tokenize_pharma_string("بانادول٥٠٠مجم")
        assert "500" in decoupled
        assert "مجم" in decoupled

    def test_pre_tokenize_empty_and_non_string(self):
        """Handles empty or None input gracefully."""
        assert pre_tokenize_pharma_string("") == ""
        assert pre_tokenize_pharma_string(None) == ""


class TestBidirectionalCanonicalBrandExtraction:
    """Validates extract_canonical_brand for bidirectional Arabic <-> English equivalence."""

    @pytest.mark.parametrize("arabic_text, english_text, expected_canonical", [
        ("بانادول اكسترا 500 مجم", "Panadol Extra 500mg", "panadol"),
        ("اوجمنتين 1 جم 14 قرص", "Augmentin 1g 14 Tab", "augmentin"),
        ("كتافلام 50مجم 20قرص", "Cataflam 50mg 20 Tab", "cataflam"),
        ("كونكور 5 مجم 30 قرص", "Concor 5mg 30 Tab", "concor"),
        ("بروفين 400مجم اقراص", "Brufen 400mg Tablets", "brufen"),
        ("فلاجيل 500 مجم 20 قرص", "Flagyl 500mg 20 Tab", "flagyl"),
        ("نيكسيوم 40 مجم 14 قرص", "Nexium 40mg 14 Tab", "nexium"),
        ("فولتارين 50 مجم 20 قرص", "Voltaren 50mg 20 Tab", "voltaren"),
        ("انتينال 24 كبسول", "Antinal 24 Capsules", "antinal"),
        ("اماريل 2 مجم 30 قرص", "Amaryl 2mg 30 Tab", "amaryl"),
        ("كريستور 10 مجم 28 قرص", "Crestor 10mg 28 Tab", "crestor"),
        ("جلوكوفاج 1000 مجم", "Glucophage 1000mg", "glucophage"),
        ("لانتوس سولوستار قلم", "Lantus Solostar Pen", "lantus"),
        ("تلفاست 180 مجم 20 قرص", "Telfast 180mg 20 Tab", "telfast"),
        ("اوترفين بخاخ انف", "Otrivin Nasal Spray", "otrivin"),
        ("سيردالود 4 مجم اقراص", "Sirdalud 4mg Tablets", "sirdalud"),
        ("بلافيكس 75 مجم 28 قرص", "Plavix 75mg 28 Tab", "plavix"),
        ("دافلون 500 مجم 30 قرص", "Daflon 500mg 30 Tab", "daflon"),
        ("لاسيكس 40 مجم 24 قرص", "Lasix 40mg 24 Tab", "lasix"),
        ("جانوفيا 100 مجم 28 قرص", "Januvia 100mg 28 Tab", "januvia"),
        ("فورسيجا 10 مجم 28 قرص", "Forxiga 10mg 28 Tab", "forxiga"),
        ("جاردينس 10 مجم 30 قرص", "Jardiance 10mg 30 Tab", "jardiance"),
        ("بيتادين 60 مل مطهر", "Betadine 60ml Antiseptic", "betadine"),
        ("ميبو مرهم 15 جم", "Mebo Ointment 15g", "mebo"),
        ("زيثروماكس 500 مجم 3 كبسول", "Zithromax 500mg 3 Cap", "zithromax"),
    ])
    def test_bidirectional_brand_equivalence(self, arabic_text, english_text, expected_canonical):
        """Tests that Arabic and English commercial trade names map to identical canonical English roots."""
        ar_brand = extract_canonical_brand(arabic_text)
        en_brand = extract_canonical_brand(english_text)
        assert ar_brand == expected_canonical, f"Arabic '{arabic_text}' -> '{ar_brand}', expected '{expected_canonical}'"
        assert en_brand == expected_canonical, f"English '{english_text}' -> '{en_brand}', expected '{expected_canonical}'"
        assert ar_brand == en_brand, f"Equivalence failed: Arabic '{ar_brand}' != English '{en_brand}'"

    @pytest.mark.parametrize("po_glued_str, expected_root", [
        ("ابيزيثرو500مجم3قرص", "epizithro"),
        ("اتراكون14كبسوله", "itracon"),
        ("اريثركس200مجم2شريط", "erythrex"),
        ("اسبرين بروتكت 100مجم3شريط", "aspirin protect"),
        ("اسيتايل سستايين 600مجم اكياس", "acetylcysteine"),
        ("افالوكس400مجم اقراص", "avelox"),
        ("افروزوليد 60 مل شراب", "averozolid"),
        ("ال كارنتين بلس 30كبسولة", "l-carnitine"),
        ("الفاثرومب5مجم20قرص", "alphathromb"),
        ("اليرزون كريم", "allerzone"),
        ("انتي كوكس 6امبول", "anticox"),
        ("لبن ابتاميل 1 ادفانس", "aptamil"),
        ("لبن نان 3 اوبتي برو", "nan"),
        ("لبن بيبيلاك 3 بيبي جونيور", "bebelac"),
        ("لبن هيرو بيبي 2", "hero baby"),
    ])
    def test_glued_po_items_extraction(self, po_glued_str, expected_root):
        """Verifies real purchase order glued medication names resolve to canonical roots."""
        root = extract_canonical_brand(po_glued_str)
        assert root == expected_root, f"PO item '{po_glued_str}' -> '{root}', expected '{expected_root}'"


class TestTherapeuticClassesCoverage:
    """Verifies coverage across all major therapeutic classes in Egyptian pharmacy practice."""

    @pytest.mark.parametrize("drug_name, expected_brand", [
        # Antibiotics & Antivirals
        ("اوجمنتين 1 جم", "augmentin"),
        ("هاي بيوتك 1 جم", "hibiotic"),
        ("كيورام 1 جم", "curam"),
        ("ميجا موكس 1 جم", "megamox"),
        ("ايموكسكلاف 625", "emoxclav"),
        ("كلافوران 1 جم فيال", "claforan"),
        ("سيفوتاكس 1 جم فيال", "cefotax"),
        ("يوناسين 1.5 جم", "unasyn"),
        ("يونيكتام 1500", "unictam"),
        ("زينات 500 مجم", "zinnat"),
        ("افالوكس 400 مجم", "avelox"),
        ("تاريفيد 200 مجم", "tarivid"),
        ("تافانيك 500 مجم", "tavanic"),
        ("دالاسين سي 300 مجم", "dalacin"),
        ("كلاسيد 500 مجم", "klacid"),
        ("ماكسيبيم 1 جم", "maxipime"),
        ("سيفيكسيم 100 شراب", "cefixime"),
        # Antifungals
        ("اتراكون 100 مجم", "itracon"),
        ("ديفلوكان 150 مجم", "diflucan"),
        ("فلوكورال 150 مجم", "flucoral"),
        ("فانجيكان 150 مجم", "fungican"),
        ("دكتاكورت كريم", "daktacort"),
        ("دكتارين جل", "daktarin"),
        ("ميكوناز جل", "miconaz"),
        # Cardiovascular & Anticoagulant
        ("كلكسان 40 مجم سرنجة", "clexane"),
        ("اينوهيب 10000 وحدة", "innohep"),
        ("زاريلتو 20 مجم", "xarelto"),
        ("اليكويس 5 مجم", "eliquis"),
        ("اتاكاند 16 مجم", "atacand"),
        ("اكسفورج 10/160", "exforge"),
        ("سيلوكين 100 مجم", "seloken"),
        ("نيبيليت 5 مجم", "nebilet"),
        ("ناتريلكس اس ار", "natrilix"),
        ("كوفرسيل 5 مجم", "coversyl"),
        ("تريتاس 5 مجم", "tritace"),
        # GI & Hepato
        ("كنترولوك 40 مجم", "controloc"),
        ("بانتازول 40 مجم", "pantazol"),
        ("زوركال 40 مجم", "zurcal"),
        ("دوسباتالين 200 ريتارد", "duspatalin"),
        ("كولوفيرين د", "coloverin"),
        ("موتيليوم 10 مجم", "motilium"),
        ("جاستروموتيل 10 مجم", "gastromotil"),
        ("اورسوفالك 250 مجم", "ursofalk"),
        ("هيباميرز اكياس", "hepamerc"),
        ("رواكول كبسول", "rowachol"),
        ("رواتينكس كبسول", "rowatinex"),
        # Respiratory & Cold/Flu
        ("كونجستال اقراص", "congestal"),
        ("كولد فري اقراص", "cold free"),
        ("فلورست اقراص", "flurest"),
        ("كومتركس اقراص", "comtrex"),
        ("وان تو ثري اقراص", "123"),
        ("فنتولين بخاخ", "ventolin"),
        ("فاركولين محلول", "farcolin"),
        ("اتروفنت امبول", "atrovent"),
        ("بالميكورت 0.5 امبول", "pulmicort"),
        ("ايريوس 5 مجم", "aerius"),
        ("كلاريتين 10 مجم", "claritine"),
        ("اسيتيل سيستايين 600 فوار", "acetylcysteine"),
        # Infant Nutrition
        ("لبن نان 1 اوبتي برو", "nan"),
        ("لبن بيبيلاك 1", "bebelac"),
        ("لبن ابتاميل 1", "aptamil"),
        ("لبن هيرو بيبي 1", "hero baby"),
        ("لبن بيوميل 1", "biomil"),
        ("لبن سيميلاك 1", "similac"),
        # Dermatological
        ("بانثينول كريم", "panthenol"),
        ("درموفيت كريم", "dermovate"),
        ("اليكا كريم", "elica"),
        ("كيناكومب كريم", "kenacomb"),
        ("فيوسيدين مرهم", "fucidin"),
        ("فيوسيكورت كريم", "fucicort"),
    ])
    def test_therapeutic_category_brand(self, drug_name, expected_brand):
        """Verifies representative medication brands across all major clinical categories."""
        res = extract_canonical_brand(drug_name)
        assert res == expected_brand, f"Medication '{drug_name}' mapped to '{res}', expected '{expected_brand}'"


class TestZeroRegressions:
    """Verifies vendor name resolution, Canadian/Runic glyph maps, and presentation forms."""

    def test_vendor_name_normalization_resolves_collisions(self):
        """Confirms wholesale vs Gamal collision fix is preserved."""
        assert normalize_vendor_name("ادم جمله.pdf") == "مخزن ادم جملة"
        assert normalize_vendor_name("جمله محجوب السنبلاوين.pdf") == "مخزن محجوب السنبلاوين"
        assert normalize_vendor_name("الاحد_انفنتي_نقدي.pdf") == "مخزن انفينتي"

    def test_custom_catalog_glyphs_decoding(self):
        """Confirms Canadian Aboriginal and Runic ERP glyph decoding is preserved."""
        # ᗷ -> ب, ᜧ -> ك, ᘭ -> ي
        encoded = "ᗷᜧᘭ"
        decoded = decode_custom_catalog_glyphs(encoded)
        assert decoded == "بكي"

    def test_presentation_forms_mapping(self):
        """Confirms Arabic presentation forms-A/B mapping is preserved."""
        # U+FE8E Final Alef (ﺎ), U+FE94 Final Teh Marbuta (ﺔ)
        assert ARABIC_CHAR_MAP['ﺎ'] == 'ا'
        assert ARABIC_CHAR_MAP['ﺔ'] == 'ه'
