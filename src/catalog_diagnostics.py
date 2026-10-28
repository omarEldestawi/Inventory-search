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
class SourceIdentity:
    page: int
    table: int = 0
    row: Optional[int] = None
    bbox: Optional[list[float]] = None
    is_region_issue: bool = False
    source_id: str = ""

    def __post_init__(self) -> None:
        if self.row is None:
            self.is_region_issue = True
        if not self.source_id:
            if self.is_region_issue or self.row is None:
                self.source_id = f"p{self.page}_t{self.table}_region"
            else:
                self.source_id = f"p{self.page}_t{self.table}_r{self.row}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceIdentity":
        return cls(**data)


@dataclass
class ReviewIssue:
    source_id: str = ""
    identity: Optional[SourceIdentity] = None
    raw_cells: list[Any] = field(default_factory=list)
    bbox: Optional[list[float]] = None
    rejection_reason: str = ""
    attempted_strategies: list[str] = field(default_factory=list)
    strategy_outcomes: dict[str, str] = field(default_factory=dict)
    provenance: str = "original_extraction"
    resolved: bool = False
    item: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.identity is not None and not self.source_id:
            self.source_id = self.identity.source_id
        elif self.identity is None and self.source_id:
            import re
            m = re.match(r"p(\d+)_t(\d+)_(?:r(\d+)|region)", self.source_id)
            if m:
                p, t, r = m.groups()
                self.identity = SourceIdentity(
                    page=int(p),
                    table=int(t),
                    row=int(r) if r is not None else None,
                    bbox=self.bbox,
                    is_region_issue=(r is None),
                    source_id=self.source_id,
                )
            else:
                self.identity = SourceIdentity(
                    page=1,
                    table=0,
                    row=None,
                    bbox=self.bbox,
                    is_region_issue=True,
                    source_id=self.source_id,
                )
        if self.bbox is None and self.identity is not None and self.identity.bbox:
            self.bbox = self.identity.bbox

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewIssue":
        d = dict(data)
        ident = d.get("identity")
        if isinstance(ident, dict):
            d["identity"] = SourceIdentity.from_dict(ident)
        return cls(**d)


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
    table: int = 0
    is_region_issue: bool = False
    source_id: str = ""
    attempted_strategies: list[str] = field(default_factory=list)
    provenance: str = "original_extraction"

    def __post_init__(self) -> None:
        if not self.source_id:
            if self.is_region_issue or self.row is None:
                self.source_id = f"p{self.page}_t{self.table}_region"
            else:
                self.source_id = f"p{self.page}_t{self.table}_r{self.row}"

    def to_review_issue(self) -> ReviewIssue:
        ident = SourceIdentity(
            page=self.page,
            table=self.table,
            row=None if self.is_region_issue else self.row,
            bbox=self.bbox,
            is_region_issue=self.is_region_issue,
            source_id=self.source_id,
        )
        return ReviewIssue(
            source_id=self.source_id,
            identity=ident,
            raw_cells=list(self.raw_cells),
            bbox=self.bbox,
            rejection_reason=self.reason or self.outcome,
            attempted_strategies=list(self.attempted_strategies),
            strategy_outcomes={},
            provenance=self.provenance,
            resolved=(self.outcome in ("accepted", "recovered", "corrected")),
            item={"item_name": self.item_name} if self.item_name else None,
        )


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
    unresolved_region_count: int = 0
    attempted_recovery_count: int = 0
    successful_recovery_count: int = 0

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
                          or self.rejected_rows or self.unprocessed_rows or self.unresolved_region_count)
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
        valid_keys = {
            "accepted_rows", "unique_records", "duplicate_records", "errors", "warnings",
            "unresolved_region_count", "attempted_recovery_count", "successful_recovery_count"
        }
        clean_values = {k: v for k, v in values.items() if k in valid_keys}
        return cls(pages=pages, **clean_values)

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
    review_issues: list[ReviewIssue] = field(default_factory=list)
    issues_by_source_id: dict[str, ReviewIssue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.review_issues and not self.issues_by_source_id and self.diagnostics:
            extracted_issues: list[ReviewIssue] = []
            for p in getattr(self.diagnostics, "pages", []):
                for g in getattr(p, "groups", []):
                    for r in getattr(g, "rows", []):
                        if getattr(r, "outcome", None) not in ("accepted",):
                            extracted_issues.append(r.to_review_issue())
            if extracted_issues:
                self.review_issues = extracted_issues
                self.issues_by_source_id = {iss.source_id: iss for iss in extracted_issues if iss.source_id}
        elif self.review_issues and not self.issues_by_source_id:
            self.issues_by_source_id = {issue.source_id: issue for issue in self.review_issues if issue.source_id}
        elif self.issues_by_source_id and not self.review_issues:
            self.review_issues = list(self.issues_by_source_id.values())

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
        meta = CatalogImportMetadata(
            diagnostics=self.diagnostics,
            fingerprint=self.fingerprint,
            acknowledgment_token=self.acknowledgment_token,
        )
        if self.review_issues:
            meta["review_issues"] = [issue.to_dict() for issue in self.review_issues]
            try:
                meta.review_issues = [issue.to_dict() for issue in self.review_issues]
            except Exception:
                pass
        frame.attrs[METADATA_KEY] = meta
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
            raw_issues = getattr(metadata, "review_issues", None)
            if raw_issues is None and isinstance(metadata, dict):
                raw_issues = metadata.get("review_issues", [])
            review_issues: list[ReviewIssue] = []
            if isinstance(raw_issues, list):
                for iss in raw_issues:
                    if isinstance(iss, ReviewIssue):
                        review_issues.append(iss)
                    elif isinstance(iss, dict):
                        review_issues.append(ReviewIssue.from_dict(iss))
            issues_by_source_id = {iss.source_id: iss for iss in review_issues if iss.source_id}

            if isinstance(diag_attr, ImportDiagnostics):
                return cls(
                    dataframe=frame.copy(deep=True),
                    diagnostics=diag_attr,
                    fingerprint=fp_attr,
                    review_issues=review_issues,
                    issues_by_source_id=issues_by_source_id,
                )

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

            return cls(
                dataframe=frame.copy(deep=True),
                diagnostics=diag_obj,
                fingerprint=fp_obj,
                review_issues=review_issues,
                issues_by_source_id=issues_by_source_id,
            )
        except (KeyError, TypeError, ValueError):
            return None
