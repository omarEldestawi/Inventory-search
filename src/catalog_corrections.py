"""
Atomic, fingerprinted catalog correction persistence and cache invalidation.

Persists versioned corrections under:
%LOCALAPPDATA%/EgyptianPharmaOptimizer/data/catalog_corrections/<sha256>.json

Implements:
- Atomic file operations using tempfile + flush + fsync + os.replace
- Source catalog SHA-256 fingerprint validation
- Non-transferability invariant (corrections are never applied to changed/different PDFs)
- Graceful recovery from corrupt, truncated, or invalid JSON documents
- Monotonically increasing corrections revision tracking
- Cache freshness and acknowledgment token invalidation
- Dynamic wiring for CatalogCorrectionService and FileFingerprint
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("CatalogCorrections")

SCHEMA_VERSION = "2.5"
DEFAULT_CORRECTIONS_DIR: Optional[str] = None
_DIR_LOCK = threading.RLock()


def compute_file_sha256(file_path: str) -> Optional[str]:
    """Computes streaming SHA-256 hex digest of a file on disk."""
    if not file_path or not isinstance(file_path, str):
        return None
    try:
        norm = os.path.normcase(os.path.realpath(os.path.abspath(file_path)))
        if not os.path.isfile(norm):
            return None
        digest = hashlib.sha256()
        with open(norm, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, IOError) as exc:
        logger.debug(f"Error computing SHA-256 for '{file_path}': {exc}")
        return None


def get_corrections_dir(custom_dir: Optional[str] = None) -> str:
    """
    Resolves the canonical directory for storing catalog corrections.
    Resolution order:
    1. custom_dir parameter
    2. DEFAULT_CORRECTIONS_DIR (set via set_corrections_dir for test isolation)
    3. EPO_CORRECTIONS_DIR environment variable
    4. %LOCALAPPDATA%/EgyptianPharmaOptimizer/data/catalog_corrections
    """
    with _DIR_LOCK:
        if custom_dir:
            return os.path.normpath(os.path.abspath(custom_dir))
        if DEFAULT_CORRECTIONS_DIR:
            return DEFAULT_CORRECTIONS_DIR
        env_dir = os.environ.get("EPO_CORRECTIONS_DIR")
        if env_dir:
            return os.path.normpath(os.path.abspath(env_dir))
        local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.normpath(
            os.path.join(local_app_data, "EgyptianPharmaOptimizer", "data", "catalog_corrections")
        )


def set_corrections_dir(custom_dir: Optional[str]) -> None:
    """Sets a global override for the corrections directory (used primarily in tests)."""
    global DEFAULT_CORRECTIONS_DIR
    with _DIR_LOCK:
        if custom_dir is None:
            DEFAULT_CORRECTIONS_DIR = None
        else:
            DEFAULT_CORRECTIONS_DIR = os.path.normpath(os.path.abspath(custom_dir))


def get_corrections_file_path(
    catalog_path_or_sha256: str,
    corrections_dir: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (sha256, target_json_path) for a catalog path or raw SHA-256 hash.
    """
    cdir = get_corrections_dir(corrections_dir)
    # Check if input is already a 64-char hex SHA-256
    if (
        isinstance(catalog_path_or_sha256, str)
        and len(catalog_path_or_sha256) == 64
        and all(c in "0123456789abcdefABCDEF" for c in catalog_path_or_sha256)
        and not os.path.isfile(catalog_path_or_sha256)
    ):
        file_sha256 = catalog_path_or_sha256.lower()
        return file_sha256, os.path.join(cdir, f"{file_sha256}.json")

    file_sha256 = compute_file_sha256(catalog_path_or_sha256)
    if not file_sha256:
        return None, None

    return file_sha256, os.path.join(cdir, f"{file_sha256}.json")


