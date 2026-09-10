"""원본 전처리 CSV를 읽되 절대 수정하지 않는 읽기 전용 어댑터."""

import csv
import json
import hashlib
import re
from collections import Counter
from pathlib import Path

from ..config import get_settings
from .raw_preprocessor import _is_section_heading
from .quantity_rule_engine import (
    canonical_key as _engine_canonical_key,
    canonical_unit as _engine_canonical_unit,
    classify_material_relation,
    clean_text as _engine_clean_text,
    compare_version_quantities,
    compare_related_totals,
    compare_quantity,
    formula_rounding_tolerance,
    simple_formula_value as _engine_simple_formula_value,
    spec_compatible as _engine_spec_compatible,
    warning_threshold as _engine_warning_threshold,
)


_WORK_PACKAGE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("방수공사", ("방수", "우레탄", "도막")),
    ("조적공사", ("조적", "벽돌", "블록")),
    ("철골공사", ("철골", "H-", "H형", "SG", "강재", "ST'L", "스틸")),
    ("철근콘크리트공사", ("철근", "콘크리트", "거푸집", "HD", "D13", "D16", "D22", "무근")),
    ("토공사", ("토공", "터파기", "되메우기", "잔토", "굴착", "잡석", "토사")),
    ("타일공사", ("타일",)),
    ("석공사", ("화강석", "석재", "돌붙임", "물갈기")),
    ("유리공사", ("유리", "복층유리", "강화유리")),
    ("금속공사", ("금속", "알루미늄", "알미늄", "코너비드", "후레싱", "난간")),
    ("미장공사", ("몰탈", "모르타르", "미장", "시멘트")),
    ("도장공사", ("도장", "에폭시", "코팅", "페인트")),
    ("수장공사", ("석고보드", "장판", "벽지", "천장", "마감")),
    ("패널공사", ("패널", "판넬", "샌드위치")),
    ("창호공사", ("창호", "문", "셔터")),
    ("홈통공사", ("홈통", "드레인")),
)


def infer_work_package(*values: object) -> str:
    """내역서 공사분류 명칭으로 후보 항목을 분류한다."""
    text = " ".join(str(value or "") for value in values).upper()
    for label, keywords in _WORK_PACKAGE_RULES:
        if any(keyword.upper() in text for keyword in keywords):
            return label
    return "미분류·원천 확인 필요"


def _clean_text(value: object) -> str:
    """Normalize harmless whitespace/case differences for field comparison."""
    return _engine_clean_text(value)


def _spec_compatible(left: object, right: object) -> bool:
    """Compare specifications independent of punctuation/order.

    Estimate sheets often write ``(D.R.A+T4) Φ500`` while calculation sheets
    write ``Φ500, (D.R.A+T4)``. They describe the same specification, but a
    raw string comparison treated them as unrelated and hid the recalculated
    quantity. Token comparison keeps meaningful numbers/materials while
    ignoring commas, brackets and ordering.
    """
    return _engine_spec_compatible(left, right)


def _canonical_unit(value: object) -> str:
    """Keep harmless unit spellings from splitting one quantity group."""
    return _engine_canonical_unit(value)


def _canonical_key(value: object) -> str:
    """Normalize a comparison key without replacing the displayed original."""
    return _engine_canonical_key(value)


def _simple_formula_value(value: object) -> float | None:
    """Evaluate only literal arithmetic retained from a quantity sheet.

    Formula cells containing a workbook reference, function, name, or any
    non-arithmetic token are intentionally not evaluated here. They remain
    traceable `재검산 불가` evidence instead of being guessed.
    """
    return _engine_simple_formula_value(value)


_formula_rounding_tolerance = formula_rounding_tolerance


