from pathlib import Path
import zipfile
from types import SimpleNamespace

from app.services.raw_preprocessor import RawPreprocessor, _is_section_heading, is_non_office_scope
from app.services.preprocessing_reader import PreprocessingReader, _canonical_unit, _formula_rounding_tolerance, _simple_formula_value, _spec_compatible, classification_status, infer_work_package
from app.services.quantity_rule_engine import canonical_name, canonical_spec, classify_material_relation, compare_quantity, compare_related_totals, compare_version_quantities, spec_compatible


def test_map_row_normalizes_korean_headers_and_numbers():
    row = RawPreprocessor._map_row({"품명": "콘크리트", "규격": "25-24-150", "단위": "m3", "수량": "1,250.50", "단가": "100,000", "금액": "125,050,000"})
    assert row["item_name"] == "콘크리트"
    assert row["normalized_name"] == "콘크리트"
    assert row["quantity"] == 1250.5
    assert row["unit_price"] == 100000
    assert row["amount"] == 125050000


def test_structural_member_callouts_are_classified_as_steel():
    assert infer_work_package("#SB27M") == "철골공사"
    assert infer_work_package("BASE PL-180x100x12t") == "철골공사"


def test_non_office_scope_guard_blocks_reference_buildings_from_linkage():
    assert is_non_office_scope("콘크리트", "보안동", "사무동") is True
    assert is_non_office_scope("콘크리트", "사무동", "건축공사") is False


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


def test_related_total_missing_role_uses_the_actual_quantity_label():
    assert compare_related_totals(12, None, quantity_label="m2").result == "시공 m2 연결 근거 없음"


def test_version_comparison_reports_direction_without_approval():
    assert compare_version_quantities(100, 100.005).result == "변경 없음(허용오차)"
    assert compare_version_quantities(100, 110).result == "변경 후 증가"
    assert compare_version_quantities(100, 90).result == "변경 후 감소"
    assert compare_version_quantities(None, 90).result == "대조 근거 없음"


def test_steel_version_comparison_uses_aggregated_size_bands():
    # 12.5 -> 12.6 TON is a 0.8% change, so it is within the recommended
    # 5~50 TON steel reconciliation band (±1%), not a hard mismatch.
    matched = compare_version_quantities(12.5, 12.6, work_package="철골공사", item_text="H형강", comparison_key="h형강|ss275|ton", unit="TON")
    assert matched.result == "일치(철골 허용오차 내)"
    assert matched.comparison_band == "match"
    assert matched.tolerance_rate == 0.01

    review = compare_version_quantities(12.5, 12.75, work_package="철골공사", item_text="H형강", comparison_key="h형강|ss275|ton", unit="TON")
    assert review.result == "검토 후보(철골 허용오차 초과)"
    assert review.comparison_band == "review"

    mismatch = compare_version_quantities(12.5, 13.0, work_package="철골공사", item_text="H형강", comparison_key="h형강|ss275|ton", unit="TON")
    assert mismatch.result == "변경 후 증가"
    assert mismatch.comparison_band == "mismatch"


def test_steel_large_scope_uses_tighter_band():
    matched = compare_version_quantities(100, 100.4, work_package="철골공사", item_text="H형강", comparison_key="h형강|ss275|ton", unit="TON")
    assert matched.result == "일치(철골 허용오차 내)"
    assert matched.tolerance_rate == 0.005

    review = compare_version_quantities(100, 101.5, work_package="철골공사", item_text="H형강", comparison_key="h형강|ss275|ton", unit="TON")
    assert review.result == "검토 후보(철골 허용오차 초과)"


def test_steel_package_related_nonsteel_item_keeps_generic_rule():
    hinge = compare_version_quantities(150, 151, work_package="철골공사", item_text="BALL BEARING BUTT HINGE", unit="EA")
    assert hinge.result == "변경 후 증가"
    assert hinge.tolerance_rate is None


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


