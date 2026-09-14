# 투자사업 공사비 적정성 검토 MVP

도면·내역서·수량산출서 원본만 업로드하면 내부 전처리 작업을 시작하고, 규칙 기반 공사비 검토·신규내역 단가 검토·부서별 승인 이력을 제공하는 내부 웹 서비스입니다. 기존 광양5 전처리 결과는 관리자용 회귀·초기 데이터 경로로만 사용하며 지도학습 모델은 포함하지 않습니다.

## 문서 기준

비판적 검토 결과와 개선된 개발 기준 PRD는 다음 문서에 정리되어 있습니다.

- [개선 PRD v2](PRD_v2.md)
- [PRD 비판적 검토표](PRD_REVIEW.md)
- `PRD.md`: 기존 인터뷰 결정사항을 보존한 원본 기준 문서

신규 기능 구현·테스트·운영 인수는 `PRD_v2.md`를 기준으로 진행합니다.

## MVP 원칙

- 원본 PDF·DWG·엑셀은 `UPLOAD_DIR`에 보존하고, 업로드 후 비동기 전처리 결과는 별도 `preprocessing` 산출물로 생성합니다.
- `전처리결과_20260908`은 관리자용 기존 결과 가져오기·회귀검증 경로로 읽기 전용 마운트합니다.
- 규칙 엔진은 복수 후보, 근거 대기, 낮은 신뢰도를 `추가 확인 필요` 또는 `근거 요청`으로 분류합니다.
- 수량·금액·단가는 공사부서 → 설계부서 → 구매부서의 승인 전까지 자동 확정하지 않습니다.
- PostgreSQL에는 원본 파일 본문이 아니라 파일 경로·해시, 전처리 실행 상태·표준화 결과·검토·승인 이력을 저장합니다. 전처리 레코드는 실행별로 보관되어 필요한 실행·종류·상태만 선택 재조회할 수 있습니다.
- 근거 기반 검토 챗봇은 프로젝트·건물·공사 권한 범위 안의 자료만 검색하고, 답변마다 원본 근거를 인용하며 승인·단가 확정·원본 수정을 실행하지 않습니다. 챗봇 API·화면은 PRD에 정의된 다음 구현 단계입니다.

## 폴더 구조

```text
cost-review-mvp/
├── frontend/                 # Next.js 검토 현황·대기열·승인 화면
│   ├── app/                  # 대시보드·자료업로드·도면/수량/단가/승인/이력 화면
│   └── components/api.ts     # FastAPI 호출 모듈
├── backend/                  # FastAPI 및 규칙 엔진
│   ├── app/services/preprocessing_reader.py  # 기존 결과 관리자용 읽기 어댑터
│   ├── app/services/raw_preprocessor.py      # 원본 CSV/XLSX와 문서 메타데이터 전처리기
│   ├── app/main.py           # API, 승인 이력 엔드포인트
│   ├── alembic/               # 버전 관리형 PostgreSQL migration
│   └── scripts/seed_sample.py # 프로젝트·권한·검토 샘플 시드
│   └── tests/                # 핵심 보호 규칙 테스트
├── db/init.sql               # PostgreSQL 초기화 예약 지점
├── db/migrations/002_raw_preprocessing.sql # 직접 적용용 원본 전처리·감사 확장 SQL
├── uploads/                  # 원본 파일 저장소
├── exports/                  # 검토 결과 패키지 저장소
├── docker-compose.yml        # Next.js + FastAPI + PostgreSQL
└── .env.example
```

상위 폴더의 `전처리결과_20260908/`은 Docker에서 `/data/preprocessing`으로 읽기 전용 연결됩니다. 정상 운영 흐름은 사용자가 업로드한 PDF·DWG·엑셀 원본을 `UPLOAD_DIR`(Docker: `/data/uploads`)에 보관한 뒤 자동 전처리 작업을 실행하는 것입니다. PostgreSQL에는 원본 본문이 아니라 경로·SHA-256·Rev.·시트·행·업로더와 내부 전처리 결과를 기록합니다. 기존 전처리 산출물은 관리자용 보조 경로입니다.

