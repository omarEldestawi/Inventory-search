# -*- coding: utf-8 -*-
"""
Empirical Adversarial Challenge Suite: Milestone M3
Canonical Brand Dictionary Expansion & Pre-Tokenizer Decoupling Benchmark
Challenger: Challenger M3_2 (critic, specialist)
"""
import time
import pytest
import pandas as pd

from src.normalizer import (
    ARABIC_TO_ENGLISH_BRANDS,
    ENGLISH_TO_ARABIC_BRANDS,
    pre_tokenize_pharma_string,
    extract_canonical_brand,
    normalize_drug_text,
)
from src.excel_parser import load_purchase_order
from src.pharma_matcher import is_safe_pharmaceutical_match


class TestCanonicalBrandDictionaryCapacity:
    """Verifies dictionary capacity, data integrity, and backwards compatibility."""

    def test_dictionary_size_exceeds_500(self):
        """Asserts len(ARABIC_TO_ENGLISH_BRANDS) >= 500 as mandated by dispatch."""
        count = len(ARABIC_TO_ENGLISH_BRANDS)
        assert count >= 500, f"Expected len(ARABIC_TO_ENGLISH_BRANDS) >= 500, got {count}"
        print(f"\n[CHALLENGER VERIFIED] ARABIC_TO_ENGLISH_BRANDS contains {count} entries (requirement: >= 500).")

    def test_reverse_dictionary_consistency(self):
        """Verifies ENGLISH_TO_ARABIC_BRANDS reverse lookup consistency."""
        assert len(ENGLISH_TO_ARABIC_BRANDS) > 0
        unique_en_roots = set(ARABIC_TO_ENGLISH_BRANDS.values())
        assert len(ENGLISH_TO_ARABIC_BRANDS) == len(unique_en_roots)
        for en_root in unique_en_roots:
            assert en_root in ENGLISH_TO_ARABIC_BRANDS
            ar_brand = ENGLISH_TO_ARABIC_BRANDS[en_root]
            assert ARABIC_TO_ENGLISH_BRANDS[ar_brand] == en_root

    def test_all_baseline_88_brands_intact(self):
        """Ensures 100% preservation of all 88 baseline brands with zero regression."""
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
            assert b in ARABIC_TO_ENGLISH_BRANDS, f"Baseline brand '{b}' was lost during dictionary expansion!"


