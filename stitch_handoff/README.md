# Stitch 전달 묶음

이 폴더는 Stitch에 한 번에 전달할 수 있도록 정리한 자료다.

## 먼저 전달할 파일

1. `STITCH_PROMPT.md` — 2안 최종 프롬프트
2. `PRD_v2.md` — 제품 요구사항과 상태·권한·완료 조건
3. `globals.css` — 현재 프론트엔드 공통 스타일
4. `layout.tsx` — 현재 Next.js 공통 레이아웃
5. `api.ts` — 현재 FastAPI 연결 모듈의 응답 형태 참고
6. `page.tsx` — 현재 대시보드 참고
7. `approvals-page.tsx` — 현재 승인 화면 참고
8. `DESIGN_REVIEW.md` — 외부 사례·접근성 기준·최종 디자인 결정
9. `option_a_evidence_navy.png` — 전역 기본 디자인 참고
10. `option_b_government_neutral.png` — 대량 표·관리자 화면 참고
11. `option_c_cad_workspace.png` — 도면 변경 화면 참고

## Stitch에 요청할 작업

먼저 `STITCH_PROMPT.md`의 통합 검토 워크스페이스를 생성한다. 생성 결과가 확정되면 같은 디자인 시스템으로 도면·수량·단가·이력 화면을 차례로 추가한다.

디자인은 A안(Evidence Navy)을 기본으로 사용하고, B안의 표·오류 처리와 C안의 도면 비교 방식을 부분 결합한다. 세 시안은 그대로 복사하기보다 프로젝트 업무와 정보 구조를 이해하기 위한 참고 이미지다.

Stitch에는 실제 서비스 구현을 요청하지 않는다. API, PostgreSQL, 로그인, 파일 저장, 승인 저장은 Codex에서 기존 코드와 연결한다.

## 보안 주의

이 폴더에는 API 키, 비밀번호, DB 접속정보, 실제 원본 PDF/DWG/엑셀을 넣지 않는다. 실제 원본 대신 프롬프트의 비식별 샘플을 사용한다.