| 기능 | 전처리 산출물 |
|---|---|
| 현황/미결정 | `118_final_preprocessing_status.csv`, `72_사무동_검토우선순위_작업대기열.csv` |
| 규칙 재검토 | `70_사무동_자동연결_경고승인_통합.csv`, `75_사무동_단순산식_자동검산결과.csv`, `76_사무동_산식_재검산불가_경고대기열.csv` |
| 도면 전후 비교 | `06_도면_전후매핑후보.csv`, `17_사무동_전후도면_비교대상.csv`, `22_도면_비교_준비도_검토.csv` |
| 단가 대기열 | `79_사무동_구매부서_신규내역_단가검토_대기열.csv`, `86_사무동_PriceInfoService_단가조회결과.csv` |
| 기준 요약 | `119_최종_전처리_종합보고서.md` |

## 실행 방법 (Docker 권장)

1. `cost-review-mvp`에서 환경 파일을 준비합니다.

   ```powershell
   Copy-Item .env.example .env
   ```

2. `POSTGRES_PASSWORD` 값을 `.env`에서 변경한 후 서비스를 시작합니다. Compose는 이 값으로 API의 DB 연결 문자열도 함께 구성합니다.

   ```powershell
   docker compose up --build
   ```

3. 브라우저에서 `http://localhost:3000`을 엽니다. API 문서는 `http://localhost:8000/docs`에서 확인합니다.

API 컨테이너는 시작 시 `alembic upgrade head`를 실행하여 PostgreSQL 스키마를 생성합니다. 샘플 데이터를 넣으려면 API 컨테이너에서 아래 명령을 실행합니다.

```powershell
docker compose exec api python scripts/seed_sample.py
```

종료는 `docker compose down`입니다. 데이터베이스 볼륨까지 지우려면 명시적으로 `docker compose down -v`를 사용합니다.

## Vercel·운영 API 배포 환경변수

웹과 FastAPI는 서로 다른 실행환경으로 배포합니다. Vercel에는 `frontend`를 연결하고, FastAPI·PostgreSQL·업로드 저장소는 별도 백엔드 호스트에 둡니다. Vercel의 `NEXT_PUBLIC_API_BASE_URL`에는 백엔드의 공개 HTTPS 주소와 `/api/v1`을 지정합니다.

백엔드에만 다음 변수를 등록합니다.

| 변수 | 용도 | 공개 범위 |
|---|---|---|
| `DATABASE_URL` | 운영 PostgreSQL 연결 | 백엔드 전용 |
| `AUTH_REQUIRED=true` | 인증 강제 | 백엔드 전용 |
| `CORS_ORIGINS` | Vercel 웹 주소 허용 | 백엔드 전용 |
| `PRICE_API_URL` | 조달청 PriceInfoService 엔드포인트 | 백엔드 전용 |
| `PRICE_API_KEY` | 조달청 API 인증키 | 백엔드 전용·`NEXT_PUBLIC_*` 금지 |
| `PUBLIC_DATA_SERVICE_KEY` | 이전 전처리·PoC에서 사용한 인증키 변수명(호환) | 백엔드 전용·`NEXT_PUBLIC_*` 금지 |
| `PRICE_API_OPERATION` | PriceInfoService operation(기본: 건축 시장시공가격) | 백엔드 전용 |
| `PUBLIC_DATA_SERVICE_URL` | 이전 실행기의 엔드포인트를 그대로 사용할 때(선택) | 백엔드 전용 |
| `PRICE_API_SERVICE_NAME` | 화면에 표시할 서비스명(선택) | 백엔드 전용 |
| `PRICE_REFERENCE_CSV` | 참고단가 CSV 경로(선택) | 백엔드 전용 |

Vercel 프로젝트에는 다음 공개 변수만 등록합니다.

