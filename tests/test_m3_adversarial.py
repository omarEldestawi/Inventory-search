# -*- coding: utf-8 -*-
"""
Adversarial stress-testing suite for Milestone M3:
Canonical Brand Dictionary, Pre-Tokenizer Decoupling, and Clinical Safety Compatibility.
"""
import pytest
import re
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
from src.pharma_matcher import is_safe_pharmaceutical_match, check_modifier_compatibility


class TestAdversarialBrandDictionaryIntegrity:
    """Rigorous structural and data integrity audits on ARABIC_TO_ENGLISH_BRANDS."""

    def test_exact_count_exceeds_threshold(self):
        """Enforces strictly >= 500 brands and checks exact worker count."""
        count = len(ARABIC_TO_ENGLISH_BRANDS)
        assert count >= 500, f"Critical: Dictionary has only {count} brands, requirement is >= 500"
        assert count >= 959, f"Worker reported >= 959, found {count}"

    def test_no_empty_or_whitespace_padded_keys_or_values(self):
        """Ensures zero entries have leading/trailing whitespace or empty strings."""
        for k, v in ARABIC_TO_ENGLISH_BRANDS.items():
            assert k == k.strip(), f"Key has untrimmed whitespace: {k!r}"
            assert v == v.strip(), f"Value has untrimmed whitespace: {v!r}"
            assert len(k) >= 2, f"Key too short: {k!r}"
            assert len(v) >= 2, f"Value too short: {v!r}"

    def test_no_illegal_or_surrogate_characters(self):
        """Ensures all strings are clean unicode with no non-printable or corrupt chars."""
        for k, v in ARABIC_TO_ENGLISH_BRANDS.items():
            assert not any(ord(c) < 32 and c not in '\t\n' for c in k), f"Control char in key: {k!r}"
            assert not any(ord(c) < 32 and c not in '\t\n' for c in v), f"Control char in value: {v!r}"

    def test_all_values_strict_lowercase_ascii_or_valid_characters(self):
        """Ensures all canonical English brand values are strictly lowercase."""
        for k, v in ARABIC_TO_ENGLISH_BRANDS.items():
            assert v == v.lower(), f"Canonical brand value is not lowercase: {v!r}"
            # Only letters, digits, spaces, hyphens
            assert re.fullmatch(r'[a-z0-9\s\-]+', v), f"Unexpected characters in brand value: {v!r}"

    def test_all_baseline_88_brands_present_and_correct(self):
        """Verifies each of the 88 baseline brands is mapped properly."""
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
        for b in baseline_88:
            assert b in ARABIC_TO_ENGLISH_BRANDS, f"Baseline brand '{b}' missing from dictionary!"


class TestAdversarialPreTokenizer:
    """Stress tests on pre_tokenize_pharma_string under extreme, noisy, and pathological inputs."""

    @pytest.mark.parametrize("input_text, expected_tokens", [
        ("ابيزيثرو500مجم3قرص", ["ابيزيثرو", "500", "مجم", "3", "قرص"]),
        ("اتراكون14كبسوله", ["اتراكون", "14", "كبسوله"]),
        ("اريثركس200مجم2شريط", ["اريثركس", "200", "مجم", "2", "شريط"]),
        ("Panadol500mg24tab", ["Panadol", "500", "mg", "24", "tab"]),
        ("Augmentin1g14tab", ["Augmentin", "1", "g", "14", "tab"]),
        ("Cataflam50mg20Tab", ["Cataflam", "50", "mg", "20", "Tab"]),
        ("سيتال120مجم/5مل شراب", ["سيتال", "120", "مجم", "5", "مل", "شراب"]),
        ("12.5mg/50mg", ["12.5", "mg", "50", "mg"]),
        ("كونكور5بلس30قرص", ["كونكور", "5", "بلس", "30", "قرص"]),
        ("Cital100mg5Supp", ["Cital", "100", "mg", "5"]),
    ])
    def test_glued_pharma_boundaries(self, input_text, expected_tokens):
        res = pre_tokenize_pharma_string(input_text)
        for token in expected_tokens:
            assert token in res, f"Expected '{token}' in decoupled output: '{res}' (input: '{input_text}')"

    def test_pathological_inputs(self):
        """Verifies resilience against None, numbers, booleans, and empty strings."""
        assert pre_tokenize_pharma_string("") == ""
        assert pre_tokenize_pharma_string("   ") == ""
        assert pre_tokenize_pharma_string(None) == ""
        assert pre_tokenize_pharma_string(12345) == ""
        assert pre_tokenize_pharma_string([]) == ""

    def test_arabic_presentation_forms_and_eastern_digits(self):
        """Verifies that Eastern Arabic numerals and presentation forms are normalized before tokenization."""
        # ٥٠٠ = 500, ﺎ = ا
        text = "بانادﻭل٥٠٠مجم"
        res = pre_tokenize_pharma_string(text)
        assert "500" in res
        assert "مجم" in res
        assert "بانادول" in res or "بانادو" in res


