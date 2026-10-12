# -*- coding: utf-8 -*-
"""
Empirical Adversarial Test Suite for Milestone M3
Challenger M3_1 gen2
"""
import pytest
from src.normalizer import (
    ARABIC_TO_ENGLISH_BRANDS,
    extract_canonical_brand,
    normalize_drug_text,
)
from src.pharma_matcher import (
    extract_form_category,
    is_safe_pharmaceutical_match,
)


class TestBrandFalsePositivesAndTokenAnchoring:
    """Adversarially test brand normalization against potential false positives."""

    def test_cetapronex_not_ronex(self):
        """Verify that 'سيتابرونكس' extracts as 'cetapronex' and NOT 'ronex'."""
        brand = extract_canonical_brand('سيتابرونكس')
        assert brand == 'cetapronex', f"Expected 'cetapronex', got '{brand}'"
        assert brand != 'ronex', "False positive collision: 'سيتابرونكس' extracted as 'ronex'!"

        brand_full = extract_canonical_brand('سيتابرونكس 10 مجم اقراص')
        assert brand_full == 'cetapronex', f"Expected 'cetapronex', got '{brand_full}'"
        assert brand_full != 'ronex'

        # Also verify ronex itself still extracts as ronex
        brand_ronex = extract_canonical_brand('رونكس')
        assert brand_ronex == 'ronex', f"Expected 'ronex', got '{brand_ronex}'"
        brand_ronex_full = extract_canonical_brand('رونكس دش مهبلي 250 مل')
        assert brand_ronex_full == 'ronex'

    def test_generic_escitalopram_not_cetal(self):
        """Verify that generic 'اسيتالوبرام' does NOT falsely extract as 'cetal'."""
        brand = extract_canonical_brand('اسيتالوبرام')
        assert brand != 'cetal', f"False positive collision: 'اسيتالوبرام' extracted as 'cetal'!"

        brand_full = extract_canonical_brand('اسيتالوبرام 10 مجم اقراص')
        assert brand_full != 'cetal', f"False positive collision: 'اسيتالوبرام 10 مجم اقراص' extracted as 'cetal'!"

        # And verify cetal itself extracts as cetal
        brand_cetal = extract_canonical_brand('سيتال')
        assert brand_cetal == 'cetal', f"Expected 'cetal', got '{brand_cetal}'"
        brand_cetal_full = extract_canonical_brand('سيتال 500 مجم 20 قرص')
        assert brand_cetal_full == 'cetal'

    def test_granitron_not_rani(self):
        """Verify that 'جرانيترون' does NOT falsely extract as 'rani'."""
        brand = extract_canonical_brand('جرانيترون')
        assert brand != 'rani', f"False positive collision: 'جرانيترون' extracted as 'rani'!"

        brand_full = extract_canonical_brand('جرانيترون 1 مجم امبول')
        assert brand_full != 'rani', f"False positive collision: 'جرانيترون 1 مجم امبول' extracted as 'rani'!"

        # And verify rani itself extracts as rani
        brand_rani = extract_canonical_brand('راني')
        assert brand_rani == 'rani', f"Expected 'rani', got '{brand_rani}'"
        brand_rani_full = extract_canonical_brand('فوار راني اكياس')
        assert brand_rani_full == 'rani'

    @pytest.mark.parametrize("input_text,expected_brand", [
        ('والسيتال', 'cetal'),
        ('بالسيتال', 'cetal'),
        ('الراني', 'rani'),
        ('والراني', 'rani'),
        ('بالراني', 'rani'),
        ('والبانادول', 'panadol'),
        ('بالبانادول', 'panadol'),
        ('البانادول', 'panadol'),
        ('والكونكور', 'concor'),
        ('بالكونكور', 'concor'),
        ('الكونكور', 'concor'),
        ('والبروفين', 'brufen'),
        ('بالبروفين', 'brufen'),
        ('البروفين', 'brufen'),
        ('والجانوميت', 'janumet'),
        ('بالجانوميت', 'janumet'),
        ('الجانوميت', 'janumet'),
    ])
    def test_arabic_prefixes_resolve_to_canonical_brand(self, input_text, expected_brand):
        """Verify that Arabic prefixes like 'والسيتال', 'بالسيتال', 'الراني' still resolve correctly."""
        brand = extract_canonical_brand(input_text)
        assert brand == expected_brand, f"Failed for '{input_text}': expected '{expected_brand}', got '{brand}'"