| 변수 | 예시 |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.example.com/api/v1` |
| `NEXT_PUBLIC_PROJECT_ID` | `project-g5-office` |
| `NEXT_PUBLIC_USER_ID` | `pfc391` (MVP 기본 계정) |

배포 후에는 (1) `/health` 응답 확인, (2) 인증된 어느 계정에서든 단가 조회 요청, (3) 저장 참고단가가 없는 대표 품목 1건의 `조회 완료` 또는 추적 가능한 오류 상태 확인, (4) 구매부서 `적용 후보` 판단 후 잠정금액 계산을 순서대로 실행합니다. 조회 후보 수집은 모든 인증 사용자에게 허용하지만, 단가 적용 판단은 구매부서 또는 관리자만 수행합니다. URL·키 중 하나라도 빠지면 API를 호출하지 않고 `조회 보류`로 남으며, 저장 참고단가·공식 CSV 우선순위는 그대로 유지됩니다.

### Render에서 FastAPI·PostgreSQL 올리기

저장소 루트의 `render.yaml`은 `backend` 웹 서비스와 PostgreSQL을 함께 만드는
Blueprint입니다. Render Dashboard에서 **New → Blueprint**를 선택하고 이
GitHub 저장소의 `render.yaml`을 지정하면 됩니다. 최초 생성 화면에서
`MVP_*_PASSWORD` 4개와 `PRICE_API_URL`·`PRICE_API_KEY`(또는
`PUBLIC_DATA_SERVICE_KEY`)를 입력합니다. 배포가 끝나면 Render가 발급한 API
주소에 `/api/v1`을 붙여 Vercel Production 환경의
`NEXT_PUBLIC_API_BASE_URL`로 등록하고 Production 재배포를 실행합니다.

Blueprint는 무료 플랜에서 동작하도록 파일 경로를 `/tmp`로 지정합니다.
무료 플랜에서는 서비스 재시작 시 업로드·엑셀·PDF 파일이 사라질 수 있으므로
운영 보존이 필요하면 Render 유료 영구 디스크를 `/var/data`에 연결하고
`UPLOAD_DIR=/var/data/uploads`, `EXPORT_DIR=/var/data/exports`,
`PREPROCESSING_DIR=/var/data/preprocessing`으로 바꾸세요. PostgreSQL 데이터는
별도 데이터베이스에 저장되므로 웹 서비스 재시작과 분리됩니다.

외부 API 호출 전에는 백엔드에서 아래 명령으로 키 값 없이 설정 상태만 확인할 수 있습니다. `--dry-run`을 빼면 설정이 완전할 때만 대표 품목 1건을 호출하며, DB에는 저장하지 않습니다.

```powershell
cd backend
.venv\Scripts\python.exe scripts/price_api_smoke.py --dry-run
# 실제 키가 설정된 환경에서만
.venv\Scripts\python.exe scripts/price_api_smoke.py --item "철근콘크리트용봉강" --unit "TON"
```

스모크 결과는 키 값을 출력하지 않고 `api_key_configured`, `lookup_status`,
`price_found`만 확인할 수 있게 되어 있습니다. PowerShell의 `$env:` 설정은
해당 창에만 유효하므로 다른 터미널에서 실행하면 키가 보이지 않습니다.
실제 키는 화면·로그·저장소에 붙여 넣지 마세요.

단위 표기가 API 원문과 달라 1차 결과가 없으면 서버가 단위를 제외한 2차
조회까지 자동으로 시도합니다. 그래도 결과가 없으면 단가를 임의 적용하지
않고 `조회 결과 없음` 상태로 남깁니다.

## 로컬 개발 실행

PostgreSQL을 먼저 실행하고 `DATABASE_URL` 및 `UPLOAD_DIR`을 설정합니다. `PREPROCESSING_DIR`은 일반 원본 업로드 흐름에는 필요하지 않으며, 관리자용 기존 전처리 결과 가져오기·회귀검증을 사용할 때만 설정합니다.

```powershell
# API
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATABASE_URL = "postgresql+psycopg://cost_review:change-me@localhost:5432/cost_review"
$env:AUTH_REQUIRED = "true"
$env:UPLOAD_DIR = "C:\Users\LG\Desktop\교육자료\실전자료\cost-review-mvp\uploads"
$env:EXPORT_DIR = "C:\Users\LG\Desktop\교육자료\실전자료\cost-review-mvp\exports"
$env:PREPROCESSING_DIR = "C:\Users\LG\Desktop\교육자료\실전자료\전처리결과_20260908" # 관리자 보조 경로(선택)
alembic upgrade head
uvicorn app.main:app --reload --port 8001

