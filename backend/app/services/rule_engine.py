"""전처리 산출물만 읽어 검토 후보를 만드는 설명 가능한 규칙 엔진."""

import hashlib
import re
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import (
    DrawingChangeCandidate,
    EvidenceReference,
    MappingCandidate,
    PriceApplicationDecision,
    ProcurementPriceResult,
    Project,
    ReviewWarning,
    SourceFile,
    StandardizedItem,
)
from .preprocessing_reader import PreprocessingReader


class RuleEngine:
    """자동 확정 없이 검토 결과와 원본 추적 정보를 함께 반환한다."""

    def __init__(self, reader: PreprocessingReader | None = None):
        self.reader = reader or PreprocessingReader()

    def optional_rows(self, file_name: str) -> list[dict[str, str]]:
        try:
            return self.reader.rows(file_name)
        except FileNotFoundError:
            return []

    @staticmethod
    def stable_id(prefix: str, value: str) -> str:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:24]
        return f"{prefix}-{digest}"

    @staticmethod
    def _number(row: dict[str, str], key: str) -> int:
        try:
            return int(float(row.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _evidence_refs(value: str | None) -> list[str]:
        if not value:
            return []
        return [part.strip() for part in value.split(" | ") if part.strip()]

    def quantity_checks(self) -> list[dict[str, object]]:
        rows = self.reader.rows("75_사무동_단순산식_자동검산결과.csv")
        checks: list[dict[str, object]] = []
        for row in rows:
            mismatches = self._number(row, "mismatch_count")
            not_evaluable = self._number(row, "not_evaluable_or_no_cached_count")
            matches = self._number(row, "match_count")
            if mismatches:
                outcome, severity, reason = "불일치", "높음", f"독립 재계산 결과 불일치 {mismatches}건"
            elif not_evaluable:
                outcome, severity, reason = "추가 확인 필요", "중간", f"캐시값 없음·복합산식 등 재검산 불가 {not_evaluable}건"
            else:
                outcome, severity, reason = "검산 참고 일치", "낮음", f"독립 재계산 일치 {matches}건이나 승인 전 자동 확정하지 않음"
            checks.append({
                "id": self.stable_id("QCHK", f"{row.get('source_file')}|{row.get('sheet_name')}|{row.get('version')}"),
                "source_file": row.get("source_file"),
                "sheet_name": row.get("sheet_name"),
                "version": row.get("version"),
                "formula_cell_count": self._number(row, "formula_cell_count"),
                "match_count": matches,
                "mismatch_count": mismatches,
                "not_evaluable_count": not_evaluable,
                "outcome": outcome,
                "severity": severity,
                "status": "검토 대기",
                "reason": reason,
                "confidence": row.get("confidence") or "중간",
                "rule": row.get("preprocessing_rule"),
                "auto_confirmed": False,
            })
        for row in self.reader.rows("76_사무동_산식_재검산불가_경고대기열.csv"):
            checks.append({
                "id": self.stable_id("QWARN", f"{row.get('source_file')}|{row.get('sheet_name')}|{row.get('version')}"),
                "source_file": row.get("source_file"),
                "sheet_name": row.get("sheet_name"),
                "version": row.get("version"),
                "formula_cell_count": self._number(row, "formula_count"),
                "match_count": 0,
                "mismatch_count": 0,
                "not_evaluable_count": self._number(row, "formula_count"),
                "outcome": "추가 확인 필요",
                "severity": row.get("severity") or "중간",
                "status": row.get("status") or "검토 대기",
                "reason": row.get("action") or row.get("warning_category"),
                "confidence": "낮음",
                "rule": row.get("preprocessing_rule"),
                "auto_confirmed": False,
            })
        return checks

    def warnings(self) -> list[dict[str, object]]:
        warnings: list[dict[str, object]] = []
        for row in self.optional_rows("20_사무동_매핑_필드대조.csv"):
            checks = {
                "품명": row.get("item_check"),
                "규격": row.get("spec_check"),
                "단위": row.get("unit_check"),
                "수량": row.get("quantity_check"),
                "산식": row.get("formula_recalculation"),
            }
            mismatches = [name for name, value in checks.items() if value and value not in ("일치", "검산 일치")]
            for field in mismatches:
                check_value = checks[field] or "확인 필요"
                type_map = {"품명": "item_name_mismatch", "규격": "specification_mismatch", "단위": "unit_mismatch", "数量": "quantity_mismatch", "수량": "quantity_mismatch", "산식": "formula_mismatch"}
                warnings.append({
                    "id": self.stable_id("WARN", f"field|{row.get('mapping_id')}|{field}"),
                    "warning_type": type_map[field],
                    "title": f"{field} 불일치 또는 확인 필요: {row.get('original_item') or ''}",
                    "detail": f"원본={row.get('original_' + ('item' if field == '품명' else 'spec' if field == '규격' else 'unit' if field == '단위' else 'quantity')) or ''}; 비교값={row.get('source_' + ('item' if field == '품명' else 'spec' if field == '규격' else 'unit' if field == '단위' else 'quantity')) or check_value}",
                    "severity": "높음" if field in ("수량", "산식") else "중간",
                    "status": "검토 대기",
                    "source_file": row.get("source_file"),
                    "sheet_name": row.get("source_sheet"),
                    "row_ref": row.get("source_row"),
                    "drawing_number": None,
                    "reason": row.get("next_action") or row.get("preprocessing_rule"),
                    "confidence": row.get("confidence") or "중간",
                    "auto_confirmed": False,
                })
        for row in self.optional_rows("74_사무동_공종별_산식검산_작업대기열.csv"):
            negative = self._number(row, "negative_cell_count")
            if negative:
                warnings.append({
                    "id": self.stable_id("WARN", f"negative|{row.get('formula_queue_id')}"),
                    "warning_type": "negative_quantity_or_amount",
                    "title": "음수 수량·금액 셀 확인 필요",
                    "detail": f"음수 셀 {negative}건; 내역서 금액·수량과 산출서 결과를 원본에서 대조",
                    "severity": "높음",
                    "status": row.get("status") or "검토 대기",
                    "source_file": row.get("source_file"),
                    "sheet_name": row.get("sheet_name"),
                    "row_ref": None,
                    "drawing_number": None,
                    "reason": row.get("recommended_action") or row.get("preprocessing_rule"),
                    "confidence": "중간",
                    "auto_confirmed": False,
                })
        for row in self.reader.rows("76_사무동_산식_재검산불가_경고대기열.csv"):
            warnings.append({
                "id": self.stable_id("WARN", f"formula|{row.get('source_file')}|{row.get('sheet_name')}|{row.get('version')}"),
                "warning_type": "formula_recheck_required",
                "title": row.get("warning_category") or "산식 재검산 확인 필요",
                "detail": row.get("action") or row.get("example"),
                "severity": row.get("severity") or "중간",
                "status": row.get("status") or "검토 대기",
                "source_file": row.get("source_file"),
                "sheet_name": row.get("sheet_name"),
                "row_ref": None,
                "drawing_number": None,
                "reason": row.get("preprocessing_rule"),
                "confidence": "낮음",
                "auto_confirmed": False,
            })
        for row in self.reader.rows("70_사무동_자동연결_경고승인_통합.csv"):
            finding_type = row.get("finding_type") or "연결 후보 확인 필요"
            warning_type = "unit_mismatch" if "단위" in finding_type else "specification_mismatch" if "규격" in finding_type else "quantity_mapping_review"
            warnings.append({
                "id": self.stable_id("WARN", f"finding|{row.get('finding_id')}"),
                "warning_type": warning_type,
                "title": f"{finding_type}: {row.get('candidate_text') or row.get('candidate_key') or ''}".strip(),
                "detail": row.get("automatic_action"),
                "severity": row.get("severity") or "중간",
                "status": row.get("status") or "검토 대기",
                "source_file": None,
                "sheet_name": row.get("drawing_sheet"),
                "row_ref": row.get("source_evidence"),
                "drawing_number": row.get("drawing_sheet"),
                "reason": row.get("preprocessing_rule"),
                "confidence": row.get("confidence") or "낮음",
                "auto_confirmed": False,
                "source_evidence": self._evidence_refs(row.get("source_evidence")),
            })
        return warnings

    def drawing_comparisons(self) -> list[dict[str, object]]:
        comparisons_by_key: dict[str, dict[str, object]] = {}
        for row_number, row in enumerate(self.reader.rows("17_사무동_전후도면_비교대상.csv"), start=2):
            key = f"{row.get('baseline_file')}|{row.get('changed_file')}"
            comparisons_by_key[key] = {
                "id": self.stable_id("DRAW", f"{row.get('baseline_file')}|{row.get('changed_file')}"),
                "project_id": row.get("project_id"),
                "discipline": row.get("discipline"),
                "sheet_number": row.get("sheet_number"),
                "baseline_file": row.get("baseline_file"),
                "changed_file": row.get("changed_file"),
                "baseline_revision": row.get("baseline_version"),
                "changed_revision": row.get("changed_version"),
                "source_row_ref": f"17_사무동_전후도면_비교대상.csv:{row_number}",
                "comparison_status": row.get("comparison_status"),
                "change_region_status": row.get("change_region_status"),
                "status": "근거 확인 대기",
                "reason": "도면번호·시트·Rev. 후보는 생성했으나 위치 확정 전 설계부서 확인 필요",
                "confidence": "낮음",
                "auto_confirmed": False,
                "pair_status": "전후 비교 대상",
                "readiness": None,
                "title_relation": None,
                "change_region_decision": None,
                "next_action": None,
            }
        for row_number, row in enumerate(self.optional_rows("06_도면_전후매핑후보.csv"), start=2):
            key = f"{row.get('baseline_file')}|{row.get('changed_file')}"
            item = comparisons_by_key.setdefault(key, {
                "id": self.stable_id("DRAW", key), "project_id": "광양5_사무동", "discipline": row.get("discipline"), "sheet_number": row.get("sheet_number"), "baseline_file": row.get("baseline_file"), "changed_file": row.get("changed_file"), "baseline_revision": None, "changed_revision": None, "source_row_ref": f"06_도면_전후매핑후보.csv:{row_number}", "comparison_status": row.get("pair_status"), "change_region_status": None, "status": "근거 확인 대기", "reason": "기준·변경 도면 짝짓기 후보이며 Rev.·위치 승인 필요", "confidence": "낮음", "auto_confirmed": False, "pair_status": row.get("pair_status"), "readiness": None, "title_relation": None, "change_region_decision": None, "next_action": row.get("next_action")
            })
            item["pair_status"] = row.get("pair_status")
            item["next_action"] = row.get("next_action")
        for row_number, row in enumerate(self.optional_rows("22_도면_비교_준비도_검토.csv"), start=2):
            key = f"{row.get('baseline_file')}|{row.get('changed_file')}"
            item = comparisons_by_key.setdefault(key, {
                "id": self.stable_id("DRAW", key), "project_id": row.get("project_id"), "discipline": row.get("discipline"), "sheet_number": row.get("sheet_number"), "baseline_file": row.get("baseline_file"), "changed_file": row.get("changed_file"), "baseline_revision": "Rev.0", "changed_revision": "Rev.F/AS BUILT", "source_row_ref": f"22_도면_비교_준비도_검토.csv:{row_number}", "comparison_status": row.get("readiness"), "change_region_status": row.get("change_region_decision"), "status": "근거 확인 대기", "reason": row.get("next_action") or "도면 비교 준비도 확인 필요", "confidence": row.get("confidence") or "낮음", "auto_confirmed": False, "pair_status": None, "readiness": row.get("readiness"), "title_relation": row.get("title_relation"), "change_region_decision": row.get("change_region_decision"), "next_action": row.get("next_action")
            })
            item["readiness"] = row.get("readiness")
            item["title_relation"] = row.get("title_relation")
            item["change_region_decision"] = row.get("change_region_decision")
            item["next_action"] = row.get("next_action")
        return list(comparisons_by_key.values())

    def mapping_candidates(self) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for row in self.reader.rows("70_사무동_자동연결_경고승인_통합.csv"):
            candidates.append({
                "id": self.stable_id("MAP", row.get("finding_id") or row.get("candidate_key") or "unknown"),
                "finding_id": row.get("finding_id"),
                "candidate_key": row.get("candidate_key"),
                "candidate_text": row.get("candidate_text"),
                "discipline": row.get("discipline"),
                "drawing_number": row.get("drawing_sheet"),
                "source_candidate_count": self._number(row, "source_candidate_count"),
                "match_method": row.get("preprocessing_rule"),
                "status": row.get("status") or "검토 대기",
                "confidence": row.get("confidence") or "낮음",
                "approval_route": row.get("approval_route"),
                "reason": row.get("automatic_action"),
                "evidence": self._evidence_refs(row.get("source_evidence")),
                "auto_confirmed": False,
            })
        for row in self.optional_rows("20_사무동_매핑_필드대조.csv"):
            candidates.append({
                "id": self.stable_id("MAP", f"field|{row.get('mapping_id')}"),
                "finding_id": row.get("mapping_id"),
                "candidate_key": row.get("mapping_id"),
                "candidate_text": row.get("original_item") or row.get("source_item"),
                "discipline": row.get("scope_building"),
                "drawing_number": None,
                "source_file": row.get("source_file"),
                "source_sheet": row.get("source_sheet"),
                "source_row": row.get("source_row"),
                "source_cells": row.get("source_cells"),
                "original_spec": row.get("original_spec"),
                "source_spec": row.get("source_spec"),
                "original_unit": row.get("original_unit"),
                "source_unit": row.get("source_unit"),
                "source_candidate_count": 1,
                "match_method": row.get("preprocessing_rule"),
                "status": "검토 대기",
                "confidence": row.get("confidence") or "중간",
                "approval_route": row.get("next_action"),
                "reason": row.get("next_action") or row.get("result"),
                "evidence": [f"{row.get('source_file')}:{row.get('source_sheet')}:{row.get('source_row')}"],
                "auto_confirmed": False,
            })
        return candidates

    def price_candidates(self) -> list[dict[str, object]]:
        api_rows = {row.get("candidate_id"): row for row in self.reader.rows("86_사무동_PriceInfoService_단가조회결과.csv")}
        results: list[dict[str, object]] = []
        for row in self.reader.rows("79_사무동_구매부서_신규내역_단가검토_대기열.csv"):
            api = api_rows.get(row.get("candidate_id"), {})
            results.append({
                "id": self.stable_id("PRICE", row.get("procurement_queue_id") or row.get("candidate_id") or "unknown"),
                "candidate_id": row.get("candidate_id"),
                "standard_key": row.get("standard_key"),
                "category": row.get("category"),
                "reference_count": self._number(row, "reference_count"),
                "price_status": row.get("price_status"),
                "api_lookup_status": api.get("조회상태"),
                "review_route": row.get("review_route"),
                "status": row.get("status") or "단가 검토 대기",
                "restriction": row.get("restriction"),
                "reason": "수량·품목 승인 후 계약단가 → 유사품목 조정 → 조달청 후보 순서로 검토",
                "confidence": row.get("confidence") or "중간",
                "decision": "미검토",
                "auto_confirmed": False,
            })
        return results

    def run(self) -> dict[str, object]:
        totals, flagged = self.reader.rule_run()
        quantity = self.quantity_checks()
        warnings = self.warnings()
        drawings = self.drawing_comparisons()
        mappings = self.mapping_candidates()
        prices = self.price_candidates()
        return {
            "processed": len(quantity) + len(warnings) + len(drawings) + len(mappings) + len(prices),
            "by_result": totals,
            "flagged_source_rows": flagged,
            "quantity_checks": quantity,
            "warnings": warnings,
            "drawing_comparisons": drawings,
            "mapping_candidates": mappings,
            "price_candidates": prices,
            "notice": "전처리 결과를 읽기 전용으로 검토했습니다. 기존 승인 대기 상태를 유지하며 수량·금액·단가를 자동 확정하지 않았습니다.",
        }

    def persist(self, db: Session, project: Project, output: dict[str, object]) -> None:
        """엔진 산출물을 DB에 기록한다. 기존 승인·원본 파일은 변경하지 않는다."""
        source_cache: dict[str, SourceFile] = {}

        def source_file(path: str | None, document_type: str = "preprocessed_reference") -> SourceFile | None:
            if not path:
                return None
            if path in source_cache:
                return source_cache[path]
            existing = db.scalar(select(SourceFile).where(SourceFile.project_id == project.id, SourceFile.file_path == path))
            if existing:
                source_cache[path] = existing
                return existing
            suffix = Path(path).suffix.lower().lstrip(".") or "CSV"
            record = SourceFile(id=self.stable_id("SRC", path), project_id=project.id, file_type=suffix.upper(), document_type=document_type, original_name=Path(path).name, file_path=path, version_type="기준")
            db.add(record)
            source_cache[path] = record
            return record

        for check in output["quantity_checks"]:
            source = source_file(check.get("source_file"))
            record = db.get(ReviewWarning, check["id"])
            if not record:
                record = ReviewWarning(id=check["id"], project_id=project.id, warning_type="quantity_formula_check", severity=check["severity"], title=f"{check['source_file']} / {check['sheet_name']}", detail=check["reason"], expected_value=str(check["match_count"]), actual_value=str(check["mismatch_count"]), status=check["status"], rule_code="FORMULA_RECHECK")
                db.add(record)
            if source and not db.scalar(select(EvidenceReference).where(EvidenceReference.id == self.stable_id("EVID", check["id"]))):
                db.add(EvidenceReference(id=self.stable_id("EVID", check["id"]), project_id=project.id, warning_id=record.id, source_file_id=source.id, evidence_type="formula_result", file_path=check.get("source_file"), sheet_name=check["sheet_name"], evidence_note=check["reason"], extraction_confidence=check["confidence"]))

        for warning in output["warnings"]:
            record = db.get(ReviewWarning, warning["id"])
            if not record:
                record = ReviewWarning(id=warning["id"], project_id=project.id, warning_type=warning["warning_type"], severity=warning["severity"], title=warning["title"], detail=warning["detail"], status=warning["status"], rule_code="PREPROCESSING_RESULT")
                db.add(record)
            source = source_file(warning.get("source_file"))
            if source and not db.scalar(select(EvidenceReference).where(EvidenceReference.id == self.stable_id("EVID", warning["id"]))):
                db.add(EvidenceReference(id=self.stable_id("EVID", warning["id"]), project_id=project.id, warning_id=record.id, source_file_id=source.id, evidence_type="preprocessing_warning", file_path=warning.get("source_file"), sheet_name=warning.get("sheet_name"), row_ref=warning.get("row_ref"), location_text=warning.get("drawing_number"), evidence_note=warning.get("reason"), extraction_confidence=warning.get("confidence")))
            elif warning.get("source_evidence"):
                for index, evidence in enumerate(warning.get("source_evidence", [])):
                    evidence_key = self.stable_id("EVID", f"{warning['id']}|{index}|{evidence}")
                    if not db.get(EvidenceReference, evidence_key):
                        source_ref = source_file(evidence)
                        db.add(EvidenceReference(id=evidence_key, project_id=project.id, warning_id=record.id, source_file_id=source_ref.id if source_ref else None, evidence_type="mapping_warning_source", file_path=evidence, sheet_name=warning.get("sheet_name"), row_ref=warning.get("row_ref"), location_text=warning.get("drawing_number"), evidence_note=warning.get("reason"), extraction_confidence=warning.get("confidence")))

        drawing_cache: dict[str, DrawingChangeCandidate] = {}
        for item in output["drawing_comparisons"]:
            record = db.get(DrawingChangeCandidate, item["id"])
            if not record:
                record = DrawingChangeCandidate(id=item["id"], project_id=project.id, discipline=item["discipline"], drawing_number=item["sheet_number"], sheet_number=item["sheet_number"], candidate_text=item["reason"], change_type="전후 비교 후보", location_ref=item["sheet_number"], confidence=item["confidence"], status=item["status"], baseline_file=item.get("baseline_file"), changed_file=item.get("changed_file"), baseline_revision=item.get("baseline_revision"), changed_revision=item.get("changed_revision"), source_row_ref=item.get("source_row"))
                db.add(record)
            else:
                record.baseline_file = record.baseline_file or item.get("baseline_file")
                record.changed_file = record.changed_file or item.get("changed_file")
                record.baseline_revision = record.baseline_revision or item.get("baseline_revision")
                record.changed_revision = record.changed_revision or item.get("changed_revision")
                record.sheet_number = record.sheet_number or item.get("sheet_number")
            drawing_cache[item["id"]] = record
            source_file(item.get("baseline_file"), "drawing")
            source_file(item.get("changed_file"), "drawing")

        for item in output["mapping_candidates"]:
            record = db.get(MappingCandidate, item["id"])
            if not record:
                source = source_file(item.get("source_file"))
                item_record = StandardizedItem(id=self.stable_id("ITEM", item["id"]), project_id=project.id, source_file_id=source.id if source else None, item_kind="mapping_candidate", item_code=item.get("candidate_key"), discipline=item.get("discipline"), item_name=item.get("candidate_text") or item.get("candidate_key") or "연결 후보", normalized_name=item.get("candidate_key"), specification=item.get("source_spec") or item.get("original_spec"), unit=item.get("source_unit") or item.get("original_unit"), drawing_number=item.get("drawing_number"), source_row_ref=item.get("source_row") or item.get("finding_id"), source_cell_ref=item.get("source_cells"))
                db.add(item_record)
                record = MappingCandidate(id=item["id"], project_id=project.id, estimate_item_id=item_record.id, quantity_item_id=item_record.id, candidate_key=item.get("candidate_key"), match_method=item.get("match_method"), confidence=item.get("confidence"), status=item.get("status"), source_candidate_count=item.get("source_candidate_count"), auto_decision="자동 확정 금지")
                db.add(record)
                for evidence in item.get("evidence", []):
                    source = source_file(evidence)
                    db.add(EvidenceReference(id=self.stable_id("EVID", f"{item['id']}|{evidence}"), project_id=project.id, mapping_candidate_id=record.id, source_file_id=source.id if source else None, evidence_type="mapping_source", file_path=evidence, evidence_note=item.get("reason"), extraction_confidence=item.get("confidence")))

        for item in output["price_candidates"]:
            if not db.get(ProcurementPriceResult, item["id"]):
                result = ProcurementPriceResult(id=item["id"], project_id=project.id, candidate_id=item.get("candidate_id") or item["id"], standard_key=item.get("standard_key"), lookup_status=item.get("api_lookup_status") or item.get("price_status") or "미검토", service_name="PriceInfoService")
                db.add(result)
                db.add(PriceApplicationDecision(id=self.stable_id("PRICEDEC", item["id"]), project_id=project.id, price_result_id=result.id, price_type="계약단가→유사품목→조달청", decision="미검토", reason=item.get("reason"), evidence_ref=item.get("candidate_id")))
        db.commit()
