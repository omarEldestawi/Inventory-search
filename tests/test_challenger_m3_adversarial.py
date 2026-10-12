# -*- coding: utf-8 -*-
"""
Adversarial Challenge Test Suite for Milestone M3:
Canonical Brand Dictionary Expansion & Pre-Tokenizer Decoupling.

Authored by Challenger M3_1.
Empirically tests failure modes, edge cases, regex boundaries,
and stress scenarios for:
  - pre_tokenize_pharma_string
  - extract_canonical_brand
  - normalize_drug_text
  - ARABIC_TO_ENGLISH_BRANDS dictionary integrity & size
"""
import re
import random
import pytest
from src.normalizer import (
    ARABIC_TO_ENGLISH_BRANDS,
    ENGLISH_TO_ARABIC_BRANDS,
    CANONICAL_NOISE_WORDS,
    pre_tokenize_pharma_string,
    normalize_drug_text,
    extract_canonical_brand,
    normalize_arabic_text,
    decode_custom_catalog_glyphs,
)


class TestAdversarialDictionaryIntegrity:
    """Stress tests and asserts strict invariants on the brand dictionary."""

    def test_dictionary_count_strict_lower_bound(self):
        """Asserts dictionary count >= 500 entries (Milestone M3 requirement)."""
        count = len(ARABIC_TO_ENGLISH_BRANDS)
        assert count >= 500, f"Dictionary count {count} is strictly less than 500"
        print(f"\n[EMPIRICAL] Dictionary count verified: {count} >= 500")

    def test_no_empty_or_whitespace_keys_or_values(self):
        """Verifies no empty, single-character, or whitespace-only keys or values."""
        for ar_k, en_v in ARABIC_TO_ENGLISH_BRANDS.items():
            assert ar_k and ar_k.strip() == ar_k, f"Invalid key whitespace: {ar_k!r}"
            assert len(ar_k) >= 2, f"Key too short (<2 chars): {ar_k!r}"
            assert en_v and en_v.strip() == en_v, f"Invalid val whitespace: {en_v!r}"
            assert len(en_v) >= 2, f"Value too short (<2 chars): {en_v!r}"
            assert en_v == en_v.lower(), f"Canonical value not lowercase: {en_v!r}"

    def test_no_dangerous_punctuation_in_canonical_roots(self):
        """Canonical roots must be alphanumeric or hyphenated, no punctuation that breaks SQL/regex."""
        forbidden_pattern = re.compile(r'[`"\'\\;{}()\[\]*+?^$|]')
        for ar_k, en_v in ARABIC_TO_ENGLISH_BRANDS.items():
            assert not forbidden_pattern.search(en_v), (
                f"Dangerous characters found in canonical value {en_v!r} for key {ar_k!r}"
            )


