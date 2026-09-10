# 규칙–현재 코드 대조표

기준 문서: [RULE_CATALOG.md](./RULE_CATALOG.md)

## 적용 중인 규칙

| 규칙 | 현재 위치 | 상태 | 확인 내용 |
|---|---|---|---|
| SCOPE-001 | `preprocessing_reader.py::raw_quantity_analysis` | 적용 | 사무동 Building 및 사무동 파일명만 허용 |
| ROW-001 | `raw_quantity_analysis` | 적용 | 내역서 estimate 행을 결과 기준으로 생성 |
| ROW-002 | `raw_preprocessor.py::_is_section_heading` | 적용 | 번호+공사 제목 행 제외, 테스트 있음 |
| SET-001 | `raw_quantity_analysis` | 적용 | 기준/변경 version별 후보 사전 분리 |
| NAME-001 | `PreprocessingReader::_office_mappings` | 부분 적용 | 기존 매핑은 이름·규격·단위 표준화에만 사용, 기존 수량은 미사용 |
| SPEC-001 | `_spec_compatible` | 부분 적용 | 토큰 포함 관계를 허용하지만 의미 동등성 사전은 제한적 |
| UNIT-001 | `_canonical_unit` | 적용 | 면적·체적·톤·개수 표기 통일 |
| CONTEXT-001 | `narrow_by_context` | 적용 | 코드·동·층·부위·도면 순으로 축소 |
| GROUP-001 | `quantities_by_key_version` 및 표준화 그룹 합계 | 적용 | 같은 표준 그룹의 여러 산출행을 합산 |
| QTY-001 | `quantity_rule_engine.py::compare_quantity` | 적용 | 기준/변경 공통 0.01% 기술 허용오차 |
| QTY-002 | `quantity_rule_engine.py::warning_threshold` → `compare_quantity` | 적용 | 내역 금액구간별 3/2/1% 근사 일치 |
| QTY-003 | quantity API + `/quantities` | 적용 | 내역값·산출값·차이·근거 표시 |
| CAND-001 | `raw_quantity_analysis` | 적용 | 서로 다른 규격·문맥 후보는 합산하지 않고 후보 표시 |
| TRACE-001 | `source_locator`, candidate payload | 적용 | 파일·시트·원본 행 연결 |
| FORM-001 | `_simple_formula_value`, 철골 산식 패널 | 적용 | 숫자 사칙연산만 재계산 |
| FORM-002 | `RawPreprocessor.process`, `/upload` | 적용 | 산식·수량 누락 경고 및 추가자료 요청 링크 |
| STEEL-002 | `_steel_coating_formula_summary` | 적용 | 도장·내화 면적 산식 별도 검산 |
| APPROVAL-001 | 승인 API 및 `/approvals` | 기존 구현 보존 | 승인 전 확정 금지 및 단계 잠금 |

## 놓치거나 구조적으로 부족한 규칙

| 규칙 | 문제 | 영향 | 다음 조치 |
|---|---|---|---|
| NAME-001/SPEC-001 | 표준화가 `PreprocessingReader` 내부에만 있고 업로드 전처리 저장값과 공통으로 공유되지 않음 | 신규 자료와 기존 자료의 판정 경로가 달라질 수 있음 | 공통 엔진으로 이동 |
| GROUP-001 | 표준 그룹 키에 공종 관계·부재 분류가 아직 없음 | 같은 품명이 여러 산식 그룹으로 분리되지 않을 수 있음 | 그룹 키와 관계 키를 엔진에서 명시 |
| STEEL-001 | `quantity_rule_engine.py::compare_related_totals` + `_steel_relation_summary` | 자재·시공 TON 열이 모두 있을 때만 총량 비교, 없으면 보류 | 열 존재 여부를 선검증하고 없으면 보류 |
| 재료–시공 관계 | `classify_material_relation`과 `material_construction_relation_summary` 적용 | 명시 역할·동일 단위만 관계 후보로 비교하고 미확인 역할은 보류 | 후보별 근거 행과 차이 표시, 철골 TON은 전용 규칙으로 분리 |
| 기준↔변경 대조 | `compare_version_quantities` + `baseline_changed_comparison` | 공종·표준키가 양쪽에 존재하는 내역만 증가·감소·허용오차로 대조 | 화면 표와 원본 행 근거 표시 |
| FORM-001 | 현재 요약은 철골 도장·내화 중심이며 일반 수량산출서 전체 요약과 분리됨 | 공종별 산식 검산 현황이 일관되지 않음 | 공통 산식 검산 인터페이스 추가 |

## 현재 검증 결과

- 최신 raw-v9 전처리: 28,782행 완료
- 기준자료: 583건, 변경자료: 1,840건
- 기준자료 판정: 일치 117건, 불일치 220건, 연결 근거 없음 243건, 재검산 불가 3건
- 변경자료 판정: 일치 356건, 불일치 709건, 연결 근거 없음 775건
- 산식·수량 누락: 13건을 원본 근거와 함께 분리
- 철골 도장·내화: 단순 산식 재계산 결과를 별도 표시
- 철골 TON 총량: 현재 원본 열 부재로 보류(자동 0 대입 금지)
- 재료–시공 관계 후보: 명시 역할·동일 단위가 확인된 그룹을 별도 요약
- 기준↔변경 대조: 공종·표준키별 양쪽 내역 수량을 합산해 증가·감소·허용오차 결과와 원본 행을 표시하며, 자료 세트·결과 필터로 405개 대조 행(허용오차 일치 43개)을 조회
- 대조 상세 근거: 선택한 행에서 기준 원본행·변경 원본행·각 수량·증감률을 분리 표시
- 운영 빌드: `/approvals`의 검색 파라미터 Suspense 경계를 보완해 `next build` 성공
- 공종별 필터 검증: 기준 방수 31건, 변경 타일 54건, 변경 철골 105건을 사무동 범위로 확인

## 3단계 진행 상태

- 수량 판정(정확 일치·허용오차 내 근사·불일치·수량 누락), 표준 키·단위·규격
  비교, 단순 산식 재검산은 `backend/app/services/quantity_rule_engine.py`의
  순수 함수로 추출했다.
- `PreprocessingReader`는 해당 엔진을 호출하므로 기준자료·변경자료가 같은
  판정 결과와 차이율을 사용한다.
- 과거 사무동 매핑 파일을 조회해 표준명을 선택하는 정책과 공사관계 그룹화는
  아직 Reader에 남아 있다. 다음 순서에서 이 정책을 엔진 입력·출력 계약으로
  명시한 뒤 기준/변경 자료를 각각 재검증한다.

이 표에서 `놓치거나 구조적으로 부족한 규칙`을 다음 단계 공통 엔진의 최소 범위로 삼는다.
