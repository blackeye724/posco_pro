"""조달청 단가 조회 어댑터.

인증키와 엔드포인트는 환경변수로만 주입하며, 조회 결과는 참고 후보로만 저장한다.
"""

import json
import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse, unquote
from urllib.request import Request, urlopen

from ..config import get_settings
from ..database import ProcurementPriceResult


class PriceLookupService:
    def __init__(self):
        self.settings = get_settings()

    def _url(self, request: ProcurementPriceResult, *, include_unit: bool = True) -> str | None:
        api_url = self.settings.effective_price_api_url
        api_key = self.settings.effective_price_api_key
        if not api_url or not api_key:
            return None
        # 엔드포인트를 생략한 이전 설정은 프로젝트의 기존 우선순위인
        # PriceInfoService(15129415) 오퍼레이션을 사용한다. 표준시장단가
        # (15151298)는 PUBLIC_DATA_SERVICE_URL/PRICE_API_URL로 명시한 경우에만
        # 호출한다. 데이터셋별 이용신청 권한이 다르므로 키만으로 엔드포인트를
        # 임의 전환하면 정상 키도 401이 될 수 있다.
        parsed = urlparse(api_url)
        query = dict(parse_qsl(parsed.query))
        query.update({
            # 공공데이터포털 Encoding/Decoding 키 어느 형태든 한 번만
            # URL 인코딩되도록 기존 PoC와 동일하게 먼저 디코딩한다.
            "serviceKey": unquote(api_key),
            "pageNo": "1",
            "numOfRows": "20",
            "type": "json",
            "itemName": request.item_name or "",
            "specification": request.specification or "",
        })
        if include_unit:
            query["unit"] = request.unit or ""
        return urlunparse(parsed._replace(query=urlencode(query)))

    @staticmethod
    def _value(row: dict[str, str], names: tuple[str, ...]) -> str:
        for name in names:
            value = str(row.get(name) or "").strip()
            if value:
                return value
        return ""

    def _official_reference_paths(self) -> list[tuple[Path, str]]:
        paths: list[tuple[Path, str]] = []
        if self.settings.official_price_csv:
            paths.append((self.settings.official_price_csv, "공식 CSV"))
        if self.settings.standard_market_price_csv:
            paths.append((self.settings.standard_market_price_csv, "표준시장단가"))
        # 기존 전처리 결과에 포함된 공식 CSV/표준시장단가 파일도 운영 참고자료로 사용한다.
        for path, kind in (
            (self.settings.preprocessing_dir / "83_사무동_조달청_공식CSV_참고매칭.csv", "공식 CSV"),
            (self.settings.preprocessing_dir / "87_사무동_조달청_공식CSV_검색어기반_보조후보.csv", "공식 CSV"),
            (self.settings.preprocessing_dir / "표준시장단가.csv", "표준시장단가"),
            (self.settings.preprocessing_dir / "조달청_공사원가_표준시장단가.csv", "표준시장단가"),
        ):
            if path.exists():
                paths.append((path, kind))
        return paths

    def _lookup_csv(self, record: ProcurementPriceResult, path: Path, source_kind: str) -> tuple[float | None, dict[str, object] | None]:
        # 기존 조달청 표준시장단가 파일은 CP949인 경우가 많다. UTF-8
        # 실패 시 CP949로 재시도해 이전 전처리 자료를 그대로 재사용한다.
        for encoding in ("utf-8-sig", "cp949"):
            try:
                with path.open("r", encoding=encoding, newline="") as source:
                    for row_number, row in enumerate(csv.DictReader(source), start=2):
                        names = {
                            self._value(row, ("standard_item", "standard_name", "표준품명", "품명", "original_item")),
                            self._value(row, ("original_item", "품명", "품목", "item_name")),
                        }
                        normalize = lambda value: re.sub(r"\s+", "", str(value or "")).casefold()
                        if not record.item_name or normalize(record.item_name) not in {normalize(name) for name in names}:
                            continue
                        row_unit = self._value(row, ("standard_unit", "unit", "단위"))
                        if record.unit and row_unit and normalize(record.unit) != normalize(row_unit):
                            continue
                        raw_price = self._value(row, ("unit_price", "estimate_unit_price", "price", "단가", "가격", "합계", "total", "totalprice")).replace(",", "")
                        try:
                            price = float(raw_price) if raw_price else None
                        except ValueError:
                            price = None
                        if price is not None:
                            return price, {"source_file": str(path), "row": row_number, "source_kind": source_kind, "building": row.get("building"), "provenance": row.get("provenance"), "restriction": row.get("restriction"), "dataset_use": row.get("dataset_use"), "reference_date": path.stat().st_mtime}
            except UnicodeDecodeError:
                continue
            except (OSError, csv.Error):
                return None, None
        return None, None

    def _fallback_lookup(self, record: ProcurementPriceResult) -> tuple[float | None, dict[str, object] | None]:
        """공식 CSV·표준시장단가를 먼저 찾고, 없을 때 타건물 참고단가를 찾는다."""
        for path, source_kind in self._official_reference_paths():
            price, reference = self._lookup_csv(record, path, source_kind)
            if reference:
                return price, reference
        configured = self.settings.price_reference_csv
        # An empty/missing optional setting must not disable the historical
        # preprocessing fallback (Pydantic parses an empty Path as ``.``).
        path = configured if configured and configured.is_file() else (self.settings.preprocessing_dir / "15_타건물_기계약단가_참고.csv")
        if not path.is_file():
            return None, None
        return self._lookup_csv(record, path, "동일 프로젝트·타건물 참고")

    @staticmethod
    def _to_number(value: object) -> float | None:
        try:
            cleaned = str(value).replace(",", "").strip()
            return float(cleaned) if cleaned else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _find_numeric(payload: object, aliases: set[str]) -> float | None:
        """Find the first numeric value for a known API field name."""
        if isinstance(payload, dict):
            for key, value in payload.items():
                normalized = str(key).replace("_", "").replace(" ", "").lower()
                if normalized in aliases:
                    number = PriceLookupService._to_number(value)
                    if number is not None:
                        return number
                found = PriceLookupService._find_numeric(value, aliases)
                if found is not None:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = PriceLookupService._find_numeric(value, aliases)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _find_price(payload: object) -> float | None:
        """Backward-compatible generic price extractor used by older callers."""
        return PriceLookupService._find_numeric(payload, {"price", "가격", "unitprice", "단가"})

    @staticmethod
    def _extract_api_fields(payload: object) -> dict[str, float | str | None]:
        # 조달청 공사원가/가격정보 응답은 서비스별로 영문·한글 필드명이
        # 다를 수 있어, 적용단가를 우선하고 합계·일반 단가를 보조로 사용한다.
        # PriceInfoService 건축 시장시공가격 응답은 영문 축약 필드
        # ``prce/mtrlcst/lbrcst/gnrlexpns``를 사용한다. 한글·일반
        # 별칭만 사용하면 응답 건수는 있어도 가격을 놓치므로 함께
        # 인식한다.
        applied_aliases = {"적용단가", "적용가격", "applyprice", "applyprc", "appliedprice", "unitprice", "단가", "price", "가격", "합계", "total", "totalprice", "prce"}
        total_aliases = {"합계", "총계", "total", "totalprice", "sumprice", "sumprc", "계", "prce"}
        material_aliases = {"재료비", "materialcost", "materialprice", "materialprc", "material", "mtrlcst"}
        labor_aliases = {"노무비", "laborcost", "laborprice", "laborprc", "labor", "lbrcst"}
        expense_aliases = {"경비", "경비비", "expensecost", "expenseprice", "expenseprc", "expense", "gnrlexpns"}
        price = PriceLookupService._find_numeric(payload, applied_aliases)
        return {
            "price": price if price is not None else PriceLookupService._find_numeric(payload, total_aliases),
            "material_cost": PriceLookupService._find_numeric(payload, material_aliases),
            "labor_cost": PriceLookupService._find_numeric(payload, labor_aliases),
            "expense_cost": PriceLookupService._find_numeric(payload, expense_aliases),
        }

    def execute(self, record: ProcurementPriceResult) -> ProcurementPriceResult:
        # 공식 참고자료가 있으면 외부 API보다 우선하며, 승인 전 후보로만 보존한다.
        fallback_price, fallback = self._fallback_lookup(record)
        if fallback:
            record.price = fallback_price
            record.lookup_status = f"대체자료 적용 후보 - {fallback.get('source_kind', '공식 참고자료')} (구매부서 승인 전 확정 금지)"
            record.raw_response = json.dumps({"fallback": fallback, "api_skipped": True}, ensure_ascii=False)
            return record
        url = self._url(record)
        if not url:
            record.lookup_status = "조회 보류 - 공식 CSV·표준시장단가 없음 및 API 인증키 또는 URL 미설정"
            return record
        try:
            # 단위 표기가 API 원문과 다른 경우를 대비한다. 1차(단위 포함)
            # 조회가 비어 있을 때만 2차(단위 제외)를 호출해 오조회·호출량을
            # 최소화한다.
            urls = [url]
            if record.unit:
                broad_url = self._url(record, include_unit=False)
                if broad_url and broad_url != url:
                    urls.append(broad_url)
            raw = ""
            for attempt_url in urls:
                request = Request(attempt_url, headers={"Accept": "application/json", "User-Agent": "cost-review-mvp/0.1"})
                with urlopen(request, timeout=15) as response:
                    raw = response.read(1_000_000).decode("utf-8", errors="replace")
                try:
                    api_payload = json.loads(raw)
                    extracted = self._extract_api_fields(api_payload)
                except json.JSONDecodeError:
                    extracted = {"price": None, "material_cost": None, "labor_cost": None, "expense_cost": None}
                record.price = extracted["price"]
                record.material_cost = extracted["material_cost"]
                record.labor_cost = extracted["labor_cost"]
                record.expense_cost = extracted["expense_cost"]
                if record.price is not None:
                    break
            record.raw_response = raw
            if record.price is not None:
                record.lookup_status = "조회 완료 - 구매부서 적용 판단 대기"
            else:
                fallback_price, fallback = self._fallback_lookup(record)
                if fallback:
                    record.price = fallback_price
                    record.lookup_status = "조회 결과 없음 - 대체자료 적용 후보(구매부서 승인 전 확정 금지)"
                    record.raw_response = json.dumps({"api_response": raw, "fallback": fallback}, ensure_ascii=False)
                else:
                    record.lookup_status = "조회 결과 없음 - 적용 판단 대기"
        except HTTPError as error:
            # 공공데이터포털의 401/403 응답 본문에는 키 승인·활용신청
            # 상태를 설명하는 메시지가 들어오는 경우가 많다. 키 자체나
            # 요청 URL은 저장하지 않고, 짧은 응답 메시지만 진단 근거로
            # 보존한다.
            try:
                api_message = error.read(2000).decode("utf-8", errors="replace").strip()
            except Exception:
                api_message = ""
            fallback_price, fallback = self._fallback_lookup(record)
            if fallback:
                record.price = fallback_price
                category = "권한 오류" if error.code in {401, 403} else "호출 제한" if error.code == 429 else "API 오류"
                record.lookup_status = f"{category} - 대체자료 적용 후보(구매부서 승인 전 확정 금지)"
                record.raw_response = json.dumps({"api_error": error.code, "api_message": api_message[:500], "fallback": fallback}, ensure_ascii=False)
            else:
                category = "권한 오류" if error.code in {401, 403} else "호출 제한" if error.code == 429 else "조회 실패"
                record.lookup_status = f"{category} - 적용 판단 대기 ({error.code})"
                record.raw_response = json.dumps({"api_error": error.code, "api_message": api_message[:500]}, ensure_ascii=False)
        except (URLError, TimeoutError, OSError) as error:
            fallback_price, fallback = self._fallback_lookup(record)
            if fallback:
                record.price = fallback_price
                record.lookup_status = f"네트워크 오류 - 대체자료 적용 후보(구매부서 승인 전 확정 금지)"
                record.raw_response = json.dumps({"api_error": type(error).__name__, "fallback": fallback}, ensure_ascii=False)
            else:
                record.lookup_status = f"조회 실패 - 적용 판단 대기 ({type(error).__name__})"
        return record