# 별도 터미널: 웹
cd frontend
npm install
# 로컬 개발 기본값은 8001입니다. 8000을 사용할 경우 이 값을 8000으로 맞춥니다.
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8001/api/v1"
npm run dev
```

### 로컬 접속 주소

- 웹 검토 화면: `http://localhost:3000`
- FastAPI 문서: `http://localhost:8001/docs`
- FastAPI 상태: `http://localhost:8001/health`
- PostgreSQL: `localhost:5432` (`cost_review` / `.env`의 계정)

### 전체 통합 스모크 테스트

API를 실행한 상태에서 별도 터미널에서 아래 명령을 실행하면 원본 업로드, 비동기 전처리 작업, 규칙 작업, API 조회, 순차 승인, 단가 조회 요청, 이력 재조회까지 검증합니다. 테스트는 현재 `DATABASE_URL`에 연결된 DB에 테스트 계정을 추가합니다.

```powershell
cd backend
$env:INTEGRATION_API_BASE = "http://localhost:8001/api/v1"
.venv\Scripts\python.exe scripts/integration_smoke.py
```

성공 시 `{"ok": true, "checks": [...]}`가 출력됩니다. 운영 DB에서 실행하기 전에는 테스트 전용 데이터베이스를 사용하세요.

통합 테스트가 확인하는 항목은 다음과 같습니다.

| 영역 | 확인 내용 |
|---|---|
| 자료 업로드 | 3MB급 PDF 스트리밍 저장, DWG/XLSX 시그니처, 잘못된 확장자 거부 |
| 전처리·규칙 | 원본 업로드 후 비동기 전처리 접수·완료, 최대 5회 재시도 정책, 표준화·경고·도면·수량·매핑·단가 조회, 실행별 선택 로딩 |
| 버전 관리 | 동일 SHA-256 재업로드 전처리 재사용, 동일 Rev. 다른 해시 보존·충돌 경고 |
| 승인·권한 | 인증 누락 401, 타 부서 단가 요청 403, 공사→설계→구매 순차 승인, 선택 일괄승인 항목별 성공·실패 |
| 추적성 | 업로드 SHA-256·경로·Rev.·도면번호·시트 저장, 근거·이력 재조회 |
| 결과 패키지 | 동일 `export_id` 상태 조회, ZIP/Manifest 다운로드, Excel·PDF 선택 의존성 경고 상태 |
| 조달청 오류 | 인증키/URL 미설정·네트워크/HTTP 오류를 적용 대기 상태로 보존 |
| 프론트 연결 | Next.js `/`, `/upload`, `/drawings`, `/quantities`, `/prices`, `/approvals`, `/history` production build 및 API 계약 확인 |