class TestGluedPackagingAndUnitsStress:
    """Stress tests pre_tokenize_pharma_string with pathological glued packaging strings."""

    @pytest.mark.parametrize("glued_str, expected_tokens", [
        # Multiple concatenated dosage units & numbers
        ("500مجم3قرص2شريط", ["500", "مجم", "3", "قرص", "2", "شريط"]),
        ("2شريط10كبسولات500مجم", ["2", "شريط", "10", "كبسولات", "500", "مجم"]),
        ("1000مجم14قرص", ["1000", "مجم", "14", "قرص"]),
        ("0.5مجم30قرص", ["0.5", "مجم", "30", "قرص"]),
        ("12.5mg30tab", ["12.5", "mg", "30", "tab"]),
        ("1g14tab", ["1", "g", "14", "tab"]),
        ("400mg20capsules", ["400", "mg", "20", "capsules"]),
        ("100مجم3شريط", ["100", "مجم", "3", "شريط"]),
        ("14كبسوله", ["14", "كبسوله"]),
        ("5لبوس", ["5", "لبوس"]),
        ("200مجم2شريط", ["200", "مجم", "2", "شريط"]),
        ("6امبولات2مل", ["6", "امبولات", "2", "مل"]),
        ("100ملشراب", ["100", "مل", "شراب"]),
        ("50جممرهم", ["50", "جم", "مرهم"]),
        ("30قرصاستحلاب", ["30", "قرص"]),
    ])
    def test_glued_packaging_decoupling(self, glued_str, expected_tokens):
        """Verifies complex concatenated packaging forms are completely separated."""
        result = pre_tokenize_pharma_string(glued_str)
        for token in expected_tokens:
            assert token in result, f"Token {token!r} missing from decoupled output: {result!r}"

    @pytest.mark.parametrize("glued_med, expected_brand", [
        ("ابيزيثرو500مجم3قرص", "epizithro"),
        ("اتراكون14كبسوله", "itracon"),
        ("اريثركس200مجم2شريط", "erythrex"),
        ("اسبرين بروتكت 100مجم3شريط", "aspirin protect"),
        ("سيتال5لبوس", "cetal"),
        ("افالوكس400مجم اقراص", "avelox"),
        ("كونكور5مجم30قرص", "concor"),
        ("بروفين400مجم3شريط", "brufen"),
        ("فلاجيل500مجم20قرص", "flagyl"),
        ("دافلون500مجم30قرص", "daflon"),
        ("كتافلام50مجم20قرص", "cataflam"),
        ("كلكسان40مجم2سرنجة", "clexane"),
        ("اماريل2مجم30قرص", "amaryl"),
        ("نيكسيوم40مجم14قرص", "nexium"),
        ("لانتوس100وحدةسولوستار", "lantus"),
    ])
    def test_extract_canonical_brand_from_glued_strings(self, glued_med, expected_brand):
        """Verifies extract_canonical_brand resolves glued real-world purchase order strings."""
        canonical = extract_canonical_brand(glued_med)
        assert canonical == expected_brand, (
            f"Failed on glued string {glued_med!r}: got {canonical!r}, expected {expected_brand!r}"
        )

    @pytest.mark.parametrize("input_str, expected_brand", [
        # Leading numbers
        ("123بانادول 500 مجم", "panadol"),
        ("001بروفين 400 مجم", "brufen"),
        ("999كتافلام 50 مجم", "cataflam"),
        # Trailing numbers
        ("بانادول 500 مجم 2026", "panadol"),
        ("بروفين 400 مجم 1234", "brufen"),
        ("كتافلام 50 مجم 99", "cataflam"),
        # Leading AND trailing numbers glued
        ("123بانادول500مجم456", "panadol"),
        ("001بروفين400مجم999", "brufen"),
    ])
    def test_leading_and_trailing_numbers_handling(self, input_str, expected_brand):
        """Verifies leading and trailing numbers do not confuse brand extraction."""
        canonical = extract_canonical_brand(input_str)
        assert canonical == expected_brand, (
            f"Failed on boundary numbered string {input_str!r}: got {canonical!r}, expected {expected_brand!r}"
        )

    @pytest.mark.parametrize("mixed_str, expected_brand", [
        # Latin brand with Arabic strength/pack
        ("Cataflam 50مجم 20قرص", "cataflam"),
        ("Panadol 500مجم 24قرص", "panadol"),
        ("Brufen 400مجم 30قرص", "brufen"),
        ("Augmentin 1جم 14قرص", "augmentin"),
        ("Voltaren 50مجم 20قرص", "voltaren"),
        ("Concor 5مجم 30قرص", "concor"),
        # Arabic brand with Latin strength/pack
        ("بانادول 500mg 24tab", "panadol"),
        ("بروفين 400mg 30tab", "brufen"),
        ("كتافلام 50mg 20tab", "cataflam"),
        ("كونكور 5mg 30tab", "concor"),
        ("فولتارين 50mg 20tab", "voltaren"),
        ("اوجمنتين 1g 14tab", "augmentin"),
    ])
    def test_mixed_arabic_latin_combinations(self, mixed_str, expected_brand):
        """Verifies mixed Arabic/Latin strings extract canonical brand cleanly."""
        canonical = extract_canonical_brand(mixed_str)
        assert canonical == expected_brand, (
            f"Failed on mixed string {mixed_str!r}: got {canonical!r}, expected {expected_brand!r}"
        )