class TestAdversarialCanonicalBrandMatching:
    """Stress tests on extract_canonical_brand against false positives and tricky variations."""

    @pytest.mark.parametrize("query, expected_canonical", [
        ("بانادول اكسترا 500 مجم 24 قرص", "panadol"),
        ("بانادول كولد اند فلو داي", "panadol"),
        ("PANADOL EXTRA 500MG 24 TAB", "panadol"),
        ("panadol cold & flu", "panadol"),
        ("اوجمنتين 1 جم 14 قرص", "augmentin"),
        ("Augmentin 1000mg 14 Tablets", "augmentin"),
        ("كتافلام 50 مجم 20 قرص", "cataflam"),
        ("Cataflam 50 mg", "cataflam"),
        ("بروفين 600 فوار 10 اكياس", "brufen"),
        ("Brufen 600mg Effervescent 10 Sachets", "brufen"),
        ("وان تو ثري اقراص", "123"),
        ("123 اقراص", "123"),
        ("123 Tablets", "123"),
        ("اسبرين بروتكت 100 مجم", "aspirin protect"),
        ("Aspirin Protect 100mg", "aspirin protect"),
        ("دالاسين سي 300 مجم 16 كبسول", "dalacin"),
        ("Dalacin C 300mg", "dalacin"),
        ("لبن نان 1 اوبتي برو", "nan"),
        ("لبن نان 2", "nan"),
        ("Nan 1 Optipro", "nan"),
        ("لبن هيرو بيبي 1 حليب اطفال", "hero baby"),
        ("Hero Baby 1 Milk", "hero baby"),
    ])
    def test_canonical_brand_extraction_adversarial(self, query, expected_canonical):
        res = extract_canonical_brand(query)
        assert res == expected_canonical, f"Failed for '{query}': got '{res}', expected '{expected_canonical}'"

    def test_substring_containment_avoidance(self):
        """Longer brand roots must match over shorter sub-roots."""
        # 'اسبرين بروتكت' should resolve to 'aspirin protect', NOT 'aspirin'
        assert extract_canonical_brand("اسبرين بروتكت 100 مجم") == "aspirin protect"
        # 'باي كيتوفان' should resolve to 'bi-ketofan', NOT 'ketofan'
        assert extract_canonical_brand("باي كيتوفان 150 مجم") == "bi-ketofan"
        # 'هاي بيوتك' should resolve to 'hibiotic', NOT 'optic'
        assert extract_canonical_brand("هاي بيوتك 1 جم اقراص") == "hibiotic"

    def test_unknown_medications_fallback_graceful(self):
        """Unknown medication strings should fallback cleanly without exceptions."""
        res = extract_canonical_brand("دواء غير معروف نهائيا 999")
        assert isinstance(res, str)
        assert len(res) > 0


class TestClinicalMatcherIntegration:
    """Verifies that extracted canonical brands integrate safely with pharma_matcher clinical gates."""

    def test_modifier_compatibility_with_canonical_brands(self):
        """Ensures that brands with modifiers (extra, cold_flu) don't cross-match dangerously."""
        po_item = "بانادول اكسترا 500 مجم اقراص"
        cat_match = "بانادول 500 مجم 24 قرص"
        
        brand_po = extract_canonical_brand(po_item)
        brand_cat = extract_canonical_brand(cat_match)
        # Both share the same canonical root
        assert brand_po == brand_cat == "panadol"
        
        # Clinical modifier compatibility must block extra vs regular
        compatible = check_modifier_compatibility(po_item, cat_match)
        assert not compatible, "Clinical safety gate failure: Panadol Extra matched with plain Panadol!"

    def test_form_compatibility_with_canonical_brands(self):
        """Ensures that tablet vs syrup is blocked even if canonical brand matches."""
        req = {'name': 'سيتال 500 مجم اقراص', 'dosage': '500mg', 'unit_size': 20}
        cand = {'name': 'سيتال 120 مجم/5مل شراب', 'dosage': '120mg/5ml', 'unit_size': 100}
        
        brand_req = extract_canonical_brand(req['name'])
        brand_cand = extract_canonical_brand(cand['name'])
        assert brand_req == brand_cand == "cetal"
        
        # Clinical gate must reject syrup vs tablet
        safe = is_safe_pharmaceutical_match(req, cand)
        assert not safe, f"Expected unsafe match due to form mismatch, got {safe}"


def load_tests(loader, tests, pattern):
    import unittest, os
    suite = unittest.TestSuite()
    class PytestRunner(unittest.TestCase):
        def test_suite(self):
            code = pytest.main(["-q", os.path.abspath(__file__)])
            self.assertEqual(code, 0, f"pytest exit code: {code}")
    suite.addTests(loader.loadTestsFromTestCase(PytestRunner))
    return suite
