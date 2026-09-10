from pathlib import Path
import zipfile

from app.services.raw_preprocessor import RawPreprocessor, _is_section_heading
from app.services.preprocessing_reader import PreprocessingReader, _canonical_unit, _formula_rounding_tolerance, _simple_formula_value, _spec_compatible
from app.services.quantity_rule_engine import classify_material_relation, compare_quantity, compare_related_totals, compare_version_quantities


def test_map_row_normalizes_korean_headers_and_numbers():
    row = RawPreprocessor._map_row({"품명": "콘크리트", "규격": "25-24-150", "단위": "m3", "수량": "1,250.50", "단가": "100,000", "금액": "125,050,000"})
    assert row["item_name"] == "콘크리트"
    assert row["normalized_name"] == "콘크리트"
    assert row["quantity"] == 1250.5
    assert row["unit_price"] == 100000
    assert row["amount"] == 125050000


def test_map_row_preserves_quantity_context_aliases():
    row = RawPreprocessor._map_row({"품명": "터파기", "층범위": "지상1층", "부위": "기초", "도면번호": "A-101", "단위": "m3", "수량": "10"})

    assert row["floor"] == "지상1층"
    assert row["space"] == "기초"
    assert row["drawing_number"] == "A-101"


def test_map_row_preserves_steel_tonnage_and_member_metadata():
    row = RawPreprocessor._map_row({"품명": "H형강", "물량(TON)": "12.50", "자재구분": "철골자재", "부재구분": "기둥"})

    assert row["quantity_ton"] == 12.5
    assert row["material_class"] == "철골자재"
    assert row["member_class"] == "기둥"


def test_map_row_keeps_formula_when_source_quantity_is_missing():
    row = RawPreprocessor._map_row({"품명": "조합페인트", "단위": "M2", "산식": "0.074*1"})

    assert row["formula"] == "0.074*1"
    assert row["quantity"] is None


def test_common_quantity_rule_engine_distinguishes_exact_and_near_match():
    exact = compare_quantity(100, 100.005, total_amount=5_000_000)
    near = compare_quantity(100, 102, total_amount=5_000_000)
    mismatch = compare_quantity(100, 110, total_amount=5_000_000)

    assert exact.issue_type == "일치"
    assert near.judgement == "허용오차 내 근사 일치"
    assert mismatch.issue_type == "불일치"


def test_related_total_rule_never_treats_missing_role_as_zero():
    assert compare_related_totals(100, 100.05).result == "총량 일치권"
    assert compare_related_totals(100, 101).result == "총량 차이 확인 필요"
    assert compare_related_totals(100, None).result == "시공 TON 연결 근거 없음"


def test_material_construction_relation_requires_explicit_role_marker():
    assert classify_material_relation("앵커볼트 자재") == ("앵커볼트", "재료")
    assert classify_material_relation("앵커볼트 설치") == ("앵커볼트", "시공")
    assert classify_material_relation("앵커볼트") is None


def test_version_comparison_reports_direction_without_approval():
    assert compare_version_quantities(100, 100.005).result == "변경 없음(허용오차)"
    assert compare_version_quantities(100, 110).result == "변경 후 증가"
    assert compare_version_quantities(100, 90).result == "변경 후 감소"
    assert compare_version_quantities(None, 90).result == "대조 근거 없음"


def test_specification_matching_ignores_order_and_punctuation():
    assert _spec_compatible("(D.R.A+T4) Φ500", "Φ500, (D.R.A+T4)")


def test_unit_aliases_keep_the_same_quantity_group():
    assert _canonical_unit("M2") == _canonical_unit("㎡") == _canonical_unit("m²")
    assert _canonical_unit("M3") == _canonical_unit("㎥") == _canonical_unit("m³")


def test_simple_formula_recheck_accepts_only_literal_arithmetic():
    assert _simple_formula_value("(0.25*2+0.25*4-0.009*2)*(4.75*2+35.0*2)") == 117.819
    assert _simple_formula_value("SUM(A1:A2)") is None
    assert _formula_rounding_tolerance(3.844) == 0.001