def test_work_package_classification_covers_common_office_items():
    assert infer_work_package("고장력볼트") == "철골공사"
    assert infer_work_package("레미콘") == "철근콘크리트공사"
    assert infer_work_package("수밀코킹(10mm각)") == "방수공사"
    assert infer_work_package("세면대하부장") == "수장공사"
    assert infer_work_package("플로어힌지설치") == "창호공사"
    assert infer_work_package("강관비계 설치 및 해체") == "가설공사"
    assert infer_work_package("승객용엘리베이터") == "승강기공사"
    assert infer_work_package("SD01[F:1.6T,D:0.8T]") == "창호공사"
    assert infer_work_package("압출발포폴리스티렌 설치") == "단열공사"
    assert infer_work_package("앵커 볼트 설치") == "철골공사"
    assert infer_work_package("되메우고다지기") == "토공사"
    assert infer_work_package("MORTISE LEVER SET") == "창호공사"
    assert _is_section_heading("0318. 골재대", {"quantity": 0})
    assert _is_section_heading("0413 골재대", {"quantity": 0})
    assert _is_section_heading("12010. 운반비", {"quantity": 0})
    assert not _is_section_heading("타일공사 보수", {"unit": "M2", "quantity": "12"})


def test_window_schedule_codes_are_classified_without_promoting_generic_al_items():
    assert infer_work_package("AW01[150mm AL 단열바]") == "창호공사"
    assert infer_work_package("AW_E03[2.사무동]") == "창호공사"
    assert infer_work_package("AWE01[150mm PVC,FIX]") == "창호공사"
    assert infer_work_package("FSD01[2.사무동]") == "창호공사"
    assert infer_work_package("SSD_E1[1.5T SST HL]") == "창호공사"
    assert infer_work_package("SD_E2[2.사무동]") == "창호공사"
    assert infer_work_package("AL몰딩설치") == "금속공사"
    assert infer_work_package("GALV.GUTTER 설치") == "홈통공사"
    assert infer_work_package("강관동바리 설치 및 해체") == "가설공사"
    assert infer_work_package("그라스울단열설치/외벽") == "단열공사"
    assert infer_work_package("강섬유") == "철근콘크리트공사"
    assert infer_work_package("유용토 운반") == "토공사"
    assert infer_work_package("철강채널") == "철골공사"
    assert infer_work_package("계단논슬립") == "금속공사"
    assert infer_work_package("천정점검구") == "수장공사"
    assert infer_work_package("아연도골강판 설치/외벽") == "패널공사"
    assert infer_work_package("FST01[2.사무동]") == "창호공사"
    assert infer_work_package("PD01[2.사무동]") == "창호공사"
    assert infer_work_package("PW01[150mm PVC,FIX]") == "창호공사"
    assert infer_work_package("관통볼트") == "철골공사"
    assert infer_work_package("그라스크로스 설치") == "방수공사"
    assert infer_work_package("앵글코너가드/집수정") == "금속공사"
    assert infer_work_package("기존 보온재 철거") == "단열공사"
    assert infer_work_package("ELEV내부 작업발판") == "승강기공사"


def test_unclassified_items_expose_actionable_classification_status():
    assert classification_status("미분류·원천 확인 필요", "PILE 소운반", "pile소운반") == "원천 파일 확인 필요"
    assert classification_status("미분류·원천 확인 필요", "DYNAMIC LOAD TEST") == "공종 분류 불가"
    assert classification_status("철골공사", "DYNAMIC LOAD TEST") is None
    assert infer_work_package("화장실점자안내판") == "금속공사"
    assert infer_work_package("DOOR CLOSER") == "창호공사"
    assert infer_work_package("CT형강") == "철골공사"
    assert infer_work_package("DRY WALL(C-100)") == "수장공사"


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