class TestStrengthRatiosAndDecimalIntegrity:
    """Stress tests combination drug ratios (e.g. 500/125, 20/12.5/5, 1000/62.5)."""

    @pytest.mark.parametrize("ratio_str, expected_numbers", [
        ("500/125", ["500", "125"]),
        ("20/12.5/5", ["20", "12.5", "5"]),
        ("1000/62.5", ["1000", "62.5"]),
        ("160/12.5", ["160", "12.5"]),
        ("10/160/12.5", ["10", "160", "12.5"]),
        ("875/125", ["875", "125"]),
        ("400/57", ["400", "57"]),
        ("250/62.5", ["250", "62.5"]),
        ("5/1.25", ["5", "1.25"]),
    ])
    def test_pre_tokenize_preserves_ratios_and_decimals(self, ratio_str, expected_numbers):
        """Verifies pre_tokenize does not mangle decimals or split ratio tokens internally."""
        decoupled = pre_tokenize_pharma_string(ratio_str)
        # Numbers must not have intra-number spaces (e.g. '12 . 5' is a corruption)
        for num in expected_numbers:
            assert num in decoupled, f"Number {num!r} corrupted in {ratio_str!r} -> {decoupled!r}"
            # Ensure decimal points aren't separated by spaces
            if "." in num:
                parts = num.split(".")
                assert f"{parts[0]} . {parts[1]}" not in decoupled, (
                    f"Decimal split corrupted in {ratio_str!r} -> {decoupled!r}"
                )

    @pytest.mark.parametrize("ratio_med, expected_brand", [
        ("اوجمنتين 500/125 مجم اقراص", "augmentin"),
        ("Augmentin 500/125 mg tabs", "augmentin"),
        ("اوجمانتين 1000/62.5 مجم", "augmentin"),
        ("اكسفورج 10/160/12.5 مجم", "exforge"),
        ("Exforge 10/160/12.5 mg", "exforge"),
        ("كابوزيد 50/25 مجم 20 قرص", "capozide"),
        ("Capozide 50/25 mg", "capozide"),
        ("هاي بيوتك 875/125 مجم", "hibiotic"),
        ("كيورام 1000/62.5", "curam"),
        ("ميجا موكس 400/57 شراب", "megamox"),
    ])
    def test_canonical_brand_extraction_with_ratios(self, ratio_med, expected_brand):
        """Verifies ratio drugs successfully isolate the canonical brand."""
        canonical = extract_canonical_brand(ratio_med)
        assert canonical == expected_brand, (
            f"Failed on ratio medication {ratio_med!r}: got {canonical!r}, expected {expected_brand!r}"
        )


