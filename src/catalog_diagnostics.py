"""Shared, serializable evidence for catalog extraction and cache validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from typing import Any, Optional

import pandas as pd
import pymupdf

PARSER_REVISION = "2026.10.27.1"
METADATA_KEY = "catalog_import"


@dataclass(frozen=True)
class FileFingerprint:
    path: str
    sha256: str
    parser_revision: str = PARSER_REVISION
    library_version: str = pymupdf.__version__

    @classmethod
    def from_path(cls, path: str) -> "FileFingerprint":
        canonical = os.path.normcase(os.path.realpath(os.path.abspath(path)))
        digest = hashlib.sha256()
        with open(canonical, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return cls(canonical, digest.hexdigest())

    def is_current(self, path: Optional[str] = None) -> bool:
        try:
            return self == self.from_path(path or self.path)
        except OSError:
            return False


@dataclass
class RowDiagnostic:
    page: int
    group: int
    row: int
    outcome: str  # accepted, rejected, or unprocessed
    reason: str = ""
    bbox: Optional[list[float]] = None
    raw_cells: list[Any] = field(default_factory=list)
    item_name: str = ""


@dataclass
class GroupDiagnostics:
    group: int
    strategy: str
    candidate_rows: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    unprocessed_rows: int = 0
    bbox: Optional[list[float]] = None
    rows: list[RowDiagnostic] = field(default_factory=list)


@dataclass
class PageDiagnostics:
    page: int
    strategy: str = "legacy"
    expected_count_known: bool = False
    accepted_rows: int = 0
    groups: list[GroupDiagnostics] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportDiagnostics:
    pages: list[PageDiagnostics] = field(default_factory=list)
    accepted_rows: int = 0
    unique_records: int = 0
    duplicate_records: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def candidate_rows(self) -> int:
        return sum(g.candidate_rows for p in self.pages for g in p.groups)

    @property
    def rejected_rows(self) -> int:
        return sum(g.rejected_rows for p in self.pages for g in p.groups)

    @property
    def unprocessed_rows(self) -> int:
        return sum(g.unprocessed_rows for p in self.pages for g in p.groups)

    @property
    def status(self) -> str:
        has_issues = bool(self.errors or any(p.errors for p in self.pages)
                          or self.rejected_rows or self.unprocessed_rows)
        if has_issues:
            return "partial" if self.unique_records else "failed"
        if self.pages and all(p.expected_count_known for p in self.pages):
            return "complete"
        return "unverified"

    @property
    def requires_acknowledgment(self) -> bool:
        return self.status == "partial"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ImportDiagnostics":
        values = dict(data)
        pages = []
        for page in values.pop("pages", []):
            pv = dict(page)
            groups = []
            for group in pv.pop("groups", []):
                gv = dict(group)
                gv["rows"] = [RowDiagnostic(**r) for r in gv.get("rows", [])]
                groups.append(GroupDiagnostics(**gv))
            pages.append(PageDiagnostics(groups=groups, **pv))
        return cls(pages=pages, **values)

    def summary(self) -> str:
        if self.status == "complete":
            return f"Complete: {self.unique_records} items; {self.duplicate_records} duplicates removed."
        if self.status == "unverified":
            return f"{self.unique_records} items; completeness not verified."
        issues = []
        for page in self.pages:
            if page.errors:
                issues.append(f"page {page.page}: {'; '.join(page.errors)}")
            for group in page.groups:
                if group.rejected_rows or group.unprocessed_rows:
                    issues.append(f"page {page.page}, group {group.group}: "
                                  f"{group.rejected_rows} rejected, {group.unprocessed_rows} unprocessed")
        issues.extend(self.errors)
        return f"{self.status.title()} import: {self.unique_records} recovered items. " + "; ".join(issues)


try:
    from .catalog_reader import CatalogImportMetadata
except ImportError:
    try:
        from catalog_reader import CatalogImportMetadata
    except ImportError:
        class CatalogImportMetadata(dict):
            """Metadata dictionary stored in frame.attrs['catalog_import']."""
            def __init__(self, diagnostics: Any, fingerprint: Optional[Any], acknowledgment_token: str):
                super().__init__({
                    "fingerprint": asdict(fingerprint) if fingerprint else None,
                    "diagnostics": diagnostics.to_dict() if hasattr(diagnostics, "to_dict") else diagnostics,
                })
                self.diagnostics = diagnostics
                self.fingerprint = fingerprint
                self.acknowledgment_token = acknowledgment_token

            @property
            def status(self) -> str:
                return getattr(self.diagnostics, "status", "unknown")


@dataclass
class CatalogResult:
    dataframe: pd.DataFrame
    diagnostics: ImportDiagnostics
    fingerprint: Optional[FileFingerprint] = None

    @property
    def acknowledgment_token(self) -> str:
        payload = {
            "fingerprint": asdict(self.fingerprint) if self.fingerprint else None,
            "diagnostics": self.diagnostics.to_dict(),
            "records": self.dataframe.to_json(orient="split", index=False, force_ascii=False),
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def is_current(self, path: Optional[str] = None) -> bool:
        return self.fingerprint is not None and self.fingerprint.is_current(path)

    def to_dataframe(self) -> pd.DataFrame:
        frame = self.dataframe.copy(deep=True)
        frame.attrs[METADATA_KEY] = CatalogImportMetadata(
            diagnostics=self.diagnostics,
            fingerprint=self.fingerprint,
            acknowledgment_token=self.acknowledgment_token,
        )
        return frame

    @classmethod
    def from_dataframe(cls, frame: pd.DataFrame) -> Optional["CatalogResult"]:
        metadata = frame.attrs.get(METADATA_KEY)
        if isinstance(metadata, cls):
            return metadata
        if not isinstance(metadata, dict):
            return None
        try:
            diag_attr = getattr(metadata, "diagnostics", None)
            fp_attr = getattr(metadata, "fingerprint", None)
            if isinstance(diag_attr, ImportDiagnostics):
                return cls(frame.copy(deep=True), diag_attr, fp_attr)

            fingerprint = metadata.get("fingerprint")
            diag_val = metadata.get("diagnostics")
            if isinstance(diag_val, ImportDiagnostics):
                diag_obj = diag_val
            elif isinstance(diag_val, dict):
                diag_obj = ImportDiagnostics.from_dict(diag_val)
            else:
                return None

            fp_obj = None
            if isinstance(fingerprint, FileFingerprint):
                fp_obj = fingerprint
            elif isinstance(fingerprint, dict):
                fp_obj = FileFingerprint(**fingerprint)

            return cls(frame.copy(deep=True), diag_obj, fp_obj)
        except (KeyError, TypeError, ValueError):
            return None
