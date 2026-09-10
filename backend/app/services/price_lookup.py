"""조달청 단가 조회 어댑터.

인증키와 엔드포인트는 환경변수로만 주입하며, 조회 결과는 참고 후보로만 저장한다.
"""

import json
import csv
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from urllib.request import Request, urlopen

from ..config import get_settings
from ..database import ProcurementPriceResult


class PriceLookupService:
    def __init__(self):
        self.settings = get_settings()

    def _url(self, request: ProcurementPriceResult) -> str | None:
        if not self.settings.price_api_url or not self.settings.price_api_key:
            return None
        parsed = urlparse(self.settings.price_api_url)
        query = dict(parse_qsl(parsed.query))
        query.update({
            "serviceKey": self.settings.price_api_key,
            "pageNo": "1",
            "numOfRows": "20",
            "type": "json",
            "itemName": request.item_name or "",
            "specification": request.specification or "",
            "unit": request.unit or "",
        })
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
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                for row_number, row in enumerate(csv.DictReader(source), start=2):
                    names = {
                        self._value(row, ("standard_item", "standard_name", "표준품명", "품명", "original_item")),
                        self._value(row, ("original_item", "품명", "품목", "item_name")),
                    }
                    if not record.item_name or record.item_name.strip() not in names:
                        continue
                    row_unit = self._value(row, ("standard_unit", "unit", "단위"))
                    if record.unit and row_unit and record.unit.strip().lower() != row_unit.lower():
                        continue
                    raw_price = self._value(row, ("unit_price", "estimate_unit_price", "price", "단가", "가격")).replace(",", "")
                    try:
                        price = float(raw_price) if raw_price else None
                    except ValueError:
                        price = None
                    if price is not None:
                        return price, {"source_file": str(path), "row": row_number, "source_kind": source_kind, "building": row.get("building"), "provenance": row.get("provenance"), "restriction": row.get("restriction"), "dataset_use": row.get("dataset_use"), "reference_date": path.stat().st_mtime}
        except (OSError, csv.Error):
            return None, None
        return None, None

    def _fallback_lookup(self, record: ProcurementPriceResult) -> tuple[float | None, dict[str, object] | None]:
        """공식 CSV·표준시장단가를 먼저 찾고, 없을 때 타건물 참고단가를 찾는다."""
        for path, source_kind in self._official_reference_paths():
            price, reference = self._lookup_csv(record, path, source_kind)
            if reference:
                return price, reference
        path = self.settings.preprocessing_dir / "15_타건물_기계약단가_참고.csv"
        if not path.exists():
            return None, None
        return self._lookup_csv(record, path, "동일 프로젝트·타건물 참고")

    @staticmethod
    def _find_price(payload: object) -> float | None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if str(key).lower() in {"price", "가격", "unitprice", "단가"}:
                    try:
                        return float(str(value).replace(",", ""))
                    except (TypeError, ValueError):
                        pass
                found = PriceLookupService._find_price(value)
                if found is not None:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = PriceLookupService._find_price(value)
                if found is not None:
                    return found
        return None

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
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "cost-review-mvp/0.1"})
            with urlopen(request, timeout=15) as response:
                raw = response.read(1_000_000).decode("utf-8", errors="replace")
            record.raw_response = raw
            try:
                record.price = self._find_price(json.loads(raw))
            except json.JSONDecodeError:
                record.price = None
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
            fallback_price, fallback = self._fallback_lookup(record)
            if fallback:
                record.price = fallback_price
                category = "권한 오류" if error.code in {401, 403} else "호출 제한" if error.code == 429 else "API 오류"
                record.lookup_status = f"{category} - 대체자료 적용 후보(구매부서 승인 전 확정 금지)"
                record.raw_response = json.dumps({"api_error": error.code, "fallback": fallback}, ensure_ascii=False)
            else:
                category = "권한 오류" if error.code in {401, 403} else "호출 제한" if error.code == 429 else "조회 실패"
                record.lookup_status = f"{category} - 적용 판단 대기 ({error.code})"
        except (URLError, TimeoutError, OSError) as error:
            fallback_price, fallback = self._fallback_lookup(record)
            if fallback:
                record.price = fallback_price
                record.lookup_status = f"네트워크 오류 - 대체자료 적용 후보(구매부서 승인 전 확정 금지)"
                record.raw_response = json.dumps({"api_error": type(error).__name__, "fallback": fallback}, ensure_ascii=False)
            else:
                record.lookup_status = f"조회 실패 - 적용 판단 대기 ({type(error).__name__})"
        return record