class TestBidirectionalMappingAcross50RandomBrands:
    """Stress tests bidirectional equivalence across at least 50 distinct brands."""

    def test_bidirectional_mapping_minimum_50_brands(self):
        """
        Samples >= 50 distinct brand mappings from ARABIC_TO_ENGLISH_BRANDS.
        Verifies:
          extract_canonical_brand(arabic_name) == extract_canonical_brand(english_name) == canonical_root
        """
        tested_pairs = [
            ("بانادول", "panadol"),
            ("اوجمنتين", "augmentin"),
            ("كتافلام", "cataflam"),
            ("كونكور", "concor"),
            ("بروفين", "brufen"),
            ("فلاجيل", "flagyl"),
            ("نيكسيوم", "nexium"),
            ("فولتارين", "voltaren"),
            ("انتينال", "antinal"),
            ("اماريل", "amaryl"),
            ("كريستور", "crestor"),
            ("جلوكوفاج", "glucophage"),
            ("لانتوس", "lantus"),
            ("كلارينيز", "clarinase"),
            ("تلفاست", "telfast"),
            ("زيرتك", "zyrtec"),
            ("اوترفين", "otrivin"),
            ("موبيك", "mobic"),
            ("سيردالود", "sirdalud"),
            ("كولونا", "colona"),
            ("دوفاستون", "duphaston"),
            ("سياليس", "cialis"),
            ("فياجرا", "viagra"),
            ("ليبيتور", "lipitor"),
            ("بلافيكس", "plavix"),
            ("دافلون", "daflon"),
            ("لاسيكس", "lasix"),
            ("جانوفيا", "januvia"),
            ("جالفوس", "galvus"),
            ("فورسيجا", "forxiga"),
            ("جاردينس", "jardiance"),
            ("سوبرافيت", "supravit"),
            ("كيروفيت", "kerovit"),
            ("بيتادين", "betadine"),
            ("ميبو", "mebo"),
            ("كتافاست", "catafast"),
            ("هاي بيوتك", "hibiotic"),
            ("كيورام", "curam"),
            ("ميجا موكس", "megamox"),
            ("زيثروماكس", "zithromax"),
            ("زيثرون", "zithron"),
            ("ازيثروسين", "azithrocin"),
            ("سيبروفار", "ciprofar"),
            ("يوناسين", "unasyn"),
            ("كابوزيد", "capozide"),
            ("كاردورا", "cardura"),
            ("الداكتون", "aldactone"),
            ("اندرال", "inderal"),
            ("نورفاسك", "norvasc"),
            ("تنورمين", "tenormin"),
            ("تريتاس", "tritace"),
            ("نيوروتون", "neuroton"),
            ("نيوروبيون", "neurobion"),
            ("ميلجا", "milga"),
            ("التروكسين", "eltroxin"),
            ("يوريفين", "urivin"),
            ("ديجستين", "digestin"),
            ("سبازموفري", "spasmofree"),
            ("اتراكون", "itracon"),
            ("كلكسان", "clexane"),
            ("زاريلتو", "xarelto"),
            ("اليكويس", "eliquis"),
        ]
        assert len(tested_pairs) >= 50, f"Sample set {len(tested_pairs)} must be >= 50"

        failures = []
        for ar_name, en_root in tested_pairs:
            # Test isolated names
            ar_res = extract_canonical_brand(ar_name)
            en_res = extract_canonical_brand(en_root)
            if ar_res != en_root or en_res != en_root:
                failures.append(f"Isolated: '{ar_name}' -> '{ar_res}', '{en_root}' -> '{en_res}' (expected '{en_root}')")

            # Test realistic full trade phrases
            ar_full = f"{ar_name} 500 مجم 20 قرص"
            en_full = f"{en_root.capitalize()} 500mg 20 Tablets"
            ar_full_res = extract_canonical_brand(ar_full)
            en_full_res = extract_canonical_brand(en_full)
            if ar_full_res != en_root or en_full_res != en_root:
                failures.append(f"Full phrase: '{ar_full}' -> '{ar_full_res}', '{en_full}' -> '{en_full_res}' (expected '{en_root}')")

        assert not failures, f"Bidirectional failures ({len(failures)}):\n" + "\n".join(failures[:10])
        print(f"\n[EMPIRICAL] Successfully verified bidirectional mapping across {len(tested_pairs)} distinct brands.")

    def test_random_sample_bidirectional_coverage(self):
        """Randomly draws 50 brand entries from dictionary and tests bidirectional equivalence."""
        rng = random.Random(42)
        sample_keys = rng.sample(list(ARABIC_TO_ENGLISH_BRANDS.keys()), 50)
        failures = []
        for ar_k in sample_keys:
            en_v = ARABIC_TO_ENGLISH_BRANDS[ar_k]
            ar_brand = extract_canonical_brand(ar_k)
            en_brand = extract_canonical_brand(en_v)
            if ar_brand != en_v:
                failures.append(f"Arabic '{ar_k}' mapped to '{ar_brand}', expected '{en_v}'")
            if en_brand != en_v:
                failures.append(f"English '{en_v}' mapped to '{en_brand}', expected '{en_v}'")
        assert not failures, f"Random sample failures ({len(failures)}):\n" + "\n".join(failures[:5])

    def test_transliteration_divergence_baseline_caveat(self):
        """
        Adversarial test documenting the baseline 'كلافيموكس' transliteration:
        In original 88 baseline, 'كلافيموكس' was mapped to 'klavimox' (with k).
        Verifies that 'كلافيموكس' maps to 'klavimox', and 'klavimox' maps to 'klavimox'.
        """
        assert extract_canonical_brand("كلافيموكس 1000/62.5") == "klavimox"
        assert extract_canonical_brand("Klavimox 1000/62.5mg") == "klavimox"


