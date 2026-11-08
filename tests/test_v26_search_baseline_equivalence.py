import json
import os
import shutil
import subprocess
import sys
import unittest


class TestIsolatedSearchBaselineEquivalence(unittest.TestCase):
    """
    Formally demonstrates search equivalence against baseline commit 9aa5eff
    executing in completely isolated processes and environments.
    Guarantees no shared in-memory modules or runtime dependencies between baseline and current.
    """

    @classmethod
    def setUpClass(cls):
        cls.work_dir = os.path.abspath("tmp/search_equivalence")
        os.makedirs(cls.work_dir, exist_ok=True)

        cls.baseline_dir = os.path.join(cls.work_dir, "baseline_env")
        cls.baseline_src = os.path.join(cls.baseline_dir, "src")
        os.makedirs(cls.baseline_src, exist_ok=True)

        # 1. Extract 9aa5eff files directly from git into isolated baseline directory
        needed_files = [
            "allocator.py", "pharma_matcher.py", "normalizer.py",
            "gemini_matcher.py", "average_discounts.py", "medication_db.py"
        ]
        for fname in needed_files:
            cmd = ["git", "show", f"9aa5eff:src/{fname}"]
            res = subprocess.run(cmd, capture_output=True, check=True)
            with open(os.path.join(cls.baseline_src, fname), "wb") as f:
                f.write(res.stdout)

        # Create empty __init__.py in baseline src
        with open(os.path.join(cls.baseline_src, "__init__.py"), "w") as f:
            pass

        # Copy medications.db into baseline environment so MedicationDB operates on identical database
        baseline_data = os.path.join(cls.baseline_dir, "data")
        os.makedirs(baseline_data, exist_ok=True)
        for ext in ["", "-wal", "-shm"]:
            fpath = f"data/medications.db{ext}"
            if os.path.exists(fpath):
                shutil.copy(fpath, os.path.join(baseline_data, f"medications.db{ext}"))

        # 2. Shared test inputs: 50 clinical queries and 40 catalog items
        cls.test_queries = [
            "كونكور 5 مجم", "كونكور كور 2.5", "بنادول اكسترا", "بنادول ادفانس",
            "اماريل 2 مجم", "اماريل 3 مجم", "اوجمنتين 1 جم", "اوجمنتين 625",
            "كتافلام 50 مجم", "فولتارين 75 امبول", "فولتارين 100 اقماع", "سيتال شراب",
            "انتوسيد اقراص", "كابوتن 25 مجم", "كاردورا 4 مجم", "لاسيكس 40 مجم",
            "الفينترن اقراص", "نيوروتون امبول", "نيوروبيون اقراص", "جلوكوفاج 1000",
            "جلوكوفاج 500 مجم", "اتور 10 مجم", "اتور 20 مجم", "اتور 40 مجم",
            "اتورستات 10 مجم", "اركوكسيا 60 مجم", "اركوكسيا 90 مجم", "سولبادين فوار",
            "بروفين 400", "بروفين 600", "دافلون 500 مجم", "موبيك 15 مجم",
            "زانتاك 150", "كونترولوك 40", "نيكسيوم 40 مجم", "اوميز 20 مجم",
            "فلاجيل 500", "كيبوركس 1 جم", "سيبتازول اقراص", "ميجاموكس 1 جم",
            "كليندامايسين 300", "سيبروسين 500", "تافانيك 500", "تاريفيد 200",
            "رواتكس كبسول", "يورينكس كبسول", "كولونا اقراص", "سبازموديجستين",
            "ليبراكس اقراص", "دوجماتيل 50"
        ]

        cls.catalog_data = [
            {"warehouse_name": "W1", "item_name": "CONCOR 5 MG 30 TAB", "base_price": 40.50, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "كونكور 5 مجم 30 قرص", "base_price": 40.50, "discount_rate": 0.22, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "CONCOR COR 2.5 MG 30 TAB", "base_price": 32.50, "discount_rate": 0.18, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "كونكور كور 2.5 مجم 30 قرص", "base_price": 32.50, "discount_rate": 0.19, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "PANADOL EXTRA 24 TAB", "base_price": 35.00, "discount_rate": 0.15, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "بنادول اكسترا 24 قرص", "base_price": 35.00, "discount_rate": 0.16, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "AMARYL 2 MG 30 TAB", "base_price": 46.50, "discount_rate": 0.21, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "اماريل 2 مجم 30 قرص", "base_price": 46.50, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "AUGMENTIN 1 GM 14 TAB", "base_price": 99.00, "discount_rate": 0.23, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "اوجمنتين 1 جم 14 قرص", "base_price": 99.00, "discount_rate": 0.25, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "CATAFLAM 50 MG 20 TAB", "base_price": 38.00, "discount_rate": 0.18, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "كتافلام 50 مجم 20 قرص", "base_price": 38.00, "discount_rate": 0.18, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "VOLTAREN 75 MG 6 AMP", "base_price": 52.00, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "فولتارين 75 مجم 6 امبول", "base_price": 52.00, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "CETAL SYRUP 120 ML", "base_price": 18.00, "discount_rate": 0.15, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "سيتال شراب 120 مل", "base_price": 18.00, "discount_rate": 0.16, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "ANTINAL 24 CAP", "base_price": 26.00, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "انتوسيد 20 قرص", "base_price": 15.00, "discount_rate": 0.10, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "CAPOTEN 25 MG 20 TAB", "base_price": 24.00, "discount_rate": 0.15, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "كابوتن 25 مجم 20 قرص", "base_price": 24.00, "discount_rate": 0.17, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "CARDURA 4 MG 28 TAB", "base_price": 85.00, "discount_rate": 0.22, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "كاردورا 4 مجم 28 قرص", "base_price": 85.00, "discount_rate": 0.22, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "LASIX 40 MG 24 TAB", "base_price": 21.00, "discount_rate": 0.18, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "لاسيكس 40 مجم 24 قرص", "base_price": 21.00, "discount_rate": 0.19, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "ALPHINTERN 30 TAB", "base_price": 45.00, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "الفينترن 30 قرص", "base_price": 45.00, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "NEUROTON 6 AMP", "base_price": 37.50, "discount_rate": 0.18, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "نيوروتون 6 امبول", "base_price": 37.50, "discount_rate": 0.18, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "GLUCOPHAGE 1000 MG 30 TAB", "base_price": 60.00, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "جلوكوفاج 1000 مجم 30 قرص", "base_price": 60.00, "discount_rate": 0.21, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "ATOR 10 MG 7 TAB", "base_price": 22.00, "discount_rate": 0.15, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "اتور 10 مجم 7 قرص", "base_price": 22.00, "discount_rate": 0.15, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "ATORSTAT 10 MG 14 TAB", "base_price": 35.00, "discount_rate": 0.17, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "اتورستات 10 مجم 14 قرص", "base_price": 35.00, "discount_rate": 0.18, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "ARCOXIA 60 MG 14 TAB", "base_price": 115.00, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "اركوكسيا 60 مجم 14 قرص", "base_price": 115.00, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "BRUFEN 400 MG 30 TAB", "base_price": 42.00, "discount_rate": 0.16, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "بروفين 400 مجم 30 قرص", "base_price": 42.00, "discount_rate": 0.18, "stock_status": True},
            {"warehouse_name": "W1", "item_name": "DAFLON 500 MG 30 TAB", "base_price": 75.00, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "W2", "item_name": "دافلون 500 مجم 30 قرص", "base_price": 75.00, "discount_rate": 0.21, "stock_status": True},
        ]

        cls.order_items = [
            {"requested_item": "كونكور 5 مجم", "quantity": 10},
            {"requested_item": "بنادول اكسترا", "quantity": 15},
            {"requested_item": "اوجمنتين 1 جم", "quantity": 5},
            {"requested_item": "فولتارين 75 امبول", "quantity": 8},
            {"requested_item": "اتور 10 مجم", "quantity": 12},
        ]

        # Write runner script for isolated execution
        runner_script = """
import json
import os
import sys
import pandas as pd

from src.allocator import MedicineAllocator
from src.normalizer import normalize_arabic_text, normalize_drug_text, parse_dosage_and_pack

input_file = sys.argv[1]
output_file = sys.argv[2]

with open(input_file, 'r', encoding='utf-8') as f:
    cfg = json.load(f)

queries = cfg['queries']
catalog_data = cfg['catalog_data']
order_items = cfg['order_items']

# 1. Normalization results
norm_results = {}
for q in queries:
    norm_results[q] = {
        'norm_arabic': normalize_arabic_text(q),
        'norm_drug': normalize_drug_text(q),
        'dosage_pack': parse_dosage_and_pack(q),
    }

# 2. Candidate matches via MedicineAllocator
df = pd.DataFrame(catalog_data)
df['normalized_name'] = df['item_name'].apply(normalize_arabic_text)
allocator = MedicineAllocator(warehouse_inventory=df, enable_ai=False)

search_matches = {}
for q in queries:
    cands = allocator._find_safe_candidates(q)
    cand_items = sorted(cands['item_name'].tolist()) if len(cands) > 0 else []
    search_matches[q] = cand_items

# 3. Order allocation
buying_df = pd.DataFrame(order_items)
alloc_res = allocator.allocate_order(buying_df)
kpis = alloc_res.get('kpis', {})

# Clean float/int types for JSON
clean_kpis = {k: float(v) if isinstance(v, (int, float)) else v for k, v in kpis.items() if not isinstance(v, dict)}

output = {
    'norm_results': norm_results,
    'search_matches': search_matches,
    'kpis': clean_kpis,
}

with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
"""
        cls.runner_path = os.path.join(cls.work_dir, "search_runner.py")
        with open(cls.runner_path, "w", encoding="utf-8") as f:
            f.write(runner_script)

        cls.config_path = os.path.join(cls.work_dir, "test_config.json")
        with open(cls.config_path, "w", encoding="utf-8") as f:
            json.dump({
                "queries": cls.test_queries,
                "catalog_data": cls.catalog_data,
                "order_items": cls.order_items,
            }, f, ensure_ascii=False)

        cls.baseline_out = os.path.join(cls.work_dir, "baseline_out.json")
        cls.current_out = os.path.join(cls.work_dir, "current_out.json")

    def test_search_baseline_equivalence_in_isolated_processes(self):
        """
        Executes isolated subprocesses for baseline 9aa5eff and current implementation,
        then proves 100% equivalence in candidates, normalization, and allocation KPIs.
        """
        python_exe = sys.executable

        # 1. Execute Subprocess A: Isolated Baseline Environment (PYTHONPATH=baseline_dir)
        env_base = os.environ.copy()
        env_base["PYTHONPATH"] = self.baseline_dir
        proc_base = subprocess.run(
            [python_exe, self.runner_path, self.config_path, self.baseline_out],
            env=env_base,
            capture_output=True,
            text=True
        )
        self.assertEqual(
            proc_base.returncode, 0,
            f"Baseline isolated runner failed:\nSTDOUT:\n{proc_base.stdout}\nSTDERR:\n{proc_base.stderr}"
        )

        # 2. Execute Subprocess B: Current Environment (PYTHONPATH=workspace_root)
        env_curr = os.environ.copy()
        env_curr["PYTHONPATH"] = os.path.abspath(".")
        proc_curr = subprocess.run(
            [python_exe, self.runner_path, self.config_path, self.current_out],
            env=env_curr,
            capture_output=True,
            text=True
        )
        self.assertEqual(
            proc_curr.returncode, 0,
            f"Current isolated runner failed:\nSTDOUT:\n{proc_curr.stdout}\nSTDERR:\n{proc_curr.stderr}"
        )

        # 3. Load and assert 100% equivalence between isolated process outputs
        with open(self.baseline_out, "r", encoding="utf-8") as f:
            base_data = json.load(f)
        with open(self.current_out, "r", encoding="utf-8") as f:
            curr_data = json.load(f)

        # A. Normalization Equivalence across all 50 queries
        for q in self.test_queries:
            b_norm = base_data["norm_results"][q]
            c_norm = curr_data["norm_results"][q]
            self.assertEqual(b_norm["norm_arabic"], c_norm["norm_arabic"], f"norm_arabic mismatch on {q}")
            self.assertEqual(b_norm["norm_drug"], c_norm["norm_drug"], f"norm_drug mismatch on {q}")
            self.assertEqual(b_norm["dosage_pack"], c_norm["dosage_pack"], f"dosage_pack mismatch on {q}")

        # B. Safe Candidate Matches Equivalence across all 50 queries
        for q in self.test_queries:
            b_cands = base_data["search_matches"][q]
            c_cands = curr_data["search_matches"][q]
            self.assertEqual(b_cands, c_cands, f"Candidate matches mismatch for query: {q}")

        # C. Order Allocation KPIs Equivalence
        b_kpis = base_data["kpis"]
        c_kpis = curr_data["kpis"]
        self.assertEqual(b_kpis["total_items"], c_kpis["total_items"])
        self.assertEqual(b_kpis["matched_items"], c_kpis["matched_items"])
        self.assertAlmostEqual(b_kpis["total_purchase_cost"], c_kpis["total_purchase_cost"], places=2)
        self.assertAlmostEqual(b_kpis["total_savings"], c_kpis["total_savings"], places=2)
        self.assertAlmostEqual(b_kpis["savings_pct"], c_kpis["savings_pct"], places=1)


if __name__ == "__main__":
    unittest.main()