def load_corrections(
    catalog_path: str,
    expected_sha256: Optional[str] = None,
    corrections_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Loads persisted corrections for catalog_path.

    Safeguards:
    1. Verifies that the catalog file exists on disk and its SHA-256 matches expected_sha256.
       If modified or mismatched, refuses to apply corrections and logs a warning.
    2. Gracefully handles corrupted JSON, schema mismatches, or truncated files:
       logs an explicit review explanation and returns None without crashing.
    3. Verifies that the internal stored SHA-256 matches the file on disk.

    Returns the parsed corrections dictionary or None if not found/invalid.
    """
    if not catalog_path or not isinstance(catalog_path, str):
        return None

    disk_sha256, target_file = get_corrections_file_path(catalog_path, corrections_dir=corrections_dir)
    if not disk_sha256 or not target_file:
        return None

    # Enforce SHA-256 match if caller specified expected_sha256
    if expected_sha256:
        norm_expected = str(expected_sha256).strip().lower()
        if disk_sha256.lower() != norm_expected:
            logger.warning(
                f"Disk SHA-256 mismatch for catalog '{catalog_path}': "
                f"expected '{norm_expected}', disk has '{disk_sha256}'. "
                f"Refusing to transfer or apply saved corrections to a modified catalog file."
            )
            return None

    if not os.path.isfile(target_file):
        return None

    try:
        with open(target_file, "r", encoding="utf-8") as stream:
            content = stream.read()
    except OSError as exc:
        logger.warning(
            f"Failed to read corrections file '{target_file}' for '{catalog_path}': {exc}. "
            f"Review explanation: Storage read failure. Returning empty corrections."
        )
        return None

    if not content.strip():
        logger.warning(
            f"Corrections file '{target_file}' for '{catalog_path}' is empty. "
            f"Review explanation: Empty storage file encountered. Returning empty corrections."
        )
        return None

    try:
        doc = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning(
            f"Corrupt JSON encountered in corrections file '{target_file}' for '{catalog_path}': {exc}. "
            f"Review explanation: JSON decoding error. Persisted correction document is malformed "
            f"and cannot be parsed. Returning empty corrections without crashing."
        )
        return None

    if not isinstance(doc, dict):
        logger.warning(
            f"Malformed corrections document in '{target_file}' for '{catalog_path}': "
            f"expected JSON object, got {type(doc).__name__}. "
            f"Review explanation: Invalid root schema type. Returning empty corrections."
        )
        return None

    # Validate schema version compatibility
    schema_ver = str(doc.get("schema_version", ""))
    if not schema_ver.startswith("2."):
        logger.warning(
            f"Schema version mismatch in corrections file '{target_file}' for '{catalog_path}': "
            f"expected '2.x', found '{schema_ver}'. "
            f"Review explanation: Incompatible schema version. Returning empty corrections."
        )
        return None

    # Validate stored SHA-256 matches current file on disk
    stored_sha = str(doc.get("sha256", "")).strip().lower()
    if stored_sha != disk_sha256.lower():
        logger.warning(
            f"Internal SHA-256 mismatch in corrections file '{target_file}' for '{catalog_path}': "
            f"stored '{stored_sha}', disk '{disk_sha256}'. "
            f"Review explanation: The catalog file has been modified since corrections were recorded. "
            f"Refusing to apply invalid corrections."
        )
        return None

    return doc


def save_corrections(
    catalog_path: str,
    corrections_data: Dict[str, Any],
    corrections_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Atomically saves versioned catalog corrections under %LOCALAPPDATA% directory.

    Employs strict atomic writes:
    - Writes to a temporary file in the exact same directory (guaranteeing same filesystem volume)
    - Flushes buffer to OS
    - Calls os.fsync to ensure disk synchronization
    - Closes temp file handle before rename (mandatory for Windows compatibility)
    - Performs atomic rename via os.replace

    Increments corrections_revision monotonically.
    """
    if not catalog_path or not isinstance(catalog_path, str):
        raise ValueError("Invalid catalog path provided to save_corrections.")

    norm_path = os.path.normpath(os.path.abspath(catalog_path))
    if not os.path.isfile(norm_path):
        raise FileNotFoundError(f"Cannot save corrections for non-existent catalog file: {norm_path}")

    disk_sha256, target_file = get_corrections_file_path(norm_path, corrections_dir=corrections_dir)
    if not disk_sha256 or not target_file:
        raise ValueError(f"Could not compute SHA-256 for catalog file: {norm_path}")

    cdir = os.path.dirname(target_file)
    os.makedirs(cdir, exist_ok=True)

    canonical_path = os.path.normcase(os.path.realpath(norm_path))

    # Read existing doc if any to preserve revision sequence and created_at
    existing_doc = load_corrections(norm_path, expected_sha256=disk_sha256, corrections_dir=cdir)
    current_rev = (existing_doc.get("corrections_revision", 0) if existing_doc else 0) + 1

    now_utc = datetime.now(timezone.utc).isoformat()
    created_at = existing_doc.get("created_at_utc", now_utc) if existing_doc else now_utc

    raw_mappings = corrections_data.get("table_mappings", {})
    # Normalize mapping keys to string for JSON serialization
    serialized_mappings = {str(k): v for k, v in raw_mappings.items()}

    raw_field_corr = corrections_data.get("field_corrections", {})
    serialized_field_corr: Dict[str, Any] = {}
    for sid, updates in raw_field_corr.items():
        if isinstance(updates, dict):
            # Normalize each record to include both standard fields and provenance metadata
            corr_entry = dict(updates)
            if "source_id" not in corr_entry:
                corr_entry["source_id"] = sid
            if "provenance" not in corr_entry:
                corr_entry["provenance"] = "manual_correction"
            if "updated_at" not in corr_entry:
                corr_entry["updated_at"] = now_utc
            serialized_field_corr[sid] = corr_entry

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "canonical_path": canonical_path,
        "sha256": disk_sha256,
        "corrections_revision": current_rev,
        "created_at_utc": created_at,
        "updated_at_utc": now_utc,
        "table_mappings": serialized_mappings,
        "field_corrections": serialized_field_corr,
        "manual_entries": corrections_data.get("manual_entries", []),
        "corrections": corrections_data.get("corrections", serialized_field_corr),
    }

    # Atomic write to temporary file in the same directory
    prefix = f".tmp_{disk_sha256[:8]}_"
    temp_file = tempfile.NamedTemporaryFile(
        dir=cdir,
        mode="w",
        encoding="utf-8",
        delete=False,
        suffix=".tmp",
        prefix=prefix,
    )
    temp_path = temp_file.name
    try:
        json.dump(payload, temp_file, ensure_ascii=False, indent=2)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_file.close()
        # Atomic replacement
        os.replace(temp_path, target_file)
    except Exception:
        temp_file.close()
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise

    logger.info(
        f"Persisted corrections revision {current_rev} for '{os.path.basename(norm_path)}' "
        f"at '{target_file}'"
    )
    return payload


