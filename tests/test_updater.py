# -*- coding: utf-8 -*-
import pytest
from unittest.mock import patch, MagicMock
from src.updater import (
    parse_version,
    is_newer_version,
    check_for_updates,
    UpdateCheckResult,
    AutoUpdateManager,
)

def test_parse_version():
    assert parse_version("1.8") == (1, 8)
    assert parse_version("v1.8.1") == (1, 8, 1)
    assert parse_version("v2.0-beta") == (2, 0)
    assert parse_version("invalid") == (0,)

def test_is_newer_version():
    assert is_newer_version("1.9", "1.8") is True
    assert is_newer_version("1.8.1", "1.8") is True
    assert is_newer_version("2.0.0", "1.8") is True
    assert is_newer_version("1.8", "1.8") is False
    assert is_newer_version("1.7", "1.8") is False

@patch("src.updater.urlopen")
def test_check_for_updates_available(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_data = {
        "tag_name": "v1.9",
        "body": "Bug fixes and improvements",
        "html_url": "https://github.com/omarEldestawi/Inventory-search/releases/tag/v1.9",
        "assets": [
            {
                "name": "EgyptianPharmaOptimizer_Setup_v1.9.exe",
                "browser_download_url": "https://github.com/.../Setup_v1.9.exe",
                "size": 140000000,
            }
        ]
    }
    import json
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    res = check_for_updates("1.8")
    assert res.has_update is True
    assert res.latest_version == "1.9"
    assert "Setup_v1.9.exe" in res.download_url
    assert res.error is None

@patch("src.updater.urlopen")
def test_check_for_updates_same_version(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_data = {
        "tag_name": "v1.8",
        "body": "Current release",
        "html_url": "https://github.com/omarEldestawi/Inventory-search/releases/tag/v1.8",
        "assets": [
            {
                "name": "EgyptianPharmaOptimizer_Setup_v1.8.exe",
                "browser_download_url": "https://github.com/.../Setup_v1.8.exe",
                "size": 140000000,
            }
        ]
    }
    import json
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    res = check_for_updates("1.8")
    assert res.has_update is False
    assert res.latest_version == "1.8"
