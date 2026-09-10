import csv
from pathlib import Path

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