class PreprocessingReader:
    def __init__(self, root: Path | None = None):
        self.root = root or get_settings().preprocessing_dir
        self._office_mapping_catalog: list[dict[str, str]] | None = None

    def _office_mappings(self) -> list[dict[str, str]]:
        """Load historic office mappings strictly as read-only comparison aids.

        The mapping file is an audited reference to vocabulary and source-row
        relations discovered during the previous office review.  It is *not*
        an approval record for a new upload: current quantities are always
        read from the current raw-upload run below.
        """
        if self._office_mapping_catalog is not None:
            return self._office_mapping_catalog
        path = self.root / "14_사무동_현재검토_표준화매핑.csv"
        if not path.exists():
            self._office_mapping_catalog = []
            return self._office_mapping_catalog
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            self._office_mapping_catalog = [
                row for row in csv.DictReader(source)
                if row.get("in_scope") == "Y" and _clean_text(row.get("building")) == "사무동"
            ]
        return self._office_mapping_catalog

    def _standardized_fields(self, item) -> tuple[str, str, str, bool]:
        """Return semantic name/spec/unit and whether legacy vocabulary helped.

        This intentionally standardizes only items covered by the existing
        사무동 mapping reference.  Unknown incoming vocabulary remains a
        traceable raw comparison rather than being guessed from a fuzzy match.
        """
        item_name = _canonical_key(item.item_name or item.normalized_name)
        specification = _canonical_key(item.specification)
        unit = _canonical_unit(item.unit)
        for mapping in self._office_mappings():
            original_name = _canonical_key(mapping.get("original_item"))
            standard_name = _canonical_key(mapping.get("standard_item"))
            original_spec = _canonical_key(mapping.get("original_spec"))
            estimate_spec = _canonical_key(mapping.get("estimate_spec"))
            original_unit = _canonical_unit(mapping.get("original_unit"))
            standard_unit = _canonical_unit(mapping.get("standard_unit"))
            # Name aliases are admitted only when the accompanying spec/unit
            # agrees with this audited mapping. This stops a generic item name
            # from joining unrelated work packages.
            name_matches = item_name in {original_name, standard_name}
            spec_matches = not specification or specification in {original_spec, estimate_spec}
            unit_matches = not unit or unit in {original_unit, standard_unit}
            if name_matches and spec_matches and unit_matches:
                return standard_name or item_name, estimate_spec or specification, standard_unit or unit, True
        return item_name, specification, unit, False

    @staticmethod
    def _quantity_warning_threshold(total_amount: object) -> float:
        """PRD quantity-warning band; distinct from the exact-match tolerance."""
        return _engine_warning_threshold(total_amount)

    def rows(self, file_name: str) -> list[dict[str, str]]:
        path = self.root / file_name
        if not path.exists():
            raise FileNotFoundError(f"전처리 파일을 찾을 수 없습니다: {path}")
        # 전처리 산출물은 UTF-8/BOM 형태로 생성되어 있어 BOM을 제거한다.
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            return list(csv.DictReader(source))

    def dashboard(self) -> dict:
        status_rows = self.rows("118_final_preprocessing_status.csv")
        queue = self.rows("72_사무동_검토우선순위_작업대기열.csv")
        return {
            "status_rows": status_rows,
            "critical_items": [row for row in queue if row.get("severity") == "높음"][:8],
            "total_queue": len(queue),
        }

    def review_items(self, limit: int = 50, status: str | None = None) -> list[dict[str, str]]:
        rows = self.rows("72_사무동_검토우선순위_작업대기열.csv")
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows[:limit]

    def rule_run(self) -> tuple[dict[str, int], list[dict[str, str]]]:
        """규칙: 자동 확정 금지, 복수 후보, 근거 대기, 낮은 신뢰도를 재검토로 분류한다."""
        findings = self.rows("70_사무동_자동연결_경고승인_통합.csv")
        results: Counter[str] = Counter()
        flagged: list[dict[str, str]] = []
        for finding in findings:
            candidate_count = int(finding.get("source_candidate_count") or 0)
            status = finding.get("status", "")
            confidence = finding.get("confidence", "")
            if candidate_count > 1:
                outcome = "추가 확인 필요"
            elif "대기" in status or confidence == "낮음":
                outcome = "근거 요청"
            else:
                outcome = "조건부 일치"
            results[outcome] += 1
            if outcome != "조건부 일치":
                copy = dict(finding)
                copy["rule_outcome"] = outcome
                flagged.append(copy)
        return dict(results), flagged[:50]

    def prices(self) -> list[dict[str, str]]:
        queue = self.rows("79_사무동_구매부서_신규내역_단가검토_대기열.csv")
        api = {r.get("candidate_id"): r for r in self.rows("86_사무동_PriceInfoService_단가조회결과.csv")}
        for item in queue:
            item["api_status"] = api.get(item.get("candidate_id"), {}).get("조회상태", "조회 이력 없음")
        return queue

    @staticmethod
    def _drawing_revision(path: str | None) -> str | None:
        """Extract a revision token from a source filename when it is present."""
        if not path:
            return None
        match = re.search(r"(?:rev[. _-]?)([A-Za-z0-9]+)", path, flags=re.IGNORECASE)
        return f"Rev.{match.group(1)}" if match else None

    def drawing_candidates(self, limit: int = 200) -> list[dict[str, object]]:
        """Return drawing-only before/after mapping candidates from preprocessing.

        The 06 mapping file is deliberately kept separate from the quantity
        review queue.  A row here means that a drawing pair or a missing side
        needs human/CAD confirmation; it is not a quantity mismatch and must
        not be rendered as one.
        """
        rows = self.rows("06_도면_전후매핑후보.csv")
        result: list[dict[str, object]] = []
        for row_number, row in enumerate(rows, start=2):
            baseline_file = (row.get("baseline_file") or "").strip() or None
            changed_file = (row.get("changed_file") or "").strip() or None
            sheet_number = (row.get("sheet_number") or "").strip() or None
            pair_status = (row.get("pair_status") or "검토 후보").strip()
            if "구조" in " ".join(filter(None, (baseline_file, changed_file))):
                discipline = "구조"
            elif "건축" in " ".join(filter(None, (baseline_file, changed_file))):
                discipline = "건축"
            else:
                discipline = (row.get("discipline") or "미분류").strip() or "미분류"
            identity = "|".join((baseline_file or "", changed_file or "", sheet_number or "", pair_status))
            candidate_id = f"DRAW-LEGACY-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
            result.append({
                "id": candidate_id,
                "project_id": "project-g5-office",
                "discipline": discipline,
                "drawing_number": sheet_number,
                "candidate_text": f"도면 전후 매핑 후보 · {pair_status}",
                "change_type": pair_status,
                "location_ref": f"시트 {sheet_number}" if sheet_number else None,
                "confidence": "중간" if baseline_file and changed_file else "낮음",
                "status": "근거 확인 대기",
                "source_row_ref": f"06_도면_전후매핑후보.csv:{row_number}",
                "baseline_file": baseline_file,
                "changed_file": changed_file,
                "baseline_revision": PreprocessingReader._drawing_revision(baseline_file),
                "changed_revision": PreprocessingReader._drawing_revision(changed_file),
                "sheet_number": sheet_number,
                "next_action": (row.get("next_action") or "원본 도면과 CAD 객체를 확인하세요.").strip(),
            })
        return result[:max(1, min(limit, 1000))]

    @staticmethod
    def _display_number(value: object) -> str | None:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{number:g}"

    @staticmethod
    def _steel_role(item, metadata: dict[str, object]) -> str:
        """Classify a steel row without converting it into an approval link."""
        text = " ".join(str(value or "") for value in (
            item.item_name, metadata.get("material_class"), metadata.get("member_class"), item.formula_text,
        )).lower()
        if any(token in text for token in ("가공", "조립", "세우기", "설치", "용접")):
            return "시공"
        if any(token in text for token in ("도장", "페인트", "내화", "방청")):
            return "도장·내화"
        if any(token in text for token in ("h형강", "강판", "앵커", "볼트", "철골", "steel", "자재")):
            return "자재"
        return "분류 확인 필요"

    def _steel_relation_summary(self, quantities: list, source_by_id: dict) -> list[dict[str, object]]:
        """Summarize steel material/install tonnage by original member category.

        Paint/fireproofing rows commonly use area, not tonnes; they are kept as
        traceable relation evidence but never forced into a tonne comparison.
        The summary is deliberately separate from estimate quantity judgements.
        """
        groups: dict[tuple[str, str], dict[str, object]] = {}
        steel_sources_without_metadata: list[str] = []
        for item in quantities:
            source = source_by_id.get(item.source_file_id)
            try:
                metadata = json.loads(item.notes or "{}")
            except (TypeError, ValueError):
                metadata = {}
            source_name = source.original_name if source else ""
            if "철골" not in source_name and not metadata.get("material_class") and not metadata.get("member_class"):
                continue
            if not any(metadata.get(key) is not None for key in ("quantity_ton", "material_class", "member_class")):
                if source_name and source_name not in steel_sources_without_metadata:
                    steel_sources_without_metadata.append(source_name)
                # Do not infer TON or member relations from an ordinary length/
                # area quantity. The source is still reported below as a
                # traceable preprocessing gap.
                continue
            version = source.version_type if source else "미지정"
            member = str(metadata.get("member_class") or metadata.get("material_class") or "부재구분 미기록").strip()
            key = (version, member)
            group = groups.setdefault(key, {
                "version": version,
                "member_class": member,
                "material_ton": 0.0,
                "construction_ton": 0.0,
                "paint_evidence_count": 0,
                "source_rows": [],
                "material_count": 0,
                "construction_count": 0,
            })
            role = self._steel_role(item, metadata)
            ton_value = metadata.get("quantity_ton")
            if ton_value is None and _canonical_unit(item.unit) == "ton":
                ton_value = item.quantity
            try:
                ton = float(ton_value) if ton_value is not None else None
            except (TypeError, ValueError):
                ton = None
            if role == "자재" and ton is not None:
                group["material_ton"] += ton
                group["material_count"] += 1
            elif role == "시공" and ton is not None:
                group["construction_ton"] += ton
                group["construction_count"] += 1
            elif role == "도장·내화":
                group["paint_evidence_count"] += 1
            if len(group["source_rows"]) < 5:
                group["source_rows"].append(f"{source_name} · {item.source_row_ref}")

        summary: list[dict[str, object]] = []
        for group in groups.values():
            material_ton = float(group["material_ton"])
            construction_ton = float(group["construction_ton"])
            relation = compare_related_totals(
                material_ton if group["material_count"] else None,
                construction_ton if group["construction_count"] else None,
            )
            gap, result = relation.difference, relation.result
            summary.append({
                "version": group["version"],
                "member_class": group["member_class"],
                "material_ton": self._display_number(material_ton) if group["material_count"] else None,
                "construction_ton": self._display_number(construction_ton) if group["construction_count"] else None,
                "difference_ton": self._display_number(gap),
                "paint_evidence_count": group["paint_evidence_count"],
                "result": result,
                "source_rows": group["source_rows"],
                "rule": "철골 자재·시공 TON 총량 비교 / 도장·내화는 산식 근거로 별도 확인",
            })
        if not summary and steel_sources_without_metadata:
            return [{
                "version": "현재 자료 세트",
                "member_class": "철골 자재·부재 분류",
                "material_ton": None,
                "construction_ton": None,
                "difference_ton": None,
                "paint_evidence_count": 0,
                "result": "원본 분류 열 미추출",
                "source_rows": steel_sources_without_metadata[:5],
                "rule": "현재 등록 철골 원본에는 물량(TON)·자재구분·부재구분 열이 없어 총량 연계 판정을 보류",
            }]
        return sorted(summary, key=lambda item: (str(item["version"]), str(item["member_class"])))

    def _material_construction_relation_summary(self, quantities: list, source_by_id: dict) -> list[dict[str, object]]:
        """Summarize explicit material↔construction relation candidates.

        This is an evidence panel, not an approval decision. Rows without an
        explicit family/role marker are omitted instead of being fuzzy-joined.
        """
        groups: dict[tuple[str, str, str], dict[str, object]] = {}
        for item in quantities:
            source = source_by_id.get(item.source_file_id)
            source_name = source.original_name if source else ""
            relation = classify_material_relation(item.item_name, item.specification, item.notes)
            if not relation:
                continue
            family, role = relation
            # 철골은 TON·부재군 전용 패널에서 별도로 비교한다.
            if family == "철골":
                continue
            unit = _canonical_unit(item.unit) or "단위 미기록"
            version = source.version_type if source else "미지정"
            key = (version, family, unit)
            group = groups.setdefault(key, {
                "version": version,
                "relation_family": family,
                "unit": unit,
                "material_quantity": 0.0,
                "construction_quantity": 0.0,
                "material_count": 0,
                "construction_count": 0,
                "source_rows": [],
            })
            try:
                quantity = float(item.quantity) if item.quantity is not None else None
            except (TypeError, ValueError):
                quantity = None
            if quantity is not None and role == "재료":
                group["material_quantity"] += quantity
                group["material_count"] += 1
            elif quantity is not None and role == "시공":
                group["construction_quantity"] += quantity
                group["construction_count"] += 1
            if len(group["source_rows"]) < 5:
                group["source_rows"].append(f"{source_name} · {item.source_row_ref}")

        result: list[dict[str, object]] = []
        for group in groups.values():
            relation_result = compare_related_totals(
                group["material_quantity"] if group["material_count"] else None,
                group["construction_quantity"] if group["construction_count"] else None,
            )
            result.append({
                "version": group["version"],
                "relation_family": group["relation_family"],
                "unit": group["unit"],
                "material_quantity": self._display_number(group["material_quantity"]) if group["material_count"] else None,
                "construction_quantity": self._display_number(group["construction_quantity"]) if group["construction_count"] else None,
                "difference": self._display_number(relation_result.difference),
                "result": relation_result.result,
                "source_rows": group["source_rows"],
                "rule": "명시적 재료·시공 역할과 동일 단위의 총량만 관계 후보로 비교",
            })
        return sorted(result, key=lambda item: (str(item["version"]), str(item["relation_family"]), str(item["unit"])))

    def _baseline_changed_comparison(self, items: list[dict[str, object]]) -> list[dict[str, object]]:
        """Aggregate baseline/changed estimate rows by the same office item key."""
        groups: dict[tuple[str, str], dict[str, object]] = {}
        for item in items:
            source_set = item.get("source_set")
            if source_set not in ("기준자료", "변경자료"):
                continue
            item_key = str(item.get("item_key") or "").strip()
            work_package = str(item.get("work_package") or "미분류·원천 확인 필요").strip()
            if not item_key:
                continue
            try:
                quantity = float(item.get("original_value")) if item.get("original_value") is not None else None
            except (TypeError, ValueError):
                quantity = None
            key = (work_package, item_key)
            group = groups.setdefault(key, {
                "work_package": work_package,
                "item_key": item_key,
                "item_text": item.get("item_text") or item_key,
                "baseline_quantity": None,
                "changed_quantity": None,
                "baseline_count": 0,
                "changed_count": 0,
                "source_rows": [],
                "baseline_source_rows": [],
                "changed_source_rows": [],
            })
            if source_set == "기준자료":
                group["baseline_quantity"] = (group["baseline_quantity"] or 0) + quantity if quantity is not None else group["baseline_quantity"]
                group["baseline_count"] += 1
            else:
                group["changed_quantity"] = (group["changed_quantity"] or 0) + quantity if quantity is not None else group["changed_quantity"]
                group["changed_count"] += 1
            locator = str(item.get("source_locator") or item.get("source_file") or "").strip()
            if locator and len(group["source_rows"]) < 6:
                group["source_rows"].append(locator)
                group["baseline_source_rows" if source_set == "기준자료" else "changed_source_rows"].append(locator)

        result: list[dict[str, object]] = []
        for group in groups.values():
            if not group["baseline_count"] or not group["changed_count"]:
                continue
            comparison = compare_version_quantities(group["baseline_quantity"], group["changed_quantity"])
            result.append({
                "work_package": group["work_package"],
                "item_key": group["item_key"],
                "item_text": group["item_text"],
                "baseline_quantity": self._display_number(group["baseline_quantity"]),
                "changed_quantity": self._display_number(group["changed_quantity"]),
                "difference": self._display_number(comparison.difference),
                "difference_rate": f"{comparison.difference_rate * 100:.2f}%" if comparison.difference_rate is not None else None,
                "result": comparison.result,
                "baseline_count": group["baseline_count"],
                "changed_count": group["changed_count"],
                "source_rows": group["source_rows"],
                "baseline_source_rows": group["baseline_source_rows"],
                "changed_source_rows": group["changed_source_rows"],
                "rule": "내역서 표준키·공종별 기준/변경 원본 수량 합계 대조(승인 전 비교값)",
            })
        return sorted(result, key=lambda item: (str(item["work_package"]), str(item["item_key"])))[:500]

    @staticmethod
    def _comparison_items(project_id: str, comparisons: list[dict[str, object]]) -> list[dict[str, object]]:
        """Expose comparison groups through the same table contract as findings."""
        items: list[dict[str, object]] = []
        for row in comparisons:
            result = str(row.get("result") or "대조 근거 없음")
            issue_type = "일치" if result == "변경 없음(허용오차)" else "불일치"
            severity = "낮음" if issue_type == "일치" else "중간"
            items.append({
                "id": f"comparison:{row['work_package']}:{row['item_key']}",
                "project_id": project_id,
                "source_set": "기준·변경 대조",
                "version": "기준↔변경",
                "discipline": "사무동",
                "work_package": row["work_package"],
                "item_key": row["item_key"],
                "item_text": row["item_text"],
                "source_file": None,
                "sheet_or_drawing": "기준·변경 대조",
                "source_locator": " · ".join(row.get("source_rows") or []),
                "baseline_source_locator": " · ".join(row.get("baseline_source_rows") or []),
                "changed_source_locator": " · ".join(row.get("changed_source_rows") or []),
                "comparison_rate": row.get("difference_rate"),
                "quantity_context": "내역서 기준·변경 원본행 합계",
                "quantity_candidates": [],
                "issue_type": issue_type,
                "judgement": result,
                "severity": severity,
                "status": "승인 대기",
                "confidence": "중간",
                "original_value": row.get("baseline_quantity"),
                "recalculated_value": row.get("changed_quantity"),
                "recalculated_basis": "기준·변경 내역서 행 합계",
                "difference": row.get("difference"),
                "evidence": row.get("rule"),
                "required_action": "변경 사유와 원본 행을 확인한 뒤 승인하세요.",
                "rule_version": "comparison-v1-내역서기준·공종·표준키",
                "locator_status": "RESOLVED" if row.get("source_rows") else "UNRESOLVED",
            })
        return items

    def _steel_coating_formula_summary(self, quantities: list, source_by_id: dict) -> list[dict[str, object]]:
        """Recheck paint/fireproofing rows calculated inside a steel workbook."""
        groups: dict[tuple[str, str], dict[str, object]] = {}
        coating_tokens = ("페인트", "도장", "방청", "녹막이", "내화")
        for item in quantities:
            source = source_by_id.get(item.source_file_id)
            source_name = source.original_name if source else ""
            if "철골" not in source_name or not any(token in str(item.item_name or "") for token in coating_tokens):
                continue
            version = source.version_type if source else "미지정"
            key = (version, str(item.item_name or "도장·내화 항목"))
            group = groups.setdefault(key, {
                "version": version,
                "item_name": item.item_name or "도장·내화 항목",
                "stored_quantity": 0.0,
                "recalculated_quantity": 0.0,
                "formula_count": 0,
                "matched_count": 0,
                "mismatch_count": 0,
                "not_evaluable_count": 0,
                "source_missing_count": 0,
                "source_rows": [],
            })
            calculated = _simple_formula_value(item.formula_text)
            if item.quantity is not None:
                group["stored_quantity"] += float(item.quantity)
            if calculated is None:
                group["not_evaluable_count"] += 1
            else:
                group["formula_count"] += 1
                group["recalculated_quantity"] += calculated
                if item.quantity is None:
                    group["source_missing_count"] += 1
                elif abs(float(item.quantity) - calculated) <= _formula_rounding_tolerance(float(item.quantity)):
                    group["matched_count"] += 1
                else:
                    group["mismatch_count"] += 1
            if len(group["source_rows"]) < 5:
                group["source_rows"].append(f"{source_name} · {item.source_row_ref}")
        result: list[dict[str, object]] = []
        for group in groups.values():
            if group["source_missing_count"]:
                status = "원본 수량 미추출"
            elif group["mismatch_count"]:
                status = "산식 수량 차이 확인 필요"
            elif group["formula_count"]:
                status = "단순 산식 재계산 일치"
            else:
                status = "산식 재검산 불가"
            result.append({
                "version": group["version"],
                "item_name": group["item_name"],
                "stored_quantity": self._display_number(group["stored_quantity"]),
                "recalculated_quantity": self._display_number(group["recalculated_quantity"]) if group["formula_count"] else None,
                "formula_count": group["formula_count"],
                "matched_count": group["matched_count"],
                "mismatch_count": group["mismatch_count"],
                "not_evaluable_count": group["not_evaluable_count"],
                "source_missing_count": group["source_missing_count"],
                "result": status,
                "source_rows": group["source_rows"],
                "rule": "철골 산출서 도장·내화 항목의 숫자 산식만 독립 재계산; 자재 TON 연계 판정은 하지 않음",
            })
        return sorted(result, key=lambda item: (str(item["version"]), str(item["item_name"])))

    def _formula_quantity_missing_summary(self, quantities: list, source_by_id: dict) -> list[dict[str, object]]:
        """Expose every formula-bearing source row whose original quantity is absent."""
        groups: dict[str, dict[str, object]] = {}
        for item in quantities:
            if not item.formula_text or item.quantity is not None:
                continue
            source = source_by_id.get(item.source_file_id)
            source_name = source.original_name if source else "원본 파일 미지정"
            group = groups.setdefault(source_name, {
                "source_file": source_name,
                "sheet_name": source.sheet_name if source else None,
                "version": source.version_type if source else "미지정",
                "formula_cell_count": 0,
                "independently_evaluable_count": 0,
                "match_count": 0,
                "mismatch_count": 0,
                "not_evaluable_count": 0,
                "source_rows": [],
            })
            group["formula_cell_count"] += 1
            group["not_evaluable_count"] += 1
            if len(group["source_rows"]) < 10:
                group["source_rows"].append(item.source_row_ref)
        return [{
            **group,
            "result": "원본 수량 미추출",
            "confidence": "중간",
        } for group in groups.values()]

    def raw_quantity_analysis(
        self,
        db,
        project_id: str = "project-g5-office",
        limit: int = 1000,
        source_set: str | None = None,
        issue_type: str | None = None,
        severity: str | None = None,
        query: str | None = None,
        discipline: str | None = None,
        work_package: str | None = None,
    ) -> dict | None:
        """Build item-level review rows from the latest raw upload run.

        Legacy CSVs remain the read-only fallback for the seeded demo. Once a
        project has a completed raw-upload run containing estimate and
        quantity records, the UI must use those records instead of the static
        77번 queue. This prevents a drawing-only candidate from masquerading as
        a quantity mismatch and makes newly uploaded workbooks follow the same
        path as the seeded files.
        """
        from sqlalchemy import select

        from ..database import Building, MappingCandidate, PreprocessingRun, SourceFile, StandardizedItem

        runs = db.scalars(
            select(PreprocessingRun)
            .where(
                PreprocessingRun.project_id == project_id,
                PreprocessingRun.source_kind == "raw_upload",
                PreprocessingRun.status == "completed",
            )
            .order_by(PreprocessingRun.created_at.desc())
        ).all()
        if not runs:
            return None
        run = runs[0]
        source_ids = json.loads(run.source_file_ids or "[]")
        if not source_ids:
            return None
        source_rows = db.scalars(select(SourceFile).where(SourceFile.id.in_(source_ids))).all()
        source_by_id = {row.id: row for row in source_rows}
        # 광양5 사무동 검토는 사무동 건물에 등록된 내역서·수량산출서만
        # 연결한다. 타건물 자료는 가격 참고 카탈로그로 보관할 수 있지만
        # 이 분석의 원천 행이나 연결 후보로 사용하지 않는다.
        office = db.scalar(select(Building).where(Building.project_id == project_id, Building.name == "사무동"))
        allowed_source_ids = {
            row.id
            for row in source_rows
            if row.document_type in {"estimate", "quantity"}
            and (office is None or row.building_id == office.id)
        }
        if not allowed_source_ids:
            return None
        rows = db.scalars(
            select(StandardizedItem).where(
                StandardizedItem.project_id == project_id,
                StandardizedItem.source_file_id.in_(allowed_source_ids),
                StandardizedItem.item_kind.in_(["estimate", "quantity"]),
            )
        ).all()
        # StandardizedItem rows are immutable snapshots and can remain from
        # older preprocessing runs. Only the selected latest run may feed the
        # current review, otherwise a rerun would duplicate every estimate row.
        current_rows = []
        for row in rows:
            try:
                if json.loads(row.notes or "{}").get("run_id") == run.id:
                    current_rows.append(row)
            except (TypeError, ValueError):
                continue
        rows = current_rows
        def is_office_record(item) -> bool:
            source = source_by_id.get(item.source_file_id)
            if item.building_label:
                return _clean_text(item.building_label) == "사무동"
            # A source explicitly named for the office can be used when the
            # workbook has no building column; generic multi-building sheets
            # without a section label are intentionally excluded.
            return bool(source and "사무동" in (source.original_name or ""))

        estimates = [
            row for row in rows
            if row.item_kind == "estimate"
            and is_office_record(row)
            and not ((row.item_name or "").strip().startswith("[") and (row.item_name or "").strip().endswith("]"))
            and not _is_section_heading(row.item_name, {"unit": row.unit, "quantity": row.quantity, "formula": row.formula_text})
        ]
        quantities = [
            row for row in rows
            if row.item_kind == "quantity"
            and is_office_record(row)
            # 동별집계표·산출근거집계표는 여러 동/공종을 합친 요약표다.
            # 사무동 내역 행의 산출근거로 직접 연결하면 타건물 물량이
            # 합산되므로 전용 공종별 산출서만 보조근거로 사용한다.
            and not any(token in (source_by_id.get(row.source_file_id).original_name if source_by_id.get(row.source_file_id) else "") for token in ("동별집계표", "산출근거집계표"))
            and not ((row.item_name or "").strip().startswith("[") and (row.item_name or "").strip().endswith("]"))
            and not _is_section_heading(row.item_name, {"unit": row.unit, "quantity": row.quantity, "formula": row.formula_text})
        ]
        if not estimates:
            return None
        selected_mappings = db.scalars(
            select(MappingCandidate)
            .where(
                MappingCandidate.project_id == project_id,
                MappingCandidate.estimate_item_id.in_([item.id for item in estimates]),
                MappingCandidate.status == "선택됨",
            )
            .order_by(MappingCandidate.created_at.desc())
        ).all()
        manual_mapping_by_estimate = {}
        for mapping in selected_mappings:
            manual_mapping_by_estimate.setdefault(mapping.estimate_item_id, mapping)
        # The raw name is not always the business key.  Earlier office
        # preprocessing recorded a small audited vocabulary map (for example
        # ``무기질탄성도막방수(내부)`` -> ``무기질계탄성도막방수`` and
        # ``M2`` -> ``㎡``).  Use that map to construct a current-run group;
        # never import its historic quantities or approvals.
        quantities_by_key_version: dict[tuple[str, str], list] = {}
        standardized_by_id: dict[str, tuple[str, str, str, bool]] = {}
        for quantity_item in quantities:
            quantity_source = source_by_id.get(quantity_item.source_file_id)
            quantity_version = quantity_source.version_type if quantity_source else "기준"
            standardized = self._standardized_fields(quantity_item)
            standardized_by_id[quantity_item.id] = standardized
            quantities_by_key_version.setdefault((standardized[0], quantity_version), []).append(quantity_item)

        def source_label(source: SourceFile | None) -> tuple[str, str]:
            if source and source.version_type == "변경":
                return "변경자료", "변경"
            if source and source.version_type == "기준":
                return "기준자료", "기준"
            return "기준·변경 대조", source.version_type if source else "미지정"

        def item_discipline(item, source: SourceFile | None) -> str:
            name = f"{item.item_name or ''} {source.original_name if source else ''}"
            return "구조" if "구조" in name or "철골" in name or "철근" in name else "건축"

        def context_value(item, field: str) -> str:
            return _clean_text(getattr(item, field, None))

        def context_summary(item) -> str:
            labels = (
                ("동", getattr(item, "building_label", None)),
                ("층", getattr(item, "floor_label", None)),
                ("부위", getattr(item, "space_label", None)),
                ("도면", getattr(item, "drawing_number", None)),
            )
            return " · ".join(f"{label} {value}" for label, value in labels if _clean_text(value)) or "문맥 미기록"

        def narrow_by_context(estimate, base_candidates: list) -> tuple[list, bool]:
            """Prefer quantity rows sharing the estimate's persisted context.

            A workbook can repeat an item name on several floors or sheets.
            Context is therefore a narrowing key, never a reason to invent a
            quantity.  When an explicit estimate context has no corresponding
            quantity context, return no match so the row remains an evidence
            warning instead of linking to a different area.
            """
            scoped = list(base_candidates)
            context_fields = ("building_label", "floor_label", "space_label", "drawing_number")
            # Item codes, when both sides provide them, are stronger than a
            # display-name match but are optional because many legacy sheets
            # do not carry a code column.
            estimate_code = context_value(estimate, "item_code")
            if estimate_code:
                code_matches = [item for item in scoped if context_value(item, "item_code") == estimate_code]
                if code_matches:
                    scoped = code_matches
            for field in context_fields:
                expected = context_value(estimate, field)
                if not expected:
                    continue
                exact = [item for item in scoped if context_value(item, field) == expected]
                if exact:
                    scoped = exact
                elif any(context_value(item, field) for item in scoped):
                    return [], True
            return scoped, False

        result: list[dict[str, object]] = []
        comparison_mode = source_set == "기준·변경 대조"
        # 내역서 행을 기준으로 결과를 만든다. 수량산출서는 같은 자료 세트의
        # 보조 근거 행으로 묶어 합산하며, 기준·변경 세트를 교차 연결하지 않는다.
        for estimate in estimates:
            source = source_by_id.get(estimate.source_file_id)
            set_label, version = source_label(source)
            estimate_standard = self._standardized_fields(estimate)
            standardized_by_id[estimate.id] = estimate_standard
            candidates = quantities_by_key_version.get((estimate_standard[0], source.version_type if source else "기준"), [])
            matching = [
                item for item in candidates
                if (
                    not estimate_standard[2]
                    or not standardized_by_id[item.id][2]
                    or estimate_standard[2] == standardized_by_id[item.id][2]
                )
                and (
                    not estimate_standard[1]
                    or not standardized_by_id[item.id][1]
                    or _spec_compatible(estimate_standard[1], standardized_by_id[item.id][1])
                )
            ]
            matching, context_mismatch = narrow_by_context(estimate, matching)
            selection_method: str | None = None
            # A human may select one candidate from the inspector. Reuse that
            # persisted selection on subsequent reads, but keep the result in
            # the same unconfirmed review state until approval is recorded.
            manual_mapping = manual_mapping_by_estimate.get(estimate.id)
            if manual_mapping:
                selected = next((item for item in candidates if item.id == manual_mapping.quantity_item_id), None)
                if selected is not None:
                    matching = [selected]
                    context_mismatch = False
                    selection_method = "manual-selection"
            # Repeated quantity rows are common in one workbook because each
            # zone/grid is listed separately. Narrow only when one numeric row
            # is clearly closest to the estimate; this is still a review
            # candidate and never an automatic confirmation or sum.
            if not selection_method and len(matching) > 1 and estimate.quantity is not None:
                numeric_candidates = [item for item in matching if item.quantity is not None]
                ranked = sorted(numeric_candidates, key=lambda item: abs(float(item.quantity) - float(estimate.quantity)))
                if ranked:
                    best_distance = abs(float(ranked[0].quantity) - float(estimate.quantity))
                    next_distance = abs(float(ranked[1].quantity) - float(estimate.quantity)) if len(ranked) > 1 else None
                    tolerance = max(0.5, abs(float(estimate.quantity)) * 0.03)
                    clearly_closer = next_distance is None or next_distance >= max(best_distance * 2, best_distance + 1)
                    if best_distance <= tolerance and clearly_closer:
                        matching = [ranked[0]]
                        selection_method = "quantity-proximity"
            # Several calculation rows are normally the zones/components of a
            # single estimate line. They become one comparison group only when
            # their *standardized* item/spec/unit agree; an incompatible raw
            # source row remains an explicit candidate, never an implicit sum.
            signatures = {
                (standardized_by_id[item.id][1], standardized_by_id[item.id][2])
                for item in candidates
                if standardized_by_id[item.id][1] or standardized_by_id[item.id][2]
            }
            signatures_for_estimate = {
                (standardized_by_id[item.id][1], standardized_by_id[item.id][2])
                for item in matching
                if standardized_by_id[item.id][1] or standardized_by_id[item.id][2]
            }
            ambiguous = len(signatures_for_estimate) > 1 or (not matching and len(signatures) > 1)
            numeric_matching = [item for item in matching if item.quantity is not None]
            if len(matching) == 1 and numeric_matching:
                derived_quantity = float(numeric_matching[0].quantity)
                recalculated_basis = "수량산출서 1행"
            elif len(matching) > 1 and len(numeric_matching) == len(matching):
                # Show the supporting rows' arithmetic even while retaining
                # the finding as a candidate. This is a review reference, not
                # an approved quantity, and never crosses building/version
                # boundaries because candidates were scoped above.
                derived_quantity = sum(float(item.quantity) for item in numeric_matching)
                recalculated_basis = f"수량산출서 {len(matching)}행 표준화 그룹 합계"
            else:
                derived_quantity = None
                recalculated_basis = "수량산출서 재검산 불가"
            mismatch_fields: list[str] = []
            if candidates and not matching:
                mismatch_fields.extend([field for field in ("단위", "규격") if field not in mismatch_fields])
            elif matching:
                if any(estimate_standard[2] and standardized_by_id[item.id][2] and estimate_standard[2] != standardized_by_id[item.id][2] for item in matching):
                    mismatch_fields.append("단위")
                if any(estimate_standard[1] and standardized_by_id[item.id][1] and not _spec_compatible(estimate_standard[1], standardized_by_id[item.id][1]) for item in matching):
                    mismatch_fields.append("규격")
            if not candidates or context_mismatch:
                issue, judgement, severity_value = "연결 근거 없음", "원천 행 연결 필요", "높음"
                action = "같은 자료 세트의 수량산출서 행을 연결한 뒤 내역 수량을 검토하세요."
            elif not matching:
                issue, judgement, severity_value = "불일치", "필드 불일치", "높음"
                action = f"{', '.join(dict.fromkeys(mismatch_fields or ['단위', '규격']))} 값이 다릅니다. 내역서 행과 산출근거를 확인하세요."
            elif ambiguous:
                issue, judgement, severity_value = "복수 연결 후보", "조건부 일치", "중간"
                action = "수량산출서 후보의 공종·규격·시트를 확인해 내역 행의 산출근거를 선택하세요."
            elif derived_quantity is None:
                issue, judgement, severity_value = "재검산 불가", "수동 검산 필요", "중간"
                action = "수량산출서의 빈 수량·외부참조·복합산식을 원본에서 확인하세요."
            else:
                comparison = compare_quantity(
                    estimate.quantity,
                    derived_quantity,
                    mismatch_fields,
                    estimate.total_amount,
                )
                issue, judgement, severity_value = comparison.issue_type, comparison.judgement, comparison.severity
                action = comparison.required_action
            item_text = estimate.item_name
            work_value = infer_work_package(item_text, estimate.specification, source.original_name if source else None)
            locator_parts = [
                f"내역서 {source.original_name}" if source else None,
                estimate.source_row_ref if estimate else None,
            ]
            trace_candidates = matching or candidates
            candidate_contexts = list(dict.fromkeys(context_summary(item) for item in trace_candidates))
            quantity_context = " / ".join(candidate_contexts[:3])
            if len(candidate_contexts) > 3:
                quantity_context += f" / 외 {len(candidate_contexts) - 3}개 문맥"
            for quantity_item in trace_candidates[:5]:
                quantity_source = source_by_id.get(quantity_item.source_file_id)
                locator_parts.extend([
                    f"수량산출서 {quantity_source.original_name}" if quantity_source else None,
                    quantity_item.source_row_ref,
                ])
            if len(trace_candidates) > 5:
                locator_parts.append(f"외 {len(trace_candidates) - 5}개 수량산출서 행")
            src_locator = " · ".join(part for part in locator_parts if part)
            searchable = " ".join(str(value or "") for value in (item_text, estimate.item_code, estimate.specification, source.original_name if source else "", work_value, issue, action))
            # 기준·변경 대조를 요청하면 양쪽 세트를 모두 수집한 뒤
            # 아래에서 대조용 행으로 치환한다.
            if source_set and source_set != set_label and source_set != "기준·변경 대조":
                continue
            if issue_type and issue_type != issue and not comparison_mode:
                continue
            if severity and severity != severity_value and not comparison_mode:
                continue
            discipline_value = item_discipline(estimate, source)
            if discipline and discipline != discipline_value and not comparison_mode:
                continue
            if work_package and work_package != work_value and not comparison_mode:
                continue
            if query and query.lower() not in searchable.lower() and not comparison_mode:
                continue
            candidate_payload = []
            # A spec/unit mismatch is not an automatic link.  Still expose
            # same-name source rows in the inspector so a reviewer can see
            # why the derived quantity was withheld instead of seeing only
            # "추출되지 않음" in the table.
            if issue in {"복수 연결 후보", "불일치"} and trace_candidates:
                ranked_candidates = trace_candidates
                if estimate.quantity is not None:
                    ranked_candidates = sorted(
                        trace_candidates,
                        key=lambda item: abs(float(item.quantity or 0) - float(estimate.quantity)),
                    )
                for candidate in ranked_candidates[:30]:
                    candidate_source = source_by_id.get(candidate.source_file_id)
                    candidate_payload.append({
                        "id": candidate.id,
                        "quantity": self._display_number(candidate.quantity),
                        "specification": candidate.specification,
                        "unit": candidate.unit,
                        "formula": candidate.formula_text,
                        "source_file": candidate_source.original_name if candidate_source else None,
                        "source_row_ref": candidate.source_row_ref,
                        "context": context_summary(candidate),
                        "selected": bool(manual_mapping and manual_mapping.quantity_item_id == candidate.id),
                    })
            result.append({
                "id": estimate.id,
                "project_id": project_id,
                "source_set": set_label,
                "version": version,
                "discipline": discipline_value,
                "work_package": work_value,
                "item_key": estimate.item_code or estimate.normalized_name,
                "item_text": item_text,
                "source_file": source.original_name if source else None,
                "sheet_or_drawing": (
                    estimate.building_label
                    or (source.sheet_name if source else None)
                    or ((estimate.source_row_ref or "").split(":", 1)[0] or None)
                ),
                "source_locator": src_locator,
                "quantity_context": quantity_context,
                "quantity_candidates": candidate_payload,
                "issue_type": issue,
                "judgement": judgement,
                "severity": severity_value,
                "status": "승인 대기",
                "confidence": "중간" if issue != "일치" else "높음",
                "original_value": self._display_number(estimate.quantity),
                "recalculated_value": self._display_number(derived_quantity),
                "recalculated_basis": recalculated_basis,
                "difference": self._display_number((derived_quantity - float(estimate.quantity)) if estimate.quantity is not None and derived_quantity is not None else None),
                "evidence": (
                    f"내역서 1행 기준 · 수량산출서 후보 {len(trace_candidates)}행"
                    + (" · 사무동 기존 표준화 매핑 참조" if estimate_standard[3] or any(standardized_by_id[item.id][3] for item in trace_candidates) else "")
                    + (" · 수량 근접도 기준 검토 후보 1행" if selection_method else "")
                    + (" · 표준화 그룹 합계(확정값 아님)" if len(matching) > 1 and derived_quantity is not None else "")
                    if len(trace_candidates) != 1 or derived_quantity is None
                    else "내역서 1행 기준 · 수량산출서 근거 1행"
                ),
                "required_action": action,
                "rule_version": "raw-v8-내역서기준·표준매핑·그룹합계·허용오차",
                "locator_status": "RESOLVED" if src_locator else "UNRESOLVED",
            })
        baseline_changed_comparison = self._baseline_changed_comparison(result)
        if source_set == "기준·변경 대조":
            result = self._comparison_items(project_id, baseline_changed_comparison)
            if issue_type:
                result = [item for item in result if item["issue_type"] == issue_type]
            if severity:
                result = [item for item in result if item["severity"] == severity]
            if discipline:
                result = [item for item in result if item["discipline"] == discipline]
            if work_package:
                result = [item for item in result if item["work_package"] == work_package]
            if query:
                needle = query.lower()
                result = [item for item in result if needle in " ".join(str(item.get(key) or "") for key in ("item_text", "item_key", "work_package", "source_locator")).lower()]
        summary = Counter(item["issue_type"] for item in result)
        summary.update({
            "기준자료": sum(1 for item in result if item["source_set"] == "기준자료"),
            "변경자료": sum(1 for item in result if item["source_set"] == "변경자료"),
            "기준·변경 대조": sum(1 for item in result if item["source_set"] == "기준·변경 대조"),
        })
        work_package_counts = {
            source: dict(Counter(item["work_package"] or "미분류·원천 확인 필요" for item in result if item["source_set"] == source))
            for source in ("기준자료", "변경자료", "기준·변경 대조")
        }
        work_package_counts["전체"] = dict(Counter(item["work_package"] or "미분류·원천 확인 필요" for item in result))
        return {
            "project_id": project_id,
            "scope": "광양5 사무동 내역서·수량산출서 오류 분석",
            "generated_from": f"raw_upload preprocessing run {run.id} ({run.parser_version})",
            "total": len(result),
            "approval_queue_total": len(estimates),
            "summary": dict(summary),
            "work_package_counts": work_package_counts,
            "items": result[:max(1, min(limit, 5000))],
            "recheck_summary": self._formula_quantity_missing_summary(quantities, source_by_id),
            "steel_relation_summary": self._steel_relation_summary(quantities, source_by_id),
            "steel_coating_formula_summary": self._steel_coating_formula_summary(quantities, source_by_id),
            "material_construction_relation_summary": self._material_construction_relation_summary(quantities, source_by_id),
            "baseline_changed_comparison": baseline_changed_comparison,
        }

    def quantity_analysis(self, limit: int = 1000, source_set: str | None = None, issue_type: str | None = None, severity: str | None = None, query: str | None = None, discipline: str | None = None, work_package: str | None = None) -> dict:
        """전처리 산출물의 공사부서 수량 검토 대기열을 읽기 전용으로 정규화한다.

        이 결과는 확정값이 아니다. 전처리 산출물에 원본 수치가 없는 행은
        임의로 0을 채우지 않고 UNRESOLVED로 남겨 사람이 원본을 확인하게 한다.
        """
        rows = self.rows("77_사무동_공사부서_수량승인_대기열.csv")
        approval_queue_total = len(rows)
        items: list[dict[str, object]] = []

        # 20번 산출물은 파일/시트 요약이 아니라, 실제 내역 항목과
        # 수량산출서 행을 품명·규격·단위·수량 단위로 대조한 행 단위 결과다.
        # 본문 검토 목록의 기준자료는 이 결과를 사용하고, 75번 산식 요약은
        # 하단 참고 카드로만 노출한다.
        mapping_rows = self.rows("20_사무동_매핑_필드대조.csv")
        for row in mapping_rows:
            checks = {
                "품명": row.get("item_check") or "확인 필요",
                "규격": row.get("spec_check") or "확인 필요",
                "단위": row.get("unit_check") or "확인 필요",
                "수량": row.get("quantity_check") or "확인 필요",
            }
            mismatch_fields = [name for name, result in checks.items() if result != "일치"]
            formula_status = row.get("formula_recalculation") or "확인 필요"
            if mismatch_fields:
                row_issue = "불일치"
                judgement = f"{', '.join(mismatch_fields)} 불일치"
                severity_value = "높음"
                action = row.get("next_action") or "원본 내역서와 수량산출서의 불일치 필드를 확인하세요."
            elif "지원하지 않는" in formula_status or "외부값" in formula_status or "CAD" in formula_status:
                row_issue = "재검산 불가"
                judgement = "필드 일치·수동 검산 필요"
                severity_value = "중간"
                action = "외부값·CAD 근거를 원본 파일과 도면에서 확인한 뒤 승인하세요."
            else:
                row_issue = "일치"
                judgement = "필드·수량 일치"
                severity_value = "낮음"
                action = row.get("next_action") or "공사부서 승인 대기"
            source_file = (row.get("source_file") or "").strip() or None
            sheet = (row.get("source_sheet") or "").strip() or None
            source_row = (row.get("source_row") or "").strip() or None
            source_cells = (row.get("source_cells") or "").strip() or None
            work_package_value = infer_work_package(row.get("original_item"), row.get("source_item"), row.get("original_spec"), row.get("source_spec"))
            locator_parts = [part for part in (source_file, sheet, f"행 {source_row}" if source_row else None, source_cells) if part]
            searchable = " ".join(str(row.get(key) or "") for key in ("original_item", "source_item", "original_spec", "source_spec", "source_file", "source_sheet", "source_row", "next_action"))
            if source_set and source_set != "기준자료":
                continue
            if issue_type and row_issue != issue_type:
                continue
            if severity and severity_value != severity:
                continue
            if discipline and discipline != "건축":
                continue
            if work_package and work_package_value != work_package:
                continue
            if query and query.lower() not in searchable.lower():
                continue
            items.append({
                "id": row.get("mapping_id") or f"MAP-{len(items) + 1:04d}",
                "project_id": "project-g5-office",
                "source_set": "기준자료",
                "version": "기준 Rev.0",
                "discipline": "건축",
                "work_package": work_package_value,
                "item_key": row.get("source_item") or row.get("original_item") or None,
                "item_text": row.get("original_item") or row.get("source_item") or None,
                "source_file": source_file,
                "sheet_or_drawing": sheet,
                "source_locator": " · ".join(locator_parts) if locator_parts else None,
                "issue_type": row_issue,
                "judgement": judgement,
                "severity": severity_value,
                "status": "승인 대기",
                "confidence": row.get("confidence") or None,
                "original_value": row.get("mapping_quantity") or None,
                "recalculated_value": row.get("source_quantity") or None,
                "difference": row.get("quantity_difference") or None,
                "evidence": " / ".join(f"{name}: {result}" for name, result in checks.items()),
                "required_action": action,
                "rule_version": "mapping-field-check-v1",
                "locator_status": "RESOLVED" if locator_parts else "UNRESOLVED",
            })

        for row in rows:
            source_file = (row.get("source_file") or "").strip() or None
            version = "변경" if source_file and source_file.startswith("변경자료/") else "기준" if source_file and source_file.startswith("기초자료/") else "미지정"
            is_formula = row.get("queue_type") == "산식 재검산 경고"
            # 산식 경고는 파일·시트 수준 요약이므로 내역별 본문 목록에는
            # 넣지 않는다. recheck_summary에서 별도로 제공한다.
            if is_formula:
                continue
            source_label = "변경자료" if version == "변경" else "기준자료" if version == "기준" else "기준·변경 대조"
            if not source_file and not is_formula:
                # 77번 대기열의 도면 변경 후보는 변경자료에서 발견된
                # 항목이지만, 원천 내역서 행은 아직 연결되지 않았다.
                # 따라서 변경 후보로 분류하되 확정자료처럼 취급하지 않는다.
                if row.get("queue_type") == "도면 변경 후보":
                    source_label = "변경자료"
                    version = "변경 후보"
                else:
                    source_label = "기준·변경 대조"
                    version = "기준↔변경"
            if is_formula:
                row_issue = "재검산 불가"
                judgement = "추가 확인 필요"
            elif "복수" in (row.get("formula_or_quantity_status") or ""):
                row_issue = "복수 연결 후보"
                judgement = "조건부 일치"
            else:
                row_issue = "연결 근거 없음"
                judgement = "추가 확인 필요"
            work_package_value = infer_work_package(row.get("item_key"), row.get("item_text"), row.get("sheet_or_drawing"))
            locator = " · ".join(part for part in (source_file, row.get("sheet_or_drawing")) if part) if source_file else None
            searchable = " ".join(str(row.get(key) or "") for key in ("discipline", "item_key", "item_text", "source_file", "sheet_or_drawing", "formula_or_quantity_status", "required_action"))
            if source_set and source_label != source_set:
                continue
            if issue_type and row_issue != issue_type:
                continue
            if severity and row.get("severity") != severity:
                continue
            if discipline and (row.get("discipline") or "") != discipline:
                continue
            if work_package and work_package_value != work_package:
                continue
            if query and query.lower() not in searchable.lower():
                continue
            items.append({
                "id": row.get("queue_id") or f"Q-{len(items) + 1:04d}",
                "project_id": "project-g5-office",
                "source_set": source_label,
                "version": version,
                "discipline": row.get("discipline") or None,
                "work_package": work_package_value,
                "item_key": row.get("item_key") or None,
                "item_text": row.get("item_text") or None,
                "source_file": source_file,
                "sheet_or_drawing": row.get("sheet_or_drawing") or None,
                "source_locator": locator or None,
                "issue_type": row_issue,
                "judgement": judgement,
                "severity": row.get("severity") or "중간",
                "status": row.get("status") or "검토 대기",
                "confidence": row.get("confidence") or None,
                "original_value": None,
                "recalculated_value": None,
                "difference": None,
                "evidence": row.get("evidence") or None,
                "required_action": row.get("required_action") or None,
                "rule_version": "preprocessing-v1",
                "locator_status": "RESOLVED" if locator else "UNRESOLVED",
            })
        for row in self.rows("70_사무동_자동연결_경고승인_통합.csv"):
            if "복수 연결 후보" not in (row.get("finding_type") or ""):
                continue
            source_label = "기준·변경 대조"
            row_issue = "복수 연결 후보"
            work_package_value = infer_work_package(row.get("candidate_key"), row.get("candidate_text"), row.get("drawing_sheet"), row.get("source_evidence"))
            searchable = " ".join(str(row.get(key) or "") for key in ("discipline", "candidate_key", "candidate_text", "drawing_sheet", "source_evidence", "automatic_action"))
            if source_set and source_label != source_set:
                continue
            if issue_type and row_issue != issue_type:
                continue
            if severity and row.get("severity") != severity:
                continue
            if discipline and (row.get("discipline") or "") != discipline:
                continue
            if work_package and work_package_value != work_package:
                continue
            if query and query.lower() not in searchable.lower():
                continue
            evidence = row.get("source_evidence") or None
            items.append({
                "id": row.get("finding_id") or f"MAP-{len(items) + 1:04d}",
                "project_id": "project-g5-office",
                "source_set": source_label,
                "version": "기준↔변경",
                "discipline": row.get("discipline") or None,
                "work_package": work_package_value,
                "item_key": row.get("candidate_key") or None,
                "item_text": row.get("candidate_text") or None,
                "source_file": None,
                "sheet_or_drawing": row.get("drawing_sheet") or None,
                "source_locator": evidence,
                "issue_type": row_issue,
                "judgement": "조건부 일치",
                "severity": row.get("severity") or "중간",
                "status": row.get("status") or "검토 대기",
                "confidence": row.get("confidence") or "낮음",
                "original_value": None,
                "recalculated_value": None,
                "difference": None,
                "evidence": evidence,
                "required_action": row.get("automatic_action") or "공종·층·공간 문맥 확인 후 단일 연결 후보를 선택하세요.",
                "rule_version": "preprocessing-v1",
                "locator_status": "RESOLVED" if evidence else "UNRESOLVED",
            })
        summary = Counter(item["issue_type"] for item in items)
        summary.update({"기준자료": sum(1 for item in items if item["source_set"] == "기준자료"), "변경자료": sum(1 for item in items if item["source_set"] == "변경자료"), "기준·변경 대조": sum(1 for item in items if item["source_set"] == "기준·변경 대조")})
        work_package_counts = {
            source: dict(Counter(item["work_package"] or "미분류·원천 확인 필요" for item in items if item["source_set"] == source))
            for source in ("기준자료", "변경자료", "기준·변경 대조")
        }
        work_package_counts["전체"] = dict(Counter(item["work_package"] or "미분류·원천 확인 필요" for item in items))
        recheck_rows = self.rows("75_사무동_단순산식_자동검산결과.csv")
        recheck_summary = [{
            "source_file": row.get("source_file"),
            "sheet_name": row.get("sheet_name"),
            "version": row.get("version"),
            "formula_cell_count": int(row.get("formula_cell_count") or 0),
            "independently_evaluable_count": int(row.get("independently_evaluable_count") or 0),
            "match_count": int(row.get("match_count") or 0),
            "mismatch_count": int(row.get("mismatch_count") or 0),
            "not_evaluable_count": int(row.get("not_evaluable_or_no_cached_count") or 0),
            "result": row.get("result") or "확인 필요",
            "confidence": row.get("confidence") or "낮음",
        } for row in recheck_rows]
        return {
            "project_id": "project-g5-office",
            "scope": "광양5 사무동 내역서·수량산출서 오류 분석",
            "generated_from": "77_사무동_공사부서_수량승인_대기열.csv 및 75_사무동_단순산식_자동검산결과.csv",
            "total": len(items),
            "approval_queue_total": approval_queue_total,
            "summary": dict(summary),
            "work_package_counts": work_package_counts,
            "items": items[:max(1, min(limit, 5000))],
            "recheck_summary": recheck_summary,
            "material_construction_relation_summary": [],
            "baseline_changed_comparison": self._baseline_changed_comparison(items),
        }
