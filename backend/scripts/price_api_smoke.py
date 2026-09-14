"""저장·승인 없이 대표 품목 1건만 조달청 API로 점검하는 스모크 명령."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 파일을 `backend` 폴더에서 직접 실행해도 `app` 패키지를 찾도록 한다.
# (기존에는 PYTHONPATH=.를 별도로 지정해야 했다.)
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.database import ProcurementPriceResult
from app.services.price_lookup import PriceLookupService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--item", default="철근콘크리트용봉강")
    parser.add_argument("--specification", default="")
    parser.add_argument("--unit", default="TON")
    parser.add_argument("--dry-run", action="store_true", help="환경변수만 확인하고 외부 호출하지 않음")
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()
    key_source = "PRICE_API_KEY" if settings.price_api_key else "PUBLIC_DATA_SERVICE_KEY" if os.getenv("PUBLIC_DATA_SERVICE_KEY") else None
    summary = {
        "api_url_configured": bool(settings.effective_price_api_url),
        "api_key_configured": bool(settings.effective_price_api_key),
        "key_source": key_source,
        "operation": settings.price_api_operation,
        "item": args.item,
        "unit": args.unit,
    }
    if args.dry_run or not settings.effective_price_api_url or not settings.effective_price_api_key:
        print(summary)
        return 0 if args.dry_run else 2

    record = ProcurementPriceResult(
        id="price-api-smoke",
        project_id="smoke-test",
        candidate_id="price-api-smoke",
        service_name=settings.price_api_service_name,
        item_name=args.item,
        specification=args.specification or None,
        unit=args.unit or None,
    )
    result = PriceLookupService().execute(record)
    summary.update({
        "lookup_status": result.lookup_status,
        "price_found": result.price is not None,
        "price": result.price,
        "material_cost": result.material_cost,
        "labor_cost": result.labor_cost,
        "expense_cost": result.expense_cost,
    })
    print(summary)
    # PowerShell에서 딕셔너리 키를 별도 명령으로 입력하지 않아도 되도록
    # 결과 판정에 필요한 두 값을 명시적으로 한 줄씩 표시한다.
    print(f"lookup_status={result.lookup_status}")
    print(f"price_found={result.price is not None}")
    return 0 if result.price is not None else 1


if __name__ == "__main__":
    sys.exit(main())
