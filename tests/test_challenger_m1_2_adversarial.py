# -*- coding: utf-8 -*-
"""
Challenger 2 Empirical Adversarial Test Suite for Milestone 1:
- Arabic reading-direction resolution
- Multi-part ratios and decimal strength preservation
- Forward Arabic tokens & Latin characters non-inversion
- Clinical safety matching (is_safe_pharmaceutical_match) false-positive & substitution prevention
- Full empirical evaluation of 571 entries from tests/fixtures/hayah_shibin.pdf

Author: Challenger M1_2 (Empirical Challenger)
"""
import os
import sys
import re
import unittest
import unicodedata
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.normalizer import (
    unreverse_arabic_text,
    is_arabic_text_reversed,
    resolve_group_arabic_direction,
    pre_tokenize_pharma_string,
    parse_dosage_and_pack,
    normalize_arabic_text,
    FORWARD_PHARMA_TOKENS,
    REVERSED_PHARMA_TOKENS,
    REVERSED_TOKEN_MAP,
)
from src.catalog_reader import (
    ProductGroup,
    TableGeometry,
    extract_item_from_group_row,
)
from src.pdf_parser import PDFCatalogParser
from src.pharma_matcher import (
    is_safe_pharmaceutical_match,
    check_strength_compatibility,
    check_modifier_compatibility,
    extract_form_category,
)


