# 공사비 적정성 검토 UI 디자인 시안 검토

작성일: 2026-09-09
목적: Stitch에 전달하기 전에 색상·정보구조·아이콘·글꼴 방향을 3개 안으로 비교

## 조사에서 확인한 공통 패턴

| 참고 사례 | 확인한 패턴 | 우리 서비스에 적용할 점 |
|---|---|---|
| [Procore Cost Management](https://www.procore.com/cost-management) | 프로젝트 예산·변경·예측·승인 흐름을 하나의 비용 화면으로 연결 | 첫 화면은 단순 통계보다 프로젝트 비용 검토 흐름과 변경 후보를 연결 |
| [Procore Budget](https://support.procore.com/products/online/user-guide/project-level/budget) | 프로젝트 단위 예산, 세부 행, PDF/Excel 보고서, 여러 프로젝트 조회 | 통합 검토 큐, 행 단위 근거, 보고서 스냅샷을 제공 |
| [Autodesk Cost Management](https://getconstructioncloud.autodesk.com/cost-management) | 변경 주문, 비용 노출, 예산 스냅샷, 비용·일정 연결 | Rev. 변경과 수량·내역·단가 연결을 화면 중심축으로 둠 |
| [Oracle Primavera Unifier](https://www.oracle.com/construction-engineering/primavera-unifier-project-controls-asset-management/) | WBS/CBS와 비용 시트, 변경 영향, 이력·보고서 중심 | 공사/공종/내역 계층과 회차·승인 이력을 유지 |
| [한미글로벌 CCN/CDE 소개](https://hanmiglobal.com/sustainability/2025/KR/environmental/innovation.asp) | 공사비 실적 비교와 설계·공사관리 기능을 연결 | 동일 프로젝트 타건물 참고단가와 도면 근거를 함께 표현 |
| [GOV.UK Design System](https://design-system.service.gov.uk/) | 폼·표·오류요약을 반복 가능한 컴포넌트로 제공 | 오류·추가자료 요청·권한 부족을 화면 상단과 필드 옆에 함께 표시 |
| [Material Design 3 theming](https://developer.android.com/codelabs/m3-design-theming?hl=en) | 색상 역할·타이포그래피 스케일·shape 토큰을 역할 중심으로 관리 | `primary`, `warning`, `surface`, `on-surface` 토큰으로 디자인을 코드와 연결 |
| [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | 일반 텍스트 대비 4.5:1, UI 상태 대비 3:1 이상 | 경고를 색상만으로 표현하지 않고 텍스트·아이콘·테두리로 중복 표현 |

사례에서 공통적으로 확인되는 것은 화려한 랜딩 페이지보다 `프로젝트 범위 → 검토 행 → 원본 근거 → 상태/승인`의 연결이다. 따라서 KPI 카드는 보조 수단으로 두고 검토 큐와 근거 패널을 중심에 둔다.

## 시안 A: Evidence Navy

파일: `option_a_evidence_navy.svg`

- 색상: 네이비 `#102A43`, 청록 `#56C7BA`, 배경 `#F4F7F8`, 경고 amber `#E9AD3E`
- 글꼴: `Noto Sans KR` 우선, 숫자·코드에는 `Roboto Mono` 보조
- 아이콘: 선형 아이콘과 텍스트를 함께 사용
- 정보구조: 좌측 사이드바 + 상단 범위 필터 + KPI + 통합 큐 + 우측 근거 패널
- 장점: 현재 프론트엔드의 네이비/청록 스타일과 가장 잘 이어지고, 원본 근거 중심 서비스라는 인상이 분명하다.
- 단점: 상태가 많아지면 청록·amber·빨강이 동시에 보여 시각적 밀도가 높아질 수 있다.
- 적합성: 광양5 MVP의 첫 통합 검토 화면, 공사부서 대시보드

## 시안 B: Government Neutral

파일: `option_b_government_neutral.svg`

- 색상: 진회색 `#1F2937`, 파랑 `#2563EB`, 표면 `#FFFFFF`, 배경 `#F8FAFC`, 경고 `#B45309`
- 글꼴: `Noto Sans KR` 단일 계열, 숫자도 동일 글꼴로 가독성 우선
- 아이콘: 단순한 텍스트+기호 아이콘, 상태는 배지와 표 셀로 표현
- 정보구조: 좌측 메뉴 + 프로젝트 헤더 + 필터 + 표 중심 목록 + 근거 상세
- 장점: 공공·사내 업무 시스템에 익숙하고 인쇄/Excel 보고서로 확장하기 쉽다. 시각적 장식이 적어 대량 행을 읽기 좋다.
- 단점: 차별화된 브랜드 인상이 약하고 도면 비교의 공간감이 부족하다.
- 적합성: 관리자·감사·대량 승인 대기열

## 시안 C: CAD Review Workspace

파일: `option_c_cad_workspace.svg`

- 색상: charcoal `#172026`, slate `#26343B`, 주황 `#E07A25`, CAD 캔버스 `#F7F9FA`
- 글꼴: `Noto Sans KR` + 기술 값/좌표에는 `Roboto Mono`
- 아이콘: CAD 도구처럼 얇은 선형 아이콘과 좌표/GRID 라벨
- 정보구조: 축소 사이드바 + 상단 프로젝트 헤더 + 기준/변경 도면 나란히 비교 + 우측 변경 후보 상세
- 장점: 설계부서가 Rev.·좌표·GRID/ZONE·변경 후보를 집중적으로 검토하기 좋다.
- 단점: 공사부서의 수량·단가·승인 검토에는 전문 도면 도구처럼 느껴질 수 있고, 전체 서비스의 기본 화면으로 쓰면 학습 부담이 크다.
- 적합성: 설계부서 도면 변경 화면의 2차 디자인

## 비교 및 추천

| 평가 항목 | A Evidence Navy | B Government Neutral | C CAD Workspace |
|---|---:|---:|---:|
| 근거 추적성 표현 | 5 | 4 | 5 |
| 수량·단가·승인 대량 검토 | 4 | 5 | 3 |
| 도면 변경 검토 | 4 | 3 | 5 |
| 기존 Next.js와 연속성 | 5 | 4 | 3 |
| 사용자 학습 부담 | 4 | 5 | 3 |
| Stitch 생성 안정성 | 5 | 5 | 3 |
| MVP 전체 화면 확장성 | 5 | 5 | 4 |
| 합계(35점) | **32** | 31 | 26 |

### 추천안

기본 디자인은 **A Evidence Navy**를 선택한다.

근거는 세 가지다.

1. 현재 구현된 Next.js 공통 스타일이 네이비 사이드바·청록 보조색·밝은 표면 구조를 이미 사용하므로 재작업 비용이 가장 낮다.
2. 서비스의 핵심 차별점은 비용 숫자 자체가 아니라 원본 파일·시트·행·도면번호·Rev.를 연결한 검토 근거다. A안의 우측 근거 패널이 이를 가장 빠르게 전달한다.
3. A안의 기본 토큰을 유지하면서 B안의 표/오류 처리 원칙과 C안의 도면 비교 영역을 화면별로 결합할 수 있다.

## 최종 조합안

- 전역/대시보드/통합 큐: A Evidence Navy
- 대량 표·관리자·감사 이력: B Government Neutral의 표 밀도와 오류 요약
- 도면 변경 화면: C CAD Workspace의 나란히 비교 캔버스
- 색상: 상태 색상은 의미 토큰으로 고정하고, 초록은 최종 확정에만 사용
- 글꼴: `Noto Sans KR`(UI), `Roboto Mono`(파일 해시·도면번호·좌표·규칙 ID)
- 아이콘: Lucide 계열의 선형 아이콘을 권장하며, 아이콘만으로 상태를 전달하지 않음
- 모서리: 기본 8px, 상세 패널 10~12px. 버튼/배지는 과도한 pill 사용을 피함
- 접근성: WCAG 2.2 AA를 목표로 텍스트 대비 4.5:1 이상, UI 상태 대비 3:1 이상을 확인

이 결정은 Stitch 전달 전 디자인 방향이며, 사용자 확인 후에만 `stitch_handoff` 폴더에 반영한다.