현재 raw-only 경로는 CSV/XLSX/XLSM의 행·열 표준화와 선택적 PDF 페이지 텍스트 추출(`pypdf` 설치 시)을 지원하고, PDF 텍스트가 없거나 파서가 실패·미설치인 영역은 `추가 확인 필요` 상태로 보존합니다. DWG는 헤더 버전·원본 경로를 보존하며, 도면번호를 입력하지 않아도 `DWG-101`·`A-101`·`S_201` 같은 안전한 파일명 패턴을 보조 식별자로 사용합니다. 기준·변경 도면 후보는 건물·공종 패키지를 먼저 대조하고, 기존 매핑을 재생성하지 않으며 동일 파일 재실행 시 중복 후보를 만들지 않습니다. 사무동에서 감사된 품명·규격 별칭은 품명과 단위 문맥을 함께 확인한 뒤 신규 업로드와 기존 결과에 공통 적용하고, 등록되지 않은 동의어는 추정하지 않고 검토 후보로 보존합니다. 통합 스모크가 만든 `integration-source*`·`demo_*` 원본은 대시보드에 운영 자료와 별도로 포함 상태를 표시해 테스트 수치가 실자료로 오인되지 않게 합니다. 수량·도면·통합검토·단가 화면의 `자료 범위` 필터는 별도 프로젝트나 데이터베이스를 만들지 않고 운영 자료와 통합 테스트 자료를 구분하며, 선택값을 URL의 `dataScope` 파라미터에 보존해 화면 이동·새로고침 후에도 같은 범위를 유지합니다. 전처리에서 사용한 ZWCAD·CAD 뷰어·추출도구는 향후 Windows CAD 분석 워커에 연결해 재사용할 수 있습니다. CAD 워커가 없거나 라이선스 범위를 벗어난 작업은 메타데이터와 원본 근거만 남기고 자동 확정하지 않습니다. 파일을 개별 업로드해도 업로드 시점의 프로젝트 전체 검증 원본을 하나의 전처리 실행으로 묶어 수량산출서·내역서·도면 연결 후보를 생성합니다. 전처리 작업은 실행 횟수와 오류를 `preprocessing_runs`에 저장하고, 각 원본값·표준화값은 `preprocessing_records`에 실행별로 저장합니다. 업로드 화면의 `선택 실행 결과 로딩` 또는 `GET /preprocessing/runs/{run_id}/records`로 나중에 필요한 결과만 다시 검토할 수 있습니다. 일시 오류 시 최대 5회 자동 재시도하며, 최종 실패 작업은 재시도 API로 다시 접수할 수 있습니다. 기존 `전처리결과_20260908` 결과는 관리자용 가져오기·회귀검증 경로입니다.
표준 품명·규격·단위 사전은 `pfm391`만 발행·수정하고, 공사·설계·구매부서는 근거를 첨부한 수정 요청만 제출합니다. 사전 변경은 새 전처리부터 적용하며 기존 검토 결과에는 소급하지 않고, 프로젝트별 예외와 변경 이력을 별도로 보존합니다.
동일 SHA-256 파일을 다시 올리면 기존 원본·전처리 실행에 연결하고 중복 업로드만 감사 로그에 기록합니다. 다른 내용의 동일 Rev. 파일은 원본을 덮어쓰지 않고 새 파일·새 전처리 회차로 보존하며 `동일 Rev. 내용 상충` 경고를 생성합니다.

백엔드 규칙 보호 테스트는 아래와 같이 실행합니다.

```powershell
cd backend
pip install -r requirements-dev.txt
pytest -q tests
```

## 제공 API