class TestAdversarialArabicReadingDirection(unittest.TestCase):
    """Stress tests Arabic reading direction resolution, palindromes, and mixed text."""

    def test_01_palindromic_names_directional_stability(self):
        """
        Palindromic and near-palindromic pharmaceutical tokens (e.g. 'نان', 'توت', 'كوك', 'ميم', 'داد')
        must not cause direction flips or corruption when appearing in forward or reversed contexts.
        """
        palindromic_forward_cases = [
            ("نان 1 لبن اطفال 400 جم", "نان 1 لبن اطفال 400 جم"),
            ("نان 2 لبن اطفال", "نان 2 لبن اطفال"),
            ("نان 3 لبن اطفال", "نان 3 لبن اطفال"),
            ("توت شراب 100 مل", "توت شراب 100 مل"),
            ("ميم شراب للاطفال", "ميم شراب للاطفال"),
            ("كوك اقراص استحلاب", "كوك اقراص استحلاب"),
        ]
        for inp, expected in palindromic_forward_cases:
            with self.subTest(input=inp):
                # When fed to unreverse with force_reverse=False (as determined by group or forward heuristics)
                out = unreverse_arabic_text(inp, force_reverse=False)
                self.assertEqual(out, expected)

                # Even with auto-detection (force_reverse=None), forward tokens like شراب/لبن/اقراص
                # must anchor the string as forward
                out_auto = unreverse_arabic_text(inp, force_reverse=None)
                self.assertEqual(out_auto, expected)

    def test_02_ambiguous_short_names_in_group_context(self):
        """
        Ambiguous short names (e.g. 'روما', 'دوف', 'سيد', 'كير', 'نوفا', 'بايو') have no intrinsic
        direction indicators. resolve_group_arabic_direction must correctly guide them based on
        group context.
        """
        # Scenario A: Group has strong reversed majority
        reversed_group_rows = [
            ["150.0", "0.20", "صرق 20 كوزنيكوليس"],  # clearly reversed
            ["45.0", "0.15", "بارش 100 سكولموف"],    # clearly reversed
            ["30.0", "0.10", "روما"],                 # ambiguous short name
            ["75.0", "0.25", "لوبما 2 كوزنيكوليس"],  # clearly reversed
        ]
        group_dir = resolve_group_arabic_direction(reversed_group_rows, name_col=2)
        self.assertEqual(group_dir, "reversed")

        # In a reversed group, ambiguous row 'روما' gets un-reversed to 'امور'
        # while reversed pharma words get cleanly un-reversed
        ambiguous_unrev = unreverse_arabic_text("روما", force_reverse=(group_dir == "reversed"))
        self.assertEqual(ambiguous_unrev, "امور")

        # Scenario B: Group has strong forward majority
        forward_group_rows = [
            ["150.0", "0.20", "سيلوكينزوك 20 قرص"],
            ["45.0", "0.15", "فلوموكس 100 شراب"],
            ["30.0", "0.10", "روما"],
            ["75.0", "0.25", "كونكور 5 مجم اقراص"],
        ]
        group_dir_fwd = resolve_group_arabic_direction(forward_group_rows, name_col=2)
        self.assertEqual(group_dir_fwd, "forward")
        ambiguous_fwd = unreverse_arabic_text("روما", force_reverse=(group_dir_fwd == "reversed"))
        self.assertEqual(ambiguous_fwd, "روما")

    def test_03_mixed_arabic_english_complex_punctuation(self):
        """
        Mixed Arabic/English names with parentheses, slashes, brackets, hyphens, and plus signs
        must retain Latin word order, cleanly decouple units, and not invert inner terms.
        """
        test_cases = [
            (
                "Augmentin (1g) / اوجمنتين 1 جم 14 قرص",
                ["augmentin", "1", "g", "اوجمنتين", "1", "جم", "14", "قرص"]
            ),
            (
                "Panadol - بنادول (Advance) 500mg",
                ["panadol", "بنادول", "advance", "500", "mg"]
            ),
            (
                "C-Retard [500mg] سي-ريتارد 10 كبسولات",
                ["c", "retard", "500", "mg", "سي", "ريتارد", "10", "كبسولات"]
            ),
            (
                "Omega 3 Plus (اوميجا 3 بلس) 30 cap/كبسولة",
                ["omega", "3", "plus", "اوميجا", "3", "بلس", "30"]
            ),
            (
                "B-Complex + Iron (ب-كومبلكس + حديد)",
                ["b", "complex", "iron", "كومبلكس", "حديد"]
            ),
            (
                "Vitamin C 1000mg / فيتامين ج 1000 مجم",
                ["vitamin", "c", "1000", "mg", "فيتامين", "ج", "1000", "مجم"]
            )
        ]
        for raw_text, required_subtokens in test_cases:
            with self.subTest(raw_text=raw_text):
                unrev = unreverse_arabic_text(raw_text, force_reverse=False)
                for tok in required_subtokens:
                    self.assertIn(
                        tok.lower(),
                        unrev.lower(),
                        f"Token {tok!r} missing or corrupted in unreversed output: {unrev!r}"
                    )
                # Verify Latin words are NOT reversed (e.g. nitnemguA, lodanaP)
                self.assertNotIn("nitnemgua", unrev.lower())
                self.assertNotIn("lodanap", unrev.lower())
                self.assertNotIn("ecnavda", unrev.lower())

    def test_04_forward_arabic_tokens_never_reversed(self):
        """
        Ensures that forward Arabic tokens (شراب, اقراص, كبسول, نقط, مرهم, كريم, فوار, لبوس, امبول, شريط)
        are NEVER reversed into (بارش, صارقا, لوسبك, نقط, ميرك, لوبما, طيرش) under auto-detection.
        """
        forward_pharma_phrases = [
            "كونكور 5 مجم 30 قرص",
            "كونكور 5 مجم 30 اقراص",
            "بروفين 400 مجم شراب للاطفال",
            "اوميباك 20 مجم 14 كبسولة",
            "فيوسيدين 2% مرهم 15 جم",
            "فيوسيكورت كريم 15 جم",
            "فيتاسيد ج فوار 12 كيس",
            "دولفين 12.5 مجم لبوس اطفال",
            "فيسيرالجين 3 امبول",
            "سيتال 100 مجم نقط للفم",
            "الفينترن 3 شريط 30 قرص",
        ]
        for phrase in forward_pharma_phrases:
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    is_arabic_text_reversed(phrase),
                    f"Forward phrase wrongly identified as reversed: {phrase}"
                )
                res = unreverse_arabic_text(phrase)
                # Ensure no reversed tokens exist in the output
                for rev_tok in ['بارش', 'صارقا', 'صرق', 'لوسبك', 'ميرك', 'لوبما', 'طيرش']:
                    self.assertNotIn(
                        f" {rev_tok} ",
                        f" {res} ",
                        f"Forward text produced reversed token {rev_tok!r}: {res!r}"
                    )