def reset_corrections(
    catalog_path: str,
    corrections_dir: Optional[str] = None,
) -> bool:
    """
    Atomically clears/deletes persisted corrections for catalog_path.
    Returns True if corrections existed and were removed, False otherwise.
    """
    if not catalog_path or not isinstance(catalog_path, str):
        return False

    disk_sha256, target_file = get_corrections_file_path(catalog_path, corrections_dir=corrections_dir)
    if not target_file or not os.path.isfile(target_file):
        return False

    try:
        os.remove(target_file)
        logger.info(f"Reset corrections for catalog '{catalog_path}': removed '{target_file}'.")
        return True
    except OSError as exc:
        logger.warning(f"Error removing corrections file '{target_file}': {exc}")
        try:
            # Overwrite with empty file then remove
            cdir = os.path.dirname(target_file)
            temp_file = tempfile.NamedTemporaryFile(dir=cdir, delete=False, mode="w", suffix=".tmp")
            temp_name = temp_file.name
            temp_file.close()
            os.replace(temp_name, target_file)
            os.remove(target_file)
            return True
        except OSError:
            return False


def get_corrections_revision(
    catalog_path: str,
    corrections_dir: Optional[str] = None,
) -> int:
    """
    Returns current integer revision of persisted corrections for catalog_path,
    or 0 if no corrections exist or if the corrections file is corrupt/invalid.
    """
    doc = load_corrections(catalog_path, corrections_dir=corrections_dir)
    if doc and isinstance(doc, dict):
        try:
            return int(doc.get("corrections_revision", 1))
        except (ValueError, TypeError):
            return 1
    return 0


def has_persisted_corrections(
    catalog_path: str,
    corrections_dir: Optional[str] = None,
) -> bool:
    """Returns True if valid persisted corrections exist for catalog_path."""
    return get_corrections_revision(catalog_path, corrections_dir=corrections_dir) > 0