- `GET /health`: 서비스·규칙엔진·PostgreSQL 연결 상태(연결 실패 시 503)
- `GET /api/v1/dashboard`: 전처리 현황 요약
- `GET /api/v1/reviews`: 검토 대기열
- `GET /api/v1/projects`: 프로젝트 목록
- `GET /api/v1/projects/{project_id}`: 프로젝트별 경고·도면·매핑·단가·승인 현황
- `GET /api/v1/projects/{project_id}/preprocessing`: 전처리 상태
- `GET /api/v1/projects/{project_id}/preprocessing/runs/{run_id}/records`: 선택 실행의 원본값·표준화값을 종류·상태·페이지 단위로 재조회
- `POST /api/v1/projects/{project_id}/preprocessing/run`: 선택한 원본의 비동기 전처리 시작(202)
- `POST /api/v1/projects/{project_id}/preprocessing/{run_id}/retry`: 실패한 원본 전처리 재접수(최대 5회 정책)
- `POST /api/v1/admin/projects/{project_id}/preprocessing/import`: 관리자용 기존 전처리 결과 가져오기(202)
- `GET /api/v1/projects/{project_id}/price-references`: DB에 저장된 참고 단가 조회(동일 프로젝트 타건물 후보·다른 프로젝트 참고자료, 출처 프로젝트 표시)
- `POST /api/v1/admin/projects/{project_id}/price-references/import`: `15_타건물_기계약단가_참고.csv`를 프로젝트별 참고 단가 카탈로그로 저장(관리자 전용)
- `GET /api/v1/projects/{project_id}/warnings`: 경고 조회
- `GET /api/v1/projects/{project_id}/drawings/changes`: 도면 변경 후보
- `GET /api/v1/projects/{project_id}/quantities`: 수량·산식·금액 검토 결과
- `GET /api/v1/projects/{project_id}/mappings`: 도면·수량·내역 연결 후보
- `GET /api/v1/projects/{project_id}/prices/results`: 단가 검토 결과
- `GET /api/v1/projects/{project_id}/prices/{result_id}/decision`: 단가 적용 판단 조회
- `POST /api/v1/projects/{project_id}/prices/{result_id}/decision`: 구매부서 단가 적용 후보·보류 판단 저장(자동 확정 없음)
- `GET /api/v1/projects/{project_id}/evidence`: 검토 근거
- `GET /api/v1/projects/{project_id}/files`: 프로젝트 원본 파일 메타데이터
- `POST /api/v1/projects/{project_id}/files`: 원본 파일 업로드·확장자/시그니처/용량 검증(파일 본문은 DB 미저장)
- `DELETE /api/v1/projects/{project_id}/files/{file_id}`: 전체 관리자 전용 원본 논리 삭제(실제 파일 보존·감사 로그 기록)
- `POST /api/v1/auth/login`: MVP 로컬 계정 로그인(반환된 사용자 ID를 개발용 `X-User-Id`에 사용)
- `POST /api/v1/projects/{project_id}/rules/run`: 긴 규칙 실행을 비동기 작업으로 접수(202)
- `GET /api/v1/jobs/{job_id}`: 비동기 작업 상태
- `GET /api/v1/prices`: 신규내역 및 PriceInfoService 재조회 대기열
- `POST /api/v1/projects/{project_id}/prices/query`: 인증 사용자 조달청 단가 조회 요청(202; 적용 판단 권한과 분리)
- `POST /api/v1/projects/{project_id}/reviews/{source_id}/approvals`: 부서 승인 처리
- `POST /api/v1/projects/{project_id}/reviews/approvals/batch`: 동일 단계 선택 항목 일괄 승인·반려·수정 요청(항목별 성공·실패 결과)
- `POST /api/v1/projects/{project_id}/reports`: 동일 검토 스냅샷의 PDF·Excel·근거 Manifest 패키지 생성(202)
- `GET /api/v1/projects/{project_id}/reports/{export_id}`: 결과 패키지 생성 상태·파일 경로 조회
- `GET /api/v1/projects/{project_id}/reports/{export_id}/download?format=bundle|xlsx|pdf|manifest`: 준비된 결과 파일 다운로드
- `GET /api/v1/projects/{project_id}/review-history`: 검토 이력 조회
- `GET /api/v1/projects/{project_id}/audit-logs`: 삭제·상태 변경 감사 로그 조회

설계부서 이력은 같은 항목의 공사부서 승인 뒤에만, 구매부서 이력은 공사·설계부서 승인 뒤에만 기록할 수 있습니다. 수정 요청·반려·추가 확인 필요는 결론을 확정하지 않는 이력으로 보존됩니다.

MVP 공식 승인·보관 결과물은 상세 Excel, 요약 PDF, 원본 근거 Manifest·파일 링크, 원본 파일 묶음입니다. 회사 결재 양식과 전자결재 시스템 연결은 후속 범위로 둡니다.

검토·승인 상태는 `검토 대기`, `승인`, `수정 요청`, `반려`, `추가자료 요청`, `적용 후보`, `적용 보류`, `확정`을 사용하며, 승인 전 수량·금액·단가는 확정값으로 표시하지 않습니다.

