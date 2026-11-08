"""Shared, serializable evidence for catalog extraction and cache validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from typing import Any, Optional

import pandas as pd
import pymupdf

PARSER_REVISION = "2026.11.08.1"
METADATA_KEY = "catalog_import"


@dataclass(frozen=True)
class FileFingerprint:
    path: str
    sha256: str
    parser_revision: str = PARSER_REVISION
    library_version: str = pymupdf.__version__
    ocr_model_version: str = "rapidocr_arabic_ppocrv3_v1"
    recovery_config_hash: str = "v26_bounded_default"

    @classmethod
    def from_path(
        cls,
        path: str,
        ocr_model_version: str = "rapidocr_arabic_ppocrv3_v1",
        recovery_config_hash: str = "v26_bounded_default",
    ) -> "FileFingerprint":
        canonical = os.path.normcase(os.path.realpath(os.path.abspath(path)))
        digest = hashlib.sha256()
        with open(canonical, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return cls(
            canonical,
            digest.hexdigest(),
            ocr_model_version=ocr_model_version,
            recovery_config_hash=recovery_config_hash,
        )

    def is_current(self, path: Optional[str] = None) -> bool:
        try:
            target = path or self.path
            canonical = os.path.normcase(os.path.realpath(os.path.abspath(target)))
            digest = hashlib.sha256()
            with open(canonical, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            current_fp = FileFingerprint(
                canonical,
                digest.hexdigest(),
                parser_revision=PARSER_REVISION,
                library_version=pymupdf.__version__,
                ocr_model_version=self.ocr_model_version,
                recovery_config_hash=self.recovery_config_hash,
            )
            return self == current_fp
        except OSError:
            return False


def build_source_id(
    page: int,
    table: int = 0,
    group: Optional[int] = None,
    row: Optional[int] = None,
    is_region_issue: bool = False,
) -> str:
    """Builds a canonical source_id with separate page, table, group, and row components."""
    g_part = f"_g{group}" if group is not None else ""
    if is_region_issue or row is None:
        return f"p{page}_t{table}{g_part}_region"
    return f"p{page}_t{table}{g_part}_r{row}"


def find_legacy_source_id_candidates(source_id: str, available_ids: Any) -> list[str]:
    """
    Finds all candidate 4-part (or 3-part) source IDs in `available_ids` that could correspond
    to a legacy 3-part `source_id` ('p{P}_t{T}_r{R}').
    Under historical schemes:
    - `parse_structural_table` emitted 'p{P}_t{table_idx}_r{R}' for all groups in `table_idx` (`t == T`).
    - Page-level group indexing emitted 'p{P}_t{table_idx + group_idx}_r{R}' (`t + g == T`).
    If `len(candidates) > 1`, the legacy 3-part ID is ambiguous and must not be guessed.
    """
    import re
    id_list = [str(x) for x in available_ids if isinstance(x, str) and x]
    if not source_id:
        return []
    pat = re.compile(r"^p(\d+)_t(\d+)(?:_g(\d+))?_(r\d+|region)$")
    m_src = pat.match(source_id)
    if not m_src:
        return [source_id] if source_id in id_list else []

    p_s, t_s, g_s, r_s = m_src.groups()
    # If source_id is already an explicit 4-part ID, it is never a legacy guess
    if g_s is not None:
        if source_id in id_list:
            return [source_id]
        # Match legacy 3-part ID in available_ids only if g_s == '0' and no other group exists on that page/row
        legacy_equiv = f"p{p_s}_t{t_s}_{r_s}"
        if g_s == "0" and legacy_equiv in id_list:
            same_page_row_4part = [
                cand for cand in id_list
                if (mc := pat.match(cand)) and mc.group(1) == p_s and mc.group(4) == r_s and mc.group(3) is not None
            ]
            if not same_page_row_4part:
                return [legacy_equiv]
        return []

    # source_id is a legacy 3-part ID (g_s is None)
    t_int = int(t_s)
    four_part_candidates: list[str] = []
    for cand in id_list:
        mc = pat.match(cand)
        if not mc:
            continue
        p_c, t_c, g_c, r_c = mc.groups()
        if p_c != p_s or r_c != r_s:
            continue
        if g_c is not None:
            tc_int = int(t_c)
            gc_int = int(g_c)
            if tc_int == t_int or (tc_int + gc_int) == t_int:
                if cand not in four_part_candidates:
                    four_part_candidates.append(cand)

    if four_part_candidates:
        return four_part_candidates
    if source_id in id_list:
        return [source_id]
    return []


def is_ambiguous_legacy_source_id(source_id: str, available_ids: Any) -> bool:
    """
    Returns True when a legacy 3-part source_id ('p{P}_t{T}_r{R}') could map to multiple
    distinct 4-part (table, group) rows on the same page and row.
    """
    import re
    m = re.match(r"^p(\d+)_t(\d+)_(r\d+|region)$", str(source_id or ""))
    if not m:
        return False
    candidates = find_legacy_source_id_candidates(source_id, available_ids)
    return len(candidates) > 1


def source_id_matches(candidate_id: str, target_id: str, available_ids: Any = None) -> bool:
    """
    Returns True if candidate_id and target_id unambiguously refer to the same source identity.
    When `available_ids` is provided, refuses to match a legacy 3-part ID if it is ambiguous.
    """
    if not candidate_id or not target_id:
        return False
    if candidate_id == target_id:
        if available_ids is not None and is_ambiguous_legacy_source_id(target_id, available_ids):
            return False
        return True
    if available_ids is not None:
        if is_ambiguous_legacy_source_id(target_id, available_ids) or is_ambiguous_legacy_source_id(candidate_id, available_ids):
            return False
    import re
    pat = re.compile(r"^p(\d+)_t(\d+)(?:_g(\d+))?_(r\d+|region)$")
    m1 = pat.match(candidate_id)
    m2 = pat.match(target_id)
    if not m1 or not m2:
        return False
    p1, t1, g1, r1 = m1.groups()
    p2, t2, g2, r2 = m2.groups()
    if p1 != p2 or t1 != t2 or r1 != r2:
        return False
    # Legacy ID without group matches group 0 only when unambiguous
    if (g1 is None and g2 == "0") or (g2 is None and g1 == "0"):
        return True
    return g1 == g2


def resolve_compatible_source_id(source_id: str, available_ids: Any) -> str:
    """
    Resolves a source_id (including unambiguous legacy 3-part IDs) against a collection of available IDs.
    Never guesses when a legacy 3-part ID is ambiguous across multiple groups/tables.
    """
    id_list = list(available_ids)
    if is_ambiguous_legacy_source_id(source_id, id_list):
        return source_id
    candidates = find_legacy_source_id_candidates(source_id, id_list)
    if len(candidates) == 1:
        return candidates[0]
    if source_id in id_list:
        return source_id
    return source_id


@dataclass
class SourceIdentity:
    page: int
    table: int = 0
    row: Optional[int] = None
    bbox: Optional[list[float]] = None
    is_region_issue: bool = False
    source_id: str = ""
    group: Optional[int] = None
    page_number: Optional[int] = None
    region_bbox: Optional[list[float]] = None

    def __post_init__(self) -> None:
        if self.page_number is None and self.page is not None:
            self.page_number = self.page
        elif self.page is None and self.page_number is not None:
            self.page = self.page_number

        if self.region_bbox is None and self.bbox is not None:
            self.region_bbox = list(self.bbox) if self.bbox else None
        elif self.bbox is None and self.region_bbox is not None:
            self.bbox = list(self.region_bbox) if self.region_bbox else None

        if self.row is None:
            self.is_region_issue = True
        if self.source_id and self.group is None:
            import re
            m = re.match(r"p(\d+)_t(\d+)(?:_g(\d+))?_(?:r(\d+)|region)", self.source_id)
            if m and m.group(3) is not None:
                self.group = int(m.group(3))
        if not self.source_id:
            self.source_id = build_source_id(
                page=self.page,
                table=self.table,
                group=self.group,
                row=self.row,
                is_region_issue=self.is_region_issue or (self.row is None),
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceIdentity":
        valid_keys = {"page", "table", "row", "bbox", "is_region_issue", "source_id", "group", "page_number", "region_bbox"}
        clean = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**clean)


def explain_rejection_reason(reason: str) -> str:
    """
    Translates technical validation/rejection codes into a clear, plain-language
    Arabic & English explanation for the user inside the review UI.
    """
    if not reason:
        return "هذا الصف تم قبوله أو تصحيحه بنجاح. / Row accepted or corrected."
    r = str(reason).strip()
    r_low = r.lower()
    if r_low in ("unverified_ocr_strength_sequence", "ambiguous_ocr_decimal", "unverified_ocr_engine"):
        return "تعذر تأكيد التركيز من المصدر؛ تم الاحتفاظ بالصف دون اعتماده للشراء. / Source strength could not be verified; the row is retained but excluded from procurement."
    if "suspicious_characters" in r_low:
        return "يحتوي اسم الصنف على رموز غير مقروءة أو حروف مشفرة من خط PDF ويحتاج لتأكيد الاسم. / Item name contains unreadable or unmapped font characters and needs verification."
    if "numeric_mutation" in r_low:
        return "تغيرت الأرقام أو التركيز أثناء معالجة النص؛ تم إيقاف الصف لحماية التركيز والعبوة. / Numeric values or strength changed during normalization; held to protect dosage/pack size."
    if "invalid_price" in r_low or "missing_price" in r_low:
        return "سعر الصنف مفقود أو خارج النطاق المسموح (0 - 10000 ج.م). / Item price is missing or outside valid range (0 - 10,000 EGP)."
    if "invalid_discount" in r_low:
        return "نسبة الخصم غير صالحة أو تتجاوز الحد الأقصى المسموح (85%). / Discount percentage is invalid or exceeds maximum allowed (85%)."
    if "image_only_page" in r_low:
        return "هذه الصفحة عبارة عن صورة ممسوحة ضوئياً بدون نص رقمي؛ يرجى مراجعتها يدوياً. / This page is a scanned image without digital text; manual review required."
    if "ocr_unreliable" in r_low or "ocr_low_confidence" in r_low:
        return "تعذر قراءة نص الصنف بدقة عبر التعرف الضوئي (OCR)؛ يرجى المراجعة أو إعادة المحاولة. / Text could not be reliably recognized via OCR; manual review or retry required."
    if "table_recovery_failed" in r_low:
        return "تعذر استخراج هيكل الجدول من الصورة تلقائياً. / Table layout could not be recovered automatically from image."
    if "unmapped_page_content" in r_low or "unmapped_table_region" in r_low:
        return "منطقة في الصفحة تحتوي على نص لم يتم التعرف على هيكل جدوله تلقائياً. / Page region contains text whose table structure could not be mapped automatically."
    if "catalog_noise" in r_low or "header" in r_low:
        return "يبدو هذا السطر كعنوان جدول أو بيانات ترويسة وليس صنف دواء. / Row appears to be a table header or page banner rather than a medicine."
    if "empty_name" in r_low or "blank_name" in r_low or "missing_item_name" in r_low or "name_too_short" in r_low:
        return "اسم الصنف فارغ أو قصير جداً ولا يمكن اعتماده تلقائياً. / Medicine name is empty or too short to accept automatically."
    if "manual_exclusion" in r_low or "excluded" in r_low:
        return "تم استبعاد هذا الصف يدوياً بواسطة المستخدم. / This row was manually excluded by the user."
    if "ambiguous_legacy_correction" in r_low:
        return "تصحيح محفوظ بهوية قديمة غامضة قد ينطبق على أكثر من جدول أو مجموعة؛ يرجى مراجعته وتحديده يدوياً. / Saved correction uses an ambiguous legacy row identity that could match multiple groups/tables; manual review required."
    return f"يحتاج هذا الصف لمراجعة يدوية للتحقق من البيانات ({r}). / Row requires manual review to verify extracted fields ({r})."


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
    is_region_level: bool = False
    # Common field metadata (v2.6)
    source_file_hash: str = ""
    page_number: Optional[int] = None
    region_bbox: Optional[list[float]] = None
    raw_digital_text: Optional[str] = None
    raw_ocr_text: Optional[str] = None
    extraction_method: str = "digital_vector"
    validation_results: dict[str, Any] = field(default_factory=dict)
    retry_history: list[str] = field(default_factory=list)
    column_bounds: Optional[dict[str, tuple[float, float]]] = None
    final_acceptance_state: str = ""

    @property
    def plain_explanation(self) -> str:
        return explain_rejection_reason(self.rejection_reason)

    def __post_init__(self) -> None:
        if self.identity is not None and not self.source_id:
            self.source_id = self.identity.source_id
        elif self.identity is None and self.source_id:
            import re
            m = re.match(r"p(\d+)_t(\d+)(?:_g(\d+))?_(?:r(\d+)|region)", self.source_id)
            if m:
                p, t, g, r = m.groups()
                self.identity = SourceIdentity(
                    page=int(p),
                    table=int(t),
                    group=int(g) if g is not None else None,
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

        if self.page_number is None and self.identity is not None:
            self.page_number = self.identity.page

        if self.region_bbox is None and self.bbox is not None:
            self.region_bbox = list(self.bbox) if self.bbox else None
        elif self.bbox is None and self.region_bbox is not None:
            self.bbox = list(self.region_bbox) if self.region_bbox else None

        if not self.retry_history and self.attempted_strategies:
            self.retry_history = list(self.attempted_strategies)
        elif not self.attempted_strategies and self.retry_history:
            self.attempted_strategies = list(self.retry_history)

        if not self.final_acceptance_state:
            if self.resolved:
                self.final_acceptance_state = "accepted"
            elif self.provenance == "automatic_recovery":
                self.final_acceptance_state = "partially_recovered"
            elif self.rejection_reason in ("rejected", "invalid_price", "invalid_discount"):
                self.final_acceptance_state = "rejected"
            else:
                self.final_acceptance_state = "unresolved"
        elif self.final_acceptance_state == "accepted" and not self.resolved:
            self.resolved = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewIssue":
        d = dict(data)
        ident = d.get("identity")
        if isinstance(ident, dict):
            d["identity"] = SourceIdentity.from_dict(ident)
        valid_fields = {
            "source_id", "identity", "raw_cells", "bbox", "rejection_reason",
            "attempted_strategies", "strategy_outcomes", "provenance", "resolved", "item",
            "source_file_hash", "page_number", "region_bbox", "raw_digital_text", "raw_ocr_text",
            "extraction_method", "validation_results", "retry_history", "final_acceptance_state"
        }
        clean_d = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**clean_d)


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
    item: Optional[dict[str, Any]] = None
    # Common field metadata (v2.6)
    source_file_hash: str = ""
    page_number: Optional[int] = None
    region_bbox: Optional[list[float]] = None
    raw_digital_text: Optional[str] = None
    raw_ocr_text: Optional[str] = None
    extraction_method: str = "digital_vector"
    validation_results: dict[str, Any] = field(default_factory=dict)
    retry_history: list[str] = field(default_factory=list)
    column_bounds: Optional[dict[str, tuple[float, float]]] = None
    final_acceptance_state: str = ""

    def __post_init__(self) -> None:
        if not self.source_id:
            if self.is_region_issue or self.row is None:
                self.source_id = f"p{self.page}_t{self.table}_region"
            else:
                self.source_id = f"p{self.page}_t{self.table}_r{self.row}"

        if self.page_number is None and self.page is not None:
            self.page_number = self.page
        elif self.page is None and self.page_number is not None:
            self.page = self.page_number

        if self.region_bbox is None and self.bbox is not None:
            self.region_bbox = list(self.bbox) if self.bbox else None
        elif self.bbox is None and self.region_bbox is not None:
            self.bbox = list(self.region_bbox) if self.region_bbox else None

        if not self.retry_history and self.attempted_strategies:
            self.retry_history = list(self.attempted_strategies)
        elif not self.attempted_strategies and self.retry_history:
            self.attempted_strategies = list(self.retry_history)

        if not self.final_acceptance_state:
            if self.outcome in ("accepted", "recovered", "corrected"):
                self.final_acceptance_state = "accepted"
            elif self.outcome == "rejected":
                self.final_acceptance_state = "rejected"
            elif self.outcome == "partially_recovered":
                self.final_acceptance_state = "partially_recovered"
            elif self.outcome == "unprocessed":
                self.final_acceptance_state = "unresolved"
            else:
                self.final_acceptance_state = self.outcome or "unresolved"
        elif not self.outcome:
            self.outcome = self.final_acceptance_state

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RowDiagnostic":
        valid_keys = {
            "page", "group", "row", "outcome", "reason", "bbox", "raw_cells",
            "item_name", "table", "is_region_issue", "source_id", "attempted_strategies",
            "provenance", "item", "source_file_hash", "page_number", "region_bbox",
            "raw_digital_text", "raw_ocr_text", "extraction_method", "validation_results",
            "retry_history", "final_acceptance_state"
        }
        clean = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**clean)

    def to_review_issue(self) -> ReviewIssue:
        ident = SourceIdentity(
            page=self.page,
            table=self.table,
            group=self.group,
            row=None if self.is_region_issue else self.row,
            bbox=self.bbox,
            is_region_issue=self.is_region_issue,
            source_id=self.source_id,
            page_number=self.page_number or self.page,
            region_bbox=self.region_bbox or self.bbox,
        )
        issue_item = dict(self.item) if isinstance(self.item, dict) else ({"item_name": self.item_name} if self.item_name else None)
        return ReviewIssue(
            source_id=self.source_id,
            identity=ident,
            raw_cells=list(self.raw_cells),
            bbox=list(self.bbox) if self.bbox else None,
            rejection_reason=self.reason or self.outcome,
            attempted_strategies=list(self.attempted_strategies),
            strategy_outcomes={},
            provenance=self.provenance,
            resolved=(self.outcome in ("accepted", "recovered", "corrected")),
            item=issue_item,
            source_file_hash=self.source_file_hash,
            page_number=self.page_number or self.page,
            region_bbox=list(self.region_bbox) if self.region_bbox else (list(self.bbox) if self.bbox else None),
            raw_digital_text=self.raw_digital_text,
            raw_ocr_text=self.raw_ocr_text,
            extraction_method=self.extraction_method,
            validation_results=dict(self.validation_results),
            retry_history=list(self.retry_history or self.attempted_strategies),
            column_bounds=self.column_bounds,
            final_acceptance_state=self.final_acceptance_state or ("accepted" if self.outcome in ("accepted", "recovered", "corrected") else "unresolved"),
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
    page_classification: str = "usable_digital"
    selected_method: str = ""
    assessment_reasons: list[str] = field(default_factory=list)
    font_repaired: bool = False


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
        valid_page_keys = {
            "page", "strategy", "expected_count_known", "accepted_rows", "errors",
            "page_classification", "selected_method", "assessment_reasons", "font_repaired"
        }
        valid_group_keys = {
            "group", "strategy", "candidate_rows", "accepted_rows", "rejected_rows",
            "unprocessed_rows", "bbox", "rows"
        }
        valid_row_keys = {
            "page", "group", "row", "outcome", "reason", "bbox", "raw_cells",
            "item_name", "table", "is_region_issue", "source_id", "attempted_strategies",
            "provenance", "item", "source_file_hash", "page_number", "region_bbox",
            "raw_digital_text", "raw_ocr_text", "extraction_method", "validation_results",
            "retry_history", "final_acceptance_state"
        }
        for page in values.pop("pages", []):
            pv = dict(page)
            groups = []
            for group in pv.pop("groups", []):
                gv = dict(group)
                gv["rows"] = [
                    RowDiagnostic(**{rk: rv for rk, rv in r.items() if rk in valid_row_keys})
                    for r in gv.get("rows", [])
                ]
                groups.append(GroupDiagnostics(**{gk: gval for gk, gval in gv.items() if gk in valid_group_keys}))
            clean_pv = {pk: pval for pk, pval in pv.items() if pk in valid_page_keys}
            pages.append(PageDiagnostics(groups=groups, **clean_pv))
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
    def status(self) -> str:
        return getattr(self.diagnostics, "status", "unverified") if self.diagnostics else "unverified"

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
                valid_fp_keys = {
                    "path", "sha256", "parser_revision", "library_version",
                    "ocr_model_version", "recovery_config_hash"
                }
                clean_fp = {k: v for k, v in fingerprint.items() if k in valid_fp_keys}
                fp_obj = FileFingerprint(**clean_fp)

            return cls(
                dataframe=frame.copy(deep=True),
                diagnostics=diag_obj,
                fingerprint=fp_obj,
                review_issues=review_issues,
                issues_by_source_id=issues_by_source_id,
            )
        except (KeyError, TypeError, ValueError):
            return None
