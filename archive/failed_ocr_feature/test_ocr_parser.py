# -*- coding: utf-8 -*-
"""
Unit and Integration Test Suite for Milestone 1:
Catalog Inspection, RapidOCR + RapidTable Parsing, 3-Tier Fallback,
CatalogCache, and On-Demand OCR Re-read.
"""
import os
import sys
import threading
import tempfile
import pytest
import pandas as pd
import numpy as np

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.pdf_parser import (
    PDFCatalogParser,
    html_table_to_rows,
    html_table_to_df,
    get_ocr_engine,
    get_table_engine,
    find_rapid_table_model,
    find_rapid_ocr_assets,
)
from src.controller import (
    CatalogCache,
    global_catalog_cache,
    inspect_catalog_counts,
    reread_catalog_with_ocr,
)
from src.pipeline import run_procurement_pipeline


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def real_catalog_pdf():
    """Path to real sample catalog PDF."""
    path = os.path.abspath(os.path.join(project_root, "input", "catalogs", "الشركة_المتحدة.pdf"))
    assert os.path.isfile(path), f"Sample catalog not found at {path}"
    return path


@pytest.fixture
def real_order_xlsx():
    """Path to real sample order xlsx."""
    path = os.path.abspath(os.path.join(project_root, "input", "orders", "طلبية_اليوم.xlsx"))
    assert os.path.isfile(path), f"Sample order not found at {path}"
    return path


# ============================================================================
# TEST SUITE 1: HTML TABLE PARSER (Zero external dependencies, no lxml)
# ============================================================================

class TestHtmlTableParser:
    """Tests zero-dependency HTML table to rows and DataFrame parser."""

    def test_html_table_to_rows_basic(self):
        html = "<table><tr><th>Item</th><th>Price</th><th>Discount</th></tr><tr><td>Panadol</td><td>50.0</td><td>20%</td></tr></table>"
        rows = html_table_to_rows(html)
        assert len(rows) == 2
        assert rows[0] == ["Item", "Price", "Discount"]
        assert rows[1] == ["Panadol", "50.0", "20%"]

    def test_html_table_to_df_clean_conversion(self):
        html = (
            "<html><body><table>"
            "<tr><td>Item Name</td><td>Price</td><td>Disc%</td></tr>"
            "<tr><td>Augmentin 1g</td><td>120.0</td><td>23%</td></tr>"
            "<tr><td>Cataflam 50mg</td><td>55.0</td><td>24%</td></tr>"
            "</table></body></html>"
        )
        df = html_table_to_df(html)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert list(df.columns) == ["Item Name", "Price", "Disc%"]
        assert df.iloc[0]["Item Name"] == "Augmentin 1g"
        assert df.iloc[1]["Price"] == "55.0"

    def test_html_table_with_nested_tags_and_whitespace(self):
        html = "<table><tr><td><b>Item</b></td><td><span>Price</span></td></tr><tr><td><a href='#'>Ketofan 100</a></td><td><b>35.00</b></td></tr></table>"
        df = html_table_to_df(html)
        assert len(df) == 1
        assert df.iloc[0]["Item"] == "Ketofan 100"
        assert df.iloc[0]["Price"] == "35.00"

    def test_html_table_empty_or_malformed(self):
        assert html_table_to_rows("").__len__() == 0
        assert html_table_to_rows("plain text without table").__len__() == 0
        assert html_table_to_df("").empty
        assert html_table_to_df(None).empty

    def test_html_table_duplicate_headers_sanitization(self):
        html = "<table><tr><td>Col</td><td>Col</td><td></td></tr><tr><td>1</td><td>2</td><td>3</td></tr></table>"
        df = html_table_to_df(html)
        assert len(df) == 1
        assert "Col" in df.columns
        assert "Col_1" in df.columns


# ============================================================================
# TEST SUITE 2: LAZY SINGLETON INITIALIZATION & RELIABILITY
# ============================================================================