class TestNoiseWordsAndAdversarialBoundaryStripping:
    """Stress tests noise words, pricing updates, and boundary conditions."""

    @pytest.mark.parametrize("noisy_input, expected_brand", [
        # Standard ERP state tags
        ("بانادول 500 مجم سعر جديد", "panadol"),
        ("بانادول 500 مجم سعر قديم", "panadol"),
        ("بانادول 500 مجم س.ج", "panadol"),
        ("بانادول 500 مجم س.ق", "panadol"),
        ("بانادول 500 مجم س ج", "panadol"),
        ("بانادول 500 مجم س ق", "panadol"),
        ("بانادول 500 مجم جديد", "panadol"),
        ("بانادول 500 مجم قديم", "panadol"),
        # Multiple concatenated noise tokens
        ("بروفين 400 مجم س.ج علبة شريطين", "brufen"),
        ("كتافلام 50 مجم عرض خاص سعر جديد", "cataflam"),
        ("اوجمنتين 1 جم 14 قرص خصم نقدي", "augmentin"),
        ("كونكور 5 مجم 30 قرص محلي", "concor"),
        ("فلاجيل 500 مجم 20 قرص مستورد", "flagyl"),
        ("لانتوس 100 وحدة ثلاجة", "lantus"),
        ("دافلون 500 مجم باكت 30 قرص", "daflon"),
    ])
    def test_noise_words_do_not_prevent_brand_extraction(self, noisy_input, expected_brand):
        """Verifies noisy strings with pricing, storage, or packaging noise resolve to brand."""
        canonical = extract_canonical_brand(noisy_input)
        assert canonical == expected_brand, (
            f"Failed on noisy string {noisy_input!r}: got {canonical!r}, expected {expected_brand!r}"
        )

    def test_pure_noise_strings_yield_empty_or_no_brand_match(self):
        """Verifies strings consisting purely of noise words do not falsely match any brand."""
        pure_noises = [
            "سعر جديد",
            "سعر قديم",
            "س.ج",
            "س.ق",
            "س ج",
            "س ق",
            "جديد",
            "قديم",
            "علبة شريطين",
            "اقراص كبسولات",
            "مجم 500 100",
        ]
        for noise in pure_noises:
            res = extract_canonical_brand(noise)
            # Result must NOT match any commercial brand in ARABIC_TO_ENGLISH_BRANDS values
            assert res not in set(ARABIC_TO_ENGLISH_BRANDS.values()), (
                f"Pure noise {noise!r} falsely mapped to valid brand {res!r}"
            )

    @pytest.mark.parametrize("edge_input", [
        "",
        None,
        "   ",
        "!@#$%^&*()_+",
        ".....",
        "---",
    ])
    def test_pathological_inputs_and_null_safety(self, edge_input):
        """Verifies graceful handling of None, empty, or pure punctuation strings."""
        assert extract_canonical_brand(edge_input) == ""
        # Pre-tokenizer handles None / whitespace gracefully
        if not edge_input or not str(edge_input).strip():
            assert pre_tokenize_pharma_string(edge_input) == ""
            assert normalize_drug_text(edge_input) == ""

    def test_pure_numeric_string_fallback(self):
        """Pure numerical string (e.g. barcode) has no brand, fallback retains clean digits."""
        assert extract_canonical_brand("1234567890") == "1234567890"

    def test_large_repetitive_string_performance_and_safety(self):
        """Verifies no catastrophic backtracking or memory spikes on repeated tokens."""
        long_str = "بانادول 500 مجم " * 50
        res = extract_canonical_brand(long_str)
        assert res == "panadol"

    def test_tatweel_and_arabic_presentation_forms_in_brand(self):
        """Verifies tatweel (ـ) and presentation forms in brands are resolved."""
        # Tatweel in brand name: بـــانـــادول
        tatweel_brand = "بـــانـــادول 500 مجم"
        assert extract_canonical_brand(tatweel_brand) == "panadol"

        # Canadian Aboriginal ERP glyph decoding: ᗷ -> ب
        glyph_brand = "ᗷانادول 500 مجم"
        assert extract_canonical_brand(glyph_brand) == "panadol"