class TestClinicalSafetyGateCrossFormSubstitutions:
    """Verify that is_safe_pharmaceutical_match blocks dangerous cross-form substitutions."""

    def test_tablet_vs_douche_blocked(self):
        """Solid oral vs vaginal douche must be blocked."""
        # Cetapronex tab vs Ronex douche
        assert not is_safe_pharmaceutical_match(
            'سيتابرونكس 10مجم اقراص', 'رونكس دش مهبلي 250 مل'
        ), "Safety gate failed to block Cetapronex tab vs Ronex douche!"

        # Same brand name simulated tablet vs douche
        assert not is_safe_pharmaceutical_match(
            'سيتال 500 مجم اقراص', 'سيتال دش مهبلي'
        ), "Safety gate failed to block tablet vs douche with same brand root!"

    def test_tablet_vs_injectable_blocked(self):
        """Solid oral vs injectable must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'بانادول 500 مجم اقراص', 'بانادول 500 مجم امبول'
        ), "Safety gate failed to block tablet vs injectable!"

        assert not is_safe_pharmaceutical_match(
            'كتافلام 50 مجم اقراص', 'كتافلام 75 مجم امبول'
        ), "Safety gate failed to block tablet vs injectable!"

        assert not is_safe_pharmaceutical_match(
            'فولتارين 50 مجم اقراص', 'فولتارين 75 مجم حقن'
        ), "Safety gate failed to block tablet vs ampoule/injection!"

    def test_oral_liquid_vs_tablet_blocked(self):
        """Oral syrup vs tablet must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'بروفين 100 مجم شراب', 'بروفين 400 مجم اقراص'
        ), "Safety gate failed to block syrup vs tablets!"

        assert not is_safe_pharmaceutical_match(
            'سيتال شراب 120 مل', 'سيتال 500 مجم اقراص'
        ), "Safety gate failed to block syrup vs tablets!"

    def test_drops_vs_injectable_or_tablet_blocked(self):
        """Drops vs injectable or oral tablets must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'سيتال نقط للفم', 'سيتال 500 مجم اقراص'
        ), "Safety gate failed to block oral drops vs tablets!"

        assert not is_safe_pharmaceutical_match(
            'اوتروفين نقط للانف', 'اوتروفين امبول'
        ), "Safety gate failed to block drops vs ampoules!"

    def test_cream_or_gel_vs_oral_or_injectable_blocked(self):
        """Topical cream/gel vs oral/injectable must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'فولتارين جل', 'فولتارين 75 مجم امبول'
        ), "Safety gate failed to block gel vs injectable!"

        assert not is_safe_pharmaceutical_match(
            'فوسيكورت كريم', 'فوسيكورت اقراص'
        ), "Safety gate failed to block cream vs tablets!"

    def test_suppository_vs_tablet_blocked(self):
        """Suppository vs tablet must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'دولفين 12.5 مجم لبوس', 'دولفين 12.5 مجم اقراص'
        ), "Safety gate failed to block suppository vs tablet!"

    def test_sachet_vs_injectable_blocked(self):
        """Effervescent/sachet vs injectable must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'فوار راني اكياس', 'راني امبول'
        ), "Safety gate failed to block sachet vs ampoule!"

    def test_strict_dosage_form_vs_unknown_blocked(self):
        """Strict forms (INJECTABLE, DOUCHE, INFANT_MILK, DROPS, ORAL_LIQUID) cannot match UNKNOWN."""
        # Injectable vs unknown
        assert not is_safe_pharmaceutical_match(
            'امبول سيتال', 'سيتال'
        ), "Injectable must NOT match UNKNOWN form!"

        # Douche vs unknown
        assert not is_safe_pharmaceutical_match(
            'دش مهبلي رونكس', 'رونكس'
        ), "Douche must NOT match UNKNOWN form!"

        # Infant milk vs unknown (formula not recognized in candidate)
        assert not is_safe_pharmaceutical_match(
            'لبن نيوكيت 1 400 جم', 'نيوكيت'
        ), "Infant milk must NOT match UNKNOWN form!"

    def test_prefixed_brand_order_reconciliation(self):
        """Arabic prefixed orders must match catalog items."""
        assert is_safe_pharmaceutical_match(
            'والسيتال 500 مجم اقراص', 'سيتال 500 مجم اقراص'
        ), "'والسيتال' order should match 'سيتال' catalog offer!"

        assert is_safe_pharmaceutical_match(
            'بالسيتال 500 مجم اقراص', 'سيتال 500 مجم اقراص'
        ), "'بالسيتال' order should match 'سيتال' catalog offer!"

    def test_infant_milk_stage_mismatch_blocked(self):
        """Infant milk stage 1 vs stage 2 or 3 must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'لبن نان 1 400 جم', 'لبن نان 2 400 جم'
        ), "Infant milk stage 1 vs 2 must be blocked!"

        assert not is_safe_pharmaceutical_match(
            'لبن بيبيلاك 1', 'لبن بيبيلاك 3'
        ), "Infant milk stage 1 vs 3 must be blocked!"

    def test_valid_same_form_matches_pass(self):
        """Clinically valid matches with compatible forms and strengths must pass."""
        assert is_safe_pharmaceutical_match(
            'بانادول 500 مجم اقراص', 'Panadol 500mg 24 Tab'
        ), "Identical brand, form, and strength should match!"

        assert is_safe_pharmaceutical_match(
            'كونكور 5 مجم اقراص', 'concor 5mg 30 tab'
        ), "Identical brand, form, and strength should match!"

        assert is_safe_pharmaceutical_match(
            'جانوميت 50/1000 مجم 56 قرص', 'Janumet 50/1000mg 56 Tab'
        ), "Janumet combo strength and tablets should match!"

        assert is_safe_pharmaceutical_match(
            'سيتابرونكس 10مجم اقراص', 'cetapronex 10 mg tab'
        ), "Cetapronex tablets should match!"

    def test_strength_ratio_mismatch_blocked(self):
        """Combination strength ratio mismatches (e.g. 50/1000 vs 50/500) must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'جانوميت 50/1000 مجم 56 قرص', 'جانوميت 50/500 مجم 56 قرص'
        ), "Safety gate failed to block Janumet 50/1000 vs 50/500 mismatch!"

    def test_single_strength_mismatch_blocked(self):
        """Single active ingredient strength mismatch (e.g. 1g vs 625mg) must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'اوجمنتين 1 جم اقراص', 'اوجمنتين 625 مجم اقراص'
        ), "Safety gate failed to block Augmentin 1g vs 625mg mismatch!"

        assert not is_safe_pharmaceutical_match(
            'كتافلام 50 مجم اقراص', 'كتافلام 25 مجم اقراص'
        ), "Safety gate failed to block Cataflam 50mg vs 25mg mismatch!"

    def test_modifier_mismatch_blocked(self):
        """Modifier mismatches (Extra, Forte, XR) must be blocked."""
        assert not is_safe_pharmaceutical_match(
            'بانادول اكسترا اقراص', 'بانادول اقراص'
        ), "Safety gate failed to block Panadol Extra vs regular Panadol!"

    def test_digestin_vs_spasmodigestin_blocked(self):
        """Plain digestive enzymes (Digestin) must NOT match anticholinergic combination (Spasmo-digestin)."""
        assert not is_safe_pharmaceutical_match(
            'ديجستين 20 قرص', 'سبازموديجستين اقراص سعر 78 باكو 90'
        ), "Digestin must NEVER match Spasmodigestin!"
        assert not is_safe_pharmaceutical_match(
            'سبازموديجستين اقراص', 'ديجستين 20 قرص'
        ), "Spasmodigestin must NEVER match Digestin!"

    def test_cetal_vs_citalo_blocked(self):
        """Paracetamol analgesic/antipyretic (Cetal) must NEVER match Citalopram SSRI (Citalo / Citalopram)."""
        assert not is_safe_pharmaceutical_match(
            'سيتال نقط', 'سيتالو 40 مجم 30 قراص باكو 180'
        ), "Cetal drops must NEVER match Citalo 40mg tablets!"
        assert not is_safe_pharmaceutical_match(
            'سيتال 500 مجم اقراص', 'سيتالو 40 مجم اقراص'
        ), "Cetal paracetamol must NEVER match Citalo citalopram!"

    def test_compound_slash_form_inheritance(self):
        """Compound request with slash (e.g. Drafocal syrup / Osteocare) must inherit form category."""
        assert not is_safe_pharmaceutical_match(
            'درافوكال شراب/اوستيوكير', 'اوستيوكير اقراص سعر 180 باكو 100 جديد'
        ), "Syrup slash request must NEVER match tablets!"
        assert is_safe_pharmaceutical_match(
            'درافوكال شراب/اوستيوكير', 'اوستيوكير شراب باكت 25 ارضي'
        ), "Syrup slash request MUST match syrup offer!"

    def test_gripe_water_oral_liquid_match(self):
        """Paediatric gripe water is intrinsically oral liquid / syrup."""
        assert is_safe_pharmaceutical_match(
            'ماء غريب سمايل', 'ماء غريب شراب سمايل **باكو 25'
        ), "Gripe water should match gripe water syrup offer!"

    def test_limitless_product_line_separation(self):
        """Distinct nutritional lines within umbrella brand (Limitless) must not cross-substitute."""
        assert not is_safe_pharmaceutical_match(
            'ليمتلس اوميجا 3 فيش اويل', 'ليمتلس بيبي د ** نقط سعر 60 ج'
        ), "Limitless Omega 3 must NEVER match Limitless Baby D!"
        assert not is_safe_pharmaceutical_match(
            'ليمتلس ماغنسيوم 30 قرص', 'ليمتلس اوميجا 3 فيش اويل'
        ), "Limitless Magnesium must NEVER match Limitless Omega!"

    def test_cosmetic_roll_on_vs_gel_blocked(self):
        """Cosmetic roll-on must NEVER match topical gel."""
        assert not is_safe_pharmaceutical_match(
            'ستارفيل رول اون اورينت بيرل س ج/بني', 'ستارفيل جيل حمايه للبشره 200 مل'
        ), "Roll-on deodorant must NEVER match skin protection gel!"

    def test_infant_milk_lf_vs_ha_blocked(self):
        """Lactose-free (LF) infant formula must NEVER match Hypoallergenic (HA) formula."""
        assert not is_safe_pharmaceutical_match(
            'لبن هيرو بيبي ال اف', 'هيرو بيبي اتش ايه باكو 12'
        ), "Hero Baby LF must NEVER match Hero Baby HA!"
        assert not is_safe_pharmaceutical_match(
            'هيرو بيبي اتش ايه', 'لبن هيرو بيبي ال اف'
        ), "Hero Baby HA must NEVER match Hero Baby LF!"
        assert is_safe_pharmaceutical_match(
            'لبن هيرو بيبي ال اف', 'هيرو بيبي ال اف باكو 12'
        ), "Hero Baby LF MUST match Hero Baby LF offer!"

    def test_infant_milk_stages_and_types_integrity(self):
        """Infant milk stages (1, 2, 3) and therapeutic formulas (AR, Pre) must never cross-substitute."""
        assert not is_safe_pharmaceutical_match('هيرو بيبي 1', 'هيرو بيبي 2 باكو 12')
        assert not is_safe_pharmaceutical_match('هيرو بيبي 1', 'هيرو بيبي اتش ايه باكو 12')
        assert not is_safe_pharmaceutical_match('لبن بيبيلاك ايه ار', 'بيبيلاك 1 باكو 12')
        assert not is_safe_pharmaceutical_match('لبن نان بري 400 جم', 'نان 1 اوبتي برو')
        assert is_safe_pharmaceutical_match('لبن نان 1 اوبتي برو', 'نان 1 اوبتي برو باكت 24')
        assert is_safe_pharmaceutical_match('لبن نستوجين 2', 'نستوجين 2 باكت 12')

    def test_cream_vs_ointment_blocked(self):
        """Topical cream and ointment are strictly non-interchangeable dermatological formulations."""
        assert not is_safe_pharmaceutical_match(
            'فيوسي 15 جم كريم', 'فيوسي مرهم كبير*** باكو 64'
        ), "Fucy cream must NEVER match Fucy ointment!"
        assert not is_safe_pharmaceutical_match(
            'فيوسي 30 جم كريم', 'فيوسي مرهم كبير*** باكو 64'
        ), "Fucy cream must NEVER match Fucy ointment!"
        assert not is_safe_pharmaceutical_match(
            'بيتاديرم مرهم', 'بيتاديرم كريم صغير باكو 200'
        ), "Betaderm ointment must NEVER match Betaderm cream!"
        assert not is_safe_pharmaceutical_match(
            'بيتاديرم كريم', 'بيتاديرم مرهم باكو 100'
        ), "Betaderm cream must NEVER match Betaderm ointment!"

    def test_cream_to_cream_matched(self):
        """Topical cream correctly matches valid cream catalog offers."""
        assert is_safe_pharmaceutical_match('فيوسي 15 جم كريم', 'فيوسي كريم باكو 60')
        assert is_safe_pharmaceutical_match('فيوسي 30 جم كريم', 'فيوسي كريم كبيررر 5 باكت 64')

    def test_panthenol_brand_isolation(self):
        """Hepta Panthenol must not collide with NP7 Panthenol or generic Panthenol."""
        assert not is_safe_pharmaceutical_match(
            'هيبتا بانثينول كريم جلد', 'ين يي سفن بانثينول كريم %10 50 جم'
        ), "Hepta Panthenol must NEVER match NP7 Panthenol!"
        assert not is_safe_pharmaceutical_match(
            'هيبتا بانثينول كريم جلد', 'بانثينول كريم 20 جرام وسط س 45 ج باكو 25'
        ), "Hepta Panthenol must NEVER match generic Nile Panthenol!"
        assert is_safe_pharmaceutical_match(
            'هيبتا بانثينول كريم جلد', 'هيبتا بانثينول كريم جلد 50 جم باكو 10'
        ), "Hepta Panthenol MUST match Hepta Panthenol offer!"

    def test_skin_cream_vs_hair_cream_blocked(self):
        """Skin formulations must NEVER substitute for hair formulations."""
        assert not is_safe_pharmaceutical_match(
            'هيبتا بانثينول كريم جلد', 'هيبتا بانثينول كريم شعر كبار'
        ), "Skin cream must NEVER match hair cream!"


def load_tests(loader, tests, pattern):
    import unittest, os
    suite = unittest.TestSuite()
    class PytestRunner(unittest.TestCase):
        def test_suite(self):
            code = pytest.main(["-q", os.path.abspath(__file__)])
            self.assertEqual(code, 0, f"pytest exit code: {code}")
    suite.addTests(loader.loadTestsFromTestCase(PytestRunner))
    return suite
