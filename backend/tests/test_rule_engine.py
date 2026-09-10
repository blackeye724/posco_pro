import csv
from pathlib import Path

from app.services.preprocessing_reader import PreprocessingReader
from app.services.rule_engine import RuleEngine


def write_csv(root: Path, name: str, headers: list[str], rows: list[list[str]]) -> None:
    with (root / name).open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(headers)
        writer.writerows(rows)


def test_engine_keeps_pending_and_never_auto_confirms(tmp_path: Path):
    write_csv(tmp_path, "75_사무동_단순산식_자동검산결과.csv", ["source_file", "sheet_name", "version", "formula_cell_count", "independently_evaluable_count", "match_count", "mismatch_count", "not_evaluable_or_no_cached_count", "result", "confidence", "preprocessing_rule"], [["estimate.xlsx", "합본", "기준", "2", "2", "1", "1", "0", "불일치", "중간", "재검산 규칙"]])
    write_csv(tmp_path, "76_사무동_산식_재검산불가_경고대기열.csv", ["source_file", "sheet_name", "version", "warning_category", "formula_count", "example", "severity", "action", "status", "preprocessing_rule"], [])
    write_csv(tmp_path, "74_사무동_공종별_산식검산_작업대기열.csv", ["formula_queue_id", "source_file", "sheet_name", "negative_cell_count", "status", "recommended_action", "preprocessing_rule"], [])
    write_csv(tmp_path, "20_사무동_매핑_필드대조.csv", ["mapping_id", "scope_building", "source_file", "source_sheet", "source_row", "source_cells", "original_item", "source_item", "item_check", "original_spec", "source_spec", "spec_check", "original_unit", "source_unit", "unit_check", "quantity_check", "formula_recalculation", "next_action", "confidence"], [["M-1", "사무동", "qty.xlsx", "시트1", "12", "C:G", "품목A", "품목B", "불일치", "규격A", "규격B", "불일치", "M", "M2", "불일치", "불일치", "재검산 불가", "근거 확인", "낮음"]])
    write_csv(tmp_path, "70_사무동_자동연결_경고승인_통합.csv", ["finding_id", "project_id", "discipline", "drawing_sheet", "candidate_text", "candidate_key", "source_candidate_count", "finding_type", "severity", "status", "owner_department", "approval_route", "automatic_action", "confidence", "source_evidence", "preprocessing_rule"], [])
    write_csv(tmp_path, "17_사무동_전후도면_비교대상.csv", ["project_id", "baseline_version", "changed_version", "discipline", "sheet_number", "baseline_file", "changed_file", "comparison_status", "change_region_status"], [["P", "Rev.0", "Rev.F", "1A", "101", "before.dwg", "after.dwg", "비교 대기", "미확정"]])
    write_csv(tmp_path, "79_사무동_구매부서_신규내역_단가검토_대기열.csv", ["procurement_queue_id", "candidate_id", "standard_key", "category", "reference_count", "price_status", "review_route", "status", "restriction", "confidence"], [["P-1", "C-1", "KEY", "철골", "0", "미검토", "계약단가", "단가 검토 대기", "적용 금지", "높음"]])
    write_csv(tmp_path, "86_사무동_PriceInfoService_단가조회결과.csv", ["candidate_id", "조회상태"], [["C-1", "결과 없음"]])

    result = RuleEngine(PreprocessingReader(tmp_path)).run()
    assert result["quantity_checks"][0]["outcome"] == "불일치"
    assert result["quantity_checks"][0]["auto_confirmed"] is False
    assert any(w["warning_type"] == "item_name_mismatch" for w in result["warnings"])
    assert result["drawing_comparisons"][0]["status"] == "근거 확인 대기"
    assert result["price_candidates"][0]["decision"] == "미검토"
    assert all(item["auto_confirmed"] is False for item in result["mapping_candidates"])