class TestAdversarialMultipartRatiosAndDecimals(unittest.TestCase):
    """Stress tests multi-part ratios, tripartite ratios, and decimal strengths."""

    def test_01_multipart_ratios_preservation(self):
        """
        Verify that multi-part ratios: 50/1000, 10/40/25, 160/12.5, 50/250, 642.9, 0.25
        remain exactly intact across unreverse, pre_tokenize, and clinical checks.
        """
        ratio_cases = [
            ("جليبتس 50/1000 مجم 30 قرص", "50/1000"),
            ("كوفرسيل 10/40/25 مجم 30 قرص", "10/40/25"),
            ("اكسفورج 160/12.5 مجم 28 قرص", "160/12.5"),
            ("سيريتيد 50/250 بخاخ", "50/250"),
            ("اوروجلو 642.9 مجم 10 اكياس", "642.9"),
            ("ديجوكسين 0.25 مجم 100 قرص", "0.25"),
        ]
        for text, ratio_str in ratio_cases:
            with self.subTest(ratio=ratio_str):
                # 1. unreverse preserves ratio
                unrev = unreverse_arabic_text(text)
                self.assertIn(ratio_str, unrev, f"Ratio {ratio_str} corrupted in unreverse: {unrev}")

                # 2. pre_tokenize does not break the ratio numbers apart with spaces
                pre = pre_tokenize_pharma_string(text)
                clean_pre_no_space = pre.replace(" ", "")
                self.assertIn(ratio_str.replace(" ", ""), clean_pre_no_space)

    def test_02_arabic_comma_decimal_normalization(self):
        """
        Arabic comma (٫ - U+066B) used in decimal strengths (160٫12٫5, 12٫5, 0٫25) must be
        cleanly normalized to ASCII decimal point '.' and preserved.
        """
        arabic_decimal_cases = [
            ("اكسفورج 160/12٫5 مجم", "160/12.5"),
            ("دولفين 12٫5 مجم لبوس", "12.5"),
            ("ديجوكسين 0٫25 مجم", "0.25"),
            ("اوروجلو 642٫9 مجم", "642.9"),
        ]
        for inp, expected_sub in arabic_decimal_cases:
            with self.subTest(inp=inp):
                unrev = unreverse_arabic_text(inp)
                self.assertIn(expected_sub, unrev, f"Arabic decimal not normalized in {unrev}")

    def test_03_ratio_clinical_matching_safety(self):
        """
        check_strength_compatibility must correctly match matching ratios and
        reject different ratios (e.g. 50/1000 vs 50/500, 160/12.5 vs 160/25).
        """
        # Matching ratios (even if catalog reverses slash order)
        self.assertTrue(check_strength_compatibility("جليبتس 50/1000", "جليبتس 50/1000"))
        self.assertTrue(check_strength_compatibility("جليبتس 50/1000", "جليبتس 1000/50"))
        self.assertTrue(check_strength_compatibility("كوفرسيل 10/40/25", "كوفرسيل 10/40/25"))
        self.assertTrue(check_strength_compatibility("كوفرسيل 10/40/25", "كوفرسيل 25/40/10"))
        self.assertTrue(check_strength_compatibility("اكسفورج 160/12.5", "اكسفورج 160/12.5"))
        self.assertTrue(check_strength_compatibility("اكسفورج 160/12.5", "اكسفورج 12.5/160"))

        # Incompatible ratios (MUST BE FALSE)
        self.assertFalse(check_strength_compatibility("جليبتس 50/1000", "جليبتس 50/500"))
        self.assertFalse(check_strength_compatibility("جليبتس 50/1000", "جليبتس 50/850"))
        self.assertFalse(check_strength_compatibility("كوفرسيل 10/40/25", "كوفرسيل 10/40/12.5"))
        self.assertFalse(check_strength_compatibility("كوفرسيل 10/40/25", "كوفرسيل 5/20/12.5"))
        self.assertFalse(check_strength_compatibility("اكسفورج 160/12.5", "اكسفورج 160/25"))
        self.assertFalse(check_strength_compatibility("اكسفورج 160/12.5", "اكسفورج 80/12.5"))
        self.assertFalse(check_strength_compatibility("ديجوكسين 0.25", "ديجوكسين 0.125"))


