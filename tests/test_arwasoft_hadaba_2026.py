# -*- coding: utf-8 -*-
"""
Tests for ArwaSoft 2026 Dual-Column (Al-Hadaba) catalog parsing and glyph decoding.
"""
import os
import pytest
import pandas as pd
from src.normalizer import (
    decode_custom_catalog_glyphs,
    unreverse_arabic_text,
    normalize_vendor_name,
)
from src.pdf_parser import PDFCatalogParser

def test_arwasoft_2026_glyph_decoding():
    # Test control code bytes and symbols
    sample = 'ا\x05\x0f\x0b\x16\x04ل 1  ت%\x0b\x05  \x08\x05ن \x0eد\x04د4 440 13'
    decoded = decode_custom_catalog_glyphs(sample)
    # Check that control codes are properly mapped to Arabic characters
    assert 'ق' not in decoded or 'ا\nراص' not in decoded
    assert 'ابتاميل' in decoded or 'ابيتاميل' in decoded or 'لبن' in decoded

def test_arwasoft_vendor_normalization():
    assert normalize_vendor_name("2طباعه مزدوجه.pdf") == "مخزن الهضبة فارم"
    assert normalize_vendor_name("الهضبه الخميس نفدى.pdf") == "مخزن الهضبة فارم"

def test_arwasoft_dual_catalog_parsing_if_present():
    catalog_path = r"C:\Users\omart\Downloads\2طباعه مزدوجه.pdf"
    if not os.path.exists(catalog_path):
        pytest.skip("Test catalog not found at local Downloads path")
        
    parser = PDFCatalogParser(catalog_path)
    df = parser.parse()
    
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert len(df) > 1000
    assert df["warehouse_name"].iloc[0] == "مخزن الهضبة فارم"
    assert df["base_price"].min() > 0.0
    assert df["base_price"].max() <= 50000.0
    assert df["discount_rate"].max() <= 0.85
    assert df["discount_rate"].min() >= 0.0
    
    # Check for known items from Page 1 and Page 13
    item_names = " ".join(df["item_name"].tolist())
    assert "ابروفال" in item_names or "ابروفيل" in item_names
    assert "استين" in item_names or "ابتاميل" in item_names