def test_numbered_work_package_heading_is_not_a_review_item():
    # ``03. 사무동`` can occupy the adjacent specification cell.  It is a
    # section label, not an estimate with an implicit quantity.
    assert _is_section_heading("0306. 타일공사", {"specification": "03. 사무동"})
    assert not _is_section_heading("타일공사 보수", {"unit": "M2", "quantity": "12"})


def test_csv_rows_keep_source_row_locator(tmp_path: Path):
    path = tmp_path / "quantity.csv"
    path.write_text("품명,단위,수량\n철근,kg,10\n", encoding="utf-8-sig")

    rows = RawPreprocessor._csv_rows(path)

    assert rows[0][0] == "quantity.csv:row-2"
    assert rows[0][1]["품명"] == "철근"


def test_pdf_without_optional_parser_keeps_traceable_fallback(tmp_path: Path):
    path = tmp_path / "drawing.pdf"
    path.write_bytes(b"%PDF-1.7\nnot-a-full-document")

    rows = RawPreprocessor._pdf_rows(path)

    assert rows[0][0] == "drawing.pdf:file"
    assert "파서상태" in rows[0][1]


def test_xlsx_rows_detect_multiline_header_and_keep_all_sheet_rows(tmp_path: Path):
    """Real workbooks put the item header below title rows and use formulas."""
    path = tmp_path / "changed.xlsx"
    shared = ["제목", "품명", "규격", "단위", "산식", "수량", "잡석다짐", "THK.200", "M3", "2*3"]
    shared_xml = "<sst xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>" + "".join(f"<si><t>{value}</t></si>" for value in shared) + "</sst>"
    sheet_xml = """<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>
      <row r='1'><c r='A1' t='s'><v>0</v></c></row>
      <row r='4'><c r='D4' t='s'><v>1</v></c><c r='E4' t='s'><v>2</v></c><c r='F4' t='s'><v>3</v></c><c r='G4' t='s'><v>4</v></c><c r='I4' t='s'><v>5</v></c></row>
      <row r='5'><c r='D5' t='s'><v>6</v></c><c r='E5' t='s'><v>7</v></c><c r='F5' t='s'><v>8</v></c><c r='G5' t='s'><v>9</v></c><c r='I5'><v>6</v></c></row>
    </sheetData></worksheet>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    rows = RawPreprocessor._xlsx_rows(path)

    assert rows == [("xl/worksheets/sheet1.xml:row-5", {"item_name": "잡석다짐", "specification": "THK.200", "unit": "M3", "formula": "2*3", "quantity": "6"})]


def test_drawing_candidates_stay_separate_from_quantity_queue(tmp_path: Path):
    path = tmp_path / "06_도면_전후매핑후보.csv"
    path.write_text(
        "baseline_file,changed_file,discipline,next_action,pair_status,sheet_number\n"
        "기초자료/건축 Rev.0/A-101.dwg,변경자료/건축 Rev.F/A-101.dwg,1A,CAD 확인,전후 비교 후보,101\n",
        encoding="utf-8-sig",
    )

    rows = PreprocessingReader(tmp_path).drawing_candidates()

    assert len(rows) == 1
    assert rows[0]["drawing_number"] == "101"
    assert rows[0]["change_type"] == "전후 비교 후보"
    assert rows[0]["baseline_revision"] == "Rev.0"
    assert rows[0]["changed_revision"] == "Rev.F"
    assert rows[0]["status"] == "근거 확인 대기"


def test_xls_parse_failure_keeps_traceable_error(tmp_path: Path):
    path = tmp_path / "legacy.xls"
    path.write_bytes(b"not-a-biff-workbook")

    source = type("Source", (), {"file_path": str(path), "original_name": path.name, "file_type": "XLS"})()
    rows = RawPreprocessor(tmp_path)._rows(source)

    assert rows[0][0] == "legacy.xls:file"
    assert "파서오류" in rows[0][1]