def test_detailed_drawing_candidates_keep_masonry_location_and_source_link(tmp_path: Path):
    (tmp_path / "60_건축_DWG_객체비교").mkdir()
    (tmp_path / "06_도면_전후매핑후보.csv").write_text(
        "baseline_file,changed_file,discipline,next_action,pair_status,sheet_number\n"
        "기준/1A-111.pdf,변경/1A-111.pdf,1A,PDF 위치 확인,전후 비교 후보,111\n",
        encoding="utf-8-sig",
    )
    (tmp_path / "60_건축_DWG_객체비교" / "65_사무동_건축도면_자동변경후보_작업대기열.csv").write_text(
        "queue_id,drawing_sheet,change_type,candidate_text,layer,x,y,candidate_type,confidence,automatic_next_action\n"
        "ARC-111-1,1A-111,추가 후보,시멘트 벽돌 / 비노출 우레탄 방수 (H=1800),TEXT,2201,1299,건축 마감 변경 후보,중간,변경 내역서 검색\n",
        encoding="utf-8-sig",
    )
    (tmp_path / "60_건축_DWG_객체비교" / "67_사무동_건축변경_원천행_자동연결요약.csv").write_text(
        "queue_id,result,source_candidate_count,source_candidate_samples,automatic_next_action,confidence\n"
        "ARC-111-1,원천 행 복수 연결 후보 - 자동 수량 합산 금지,2,변경내역서:행 20 | 산출서:행 55,원천 행 문맥 확인,중간\n",
        encoding="utf-8-sig",
    )

    rows = PreprocessingReader(tmp_path).drawing_candidates(limit=10)
    detailed = next(row for row in rows if row["id"].startswith("DRAW-DETAIL"))

    assert detailed["work_package"] == "조적공사 · 방수공사"
    assert detailed["location_ref"].startswith("시트 1A-111 · 레이어 TEXT · 좌표 2201, 1299")
    assert detailed["text_role"] == "자재·규격 표기"
    assert detailed["location_status"] == "부위 미확정"
    assert detailed["link_status"] == "복수 원천행 후보·자동 합산 금지"
    assert detailed["linked_estimate_count"] == 2
    assert detailed["baseline_file"] == "기준/1A-111.pdf"
    assert detailed["changed_file"] == "변경/1A-111.pdf"


def test_pdf_change_terms_only_uses_exact_changed_estimate_labels():
    terms = RawPreprocessor._pdf_change_terms(
        "마감 상세: 시멘트 벽돌 및 비노출 우레탄 방수 H=1800",
        ["시멘트 벽돌", "비노출 우레탄 방수", "THK.7 지정타일"],
    )

    assert terms == ["시멘트 벽돌", "비노출 우레탄 방수"]


def test_drawing_pairing_does_not_cross_work_packages_or_buildings():
    baseline_arch = SimpleNamespace(
        id="base-arch",
        drawing_number="101",
        building_id="office",
        work_package_id="arch",
    )
    baseline_structure = SimpleNamespace(
        id="base-structure",
        drawing_number="101",
        building_id="office",
        work_package_id="structure",
    )
    changed_arch = SimpleNamespace(
        id="changed-arch",
        drawing_number="101",
        building_id="office",
        work_package_id="arch",
    )
    changed_other_building = SimpleNamespace(
        id="changed-other",
        drawing_number="101",
        building_id="warehouse",
        work_package_id="arch",
    )

    assert RawPreprocessor._match_baseline_drawing(changed_arch, [baseline_structure, baseline_arch]).id == "base-arch"
    assert RawPreprocessor._match_baseline_drawing(changed_other_building, [baseline_arch]) is None
    assert RawPreprocessor._match_baseline_drawing(SimpleNamespace(id="no-number", drawing_number=None, building_id="office", work_package_id="arch"), [baseline_arch]) is None