class TestAdversarialClinicalMatchingSafety(unittest.TestCase):
    """
    Stress tests is_safe_pharmaceutical_match to ensure:
    1. Zero cross-form substitutions (syrup vs tablets, injection vs oral, drops vs cream).
    2. Zero dangerous strength mismatches (1g vs 500mg).
    3. Reversal-aware matching matches exact reversed partners without false positives.
    4. Sound-alike and look-alike distinct drugs never match.
    """

    def test_01_cross_form_substitution_prevention(self):
        """Cross-form matching must be strictly rejected (False)."""
        cross_forms = [
            ("كونكور 5 مجم اقراص", "كونكور 5 مجم شراب"),
            ("كونكور 5 مجم اقراص", "كونكور 5 مجم نقط"),
            ("فولتارين 75 مجم امبول", "فولتارين 50 مجم اقراص"),
            ("بروفين 400 مجم اقراص", "بروفين 100 مجم شراب"),
            ("بانثينول كريم 50 جم", "بانثينول شامبو 200 مل"),
            ("بيتادين غسول 120 مل", "بيتادين مرهم 60 جم"),
            ("اوترفين نقط انف اطفال", "اوترفين بخاخ انف"),
            ("دولفين 12.5 مجم لبوس", "دولفين 12.5 مجم اقراص"),
            ("سيبروسين نقط عين", "سيبروسين اقراص 500 مجم"),
        ]
        for req, cand in cross_forms:
            with self.subTest(req=req, cand=cand):
                self.assertFalse(
                    is_safe_pharmaceutical_match(req, cand),
                    f"Dangerous cross-form match permitted: {req!r} vs {cand!r}"
                )

    def test_02_dangerous_strength_mismatch_prevention(self):
        """Dangerous clinical strength mismatches must be rejected."""
        strength_mismatches = [
            ("فلوموكس 1جم", "فلوموكس 500 مجم كبسول"),
            ("كونكور 5 مجم", "كونكور 10 مجم"),
            ("كونكور 2.5 مجم", "كونكور 5 مجم"),
            ("كابوتن 25 مجم", "كابوتن 50 مجم"),
            ("سيلوكينزوك 50 مجم", "سيلوكينزوك 100 مجم"),
            ("داونيبل 5 مجم", "داونيبل 2.5 مجم"),
            ("جليباميد 5 مجم", "جليباميد 2.5 مجم"),
            ("التروكسين 50 ميكروجرام", "التروكسين 100 ميكروجرام"),
            ("تجريتول 200 مجم", "تجريتول 400 مجم"),
        ]
        for req, cand in strength_mismatches:
            with self.subTest(req=req, cand=cand):
                self.assertFalse(
                    is_safe_pharmaceutical_match(req, cand),
                    f"Dangerous strength mismatch permitted: {req!r} vs {cand!r}"
                )

    def test_03_formulation_modifier_compatibility(self):
        """Modifiers like Extra, Plus, Rapid, Cold & Flu, SR/XR must prevent false matches."""
        modifier_mismatches = [
            ("بانادول 500 مجم", "بانادول اكسترا 500 مجم"),
            ("بانادول اكسترا", "بانادول كولد اند فلو"),
            ("كونكور 5 مجم", "كونكور بلس 5 مجم"),
            ("كيتوفان 50 مجم", "كيتوفان اس ار 200 مجم"),
            ("كتافلام 50 مجم", "كتافاست فوار"),
            ("سيتال 500 مجم", "سيتال كولد اند فلو"),
        ]
        for req, cand in modifier_mismatches:
            with self.subTest(req=req, cand=cand):
                self.assertFalse(
                    is_safe_pharmaceutical_match(req, cand),
                    f"Formulation modifier mismatch permitted: {req!r} vs {cand!r}"
                )

    def test_04_reversed_candidate_safety_and_precision(self):
        """
        When candidate name is reversed in catalog:
        - Exact matches (reversed brand + matching strength + matching form) MUST match.
        - Reversed candidate with wrong strength or wrong form MUST NOT match.
        """
        # Exact reversed partners that MUST match (Authoritative request §R2):
        self.assertTrue(
            is_safe_pharmaceutical_match("دافاليندي 200000 وحده 2 امبول", "لوبما 2 هدحو 200000 يدنيلافاد")
        )
        self.assertTrue(
            is_safe_pharmaceutical_match("سيلوكينزوك 50 مجم 28 قرص س ج", "مجم 50 كوزنيكوليس")
        )

        # Reversed candidate with wrong strength MUST NOT match:
        self.assertFalse(
            is_safe_pharmaceutical_match("دافاليندي 200000 وحده 2 امبول", "لوبما 2 هدحو 100000 يدنيلافاد")
        )
        self.assertFalse(
            is_safe_pharmaceutical_match("سيلوكينزوك 50 مجم 28 قرص س ج", "مجم 100 كوزنيكوليس")
        )

        # Reversed candidate with wrong form MUST NOT match:
        self.assertFalse(
            is_safe_pharmaceutical_match("فلوموكس 500 مجم كبسول", "بارش 100 سكولموف")
        )
        self.assertFalse(
            is_safe_pharmaceutical_match("سيلوكينزوك 50 مجم قرص", "لوبما 2 كوزنيكوليس 50")
        )

    def test_05_sound_alike_look_alike_brand_rejection(self):
        """Distinct pharmaceutical brands with similar spelling must never match."""
        distinct_brands = [
            ("اميوران 50 مجم", "امريزول 500 مجم"),
            ("داونيبل 5 مجم", "دياموكرون 30 مجم"),
            ("فلوتاك 75 مجم", "فولتارين 75 مجم"),
            ("جليبتس 50 مجم", "جليمبريد 2 مجم"),
            ("اتور 20 مجم", "اتورفا 20 مجم"),
            ("بريدسول شراب", "بريدنيسولون اقراص"),
            ("زانتاك 150 مجم", "زانتيدين 150 مجم"),
            ("كونكور 5 مجم", "كوردارون 200 مجم"),
            ("كابوتن 25 مجم", "كاردورا 1 مجم"),
            ("بلافيكس 75 مجم", "بلاسيل 10 مجم"),
            ("لازكس 40 مجم", "لوبريسور 50 مجم"),
        ]
        for req, cand in distinct_brands:
            with self.subTest(req=req, cand=cand):
                self.assertFalse(
                    is_safe_pharmaceutical_match(req, cand),
                    f"Distinct brand substitution permitted: {req!r} vs {cand!r}"
                )