class TestRealWorldGluedPackagingDecoupling:
    """Tests >= 30 real-world requested items from 0911.xlsx and 0912.xlsx with glued packaging."""

    GLUED_REAL_ITEMS = [
        ("ابيزيثرو500مجم3قرص", ["ابيزيثرو", "500", "مجم", "3", "قرص"], "epizithro"),
        ("اتراكون14كبسوله", ["اتراكون", "14", "كبسوله"], "itracon"),
        ("اريثركس200مجم2شريط", ["اريثركس", "200", "مجم", "2", "شريط"], "erythrex"),
        ("اسبرين بروتكت 100مجم3شريط", ["اسبرين", "بروتكت", "100", "مجم", "3", "شريط"], "aspirin protect"),
        ("سيتال5لبوس", ["سيتال", "5", "لبوس"], "cetal"),
        ("نت لوك40مجم20قرص", ["نت لوك", "40", "مجم", "20", "قرص"], "netlook"),
        ("ابيزيثرو شراب30ملل", ["ابيزيثرو", "شراب", "30", "ملل"], "epizithro"),
        ("تريتاس بروتكت 10مجم 20قرص", ["تريتاس", "بروتكت", "10", "مجم", "20", "قرص"], "tritace"),
        ("دايسارتان160مجم 14قرص", ["دايسارتان", "160", "مجم", "14", "قرص"], "diysartan"),
        ("سولبادول5مجم6قرص", ["سولبادول", "5", "مجم", "6", "قرص"], "solpadol"),
        ("تجريتول200 سي ار 20قرص", ["تجريتول", "200", "سي ار", "20", "قرص"], "tegretol"),
        ("نوفيستوريك20مجم اقراص", ["نوفيستوريك", "20", "مجم", "اقراص"], "novestoric"),
        ("ديكلوبرو150مجم 20قرص", ["ديكلوبرو", "150", "مجم", "20", "قرص"], "diclopro"),
        ("الكابرس10مجم30قرص", ["الكابرس", "10", "مجم", "30", "قرص"], "alcapress"),
        ("برينو ريلاكس 15مجم30كبسوله", ["برينو ريلاكس", "15", "مجم", "30", "كبسوله"], "preno relax"),
        ("ريفافلوفا20مجم20قرص", ["ريفافلوفا", "20", "مجم", "20", "قرص"], "rivaflova"),
        ("فرافيرو 27برطمان 20 كبسوله", ["فرافيرو", "27", "برطمان", "20", "كبسوله"], "phrafero"),
        ("فيتا بوينت شامبو للقشره250ملل", ["فيتا بوينت", "شامبو", "250", "ملل"], "vitapoint"),
        ("اوتيكس نقط اذن 15مل", ["اوتيكس", "نقط", "اذن", "15", "مل"], "otex"),
        ("جانوجوينت30قرص", ["جانوجوينت", "30", "قرص"], "ganojoint"),
        ("بيسلفون 20قرص", ["بيسلفون", "20", "قرص"], "bisolvon"),
        ("اليفو2شريط", ["اليفو", "2", "شريط"], "alevo"),
        ("بلينديل10مجم اقراص", ["بلينديل", "10", "مجم", "اقراص"], "plendil"),
        ("هاي بيوتك312مجم  شراب", ["هاي بيوتك", "312", "مجم", "شراب"], "hibiotic"),
        ("سيرفيتولكا20كبسوله", ["سيرفيتولكا", "20", "كبسوله"], "cervitolca"),
        ("سيريبروليسن5مجم 5امبول ث", ["سيريبروليسن", "5", "مجم", "5", "امبول"], "cerebrolysin"),
        ("راميلاكت30قرص", ["راميلاكت", "30", "قرص"], "ramilact"),
        ("لانتانون30مجم 10كبسوله", ["لانتانون", "30", "مجم", "10", "كبسوله"], "lantanon"),
        ("ليفوفيروز750مجم7قرص", ["ليفوفيروز", "750", "مجم", "7", "قرص"], "levoferoz"),
        ("بنتاكولد120مل شراب", ["بنتاكولد", "120", "مل", "شراب"], "pentacold"),
        ("لاموترين50مجم3شريط", ["لاموترين", "50", "مجم", "3", "شريط"], "lamotrene"),
        ("فليبوتون حقن 3امبولات", ["فليبوتون", "حقن", "3", "امبولات"], "phlebotone"),
        ("فيوسيست بلس 30قرص", ["فيوسيست", "بلس", "30", "قرص"], "fucicyst"),
        ("زوراكسون 1جم عضل فيال", ["زوراكسون", "1", "جم", "عضل", "فيال"], "zoraxon"),
        ("افالوكس400مجم اقراص", ["افالوكس", "400", "مجم", "اقراص"], "avelox"),
        ("كاردورا اكس ال 4مجم 28قرص", ["كاردورا", "اكس ال", "4", "مجم", "28", "قرص"], "cardura"),
        ("دولفين 75مجم اس ار كبسول", ["دولفين", "75", "مجم", "اس ار", "كبسول"], "dolphin"),
        ("فيتارون 120ملل شراب", ["فيتارون", "120", "ملل", "شراب"], "vitaron"),
        ("جليبوفين500/5مجم30قرص", ["جليبوفين", "500/5", "مجم", "30", "قرص"], "glybophen"),
    ]

    @pytest.mark.parametrize("item_text, expected_tokens, expected_brand", GLUED_REAL_ITEMS)
    def test_real_glued_po_tokens_decoupling(self, item_text, expected_tokens, expected_brand):
        """Verifies real-world glued PO strings decouple cleanly without mangling."""
        decoupled = pre_tokenize_pharma_string(item_text)
        for tok in expected_tokens:
            assert tok in decoupled, f"Expected token '{tok}' missing in decoupled '{decoupled}' for '{item_text}'"

    @pytest.mark.parametrize("item_text, expected_tokens, expected_brand", GLUED_REAL_ITEMS)
    def test_real_glued_po_brand_resolution(self, item_text, expected_tokens, expected_brand):
        """Verifies real-world glued PO strings resolve to their accurate canonical brand."""
        brand = extract_canonical_brand(item_text)
        assert brand == expected_brand, f"Item '{item_text}' resolved to '{brand}', expected '{expected_brand}'"