부서별 승인 기한은 영업일 3일입니다. 기한이 지나도 자동 승인하지 않고 `pfm391`에게 지연 알림을 보냅니다. 대리 승인은 `pfm391`이 기간·범위·사유를 등록한 경우에만 허용하며 감사 로그에 기록합니다.

운영 환경은 `AUTH_REQUIRED=true`로 실행하며 모든 API 요청에 4개 계정 중 하나의 `X-User-Id`가 필요합니다. 로컬 개발에서만 `AUTH_REQUIRED=false`로 완화할 수 있습니다. 규칙 실행·승인·단가 조회 요청은 항상 인증과 부서·관리자 권한을 검사합니다. 기본 웹 계정은 공사부서 `pfc391`입니다.

운영 계정은 `pfc391`(공사), `pfe391`(설계), `pfp391`(구매), `pfm391`(전체 관리자·승인권자) 4개만 사용합니다. 초기 비밀번호는 `.env`의 `MVP_*_PASSWORD`에서 주입하며, DB에는 해시만 저장합니다. 배포 후 초기 비밀번호를 변경하고, 계정 추가는 관리자 승인과 감사 로그를 거쳐야 합니다. SSO/MFA는 후속 단계로 보류합니다.

## Next.js 검토 화면

- `/`: 프로젝트 현황 대시보드와 규칙 재검토 작업 접수
- `/upload`: PDF·DWG·엑셀·CSV 원본 업로드 및 검증 결과, 전처리 실행 선택 재조회
- `/drawings`: 기준·변경 도면의 번호·시트·Rev. 및 파일 경로 비교 후보
- `/quantities`: 산식·수량·금액 검산 경고, 도면·수량·내역 연결 후보와 근거
- `/prices`: 신규내역 단가 후보와 조달청 조회 요청/적용 판단 대기, 저장된 타건물 참고 단가 비교
- `/approvals`: 공사부서 → 설계부서 → 구매부서 순차 승인 대기열
- `/history`: 부서별 승인·수정 요청·반려·오탐 감사 이력

데모자료 기준 최종 확인 항목과 실행 검증 결과는 [`MVP_QA_CHECKLIST.md`](./MVP_QA_CHECKLIST.md)에 기록합니다.

모든 화면은 `evidence_references`를 통해 원본 파일 경로, 시트, 행, 도면번호, 판정 사유, 추출 신뢰도를 함께 표시합니다. 수량·금액·단가는 후보값 또는 검토 대기로만 보이며, 최종 승인 전에는 확정값으로 표시하지 않습니다.

### 검토 결과 패키지

웹 화면을 기준 시스템으로 사용하고, 다운로드는 하나의 `export_id` 스냅샷에서 함께 생성합니다. 패키지는 요약 PDF, 상세 Excel(`요약`·`도면변경`·`수량산식`·`내역연결`·`단가검토`·`승인이력`·`원본근거`·`데이터정의`), 근거 Manifest(CSV/JSON), 원본 파일 링크 목록으로 구성합니다. 생성 기준일·필터·자료 버전·승인 상태·규칙 버전·입력 해시를 고정하고 `review_exports`에 저장합니다. 승인 전 패키지는 모든 수량·금액·단가를 `검토 후보`·`승인 대기`·`확정 전`으로 표시하며, 원본 파일 본문은 복사하지 않고 경로·시트·행·페이지·좌표만 연결합니다.

`/api/v1/projects/{project_id}/preprocessing/run`은 원본 파일을 내부 표준화 구조로 변환하고, 수량산출서·내역서 연결 후보와 산식·금액 경고를 생성합니다. `/api/v1/rules/run`은 기존 결과 회귀검토와 추가 규칙 실행에 사용합니다. 두 경로 모두 원본 파일과 승인 대기 상태를 자동 확정하지 않습니다.

## PostgreSQL 테이블 구성

`0001_initial_schema`가 기본 테이블을 생성하고, `0004_raw_preprocessing_and_audit`와 `0005_preprocessing_retry_policy`가 원본 업로드 전처리·감사 로그·5회 재시도 정책을 보강하며, `0006_price_reference_catalog`가 재검토용 참고 단가 카탈로그를 추가합니다.

