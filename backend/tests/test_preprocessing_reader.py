import csv
from pathlib import Path
from types import SimpleNamespace

from app.services.preprocessing_reader import PreprocessingReader


def write_csv(root: Path, name: str, headers: list[str], rows: list[list[str]]):
    with (root / name).open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(headers)
        writer.writerows(rows)


def test_rule_run_never_auto_approves_multiple_candidates(tmp_path: Path):
    write_csv(tmp_path, "70_사무동_자동연결_경고승인_통합.csv", ["finding_id", "source_candidate_count", "status", "confidence", "candidate_text"], [["F-1", "2", "검토 대기", "낮음", "항목"]])
    reader = PreprocessingReader(tmp_path)
    totals, items = reader.rule_run()
    assert totals == {"추가 확인 필요": 1}
    assert items[0]["rule_outcome"] == "추가 확인 필요"


def test_formula_summary_separates_match_mismatch_and_missing_rows(tmp_path: Path):
    reader = PreprocessingReader(tmp_path)
    source = SimpleNamespace(original_name="사무동_수량산출서.xlsx", sheet_name="방수", version_type="기준")
    rows = [
        SimpleNamespace(source_file_id="source", formula_text="2*3", quantity=6, source_row_ref="row-1"),
        SimpleNamespace(source_file_id="source", formula_text="2*3", quantity=7, source_row_ref="row-2"),
        SimpleNamespace(source_file_id="source", formula_text="SUM(A1:A2)", quantity=None, source_row_ref="row-3"),
    ]

    summary = reader._formula_quantity_missing_summary(rows, {"source": source})

    assert summary[0]["formula_cell_count"] == 3
    assert summary[0]["independently_evaluable_count"] == 2
    assert summary[0]["match_count"] == 1
    assert summary[0]["mismatch_count"] == 1
    assert summary[0]["not_evaluable_count"] == 1
    assert summary[0]["result"] == "원본 수량 미추출·재검산 불가"


def test_material_construction_relation_is_grouped_by_work_package(tmp_path: Path):
    reader = PreprocessingReader(tmp_path)
    source = SimpleNamespace(original_name="사무동_내역서.xlsx", version_type="기준")
    estimate = SimpleNamespace(source_file_id="source", item_name="콘크리트 자재", specification=None, notes=None, unit="m3", quantity=10, source_row_ref="estimate-1")
    quantity = SimpleNamespace(source_file_id="source", item_name="콘크리트 시공", specification=None, notes=None, unit="M3", quantity=10, source_row_ref="quantity-1")

    summary = reader._material_construction_relation_summary([estimate], [quantity], {"source": source})

    assert len(summary) == 1
    assert summary[0]["work_package"] == "철근콘크리트공사"
    assert summary[0]["result"] == "총량 일치권"


def test_steel_missing_metadata_is_kept_alongside_valid_groups(tmp_path: Path):
    reader = PreprocessingReader(tmp_path)
    valid_source = SimpleNamespace(original_name="사무동_철골_자재.xlsx", version_type="기준")
    missing_source = SimpleNamespace(original_name="사무동_철골_열누락.xlsx", version_type="기준")
    valid = SimpleNamespace(
        source_file_id="valid", item_name="철골 자재", formula_text=None,
        unit="TON", quantity=10, notes='{"material_class":"H형강","quantity_ton":10}',
        source_row_ref="row-1",
    )
    missing = SimpleNamespace(
        source_file_id="missing", item_name="철골", formula_text=None,
        unit="M2", quantity=20, notes=None, source_row_ref="row-2",
    )

    summary = reader._steel_relation_summary(
        [valid, missing], {"valid": valid_source, "missing": missing_source}
    )

    assert len(summary) == 2
    assert any(row["result"] == "원본 분류 열 미추출" and "열누락" in row["source_rows"][0] for row in summary)