# -----------------------------------------------------------------------------
# Dynamic Service & Fingerprint Wiring
# -----------------------------------------------------------------------------

_WIRED = False
_WIRING_LOCK = threading.RLock()


def wire_catalog_correction_service(service_cls: Optional[Any] = None) -> None:
    """
    Wires CatalogCorrectionService to persist changes via catalog_corrections
    on apply_field_correction, apply_table_column_mapping, and reset_corrections,
    and to load persisted corrections during initialization.
    Also wires FileFingerprint.is_current and from_path to verify corrections freshness.
    """
    global _WIRED
    with _WIRING_LOCK:
        if _WIRED and service_cls is None:
            return

        # 1. Wire FileFingerprint
        try:
            try:
                from .catalog_diagnostics import FileFingerprint
            except ImportError:
                from catalog_diagnostics import FileFingerprint

            orig_is_current = getattr(FileFingerprint, "_orig_is_current", None)
            if orig_is_current is None:
                orig_is_current = FileFingerprint.is_current
                FileFingerprint._orig_is_current = orig_is_current  # type: ignore

                def is_current_with_corrections(self: Any, path: Optional[str] = None) -> bool:
                    if not orig_is_current(self, path):
                        return False
                    target_path = path or getattr(self, "path", None)
                    if not target_path or not os.path.isfile(target_path):
                        return False
                    disk_rev = get_corrections_revision(target_path)
                    cached_rev = getattr(self, "corrections_revision", 0)
                    return disk_rev == cached_rev

                FileFingerprint.is_current = is_current_with_corrections  # type: ignore

            orig_from_path = getattr(FileFingerprint, "_orig_from_path", None)
            if orig_from_path is None:
                orig_from_path = FileFingerprint.from_path
                FileFingerprint._orig_from_path = orig_from_path  # type: ignore

                @classmethod
                def from_path_with_corrections(cls: Any, path: str) -> Any:
                    fp = orig_from_path(path)
                    rev = get_corrections_revision(path)
                    object.__setattr__(fp, "corrections_revision", rev)
                    return fp

                FileFingerprint.from_path = from_path_with_corrections  # type: ignore
        except Exception as exc:
            logger.debug(f"FileFingerprint wiring bypass: {exc}")

        # 2. Wire CatalogCorrectionService
        if service_cls is None:
            try:
                try:
                    from .catalog_service import CatalogCorrectionService
                except ImportError:
                    from catalog_service import CatalogCorrectionService
                service_cls = CatalogCorrectionService
            except Exception as exc:
                logger.debug(f"CatalogCorrectionService import for wiring bypass: {exc}")
                return

        if getattr(service_cls, "_persistence_wired", False):
            return

        orig_init = service_cls.__init__
        orig_apply_field = service_cls.apply_field_correction
        orig_apply_table = service_cls.apply_table_column_mapping
        orig_reset = service_cls.reset_corrections
        orig_get_refreshed = service_cls.get_refreshed_catalog_result

        def init_with_persistence(self: Any, catalog_path: str, *args: Any, **kwargs: Any) -> None:
            orig_init(self, catalog_path, *args, **kwargs)
            self.corrections_revision = 0
            try:
                doc = load_corrections(self.catalog_path)
                if doc and isinstance(doc, dict):
                    # Load field corrections
                    f_corrs = doc.get("field_corrections", {})
                    for sid, val in f_corrs.items():
                        if isinstance(val, dict):
                            # Extract field updates cleanly
                            self._field_corrections[sid] = {
                                k: v for k, v in val.items()
                                if k in ("item_name", "base_price", "discount_rate", "stock_status", "name", "price", "discount", "stock")
                            }
                    # Load table mappings
                    t_maps = doc.get("table_mappings", {})
                    for tid, val in t_maps.items():
                        if isinstance(val, dict):
                            k = int(tid) if str(tid).isdigit() else tid
                            self._table_mappings[k] = dict(val)
                    self.corrections_revision = int(doc.get("corrections_revision", 1))
            except Exception as exc:
                logger.warning(f"Error loading persisted corrections in service __init__: {exc}")

        def apply_field_correction_with_persistence(
            self: Any, source_id: str, field_updates: Dict[str, Any]
        ) -> Any:
            res = orig_apply_field(self, source_id, field_updates)
            try:
                doc = save_corrections(
                    self.catalog_path,
                    {
                        "field_corrections": self._field_corrections,
                        "table_mappings": self._table_mappings,
                    },
                )
                self.corrections_revision = int(doc.get("corrections_revision", 1))
                if res and getattr(res, "fingerprint", None):
                    object.__setattr__(res.fingerprint, "corrections_revision", self.corrections_revision)
                if res and getattr(res, "dataframe", None) is not None:
                    meta = res.dataframe.attrs.get("catalog_import")
                    if isinstance(meta, dict):
                        meta["corrections_revision"] = self.corrections_revision
            except Exception as exc:
                logger.warning(f"Error persisting field correction: {exc}")

            # Evict from in-memory cache
            try:
                try:
                    from .controller import global_catalog_cache
                except ImportError:
                    from controller import global_catalog_cache
                global_catalog_cache.remove(self.catalog_path)
            except Exception:
                pass
            return res

        def apply_table_column_mapping_with_persistence(
            self: Any, table_id: int, mapping: Dict[str, int]
        ) -> Any:
            res = orig_apply_table(self, table_id, mapping)
            try:
                doc = save_corrections(
                    self.catalog_path,
                    {
                        "field_corrections": self._field_corrections,
                        "table_mappings": self._table_mappings,
                    },
                )
                self.corrections_revision = int(doc.get("corrections_revision", 1))
                if res and getattr(res, "fingerprint", None):
                    object.__setattr__(res.fingerprint, "corrections_revision", self.corrections_revision)
                if res and getattr(res, "dataframe", None) is not None:
                    meta = res.dataframe.attrs.get("catalog_import")
                    if isinstance(meta, dict):
                        meta["corrections_revision"] = self.corrections_revision
            except Exception as exc:
                logger.warning(f"Error persisting table column mapping: {exc}")

            try:
                try:
                    from .controller import global_catalog_cache
                except ImportError:
                    from controller import global_catalog_cache
                global_catalog_cache.remove(self.catalog_path)
            except Exception:
                pass
            return res

        def reset_corrections_with_persistence(self: Any) -> Any:
            try:
                reset_corrections(self.catalog_path)
            except Exception as exc:
                logger.warning(f"Error resetting persistent corrections: {exc}")
            self.corrections_revision = 0
            try:
                try:
                    from .controller import global_catalog_cache
                except ImportError:
                    from controller import global_catalog_cache
                global_catalog_cache.remove(self.catalog_path)
            except Exception:
                pass
            res = orig_reset(self)
            if res and getattr(res, "fingerprint", None):
                object.__setattr__(res.fingerprint, "corrections_revision", 0)
            if res and getattr(res, "dataframe", None) is not None:
                meta = res.dataframe.attrs.get("catalog_import")
                if isinstance(meta, dict):
                    meta["corrections_revision"] = 0
            return res

        def get_refreshed_with_persistence(self: Any, refresh: bool = False) -> Any:
            res = orig_get_refreshed(self, refresh=refresh)
            rev = getattr(self, "corrections_revision", 0)
            if res and getattr(res, "fingerprint", None):
                object.__setattr__(res.fingerprint, "corrections_revision", rev)
            if res and getattr(res, "dataframe", None) is not None:
                meta = res.dataframe.attrs.get("catalog_import")
                if isinstance(meta, dict):
                    meta["corrections_revision"] = rev
            return res

        service_cls.__init__ = init_with_persistence  # type: ignore
        service_cls.apply_field_correction = apply_field_correction_with_persistence  # type: ignore
        service_cls.apply_table_column_mapping = apply_table_column_mapping_with_persistence  # type: ignore
        service_cls.reset_corrections = reset_corrections_with_persistence  # type: ignore
        service_cls.get_refreshed_catalog_result = get_refreshed_with_persistence  # type: ignore
        service_cls._persistence_wired = True  # type: ignore
        _WIRED = True
        logger.debug("CatalogCorrectionService and FileFingerprint successfully wired to catalog_corrections.")


# Automatically attempt wiring when module is imported
try:
    wire_catalog_correction_service()
except Exception as _wire_err:
    logger.debug(f"Auto-wiring on import deferred: {_wire_err}")
