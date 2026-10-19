# -*- coding: utf-8 -*-
"""
Auto-Update Manager for Egyptian Pharma Procurement Optimizer.
Handles background checking, downloading from GitHub Releases,
and silent in-place installation using Inno Setup switches.
"""
from __future__ import annotations

import os
import sys
import re
import tempfile
import threading
import subprocess
import logging
from typing import Optional, Callable, Dict, Any
from urllib.request import Request, urlopen
import json

logger = logging.getLogger("AutoUpdater")

GITHUB_REPO = "omarEldestawi/Inventory-search"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
SETUP_FILENAME_PATTERN = re.compile(r"EgyptianPharmaOptimizer_Setup_v?([\d\.]+)\.exe$", re.IGNORECASE)


def parse_version(v_str: str) -> tuple[int, ...]:
    """Extracts integer version tuple from string (e.g. 'v1.8.1' -> (1, 8, 1))."""
    clean = re.sub(r"^[^\d]*", "", v_str.strip())
    parts = re.split(r"[^\d]+", clean)
    nums = [int(p) for p in parts if p.isdigit()]
    return tuple(nums) if nums else (0,)


def is_newer_version(remote_ver: str, current_ver: str) -> bool:
    """Returns True if remote_ver is strictly newer than current_ver."""
    return parse_version(remote_ver) > parse_version(current_ver)


class UpdateCheckResult:
    def __init__(
        self,
        has_update: bool,
        latest_version: str,
        download_url: Optional[str] = None,
        release_notes: Optional[str] = None,
        html_url: Optional[str] = None,
        file_size: int = 0,
        error: Optional[str] = None
    ):
        self.has_update = has_update
        self.latest_version = latest_version
        self.download_url = download_url
        self.release_notes = release_notes
        self.html_url = html_url
        self.file_size = file_size
        self.error = error