def test_drawing_identity_is_derived_only_from_safe_sheet_patterns():
    source = SimpleNamespace(
        drawing_number=None,
        original_name="광양5-준공-1A-02-DWG-101 사무동 구조 도면목록표_Rev.F.dwg",
        file_path="",
        sheet_name=None,
    )
    assert RawPreprocessor._drawing_number(source) == "101"
    assert RawPreprocessor._drawing_discipline(source) == "구조"

    no_sheet = SimpleNamespace(drawing_number=None, original_name="사무동_2026-09-10.dwg", file_path="", sheet_name=None)
    assert RawPreprocessor._drawing_number(no_sheet) is None


def test_raw_upload_quantity_link_uses_shared_canonical_fields():
    estimate = SimpleNamespace(item_name="도막방수", normalized_name="도막방수", specification="(D.R.A+T4) Φ500", unit="㎡")
    quantity = SimpleNamespace(item_name="도막방수", normalized_name="도막방수", specification="Φ500, D.R.A+T4", unit="M2")
    compatible, fields = RawPreprocessor._quantity_field_match(estimate, quantity)
    assert compatible is True
    assert fields == set()

    different_unit = SimpleNamespace(item_name="도막방수", normalized_name="도막방수", specification="Φ500, D.R.A+T4", unit="M3")
    compatible, fields = RawPreprocessor._quantity_field_match(estimate, different_unit)
    assert compatible is False
    assert fields == {"단위"}


def test_raw_upload_quantity_link_uses_audited_spec_aliases():
    aliases = [{
        "original_item": "타일벽코너가드/아웃 [A00-201:6]",
        "standard_item": "코너비드설치",
        "original_spec": "AL",
        "estimate_spec": "알미늄",
        "original_unit": "M",
        "standard_unit": "M",
    }]
    estimate = SimpleNamespace(item_name="타일벽코너가드/아웃 [A00-201:6]", normalized_name="타일벽코너가드/아웃 [A00-201:6]", specification="AL", unit="M")
    quantity = SimpleNamespace(item_name="코너비드설치", normalized_name="코너비드설치", specification="알미늄", unit="M")
    compatible, fields = RawPreprocessor._quantity_field_match(estimate, quantity, aliases)
    assert compatible is True
    assert fields == set()


def test_canonical_name_applies_audited_alias_only_with_matching_context():
    aliases = [{
        "original_item": "무기질탄성도막방수(내부)",
        "standard_item": "무기질계탄성도막방수",
        "original_spec": "2회 도포",
        "estimate_spec": "2회 도포",
        "original_unit": "M2",
        "standard_unit": "㎡",
    }]
    assert canonical_name("무기질탄성도막방수(내부)", aliases, specification="2회 도포", unit="m²") == "무기질계탄성도막방수"
    assert canonical_name("무기질탄성도막방수(내부)", aliases, specification="3회 도포", unit="m²") == "무기질탄성도막방수내부"


def test_audited_spec_alias_requires_item_and_unit_context():
    aliases = [{
        "original_item": "타일벽코너가드/아웃 [A00-201:6]",
        "standard_item": "코너비드설치",
        "original_spec": "AL",
        "estimate_spec": "알미늄",
        "original_unit": "M",
        "standard_unit": "M",
    }]
    assert canonical_spec("AL", aliases, item_name="타일벽코너가드/아웃 [A00-201:6]", unit="M") == "알미늄"
    assert spec_compatible(
        "AL", "알미늄", aliases,
        left_item="타일벽코너가드/아웃 [A00-201:6]",
        right_item="코너비드설치",
        left_unit="M", right_unit="M",
    )
    assert not spec_compatible(
        "AL", "알미늄", aliases,
        left_item="다른 공종",
        right_item="코너비드설치",
        left_unit="M", right_unit="M",
    )


def test_xls_parse_failure_keeps_traceable_error(tmp_path: Path):
    path = tmp_path / "legacy.xls"
    path.write_bytes(b"not-a-biff-workbook")

    source = type("Source", (), {"file_path": str(path), "original_name": path.name, "file_type": "XLS"})()
    rows = RawPreprocessor(tmp_path)._rows(source)

    assert rows[0][0] == "legacy.xls:file"
    assert "파서오류" in rows[0][1]