class TestHighFrequencyEgyptianMedications:
    """Verifies resolution of high-frequency commercial Egyptian medications."""

    HIGH_FREQ_MEDS = [
        ("بانادول اكسترا 500 مجم", "Panadol Extra 500mg", "panadol"),
        ("بروفين 400 مجم اقراص", "Brufen 400mg Tablets", "brufen"),
        ("اوجمنتين 1 جم 14 قرص", "Augmentin 1g 14 Tab", "augmentin"),
        ("اوجمانتين 625 مجم اقراص", "Augmentin 625mg Tab", "augmentin"),
        ("كتافلام 50 مجم 20 قرص", "Cataflam 50mg 20 Tab", "cataflam"),
        ("كونكور 5 مجم 30 قرص", "Concor 5mg 30 Tab", "concor"),
        ("كنترولوك 40 مجم 14 قرص", "Controloc 40mg 14 Tab", "controloc"),
        ("ابيزيثرو 500 مجم 3 كبسول", "Epizithro 500mg 3 Cap", "epizithro"),
        ("اتراكون 100 مجم 14 كبسول", "Itracon 100mg 14 Cap", "itracon"),
        ("زاريلتو 20 مجم 28 قرص", "Xarelto 20mg 28 Tab", "xarelto"),
        ("كلكسان 40 مجم سرنجة", "Clexane 40mg Syringe", "clexane"),
        ("فنتولين بخاخ صدر", "Ventolin Inhaler", "ventolin"),
        ("كونجستال 20 قرص", "Congestal 20 Tab", "congestal"),
        ("اوترفين بخاخ انف", "Otrivin Nasal Spray", "otrivin"),
        ("اليكا كريم 30 جم", "Elica Cream 30g", "elica"),
        ("درموفيت كريم 25 جم", "Dermovate Cream 25g", "dermovate"),
        ("كيناكومب كريم 15 جم", "Kenacomb Cream 15g", "kenacomb"),
        ("فيوسيدين مرهم 20 جم", "Fucidin Ointment 20g", "fucidin"),
        ("فيوسيكورت كريم 15 جم", "Fucicort Cream 15g", "fucicort"),
        ("دوسباتالين 200 ريتارد كبسول", "Duspatalin 200mg Retard", "duspatalin"),
        ("كولوفيرين د 30 قرص", "Coloverin D 30 Tab", "coloverin"),
        ("موتيليوم 10 مجم 40 قرص", "Motilium 10mg 40 Tab", "motilium"),
        ("اورسوفالك 250 مجم كبسول", "Ursofalk 250mg Cap", "ursofalk"),
        ("هيباميرز اكياس فوار", "Hepamerc Sachets", "hepamerc"),
        ("جانوفيا 100 مجم 28 قرص", "Januvia 100mg 28 Tab", "januvia"),
        ("جانوميت 50/1000 مجم 56 قرص", "Janumet 50/1000mg 56 Tab", "janumet"),
        ("جالفوس 50 مجم 28 قرص", "Galvus 50mg 28 Tab", "galvus"),
        ("فورسيجا 10 مجم 28 قرص", "Forxiga 10mg 28 Tab", "forxiga"),
        ("جاردينس 10 مجم 30 قرص", "Jardiance 10mg 30 Tab", "jardiance"),
        ("لبن نان 1 اوبتي برو", "Nan 1 Optipro Milk", "nan"),
        ("لبن بيبيلاك 1 حليب اطفال", "Bebelac 1 Infant Milk", "bebelac"),
        ("لبن ابتاميل 1 ادفانس", "Aptamil 1 Advance Milk", "aptamil"),
        ("لبن هيرو بيبي 1 حليب", "Hero Baby 1 Milk", "hero baby"),
    ]

    @pytest.mark.parametrize("ar_name, en_name, expected_canonical", HIGH_FREQ_MEDS)
    def test_high_frequency_medication_resolution(self, ar_name, en_name, expected_canonical):
        """Asserts Arabic and English names resolve to the exact identical canonical brand."""
        ar_brand = extract_canonical_brand(ar_name)
        en_brand = extract_canonical_brand(en_name)
        assert ar_brand == expected_canonical, f"Arabic '{ar_name}' -> '{ar_brand}', expected '{expected_canonical}'"
        assert en_brand == expected_canonical, f"English '{en_name}' -> '{en_brand}', expected '{expected_canonical}'"
        assert ar_brand == en_brand, f"Equivalence mismatch: '{ar_brand}' != '{en_brand}'"


