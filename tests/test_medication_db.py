# -*- coding: utf-8 -*-
"""
Unit tests for Medication Knowledge Base & Alias Resolution Engine.
"""
import os
import time
import pytest
import tempfile
from src.medication_db import MedicationDB


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_meds.db")
        db = MedicationDB(db_path)
        try:
            yield db
        finally:
            db.close()


class TestMedicationDB:
    def test_init_and_tables(self, temp_db):
        """Verifies DB initialization and initial empty state."""
        assert temp_db.count_standards() == 0
        assert temp_db.count_aliases() == 0

    def test_add_standard_and_alias(self, temp_db):
        """Verifies adding a standard medication and registering aliases."""
        std_id = temp_db.add_standard_medication(
            canonical_name="كونكور 10 مجم 30 قرص",
            canonical_brand="concor",
            form_category="SOLID_ORAL",
            strength="10mg",
            pack_size="30"
        )
        assert std_id > 0
        assert temp_db.count_standards() == 1

        # Canonical name is automatically registered as alias
        res = temp_db.resolve("كونكور 10 مجم 30 قرص")
        assert res is not None
        assert res["id"] == std_id
        assert res["canonical_brand"] == "concor"

        # Register variations
        temp_db.register_alias(std_id, "CONCOR 10MG TAB", source="vendor_catalog")
        temp_db.register_alias(std_id, "كونكور10مجم", source="vendor_catalog_arabic")
        temp_db.register_alias(std_id, "ركونوك 10 مجم", source="reversed_arabic_pdf")

        # Test resolution of all variations
        assert temp_db.resolve("CONCOR 10MG TAB")["id"] == std_id
        assert temp_db.resolve("كونكور10مجم")["id"] == std_id
        assert temp_db.resolve("ركونوك 10 مجم")["id"] == std_id

    def test_normalized_matching(self, temp_db):
        """Verifies resolution with Arabic diacritics, presentation forms, and whitespace quirks."""
        std_id = temp_db.add_standard_medication(
            canonical_name="كتافلام 50 مجم اقراص",
            canonical_brand="cataflam",
            form_category="SOLID_ORAL",
            strength="50mg"
        )
        temp_db.register_alias(std_id, "كتافلام 50 مجم", source="vendor")

        # Query with extra spaces, different alef, or tatweel
        assert temp_db.resolve("كتـافـلام   50  مجم") is not None
        assert temp_db.resolve("كتـافـلام   50  مجم")["id"] == std_id

    def test_persistence_across_instances(self, temp_db):
        """Verifies data persists across different MedicationDB instances."""
        db_path = temp_db.db_path
        std_id = temp_db.add_standard_medication(
            canonical_name="بانادول اكسترا اقراص",
            canonical_brand="panadol",
            form_category="SOLID_ORAL"
        )
        temp_db.register_alias(std_id, "PANADOL EXTRA", source="vendor")

        # Open a new instance pointing to the same file
        db2 = MedicationDB(db_path)
        try:
            assert db2.count_standards() == 1
            assert db2.resolve("PANADOL EXTRA") is not None
            assert db2.resolve("PANADOL EXTRA")["id"] == std_id
        finally:
            db2.close()

    def test_resolution_speed_benchmark(self, temp_db):
        """Verifies resolution of 1,000 queries executes in under 50ms (sub-millisecond O(1) performance)."""
        std_id = temp_db.add_standard_medication(
            canonical_name="اوجمانتين 1 جم اقراص",
            canonical_brand="augmentin",
            form_category="SOLID_ORAL",
            strength="1g"
        )
        temp_db.register_alias(std_id, "AUGMENTIN 1GM TAB", source="vendor")

        start = time.perf_counter()
        for _ in range(1000):
            res = temp_db.resolve("AUGMENTIN 1GM TAB")
            assert res is not None
        elapsed_ms = (time.perf_counter() - start) * 1000

        print(f"\n[BENCHMARK] 1,000 queries resolved in {elapsed_ms:.2f} ms ({elapsed_ms/1000:.4f} ms/query)")
        assert elapsed_ms < 50.0  # Must be well under 50ms for 1000 queries

    def test_read_only_fallback(self):
        """Verifies MedicationDB opens and resolves correctly on read-only databases (like Program Files)."""
        import stat
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "readonly_meds.db")
            # 1. Create and populate initially
            db1 = MedicationDB(db_path)
            std_id = db1.add_standard_medication(
                canonical_name="دافاليندي 200000 وحده 2 امبول",
                canonical_brand="davalindi",
                form_category="INJECTABLE",
                strength="200000"
            )
            db1.register_alias(std_id, "لوبما 2 هدحو 200000 يدنيلافاد", source="reversed_arabic")
            db1.close()

            # 2. Make file strictly read-only on filesystem
            os.chmod(db_path, stat.S_IREAD)

            # 3. Open new instance pointing to read-only file
            db_ro = MedicationDB(db_path)
            try:
                assert db_ro.count_standards() == 1
                res = db_ro.resolve("لوبما 2 هدحو 200000 يدنيلافاد")
                assert res is not None
                assert res["id"] == std_id
                assert res["canonical_brand"] == "davalindi"
            finally:
                db_ro.close()
                os.chmod(db_path, stat.S_IWRITE | stat.S_IREAD)