def check_for_updates(current_version: str, timeout: int = 10) -> UpdateCheckResult:
    """
    Queries GitHub API for the latest release.
    Returns UpdateCheckResult.
    """
    headers = {
        "User-Agent": f"EgyptianPharmaOptimizer-Updater/{current_version}",
        "Accept": "application/vnd.github.v3+json"
    }
    req = Request(API_URL, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return UpdateCheckResult(
                    False, current_version, error=f"GitHub HTTP {response.status}"
                )
            data = json.loads(response.read().decode("utf-8"))
            tag = data.get("tag_name", "").lstrip("v")
            notes = data.get("body", "")
            html_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases")
            
            # Find the Windows setup .exe asset
            download_url = None
            file_size = 0
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.endswith(".exe") and ("setup" in name.lower() or "optimizer" in name.lower()):
                    download_url = asset.get("browser_download_url")
                    file_size = asset.get("size", 0)
                    break
            
            if not download_url:
                # If no matching setup asset found
                return UpdateCheckResult(False, current_version, error="No setup installer asset found in release")
            
            has_update = is_newer_version(tag, current_version)
            return UpdateCheckResult(
                has_update=has_update,
                latest_version=tag,
                download_url=download_url,
                release_notes=notes,
                html_url=html_url,
                file_size=file_size
            )
    except Exception as e:
        logger.warning(f"Update check failed (offline or unreachable): {e}")
        return UpdateCheckResult(False, current_version, error=str(e))


def download_installer(
    download_url: str,
    target_version: str,
    progress_callback: Optional[Callable[[float, int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None
) -> str:
    """
    Downloads the installer executable into user %TEMP%.
    Returns path to downloaded file.
    """
    temp_dir = tempfile.gettempdir()
    dest_path = os.path.join(temp_dir, f"EgyptianPharmaOptimizer_Setup_v{target_version}.exe")
    
    headers = {"User-Agent": "EgyptianPharmaOptimizer-Updater"}
    req = Request(download_url, headers=headers)
    
    with urlopen(req, timeout=30) as response:
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 64 * 1024  # 64 KB
        
        with open(dest_path, "wb") as f:
            while True:
                if cancel_event and cancel_event.is_set():
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                    raise RuntimeError("Download cancelled by user")
                    
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                
                if progress_callback and total_size > 0:
                    fraction = downloaded / total_size
                    progress_callback(fraction, downloaded, total_size)
                    
    return dest_path


def apply_update_and_restart(installer_path: str):
    """
    Executes the Inno Setup installer completely silently without admin prompts
    and restarts the application automatically upon completion.
    Switches:
      /VERYSILENT : Fully invisible install without wizard or progress windows
      /SUPPRESSMSGBOXES : Automatically dismisses all message boxes with default answers
      /FORCECLOSEAPPLICATIONS : Force closes running processes cleanly without prompting
      /RESTARTAPPLICATIONS : Automatically re-launches the newly installed app when done
    """
    if not os.path.isfile(installer_path):
        raise FileNotFoundError(f"Installer not found at {installer_path}")
        
    cmd = [
        installer_path,
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/FORCECLOSEAPPLICATIONS",
        "/RESTARTAPPLICATIONS",
    ]
    logger.info(f"Launching silent updater: {' '.join(cmd)}")
    subprocess.Popen(cmd, shell=False)
    sys.exit(0)


class AutoUpdateManager:
    """
    Manages update lifecycle:
    Checking -> Downloading -> ReadyToInstall -> Restart
    Thread-safe and async.
    """
    STATUS_IDLE = "IDLE"
    STATUS_CHECKING = "CHECKING"
    STATUS_NO_UPDATE = "NO_UPDATE"
    STATUS_UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
    STATUS_DOWNLOADING = "DOWNLOADING"
    STATUS_READY = "READY"
    STATUS_ERROR = "ERROR"

    def __init__(self, current_version: str):
        self.current_version = current_version
        self.status = self.STATUS_IDLE
        self.check_result: Optional[UpdateCheckResult] = None
        self.downloaded_installer_path: Optional[str] = None
        self.download_progress: float = 0.0
        self.error_message: Optional[str] = None
        self._cancel_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.on_status_change: Optional[Callable[[str], None]] = None

    def _set_status(self, new_status: str, error: Optional[str] = None):
        self.status = new_status
        if error:
            self.error_message = error
        if self.on_status_change:
            try:
                self.on_status_change(new_status)
            except Exception as e:
                logger.error(f"Error in on_status_change callback: {e}")

    def start_background_check_and_download(self):
        """Checks for update, and if found, automatically downloads it in background."""
        if self.status in (self.STATUS_CHECKING, self.STATUS_DOWNLOADING, self.STATUS_READY):
            return

        def _worker():
            self._set_status(self.STATUS_CHECKING)
            res = check_for_updates(self.current_version)
            self.check_result = res
            
            if res.error:
                self._set_status(self.STATUS_ERROR, error=res.error)
                return

            if not res.has_update:
                self._set_status(self.STATUS_NO_UPDATE)
                return

            # Update available -> start silent download
            self._set_status(self.STATUS_DOWNLOADING)
            try:
                def _prog(fraction, done, total):
                    self.download_progress = fraction

                path = download_installer(
                    res.download_url,
                    res.latest_version,
                    progress_callback=_prog,
                    cancel_event=self._cancel_event
                )
                self.downloaded_installer_path = path
                self._set_status(self.STATUS_READY)
            except Exception as e:
                self._set_status(self.STATUS_ERROR, error=f"Download failed: {e}")

        self._cancel_event.clear()
        self._thread = threading.Thread(target=_worker, daemon=True, name="AutoUpdateWorker")
        self._thread.start()

    def apply_update(self):
        """Applies the downloaded update and restarts."""
        if self.status == self.STATUS_READY and self.downloaded_installer_path:
            apply_update_and_restart(self.downloaded_installer_path)