class TestAdversarialDecouplingStressCases:
    """Stress tests complex edge cases: decimals, ratios, eastern digits, and prefix collisions."""

    @pytest.mark.parametrize("raw_input, expected_tokens", [
        ("كونكور كور 2.5مجم 30قرص", ["2.5", "مجم", "30", "قرص"]),
        ("كابوزيد25/12.5مجم20قرص", ["25/12.5", "مجم", "20", "قرص"]),
        ("اكسفورج10/160/12.5مجم", ["10/160/12.5", "مجم"]),
        ("كليكسان 4000وحدة دولية 0.4مل", ["4000", "وحده", "0.4", "مل"]),
        ("سيريبروليسين0.5جم5امبول", ["0.5", "جم", "5", "امبول"]),
        ("بانادول٥٠٠مجم٢٤قرص", ["500", "مجم", "24", "قرص"]),
        ("بروفين٤٠٠مجم", ["400", "مجم"]),
        ("كتافلام٥٠مجم", ["50", "مجم"]),
    ])
    def test_complex_number_and_eastern_digit_decoupling(self, raw_input, expected_tokens):
        """Verifies decoupled strings preserve decimals, ratios, and Eastern numerals."""
        decoupled = pre_tokenize_pharma_string(raw_input)
        for tok in expected_tokens:
            assert tok in decoupled, f"Token '{tok}' not found in '{decoupled}' for input '{raw_input}'"

    def test_longest_brand_prefix_precedence(self):
        """Verifies compound brands resolve to their specific trade entity and not partial prefixes."""
        # Aspirin protect vs Aspirin
        assert extract_canonical_brand("اسبرين بروتكت 100مجم 30قرص") == "aspirin protect"
        # Spasmo digestin vs Digestin
        assert extract_canonical_brand("سبازمو ديجستين 30قرص") == "spasmodigestin"
        # Hibiotic vs Biotic
        assert extract_canonical_brand("هاي بيوتك 1 جم 16 قرص") == "hibiotic"


class TestClinicalSafetyGateIntegration:
    """
    Stress-tests the interaction between canonical brand extraction and clinical safety gates.
    Even if an imperfect brand root is produced, is_safe_pharmaceutical_match MUST block unsafe substitutions.
    """

    def test_unanchored_substring_brand_collision_cetapronex_vs_ronex(self):
        """Cetapronex (escitalopram oral tablet) MUST NOT match Ronex (vaginal douche) as a brand substring."""
        brand = extract_canonical_brand("سيتابرونكس 10مجم اقراص")
        assert brand != "ronex", f"False brand substring collision: 'سيتابرونكس' mapped to '{brand}'!"

    def test_form_mismatch_blocks_unsafe_substitution(self):
        """Tablet vs Vaginal Wash or Suppository MUST be rejected despite brand substring overlap."""
        # Cetapronex oral tablet vs Ronex vaginal douche
        req = "سيتابرونكس 10مجم اقراص"
        cand = "رونكس دش مهبلي 250 مل"
        assert not is_safe_pharmaceutical_match(req, cand), "Safety gate FAILED to block tablet vs douche mismatch!"

    def test_strength_mismatch_blocks_unsafe_substitution(self):
        """Paracetamol 500mg vs 10mg escitalopram MUST be rejected."""
        req = "سيتال 500 مجم اقراص"
        cand = "اسيتالوبرام 10 مجم اقراص"
        assert not is_safe_pharmaceutical_match(req, cand), "Safety gate FAILED to block 500mg vs 10mg mismatch!"

    def test_antacid_vs_chemo_antiemetic_blocked(self):
        """Ranitidine 150mg vs Granisetron 1mg MUST be rejected."""
        req = "راني 150 مجم فوار"
        cand = "جرانيترون 1 مجم اقراص"
        assert not is_safe_pharmaceutical_match(req, cand), "Safety gate FAILED to block Ranitidine vs Granisetron!"


class TestFullPurchaseOrdersBenchmark:
    """Empirically evaluates brand resolution across all real-world PO items from 0911 and 0912."""

    def test_po_0911_and_0912_coverage_and_throughput(self):
        """Measures canonical brand coverage and throughput across all 945 real purchase order items."""
        po11 = load_purchase_order("train/0911.xlsx")
        po12 = load_purchase_order("train/0912.xlsx")

        assert len(po11) == 202, f"Expected 202 items in 0911, got {len(po11)}"
        assert len(po12) == 743, f"Expected 743 items in 0912, got {len(po12)}"

        all_items = list(po11["requested_item"]) + list(po12["requested_item"])
        total_items = len(all_items)

        start_time = time.perf_counter()
        canonical_brands = [extract_canonical_brand(it) for it in all_items]
        elapsed = time.perf_counter() - start_time

        print(f"\n[PERFORMANCE BENCHMARK] Extracted canonical brands for {total_items} items in {elapsed:.3f}s ({elapsed/total_items*1000:.2f} ms/item)")
        assert elapsed < 3.0, f"Extraction was too slow: {elapsed:.2f}s for {total_items} items"

        known_canonical = set(ARABIC_TO_ENGLISH_BRANDS.values())
        resolved_count = sum(1 for b in canonical_brands if b in known_canonical)
        coverage_rate = resolved_count / total_items * 100.0

        print(f"[COVERAGE BENCHMARK] Resolved to known canonical brand: {resolved_count}/{total_items} ({coverage_rate:.2f}%)")
        assert coverage_rate >= 99.0, f"Coverage rate {coverage_rate:.2f}% is below 99% threshold!"