- 사용자·권한: `users`, `departments`, `roles`, `user_roles`
- 사업 구조: `projects`, `buildings`, `work_packages`
- 원본 추적: `source_files` (원본 파일 자체는 저장하지 않고 경로·해시·행/셀 참조만 저장)
- 표준화·검토: `preprocessing_runs`, `preprocessing_records`, `preprocessing_artifacts`, `standardized_items`, `drawing_change_candidates`, `review_warnings`
- 연결 근거: `mapping_candidates`, `evidence_references`
- 승인·단가: `approval_history`, `procurement_price_results`, `price_application_decisions`, `price_reference_catalog`
- 감사: `audit_logs`; 원본 논리 삭제 메타데이터는 `source_files.deleted_*`에 보존

보존 정책 기본값은 프로젝트 종료 후 원본·전처리·검토 결과 7년, 승인 이력·감사 로그 최소 7년입니다. PostgreSQL과 원본 저장소는 일일 증분·주간 전체 백업을 전제로 하며, 최근 35일 복구본과 월별 장기 백업을 운영정책으로 관리합니다. 물리 삭제는 전체 관리자와 보존정책 확인 후에만 허용합니다.

샘플 시드는 `광양5 사무동` 프로젝트, 3개 부서, 4개 운영 계정, 대표 도면 변경 후보, 경고, 연결 근거, 단가 후보, 승인 이력을 생성합니다. 운영도 우선 이 4개 계정으로 시작하며 SSO/MFA는 후속 단계입니다.

## 다음 확장 단계

단가 검토는 동일 프로젝트 타건물의 승인 참고단가를 먼저 확인하고, 공식 조달청 CSV·표준시장단가가 있으면 조달청 API보다 먼저 검토 후보로 사용합니다. 두 자료가 모두 없을 때만 PriceInfoService API를 조회합니다. 모든 후보는 구매부서 승인 전 자동 확정하지 않으며 출처·기준일·적용 사유를 기록합니다. 관리자가 `price-references/import`를 실행하면 CSV의 품명·표준품명·규격·단위·건물·단가·출처·제한사항이 `price_reference_catalog`에 저장됩니다. 동일 프로젝트의 다른 건물에서 일치하는 내역은 신규내역 단가 후보로 제안할 수 있지만 구매부서 승인 전 자동 확정하지 않습니다. 다른 프로젝트 단가는 출처 프로젝트·건물·기준일을 표시하는 참고자료로만 조회하며 자동 후보 적용하지 않습니다. 후속 단계에서는 PDF OCR 고도화, DWG 객체·좌표 비교 worker, 인증된 PriceInfoService 재조회를 연결합니다. 정상 운영의 기본 경로는 원본 업로드→비동기 전처리→규칙 검토이며, 기존 전처리 결과는 관리자용 보조 경로로 유지합니다.

단가 적용은 조회값을 원본 내역서에 덮어쓰지 않는 2단계 방식으로 운영합니다. 구매부서가 후보를 `적용 예정`으로 판단하면 적용단가와 사유를 별도 결정 이력에 저장하고, 변경자료의 검토 수량이 있을 때만 `검토 수량 × 적용단가`를 잠정금액으로 계산해 표시합니다. 원본 단가·금액은 보존하며, 최종 확정은 별도 승인 이후에만 가능합니다. API 응답은 적용단가를 우선하고 재료비·노무비·경비 구성값을 함께 보존해 서비스별 응답 형식 차이에 대비합니다.
참고단가 CSV는 기본적으로 `PREPROCESSING_DIR/15_타건물_기계약단가_참고.csv`에서 읽으며, 운영 환경에서 별도 위치를 사용할 때는 `PRICE_REFERENCE_CSV` 환경변수로 명시할 수 있습니다. 파일이 없으면 신규내역은 `참고단가 미확인` 상태로 남고 자동 적용되지 않습니다.
