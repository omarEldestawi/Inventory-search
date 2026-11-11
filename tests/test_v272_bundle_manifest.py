from pathlib import Path
import sqlite3

import pytest

from build_exe import APP_NAME, RUNTIME_RESOURCES, WORKER, verify_bundle
from src.medication_db import _resolve_default_db_path


def test_bundle_rejects_duplicate_runtime_resource(tmp_path):
    for resource in (*RUNTIME_RESOURCES, WORKER):
        path = tmp_path / '_internal' / resource
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(resource), encoding='utf-8')
    assert verify_bundle(tmp_path) > 0
    duplicate = tmp_path / '_internal' / 'unexpected-copy'
    duplicate.write_bytes((tmp_path / '_internal' / RUNTIME_RESOURCES[0]).read_bytes())
    with pytest.raises(ValueError, match='Duplicate bundled resource'):
        verify_bundle(tmp_path)


def test_packaged_bundle_manifest_matches_distribution():
    bundle = Path(__file__).resolve().parents[1] / 'dist' / APP_NAME
    if not (bundle / 'bundle_manifest.json').is_file():
        pytest.skip('Run build_exe.py to produce the candidate distribution')
    assert verify_bundle(bundle) > 0


def test_new_template_preserves_user_database_and_corrections(monkeypatch, tmp_path):
    template = tmp_path / 'bundle' / 'data' / 'medications.db'
    template.parent.mkdir(parents=True)
    profile = tmp_path / 'profile'
    monkeypatch.setattr('sys.frozen', True, raising=False)
    monkeypatch.setattr('sys._MEIPASS', str(template.parent.parent), raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(profile))
    with sqlite3.connect(template) as db:
        db.execute('CREATE TABLE sentinel (name TEXT)')
        db.execute('INSERT INTO sentinel VALUES (?)', ('bundle',))
    user_db = Path(_resolve_default_db_path())
    with sqlite3.connect(user_db) as db:
        db.execute('UPDATE sentinel SET name = ?', ('user',))
    correction = user_db.parent / 'catalog_corrections' / 'user.json'
    correction.parent.mkdir()
    correction.write_text('{"saved": true}', encoding='utf-8')
    with sqlite3.connect(template) as db:
        db.execute('INSERT INTO sentinel VALUES (?)', ('new template',))
        db.execute('CREATE TABLE growth (data BLOB)')
        db.execute('INSERT INTO growth VALUES (zeroblob(50000))')
    for _ in range(2):
        assert Path(_resolve_default_db_path()) == user_db
        with sqlite3.connect(user_db) as db:
            assert db.execute('SELECT name FROM sentinel').fetchall() == [('user',)]
        assert correction.read_text(encoding='utf-8') == '{"saved": true}'