class TestAdversarialHayahShibinFullEmpirical(unittest.TestCase):
    """
    Exhaustive empirical analysis across all 571 extracted records from tests/fixtures/hayah_shibin.pdf:
    - 100% item count verification (exactly 571 items)
    - Diagnostic completeness (0 rejected, 0 unprocessed, status complete)
    - Price and discount validity: 0 price <= 0, 0 discount < 0 or > 0.85
    - Price/discount inversion check: NO base_price < discount_rate
    - Clean names: 0 residual reversed tokens across all 571 items
    - Spot checks on 5 required items across pages and groups
    """

    @classmethod
    def setUpClass(cls):
        cls.fixture_path = os.path.join(PROJECT_ROOT, "tests", "fixtures", "hayah_shibin.pdf")
        assert os.path.isfile(cls.fixture_path), f"Fixture not found at {cls.fixture_path}"
        cls.parser = PDFCatalogParser(cls.fixture_path)
        cls.df = cls.parser.parse()
        cls.diag = cls.df.attrs.get("catalog_import")

    def test_01_total_item_count_and_diagnostics(self):
        """Verify exactly 571 items with complete diagnostics."""
        self.assertEqual(len(self.df), 571, "Must extract exactly 571 unique records")
        self.assertIsNotNone(self.diag, "CatalogResult metadata must be attached")
        self.assertEqual(self.diag.status, "complete")
        self.assertEqual(self.diag.candidate_rows, 571)
        self.assertEqual(self.diag.accepted_rows, 571)
        self.assertEqual(self.diag.unique_records, 571)
        self.assertEqual(self.diag.duplicate_records, 0)
        self.assertEqual(self.diag.rejected_rows, 0)
        self.assertEqual(self.diag.unprocessed_rows, 0)

    def test_02_per_page_and_per_group_counts(self):
        """Per-page counts must be 141/141/141/141/7 and per-group counts 47/47/47 on pages 1-4 and 7/0/0 on page 5."""
        pages = self.diag.diagnostics.pages
        self.assertEqual(len(pages), 5)
        p_counts = [p.accepted_rows for p in pages]
        self.assertEqual(p_counts, [141, 141, 141, 141, 7], f"Unexpected per-page counts: {p_counts}")
        for p_idx in range(4):
            g_counts = [g.accepted_rows for g in pages[p_idx].groups]
            self.assertEqual(g_counts, [47, 47, 47], f"Page {p_idx+1} group counts not 47/47/47: {g_counts}")
        p5_g_counts = [g.accepted_rows for g in pages[4].groups]
        self.assertEqual(p5_g_counts[0], 7)

    def test_03_price_discount_bounds_and_no_inversions(self):
        """
        Verify no prices <= 0 or > 10,000.
        Verify no discounts < 0 or > 0.85 (85%).
        Verify no inversions where discount rate exceeds base price (discount_rate > base_price).
        """
        prices = self.df["base_price"].tolist()
        discounts = self.df["discount_rate"].tolist()

        for idx, (p, d) in enumerate(zip(prices, discounts)):
            self.assertGreater(p, 0.0, f"Row {idx} has invalid price <= 0: {p}")
            self.assertLessEqual(p, 10000.0, f"Row {idx} has unreasonably high price: {p}")
            self.assertGreaterEqual(d, 0.0, f"Row {idx} has negative discount: {d}")
            self.assertLessEqual(d, 0.85, f"Row {idx} has discount > 85%: {d}")
            # Ensure price and discount are not swapped / inverted
            self.assertGreater(
                p, d,
                f"Row {idx} has price/discount inversion: price={p}, discount={d}"
            )

    def test_04_extracted_names_are_clean_no_residual_reversed_tokens(self):
        """
        Verify that 100% of extracted names are clean Arabic/Latin strings,
        with 0 occurrences of known reversed tokens (صرق, طيرش, لوسبك, صارقا, ميرك, لوبما, هدحو, رعس, مصخ).
        """
        forbidden_rev_tokens = {'صرق', 'طيرش', 'لوسبك', 'صارقا', 'ميرك', 'لوبما', 'هدحو', 'رعس', 'مصخ'}
        for idx, name in enumerate(self.df["item_name"].tolist()):
            words = set(re.findall(r'[\u0600-\u06ff]+', name))
            intersection = words & forbidden_rev_tokens
            self.assertEqual(
                intersection, set(),
                f"Row {idx} contains residual reversed tokens {intersection} in name: {name!r}"
            )
            # Ensure name length >= 2
            self.assertGreaterEqual(len(name.strip()), 2, f"Row {idx} has name too short: {name!r}")

    def test_05_spot_check_five_golden_items(self):
        """Verify the 5 required spot-check items across pages and groups match exact price/discount."""
        spot_checks = [
            ("ابياموكس 400 مجم شراب", 70.0, 0.36),
            ("الزنتال 6 قرص", 33.0, 0.36),
            ("اوميباك 20 مجم 14 كبسول", 50.0, 0.41),  # or كبسوله
            ("جليبتس 50/1000 مجم ك 30", 192.0, 0.32),
            ("يورينكس كبسول", 66.0, 0.28),
        ]
        for name_sub, expected_price, expected_disc in spot_checks:
            matched_rows = self.df[self.df["item_name"].str.contains(name_sub[:8])]
            self.assertFalse(
                matched_rows.empty,
                f"Spot check item not found in extracted catalog: {name_sub}"
            )
            found = False
            for _, r in matched_rows.iterrows():
                if abs(r["base_price"] - expected_price) < 0.01 and abs(r["discount_rate"] - expected_disc) < 0.01:
                    found = True
                    break
            self.assertTrue(
                found,
                f"Spot check {name_sub} failed: expected price {expected_price}, discount {expected_disc}. Rows: {matched_rows[['item_name', 'base_price', 'discount_rate']]}"
            )


if __name__ == "__main__":
    unittest.main()