class TestLazySingletons:
    """Verifies that RapidOCR and RapidTable engines load cleanly on demand and degrade gracefully."""

    def test_get_ocr_engine_returns_singleton(self):
        ocr1 = get_ocr_engine()
        ocr2 = get_ocr_engine()
        assert ocr1 is ocr2
        try:
            import rapidocr_onnxruntime
            assert ocr1 is not None
        except Exception:
            assert ocr1 is None

    def test_get_table_engine_returns_singleton(self):
        tbl1 = get_table_engine()
        tbl2 = get_table_engine()
        assert tbl1 is tbl2
        try:
            import rapid_table
            assert tbl1 is not None
        except Exception:
            assert tbl1 is None

    def test_ocr_engine_graceful_degradation_missing_dependency(self, monkeypatch):
        """Verifies get_ocr_engine logs diagnostic and returns None when RapidOCR is missing."""
        import src.pdf_parser as pp
        import builtins
        monkeypatch.setattr(pp, "_ocr_engine", None)
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "rapidocr" in name:
                raise ImportError("No module named 'rapidocr_onnxruntime'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        engine = pp.get_ocr_engine()
        assert engine is None

    def test_ocr_engine_graceful_degradation_corrupted_model(self, monkeypatch):
        """Verifies get_ocr_engine logs diagnostic and returns None when model weights are corrupted."""
        import src.pdf_parser as pp
        monkeypatch.setattr(pp, "_ocr_engine", None)

        class FailingRapidOCR:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("ONNX Runtime error: corrupted model weights")

        fake_mod = type(sys)("rapidocr_onnxruntime")
        fake_mod.RapidOCR = FailingRapidOCR
        monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake_mod)

        engine = pp.get_ocr_engine()
        assert engine is None

    def test_table_engine_graceful_degradation_missing_dependency(self, monkeypatch):
        """Verifies get_table_engine logs diagnostic and returns None when RapidTable is missing."""
        import src.pdf_parser as pp
        import builtins
        monkeypatch.setattr(pp, "_table_engine", None)
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "rapid_table" in name:
                raise ImportError("No module named 'rapid_table'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        engine = pp.get_table_engine()
        assert engine is None

    def test_table_engine_graceful_degradation_corrupted_model(self, monkeypatch):
        """Verifies get_table_engine logs diagnostic and returns None when table model weights are corrupted."""
        import src.pdf_parser as pp
        monkeypatch.setattr(pp, "_table_engine", None)

        class FailingRapidTable:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("Invalid ONNX model proto")

        fake_mod = type(sys)("rapid_table")
        fake_mod.RapidTable = FailingRapidTable
        fake_mod.RapidTableInput = lambda **kwargs: None
        monkeypatch.setitem(sys.modules, "rapid_table", fake_mod)

        engine = pp.get_table_engine()
        assert engine is None

    def test_frozen_asset_discovery_meipass(self, monkeypatch, tmp_path):
        """Verifies frozen asset discovery correctly resolves paths from PyInstaller sys._MEIPASS."""
        import src.pdf_parser as pp

        fake_meipass = str(tmp_path / "fake_meipass")
        models_dir = os.path.join(fake_meipass, "models")
        os.makedirs(models_dir, exist_ok=True)

        fake_table_model = os.path.join(models_dir, "slanet-plus.onnx")
        with open(fake_table_model, "wb") as f:
            f.write(b"fake table model")

        fake_config = os.path.join(fake_meipass, "rapidocr_onnxruntime", "config.yaml")
        os.makedirs(os.path.dirname(fake_config), exist_ok=True)
        with open(fake_config, "w") as f:
            f.write("fake config")

        fake_det_model = os.path.join(models_dir, "ch_PP-OCRv4_det_infer.onnx")
        with open(fake_det_model, "wb") as f:
            f.write(b"fake det model")

        monkeypatch.setattr(sys, "_MEIPASS", fake_meipass, raising=False)

        tbl_model = pp.find_rapid_table_model()
        assert tbl_model == os.path.normpath(fake_table_model)

        cfg_path, ocr_models = pp.find_rapid_ocr_assets()
        assert cfg_path == os.path.normpath(fake_config)
        assert ocr_models.get("det_model_path") == os.path.normpath(fake_det_model)


# ============================================================================
# TEST SUITE 3: RAPIDOCR + RAPIDTABLE PDF CATALOG EXTRACTION
# ============================================================================

class TestCatalogOCRExtraction:
    """Tests PyMuPDF 300 DPI rasterization, OCR extraction, and table reconstruction."""

    def test_parse_catalog_ocr_real_pdf(self, real_catalog_pdf):
        """Tests parse_catalog_ocr classmethod interface contract on real wholesaler catalog."""
        items = PDFCatalogParser.parse_catalog_ocr(real_catalog_pdf)
        assert isinstance(items, list)
        assert len(items) > 0, "Expected at least 1 item extracted via OCR from sample catalog"

        # Verify Canonical Schema + Compatibility Aliases
        sample = items[0]
        required_keys = [
            'warehouse_name', 'item_name', 'normalized_name', 'dosage',
            'unit_size', 'base_price', 'discount_rate', 'stock_status',
            'name', 'price', 'vendor', 'category'
        ]
        for k in required_keys:
            assert k in sample, f"Missing required key: {k} in extracted record"

        # Verify numeric attributes
        assert sample['base_price'] > 0.0
        assert sample['discount_rate'] > 0.0
        assert sample['category'] == "Catalog"
        assert len(sample['item_name']) >= 2

    def test_parse_ocr_returns_canonical_dataframe(self, real_catalog_pdf):
        """Tests parse_ocr instance method returning deduplicated canonical DataFrame."""
        parser = PDFCatalogParser(real_catalog_pdf)
        progress_calls = []

        def _prog(pct, msg):
            progress_calls.append((pct, msg))

        df = parser.parse_ocr(progress_callback=_prog)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert len(progress_calls) >= 1

        expected_cols = [
            'warehouse_name', 'item_name', 'normalized_name', 'dosage',
            'unit_size', 'base_price', 'discount_rate', 'stock_status'
        ]
        for col in expected_cols:
            assert col in df.columns

    def test_3tier_fallback_on_corrupt_page(self):
        """Verifies that non-standard or corrupt PDFs degrade safely to empty DataFrame without crashing."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(b"%PDF-1.4 dummy corrupted content")
            tf_path = tf.name

        try:
            parser = PDFCatalogParser(tf_path)
            df = parser.parse_ocr()
            assert isinstance(df, pd.DataFrame)
            assert df.empty
            assert list(df.columns) == [
                'warehouse_name', 'item_name', 'normalized_name', 'dosage',
                'unit_size', 'base_price', 'discount_rate', 'stock_status'
            ]
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_parse_ocr_graceful_on_runtime_inference_error(self, real_catalog_pdf, monkeypatch):
        """Verifies that runtime exceptions during OCR inference degrade safely to Tier 3 fallback."""
        import src.pdf_parser as pp

        class MockCrashEngine:
            def __call__(self, img):
                raise RuntimeError("Simulated inference crash on corrupted weights")

        monkeypatch.setattr(pp, "get_ocr_engine", lambda: MockCrashEngine())
        monkeypatch.setattr(pp, "get_table_engine", lambda: None)

        parser = pp.PDFCatalogParser(real_catalog_pdf)
        df = parser.parse_ocr()
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert "item_name" in df.columns


# ============================================================================
# TEST SUITE 4: CATALOG CACHE & CONTROLLER BRIDGE
# ============================================================================

class TestCatalogCacheAndController:
    """Tests thread-safe CatalogCache, inspect_catalog_counts, and reread_catalog_with_ocr."""

    def test_catalog_cache_lifecycle(self):
        cache = CatalogCache()
        sample_path = r"C:\fake\catalog.pdf"
        dummy_df = pd.DataFrame([{"item_name": "Test Item", "discount_rate": 0.20}])

        assert cache.get(sample_path) is None
        cache.set(sample_path, dummy_df)

        retrieved = cache.get(sample_path)
        assert retrieved is not None
        assert len(retrieved) == 1
        assert retrieved.iloc[0]["item_name"] == "Test Item"

        # Verify copy isolation
        retrieved.iloc[0, 0] = "Modified"
        assert cache.get(sample_path).iloc[0]["item_name"] == "Test Item"

        cache.remove(sample_path)
        assert cache.get(sample_path) is None

        cache.set(sample_path, dummy_df)
        assert len(cache.all_cached()) == 1
        cache.clear()
        assert len(cache.all_cached()) == 0

    def test_catalog_cache_thread_safety(self):
        cache = CatalogCache()
        errors = []

        def _worker(thread_id):
            try:
                for i in range(25):
                    path = f"C:\\fake\\catalog_{thread_id}_{i}.pdf"
                    df = pd.DataFrame([{"id": i}])
                    cache.set(path, df)
                    got = cache.get(path)
                    assert got is not None
                    assert len(got) == 1
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        assert len(cache.all_cached()) == 125

    def test_inspect_catalog_counts(self, real_catalog_pdf):
        """Tests inspect_catalog_counts returning accurate medication count."""
        global_catalog_cache.clear()
        counts = inspect_catalog_counts([real_catalog_pdf])
        norm_key = os.path.normpath(real_catalog_pdf)
        assert norm_key in counts
        assert counts[norm_key] > 0

        # Second call should read directly from cache
        cached_counts = inspect_catalog_counts([real_catalog_pdf])
        assert cached_counts[norm_key] == counts[norm_key]

    def test_reread_catalog_with_ocr(self, real_catalog_pdf):
        """Tests on-demand OCR re-read caching and returning (path, count, records)."""
        prog_events = []

        def _cb(pct, msg):
            prog_events.append((pct, msg))

        ret_path, count, records = reread_catalog_with_ocr(real_catalog_pdf, progress_callback=_cb)
        assert ret_path == os.path.normpath(real_catalog_pdf)
        assert count > 0
        assert len(records) == count
        assert len(prog_events) > 0

        # Verify cached in global_catalog_cache
        cached_df = global_catalog_cache.get(real_catalog_pdf)
        assert cached_df is not None
        assert len(cached_df) == count


# ============================================================================
# TEST SUITE 5: PIPELINE CACHE INTEGRATION
# ============================================================================

class TestPipelineCatalogCacheIntegration:
    """Tests that run_procurement_pipeline respects and uses in-memory catalog_cache."""

    def test_pipeline_uses_provided_catalog_cache(self, real_catalog_pdf, real_order_xlsx):
        with tempfile.TemporaryDirectory() as tmp_out:
            # Build custom mock DataFrame in cache
            norm_path = os.path.normpath(real_catalog_pdf)
            mock_df = pd.DataFrame([
                {
                    'warehouse_name': 'مخزن_تجريبي_خاص',
                    'item_name': 'Augmentin 1gm 14 Tab',
                    'normalized_name': 'augmentin 1gm 14 tab',
                    'dosage': '1gm',
                    'unit_size': '14 tab',
                    'base_price': 100.0,
                    'discount_rate': 0.35,  # 35% discount
                    'stock_status': True,
                }
            ])
            custom_cache = {norm_path: mock_df}

            results = run_procurement_pipeline(
                order_files=[real_order_xlsx],
                catalog_files=[real_catalog_pdf],
                output_dir=tmp_out,
                catalog_cache=custom_cache,
            )

            assert "report_path" in results
            assert os.path.exists(results["report_path"])
            kpis = results.get("kpis", {})
            # Verify warehouse was recognized from cached DataFrame
            alloc_counts = kpis.get("allocation_counts", {})
            assert 'مخزن_تجريبي_خاص' in alloc_counts
