"""원본 도면·내역서·수량산출서를 내부 검토 구조로 변환하는 MVP 전처리기.

이 모듈은 AI 학습을 수행하지 않는다. 업로드된 원본을 읽어 원본값·표준화값·근거
위치를 저장하고, 가능한 범위에서 규칙 기반 산식·수량·연결 경고를 생성한다.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import (
    DrawingChangeCandidate,
    Building,
    EvidenceReference,
    MappingCandidate,
    PreprocessingArtifact,
    PreprocessingRecord,
    PreprocessingRun,
    ProcurementPriceResult,
    Project,
    ReviewWarning,
    SourceFile,
    StandardizedItem,
)
from .quantity_rule_engine import canonical_key as _comparison_key, canonical_name as _comparison_name, canonical_unit as _comparison_unit, spec_compatible as _comparison_spec_compatible


HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "item_code": ("품목코드", "항목코드", "item_code", "code"),
    "item_name": ("품명", "품목", "항목", "item_name", "name", "공종명"),
    "specification": ("규격", "사양", "specification", "spec", "재질", "강도"),
    "unit": ("단위", "unit", "수량단위"),
    "quantity": ("수량", "물량", "quantity", "qty", "산출수량"),
    # 철골 산출서는 일반 물량 외에 중량과 자재/부재 분류를 별도 열로
    # 관리한다. 이 정보가 사라지면 H형강·볼트·도장 같은 연관 공종을
    # 개별 품명 문자열만으로 비교하게 되므로, 원본 행 메타데이터로 보존한다.
    "quantity_ton": ("물량(TON)", "물량TON", "톤수", "중량(TON)", "tonnage"),
    "material_class": ("자재구분", "자재 분류", "재료구분"),
    "member_class": ("부재구분", "부재 분류"),
    "unit_price": ("단가", "unit_price", "price", "계약단가"),
    "amount": ("금액", "합계금액", "amount", "total", "금액계"),
    "formula": ("산식", "계산식", "formula", "수량산식"),
    "drawing_number": ("도면번호", "도면 번호", "drawing_number", "drawing_no"),
    "sheet_name": ("시트", "시트명", "sheet", "sheet_name"),
    "building": ("동", "건물", "building", "동명"),
    # 산출서에는 층/공간이 각각 "층범위", "부위"로 표기되는 경우가
    # 많다. 별도 컬럼으로 보존해야 같은 품명의 산출근거를 문맥으로
    # 좁힐 수 있으며, 값을 품명에 합쳐 버리면 원본 추적이 어려워진다.
    "floor": ("층", "floor", "층명", "층범위", "층 범위"),
    "space": ("공간", "실", "space", "실명", "부위", "부위명", "공간명"),
}

# Raw estimate workbooks can contain reference sections for adjacent buildings
# and plant areas.  Those rows may still inherit the workbook's ``사무동``
# building label, so the textual scope guard is intentionally kept alongside
# the parser and reused by every changed-item promotion path.
NON_OFFICE_SCOPE_TOKENS = (
    "보안동",
    "분석동",
    "재활용창고",
    "특고압동",
    "폐수처리동",
    "폐기물처리동",
    "수처리동",
    "덕트하우스",
    "계근대",
    "PIPE RACK",
    "한라IMS",
    "분리수거장",
)


def is_non_office_scope(*values: object) -> bool:
    """Return whether row text explicitly belongs to a non-office area."""
    text = " ".join(str(value or "") for value in values).casefold()
    return any(token.casefold() in text for token in NON_OFFICE_SCOPE_TOKENS)


def _clean_key(value: object) -> str:
    return re.sub(r"[\s_\-./()]+", "", str(value or "")).lower()


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    if not cleaned or cleaned in {"-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalized_name(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower()) or None


def _is_section_heading(item_name: object, mapped: dict[str, object]) -> bool:
    """Return ``True`` for a numbered work-package or sub-section heading.

    Estimate workbooks put labels such as ``0306. 타일공사`` and
    ``0318. 골재대`` directly above their item rows.  Those labels can share
    the item/specification columns with the data table, so they must not
    become review rows merely because the row also contains a building label.
    A real item with a unit, formula, or non-zero numeric quantity is retained.
    """
    name = str(item_name or "").strip()
    # Some sheets use four/five digit section numbers and omit the dot
    # entirely (``0413 골재대`` / ``12010. 운반비``).  The quantity/unit
    # guard below keeps real item rows safe while excluding these labels.
    if not re.fullmatch(r"\d{2,6}\s*(?:[.)]\s*|\s+).+", name):
        return False
    if _text(mapped.get("unit")) or _text(mapped.get("formula")):
        return False
    return _number(mapped.get("quantity")) in {None, 0.0}


def _building_heading(values: object) -> str | None:
    """Detect an explicit building section heading, not an item description."""
    text = " ".join(str(value or "") for value in (values.values() if isinstance(values, dict) else values))
    if not text:
        return None
    explicit_section = bool(re.search(r"(?:창호명|계단실명|동\s*명|구분명|^\s*\d+\.)", text))
    if ("[" in text and "]" in text) or "■" in text or explicit_section:
        if "사무동" in text:
            return "사무동"
        if "공장동" in text:
            return "공장동"
    return None


def _safe_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha1(value.encode('utf-8')).hexdigest()[:24]}"


def _input_hash(files: list[SourceFile]) -> str:
    material = "|".join(f"{item.id}:{item.sha256 or ''}" for item in files)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class RawPreprocessor:
    # Bump whenever workbook context extraction changes so an identical upload
    # is reprocessed instead of reusing a stale snapshot.
    # Bump when row inclusion/classification semantics change so an existing
    # completed run cannot silently mask the new preprocessing rules.
    parser_version = "raw-v10"

    def __init__(self, upload_root: Path | None = None):
        self.upload_root = upload_root or get_settings().upload_dir
        self._office_alias_catalog: list[dict[str, object]] | None = None

    def _office_aliases(self) -> list[dict[str, object]]:
        """Load the audited 사무동 vocabulary map for raw-upload matching."""
        if self._office_alias_catalog is not None:
            return self._office_alias_catalog
        path = get_settings().preprocessing_dir / "14_사무동_현재검토_표준화매핑.csv"
        if not path.is_file():
            self._office_alias_catalog = []
            return self._office_alias_catalog
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                self._office_alias_catalog = [
                    row for row in csv.DictReader(source)
                    if row.get("in_scope") == "Y" and str(row.get("building") or "").strip() == "사무동"
                ]
        except (OSError, csv.Error):
            self._office_alias_catalog = []
        return self._office_alias_catalog

    @staticmethod
    def _xlsx_rows(path: Path) -> list[tuple[str, dict[str, str]]]:
        """Read workbook rows while preserving sheet/row traceability.

        The first version of the MVP assumed that the first row of the first
        worksheet was a flat header.  Real cost workbooks are not shaped that
        way: they contain merged, multi-row headers, several sheets, and
        formulas with cached values.  That assumption silently converted every
        item into the filename, which is why changed quantity rows appeared as
        ``추출되지 않음``.  Keep the parser dependency-free, but detect a
        canonical header row on every sheet and retain the original row number.
        """
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for item in root.findall("x:si", ns):
                    shared.append("".join(node.text or "" for node in item.findall(".//x:t", ns)))
            sheet_paths = sorted(
                (name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
                key=lambda name: int(re.search(r"(\d+)", name).group(1)),
            )
            if not sheet_paths:
                return []
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            rows: list[tuple[str, dict[str, str]]] = []
            alias_to_target = {
                _clean_key(alias): target
                for target, aliases in HEADER_ALIASES.items()
                for alias in aliases
            }

            def cell_value(cell: ET.Element) -> str:
                raw = cell.find("x:v", ns)
                value = raw.text if raw is not None and raw.text is not None else ""
                if cell.attrib.get("t") == "s" and value.isdigit() and int(value) < len(shared):
                    value = shared[int(value)]
                # A formula cell can have a usable cached numeric result.  Use
                # that result for quantity/amount parsing; the formula text is
                # retained separately when the column itself is 산식.
                formula = cell.find("x:f", ns)
                if (not value) and formula is not None and formula.text:
                    return f"={formula.text}"
                return value

            for sheet_path in sheet_paths:
                root = ET.fromstring(archive.read(sheet_path))
                sheet_rows: list[tuple[str, dict[str, str]]] = []
                for row in root.findall(".//x:sheetData/x:row", ns):
                    values: dict[str, str] = {}
                    for cell in row.findall("x:c", ns):
                        ref = cell.attrib.get("r", "")
                        column = re.sub(r"\d", "", ref) or f"COL{len(values) + 1}"
                        values[column] = cell_value(cell)
                    if values:
                        sheet_rows.append((row.attrib.get("r", str(len(sheet_rows) + 1)), values))
                if not sheet_rows:
                    continue

                # Locate a header row.  Cost sheets commonly use 2~5 header
                # rows; score by the number of known labels instead of relying
                # on a fixed row number.
                header_index = -1
                header_map: dict[str, str] = {}
                for index, (_, values) in enumerate(sheet_rows[:120]):
                    candidate: dict[str, str] = {}
                    for column, value in values.items():
                        target = alias_to_target.get(_clean_key(value))
                        if target and target not in candidate:
                            candidate[target] = column
                    if len(candidate) >= 2 and ("item_name" in candidate or "specification" in candidate):
                        header_index = index
                        header_map = candidate
                        break
                if header_index < 0:
                    # Keep a traceable fallback for unusual files; these rows
                    # will be marked as low-confidence by ``process``.
                    for row_number, values in sheet_rows:
                        rows.append((f"{sheet_path}:row-{row_number}", values))
                    continue

                item_column = header_map.get("item_name")
                unit_column = header_map.get("unit")
                ordered_columns = list(sheet_rows[header_index][1])
                unit_position = ordered_columns.index(unit_column) if unit_column in ordered_columns else -1
                building_context: str | None = None
                # A building heading is often immediately above the first
                # column header, so seed the context from pre-header rows too.
                for _, pre_header_values in sheet_rows[: header_index + 1]:
                    heading = _building_heading(pre_header_values)
                    if heading:
                        building_context = heading
                for row_number, values in sheet_rows[header_index + 1 :]:
                    heading = _building_heading(values)
                    if heading:
                        building_context = heading
                    mapped: dict[str, str] = {}
                    for target, column in header_map.items():
                        if values.get(column, "") != "":
                            mapped[target] = values.get(column, "")
                    if not mapped.get("item_name"):
                        continue
                    item_name = mapped.get("item_name", "").strip()
                    # Bracketed notes/section labels (예: [비고], [공통])
                    # are not 내역 항목 even when the sheet contains a zero
                    # or a note formula beside them.
                    if item_name.startswith("[") and item_name.endswith("]"):
                        continue
                    if building_context and not mapped.get("building"):
                        mapped["building"] = building_context
                    if _is_section_heading(item_name, mapped):
                        continue
                    # Estimate sheets label the quantity column with the
                    # version (변경 전/후) rather than '수량'.  Infer the first
                    # numeric cell after the unit column only in that case.
                    if "quantity" not in mapped:
                        candidates = ordered_columns[unit_position + 1 :] if unit_position >= 0 else ordered_columns
                        for column in candidates:
                            value = values.get(column, "")
                            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value.replace(",", "").strip()):
                                mapped["quantity"] = value
                                break
                    # A row with an item name but no unit, quantity, or spec is
                    # a section label, not an estimate/quantity item.
                    if not any(mapped.get(key) for key in ("unit", "quantity", "specification", "formula")):
                        continue
                    if _is_section_heading(item_name, mapped):
                        continue
                    rows.append((f"{sheet_path}:row-{row_number}", mapped))
            return rows

    @staticmethod
    def _xls_rows(path: Path) -> list[tuple[str, dict[str, str]]]:
        """Read legacy BIFF8 workbooks through xlrd with the same trace format."""
        try:
            import xlrd
        except ImportError as error:  # pragma: no cover - deployment guard
            raise RuntimeError("구형 XLS 파서(xlrd)가 설치되지 않았습니다.") from error

        book = xlrd.open_workbook(str(path), on_demand=True)
        alias_to_target = {
            _clean_key(alias): target
            for target, aliases in HEADER_ALIASES.items()
            for alias in aliases
        }
        result: list[tuple[str, dict[str, str]]] = []

        def value_text(cell: Any) -> str:
            if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
                return ""
            if cell.ctype == xlrd.XL_CELL_BOOLEAN:
                return "TRUE" if cell.value else "FALSE"
            if cell.ctype == xlrd.XL_CELL_NUMBER:
                return f"{cell.value:g}"
            return str(cell.value).strip()

        for sheet in book.sheets():
            matrix = [[value_text(cell) for cell in sheet.row(row_index)] for row_index in range(sheet.nrows)]
            header_index = -1
            header_map: dict[int, str] = {}
            for index, values in enumerate(matrix[:120]):
                candidate: dict[int, str] = {}
                for column, value in enumerate(values):
                    target = alias_to_target.get(_clean_key(value))
                    if target and target not in candidate.values():
                        candidate[column] = target
                if len(candidate) >= 2 and any(target in candidate.values() for target in ("item_name", "specification")):
                    header_index = index
                    header_map = candidate
                    break
            if header_index < 0:
                continue
            building_context: str | None = None
            for pre_header_values in matrix[: header_index + 1]:
                heading = _building_heading(pre_header_values)
                if heading:
                    building_context = heading
            for row_index in range(header_index + 1, sheet.nrows):
                values = matrix[row_index]
                heading = _building_heading(values)
                if heading:
                    building_context = heading
                mapped = {target: values[column] for column, target in header_map.items() if column < len(values) and values[column] != ""}
                item_name = mapped.get("item_name", "").strip()
                if not item_name or (item_name.startswith("[") and item_name.endswith("]")):
                    continue
                if building_context and not mapped.get("building"):
                    mapped["building"] = building_context
                if _is_section_heading(item_name, mapped):
                    continue
                # Some estimate sheets label the quantity column with a
                # version (변경 전/후) instead of 수량. Infer the first numeric
                # value after the unit column, matching the OOXML parser.
                if "quantity" not in mapped:
                    unit_column = next((column for column, target in header_map.items() if target == "unit"), -1)
                    for value in values[unit_column + 1:] if unit_column >= 0 else values:
                        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value.replace(",", "").strip()):
                            mapped["quantity"] = value
                            break
                if not any(mapped.get(key) for key in ("unit", "quantity", "specification", "formula")):
                    continue
                result.append((f"{path.name}:sheet-{sheet.name}:row-{row_index + 1}", mapped))
        return result

    @staticmethod
    def _csv_rows(path: Path) -> list[tuple[str, dict[str, str]]]:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            return [(f"{path.name}:row-{index}", dict(row)) for index, row in enumerate(reader, start=2)]

    @staticmethod
    def _pdf_rows(path: Path) -> list[tuple[str, dict[str, str]]]:
        """Extract bounded page text when pypdf is available; otherwise keep a traceable fallback row."""
        try:
            from pypdf import PdfReader
        except ImportError:
            return [(f"{path.name}:file", {"파일명": path.name, "파일형식": "PDF", "파서상태": "PDF 텍스트 파서 미설치·추가 확인 필요"})]
        try:
            reader = PdfReader(str(path), strict=False)
            rows: list[tuple[str, dict[str, str]]] = []
            for page_number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                rows.append((f"{path.name}:page-{page_number}", {"파일명": path.name, "페이지": str(page_number), "도면텍스트": text[:20000], "파서상태": "페이지 텍스트 추출" if text else "텍스트 없음·추가 확인 필요"}))
            return rows or [(f"{path.name}:file", {"파일명": path.name, "파일형식": "PDF", "파서상태": "페이지 없음·추가 확인 필요"})]
        except Exception as error:
            return [(f"{path.name}:file", {"파일명": path.name, "파일형식": "PDF", "파서상태": f"PDF 파서 오류·추가 확인 필요: {str(error)[:300]}"})]

    @staticmethod
    def _dwg_rows(path: Path) -> list[tuple[str, dict[str, str]]]:
        try:
            header = path.open("rb").read(6).decode("ascii", errors="replace")
        except OSError:
            header = ""
        return [(f"{path.name}:file", {"파일명": path.name, "파일형식": "DWG", "DWG버전": header, "파서상태": "DWG 헤더 확인·CAD 객체 파서 추가 확인 필요"})]

    def _rows(self, source: SourceFile) -> list[tuple[str, dict[str, str]]]:
        path = Path(source.file_path)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return self._csv_rows(path)
        if suffix in {".xlsx", ".xlsm"}:
            try:
                return self._xlsx_rows(path)
            except (OSError, zipfile.BadZipFile, ET.ParseError):
                return [(f"{source.original_name}:file", {"파일명": source.original_name, "파서오류": "XLSX 구조를 읽지 못함"})]
        if suffix == ".xls":
            try:
                return self._xls_rows(path)
            except Exception as error:
                return [(f"{source.original_name}:file", {"파일명": source.original_name, "파일형식": "XLS", "파서오류": f"XLS 구조를 읽지 못함·추가 확인 필요: {str(error)[:300]}"})]
        if suffix == ".pdf":
            return self._pdf_rows(path)
        if suffix == ".dwg":
            return self._dwg_rows(path)
        # PDF/DWG/XLS는 원본 메타데이터를 먼저 검토 단위로 만든다. 전용 OCR/CAD
        # worker가 연결되면 같은 내부 레코드에 페이지·객체 정보를 추가한다.
        return [(f"{source.original_name}:file", {"파일명": source.original_name, "파일형식": source.file_type, "파서상태": "추가 파서 확인 필요"})]

    @staticmethod
    def _map_row(raw: dict[str, Any]) -> dict[str, Any]:
        by_key = {_clean_key(key): value for key, value in raw.items()}
        normalized: dict[str, Any] = {}
        for target, aliases in HEADER_ALIASES.items():
            for alias in aliases:
                value = by_key.get(_clean_key(alias))
                if value not in (None, ""):
                    normalized[target] = value
                    break
        normalized["item_name"] = _text(normalized.get("item_name"))
        normalized["specification"] = _text(normalized.get("specification"))
        normalized["unit"] = _text(normalized.get("unit"))
        normalized["quantity"] = _number(normalized.get("quantity"))
        normalized["quantity_ton"] = _number(normalized.get("quantity_ton"))
        normalized["material_class"] = _text(normalized.get("material_class"))
        normalized["member_class"] = _text(normalized.get("member_class"))
        normalized["unit_price"] = _number(normalized.get("unit_price"))
        normalized["amount"] = _number(normalized.get("amount"))
        normalized["formula"] = _text(normalized.get("formula"))
        normalized["normalized_name"] = _normalized_name(normalized.get("item_name"))
        return normalized

    @staticmethod
    def _kind(source: SourceFile) -> str:
        value = (source.document_type or "").lower()
        if "quantity" in value or "수량" in value:
            return "quantity"
        if "estimate" in value or "내역" in value:
            return "estimate"
        if "drawing" in value or "도면" in value:
            return "drawing"
        return "source"

    @staticmethod
    def _drawing_number(source: SourceFile) -> str | None:
        """Resolve a drawing number from metadata first, then a safe filename hint."""
        explicit = _text(getattr(source, "drawing_number", None))
        if explicit:
            return explicit
        text = " ".join(str(value or "") for value in (getattr(source, "original_name", None), getattr(source, "file_path", None), getattr(source, "sheet_name", None)))
        # Project drawing names commonly contain ``DWG-101``, ``A-101`` or
        # ``S_201``.  Require a drawing prefix so dates and revision numbers
        # are not accidentally promoted to sheet identifiers.
        match = re.search(r"(?:dwg|도면|[asmefp]-?)\s*[-_ ]?\s*(\d{3,4})(?!\d)", text, flags=re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _drawing_discipline(source: SourceFile) -> str | None:
        """Infer a conservative discipline hint for same-number sheets."""
        text = " ".join(str(value or "") for value in (getattr(source, "original_name", None), getattr(source, "file_path", None), getattr(source, "sheet_name", None)))
        for token, label in (("건축", "건축"), ("구조", "구조"), ("토목", "토목"), ("기계", "기계"), ("전기", "전기"), ("소방", "소방")):
            if token in text:
                return label
        return None

    @staticmethod
    def _quantity_field_match(estimate: StandardizedItem, quantity: StandardizedItem, aliases: list[dict[str, object]] | None = None) -> tuple[bool, set[str]]:
        """Apply the same canonical name/spec/unit rules to raw uploads.

        Raw preprocessing must not use stricter string equality than the
        review reader.  Harmless punctuation/unit variants and compatible
        specification token order are accepted; genuine field differences are
        returned so the UI can explain why a candidate was withheld.
        """
        estimate_name = _comparison_name(estimate.normalized_name or estimate.item_name, aliases, specification=estimate.specification, unit=estimate.unit)
        quantity_name = _comparison_name(quantity.normalized_name or quantity.item_name, aliases, specification=quantity.specification, unit=quantity.unit)
        if not estimate_name or estimate_name != quantity_name:
            return False, set()
        mismatch_fields: set[str] = set()
        estimate_unit = _comparison_unit(estimate.unit)
        quantity_unit = _comparison_unit(quantity.unit)
        if estimate_unit and quantity_unit and estimate_unit != quantity_unit:
            mismatch_fields.add("단위")
        if estimate.specification and quantity.specification and not _comparison_spec_compatible(
            estimate.specification,
            quantity.specification,
            aliases,
            left_item=estimate.normalized_name or estimate.item_name,
            right_item=quantity.normalized_name or quantity.item_name,
            left_unit=estimate.unit,
            right_unit=quantity.unit,
        ):
            mismatch_fields.add("규격")
        return not mismatch_fields, mismatch_fields

    @staticmethod
    def _match_baseline_drawing(changed_file: SourceFile, baselines: list[SourceFile]) -> SourceFile | None:
        """Return the safest 기준 도면 match for a 변경 도면.

        도면번호만으로 짝을 지으면 건축·구조처럼 같은 번호를 재사용하는
        공종이 서로 연결될 수 있다. 따라서 건물과 공종(작업 패키지)이
        명시된 경우에는 두 값이 모두 같은 후보만 허용하고, 메타데이터가
        비어 있는 레거시 파일은 도면번호 기준의 보수적 후보로만 남긴다.
        """
        changed_number = RawPreprocessor._drawing_number(changed_file)
        if not changed_number:
            return None
        number = changed_number.strip().casefold()
        candidates = [
            source for source in baselines
            if (RawPreprocessor._drawing_number(source) or "").strip().casefold() == number
        ]
        if not candidates:
            return None

        if changed_file.building_id:
            scoped = [source for source in candidates if getattr(source, "building_id", None) in {None, changed_file.building_id}]
            candidates = scoped or []
        if changed_file.work_package_id:
            scoped = [source for source in candidates if getattr(source, "work_package_id", None) in {None, changed_file.work_package_id}]
            candidates = scoped or []
        changed_discipline = RawPreprocessor._drawing_discipline(changed_file)
        if changed_discipline:
            scoped = [source for source in candidates if RawPreprocessor._drawing_discipline(source) in {None, changed_discipline}]
            candidates = scoped or []
        if not candidates:
            return None

        # 같은 번호의 기준본이 여러 개면 메타데이터가 더 완전한 파일을 우선한다.
        candidates.sort(key=lambda source: (bool(getattr(source, "building_id", None)), bool(getattr(source, "work_package_id", None)), source.id), reverse=True)
        return candidates[0]

    def create_run(self, db: Session, project: Project, source_files: list[SourceFile], requested_by: str | None, source_kind: str = "raw_upload") -> PreprocessingRun:
        if not source_files:
            raise ValueError("전처리할 원본 파일이 없습니다.")
        digest = _input_hash(source_files)
        existing = db.scalar(select(PreprocessingRun).where(PreprocessingRun.project_id == project.id, PreprocessingRun.input_hash == digest, PreprocessingRun.source_kind == source_kind, PreprocessingRun.parser_version == self.parser_version, PreprocessingRun.status == "completed").order_by(PreprocessingRun.created_at.desc()))
        if existing:
            return existing
        max_attempts = min(5, max(1, get_settings().preprocessing_max_attempts))
        run = PreprocessingRun(id=str(uuid4()), project_id=project.id, requested_by=requested_by, source_kind=source_kind, parser_version=self.parser_version, input_hash=digest, source_file_ids=json.dumps([item.id for item in source_files], ensure_ascii=False), source_count=len(source_files), status="queued", max_attempts=max_attempts)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def process(self, db: Session, run: PreprocessingRun) -> int:
        source_ids = json.loads(run.source_file_ids or "[]")
        sources = db.scalars(select(SourceFile).where(SourceFile.id.in_(source_ids))).all()
        # 광양5 사무동 검토 실행에서는 사무동으로 지정된 내역서·수량산출서만
        # 표준화·연결한다. 타건물 파일은 같은 프로젝트에 보관할 수 있지만
        # 단가 참고용으로만 남기고 수량/내역 후보 생성에서 제외한다.
        if run.project_id == "project-g5-office":
            office_building_id = db.scalar(select(Building.id).where(Building.project_id == run.project_id, Building.name == "사무동"))
            if office_building_id:
                sources = [
                    source for source in sources
                    if (
                        self._kind(source) not in {"estimate", "quantity", "drawing"}
                        or (
                            self._kind(source) in {"estimate", "quantity"}
                            and source.building_id == office_building_id
                        )
                        or (
                            self._kind(source) == "drawing"
                            and (source.building_id in {None, office_building_id})
                            and not is_non_office_scope(source.original_name, source.file_path, source.drawing_number)
                        )
                    )
                ]
        items_by_kind: dict[str, list[StandardizedItem]] = {"estimate": [], "quantity": [], "drawing": []}
        processed = 0
        summary: list[dict[str, Any]] = []
        pending_evidence: list[EvidenceReference] = []
        for source in sources:
            kind = self._kind(source)
            source_drawing_number = self._drawing_number(source) if kind == "drawing" else None
            for locator, raw in self._rows(source):
                mapped = self._map_row(raw)
                if kind in {"estimate", "quantity"} and not mapped.get("item_name"):
                    mapped["item_name"] = source.original_name
                formula_quantity_missing = bool(
                    kind == "quantity"
                    and mapped.get("formula")
                    and mapped.get("quantity") is None
                )
                item_id = _safe_id("ITEM", f"{run.id}|{source.id}|{locator}")
                item = StandardizedItem(id=item_id, project_id=run.project_id, source_file_id=source.id, item_kind=kind, item_code=_text(mapped.get("item_code")), item_name=mapped.get("item_name") or source.original_name, normalized_name=mapped.get("normalized_name") or _normalized_name(source.original_name), specification=mapped.get("specification"), unit=mapped.get("unit"), quantity=mapped.get("quantity"), unit_price=mapped.get("unit_price"), total_amount=mapped.get("amount"), formula_text=mapped.get("formula"), formula_result=mapped.get("quantity"), building_label=_text(mapped.get("building")), floor_label=_text(mapped.get("floor")), space_label=_text(mapped.get("space")), drawing_number=_text(mapped.get("drawing_number")) or source_drawing_number, source_row_ref=locator, source_cell_ref=locator, notes=json.dumps({"source_kind": run.source_kind, "parser_version": run.parser_version, "run_id": run.id, "quantity_ton": mapped.get("quantity_ton"), "material_class": mapped.get("material_class"), "member_class": mapped.get("member_class")}, ensure_ascii=False))
                db.merge(item)
                # Warning rows reference this immutable source snapshot. When
                # a formula has no cached quantity, persist the item before
                # adding its FK-backed warning (the normal batch flush occurs
                # later, after all source rows have been parsed).
                if formula_quantity_missing:
                    db.flush()
                if kind in items_by_kind:
                    items_by_kind[kind].append(item)
                parser_ok = (source.file_type in {"CSV", "XLSX", "XLSM", "XLS"} and not raw.get("파서오류")) or raw.get("파서상태") == "페이지 텍스트 추출"
                record_status = "추가 확인 필요" if formula_quantity_missing or not parser_ok else "생성"
                record = PreprocessingRecord(id=_safe_id("PRE", f"{run.id}|{source.id}|{locator}"), run_id=run.id, source_file_id=source.id, item_kind=kind, raw_payload=json.dumps(raw, ensure_ascii=False, default=str), normalized_payload=json.dumps(mapped, ensure_ascii=False, default=str), source_locator=locator, status=record_status, confidence="중간" if parser_ok else "낮음")
                db.merge(record)
                processed += 1
                summary.append({"source_file": source.original_name, "source_locator": locator, "item_kind": kind, "item_name": item.item_name})
                if formula_quantity_missing:
                    warning_id = _safe_id("WARN", f"{run.id}|formula-quantity-missing|{source.id}|{locator}")
                    db.add(ReviewWarning(
                        id=warning_id,
                        project_id=run.project_id,
                        standardized_item_id=item.id,
                        warning_type="formula_quantity_missing",
                        severity="중간",
                        title="산식은 있으나 원본 수량이 비어 있음",
                        detail="수량산출서 행에 산식은 보존됐지만 수량 원본값이 없어 자동 검산·내역 반영을 보류합니다.",
                        expected_value="원본 수량 또는 검토자 확인",
                        actual_value=str(mapped.get("formula")),
                        status="검토 대기",
                        rule_code="RAW_FORMULA_QUANTITY_REQUIRED",
                    ))
                    pending_evidence.append(EvidenceReference(
                        id=_safe_id("EVID", warning_id),
                        project_id=run.project_id,
                        warning_id=warning_id,
                        source_file_id=source.id,
                        evidence_type="formula_quantity_missing",
                        file_path=source.file_path,
                        row_ref=locator,
                        sheet_name=source.sheet_name,
                        evidence_note="수량산출서 산식 존재·원본 수량 미추출",
                        extraction_confidence="중간",
                    ))
                quantity = mapped.get("quantity")
                unit_price = mapped.get("unit_price")
                amount = mapped.get("amount")
                if quantity is not None and unit_price is not None and amount is not None:
                    expected = quantity * unit_price
                    if abs(expected - amount) > max(1.0, abs(expected) * 0.01):
                        warning_id = _safe_id("WARN", f"{run.id}|amount|{source.id}|{locator}")
                        db.add(ReviewWarning(id=warning_id, project_id=run.project_id, standardized_item_id=item.id, warning_type="amount_formula_mismatch", severity="높음", title="수량×단가와 금액 불일치", detail=f"재계산 금액 {expected:,.2f} / 원본 금액 {amount:,.2f}", expected_value=str(expected), actual_value=str(amount), status="검토 대기", rule_code="RAW_AMOUNT_RECHECK"))
                        pending_evidence.append(EvidenceReference(id=_safe_id("EVID", warning_id), project_id=run.project_id, warning_id=warning_id, source_file_id=source.id, evidence_type="raw_formula", file_path=source.file_path, row_ref=locator, sheet_name=source.sheet_name, evidence_note="원본 수량·단가·금액 재계산", extraction_confidence="중간"))
        db.flush()
        # 변경자료에만 존재하는 사무동 내역서는 구매부서 단가 검토
        # 후보를 전처리 실행 시점에 생성한다. 수량·단가는 승인 전 값으로
        # 남기고, 타건물 참고단가와 자동 연결하지 않는다.
        baseline_keys = {
            (_comparison_name(item.normalized_name or item.item_name, self._office_aliases(), specification=item.specification, unit=item.unit), _comparison_key(item.specification), _comparison_unit(item.unit))
            for item in items_by_kind["estimate"]
            if (db.get(SourceFile, item.source_file_id) and db.get(SourceFile, item.source_file_id).version_type == "기준")
        }
        for changed_item in items_by_kind["estimate"]:
            changed_source = db.get(SourceFile, changed_item.source_file_id)
            if not changed_source or changed_source.version_type != "변경":
                continue
            changed_text = " ".join(str(value or "") for value in (changed_item.item_name, changed_item.specification, changed_item.building_label, changed_item.drawing_number))
            if is_non_office_scope(changed_item.item_name, changed_item.specification, changed_item.building_label, changed_item.drawing_number):
                continue
            # A zero/negative changed quantity represents deletion or a
            # non-item subtotal, not a new purchasable line requiring a unit
            # price review.  Keep it in the quantity/change audit instead.
            if changed_item.quantity is None or changed_item.quantity <= 0:
                continue
            changed_key = (_comparison_name(changed_item.normalized_name or changed_item.item_name, self._office_aliases(), specification=changed_item.specification, unit=changed_item.unit), _comparison_key(changed_item.specification), _comparison_unit(changed_item.unit))
            if not changed_key[0] or changed_key in baseline_keys:
                continue
            # The source row is the business identity of a candidate.  Do not
            # include the preprocessing run id, otherwise rerunning the same
            # source set creates duplicate price-review rows.
            candidate_id = f"NEW-CMP-{hashlib.sha256(f'{run.project_id}|{changed_item.source_file_id}|{changed_item.source_row_ref or changed_item.id}'.encode('utf-8')).hexdigest()[:16]}"
            db.merge(ProcurementPriceResult(
                id=_safe_id("PRICE", candidate_id),
                project_id=run.project_id,
                standardized_item_id=changed_item.id,
                candidate_id=candidate_id,
                standard_key=changed_item.item_code or changed_item.normalized_name,
                item_name=changed_item.item_name,
                specification=changed_item.specification,
                unit=changed_item.unit,
                lookup_status="변경 후 신규 · 수량 승인 전 단가 검토 대기",
                service_name="기준·변경 대조 전처리",
                query_text=changed_item.item_name or changed_item.normalized_name,
                source_file_id=changed_source.id,
                source_set="변경자료 신규내역",
                work_package="사무동 내역 신규",
                changed_quantity=str(changed_item.quantity) if changed_item.quantity is not None else None,
                evidence=f"변경자료 내역서 {changed_source.original_name} · {changed_item.source_row_ref or '원본 행'} · 기준자료 표준키 미발견",
            ))
        db.flush()
        # 수량산출서와 내역서의 연결 후보를 만든다. 연결이 없을 때만 일반 경고를 만들며,
        # 도면 연결 미확인만으로 불가/높음 판정을 만들지 않는다.
        estimates = items_by_kind["estimate"]
        office_aliases = self._office_aliases()
        for quantity_item in items_by_kind["quantity"]:
            field_results = [
                (item, *self._quantity_field_match(item, quantity_item, office_aliases))
                for item in estimates
            ]
            name_matches = [item for item, _, _ in field_results if _comparison_name(item.normalized_name or item.item_name, office_aliases, specification=item.specification, unit=item.unit) == _comparison_name(quantity_item.normalized_name or quantity_item.item_name, office_aliases, specification=quantity_item.specification, unit=quantity_item.unit)]
            matches = [item for item, compatible, _ in field_results if compatible]
            mismatch_fields: set[str] = set()
            for item, _, fields in field_results:
                if item in name_matches:
                    mismatch_fields.update(fields)
            if mismatch_fields:
                warning_id = _safe_id("WARN", f"{run.id}|field-mismatch|{quantity_item.id}|{'|'.join(sorted(mismatch_fields))}")
                estimate_refs = ", ".join(f"{item.source_row_ref or item.id}" for item in name_matches[:3])
                source = db.get(SourceFile, quantity_item.source_file_id) if quantity_item.source_file_id else None
                db.add(ReviewWarning(id=warning_id, project_id=run.project_id, standardized_item_id=quantity_item.id, warning_type="field_mismatch", severity="중간", title=f"품명 일치 항목의 {'·'.join(sorted(mismatch_fields))} 확인 필요", detail=f"수량산출서 값과 내역서 후보의 {'·'.join(sorted(mismatch_fields))}이(가) 다릅니다. 비교 후보 행: {estimate_refs or '없음'}", expected_value="내역서 후보와 동일", actual_value="·".join(sorted(mismatch_fields)), status="검토 대기", rule_code="RAW_FIELD_MATCH"))
                pending_evidence.append(EvidenceReference(id=_safe_id("EVID", warning_id), project_id=run.project_id, warning_id=warning_id, source_file_id=source.id if source else None, evidence_type="field_mismatch", file_path=source.file_path if source else None, row_ref=quantity_item.source_row_ref, sheet_name=source.sheet_name if source else None, evidence_note="품명·규격·단위 표준화 값 대조", extraction_confidence="중간"))
            if matches:
                for estimate in matches[:3]:
                    mapping_id = _safe_id("MAP", f"{run.id}|{quantity_item.id}|{estimate.id}")
                    db.merge(MappingCandidate(id=mapping_id, project_id=run.project_id, estimate_item_id=estimate.id, quantity_item_id=quantity_item.id, candidate_key=quantity_item.normalized_name, match_method="raw_name_unit_match", confidence="중간", status="검토 대기", source_candidate_count=len(matches), auto_decision="자동 확정 금지"))
            else:
                warning_id = _safe_id("WARN", f"{run.id}|quantity-estimate-link|{quantity_item.id}")
                db.add(ReviewWarning(id=warning_id, project_id=run.project_id, standardized_item_id=quantity_item.id, warning_type="quantity_estimate_link_missing", severity="일반", title="수량산출서와 내역서 연결 확인 필요", detail="원본 품명·규격·단위로 대응 내역을 찾지 못했습니다. 도면 연결 실패가 아니라 수량·내역 연결 검토 대상입니다.", status="검토 대기", rule_code="RAW_QUANTITY_ESTIMATE_LINK"))
                source = db.get(SourceFile, quantity_item.source_file_id) if quantity_item.source_file_id else None
                pending_evidence.append(EvidenceReference(id=_safe_id("EVID", warning_id), project_id=run.project_id, warning_id=warning_id, source_file_id=source.id if source else None, evidence_type="quantity_estimate_link", file_path=source.file_path if source else None, row_ref=quantity_item.source_row_ref, sheet_name=source.sheet_name if source else None, evidence_note="수량산출서와 내역서 연결 후보 없음", extraction_confidence="중간"))
        # Warning rows must exist before evidence rows because the schema uses
        # foreign keys without ORM relationships to express this dependency.
        db.flush()
        if pending_evidence:
            db.add_all(pending_evidence)
            db.flush()
        # 기준/변경 도면은 후보만 만든다. 기준 도면이 없으면 일반 경고를 만들지 않고 연결 후보 상태로 둔다.
        drawing_sources = [source for source in sources if self._kind(source) == "drawing"]
        base = [source for source in drawing_sources if source.version_type == "기준"]
        changed = [source for source in drawing_sources if source.version_type == "변경"]
        for changed_file in changed:
            baseline = self._match_baseline_drawing(changed_file, base)
            drawing_number = self._drawing_number(changed_file)
            drawing_id = _safe_id("DRAW", f"{run.project_id}|{baseline.id if baseline else 'none'}|{changed_file.id}|{drawing_number or 'unknown'}")
            db.merge(DrawingChangeCandidate(id=drawing_id, project_id=run.project_id, before_file_id=baseline.id if baseline else None, after_file_id=changed_file.id, discipline=self._drawing_discipline(changed_file), drawing_number=drawing_number, candidate_text="기준·변경 도면 변경 후보", change_type="전후 비교 후보", location_ref=changed_file.sheet_name, confidence="중간" if baseline else "낮음", status="연결 후보", baseline_file=baseline.file_path if baseline else None, changed_file=changed_file.file_path, baseline_revision=baseline.revision if baseline else None, changed_revision=changed_file.revision, sheet_number=changed_file.sheet_name))
        artifact_dir = self.upload_root / run.project_id / "preprocessing"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{run.id}.json"
        payload = json.dumps({"run_id": run.id, "source_kind": run.source_kind, "parser_version": run.parser_version, "input_hash": run.input_hash, "processed_count": processed, "records": summary}, ensure_ascii=False, indent=2).encode("utf-8")
        artifact_path.write_bytes(payload)
        db.merge(PreprocessingArtifact(id=_safe_id("ART", run.id), run_id=run.id, artifact_type="normalized_summary", file_path=str(artifact_path), sha256=hashlib.sha256(payload).hexdigest()))
        return processed
