from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.database import ProcurementPriceResult
from app.config import get_settings
from app.services.price_lookup import PriceLookupService


def test_price_lookup_without_credentials_stays_pending(monkeypatch):
    monkeypatch.setenv("PRICE_API_URL", "")
    monkeypatch.setenv("PRICE_API_KEY", "")
    get_settings.cache_clear()
    service = PriceLookupService()
    result = service.execute(ProcurementPriceResult(id="p-1", project_id="project", candidate_id="c-1", service_name="PriceInfoService", item_name="품목"))
    assert result.lookup_status.startswith("조회 보류")
    assert result.price is None


def test_price_lookup_network_error_is_saved_as_reviewable_status(monkeypatch):
    monkeypatch.setenv("PRICE_API_URL", "https://example.invalid/price")
    monkeypatch.setenv("PRICE_API_KEY", "test-key")
    get_settings.cache_clear()
    service = PriceLookupService()
    result = ProcurementPriceResult(id="p-2", project_id="project", candidate_id="c-2", service_name="PriceInfoService", item_name="품목")
    with patch("app.services.price_lookup.urlopen", side_effect=URLError("network down")):
        service.execute(result)
    assert result.lookup_status.startswith("조회 실패")
    assert result.price is None


def test_price_lookup_http_error_is_saved_as_reviewable_status(monkeypatch):
    monkeypatch.setenv("PRICE_API_URL", "https://example.invalid/price")
    monkeypatch.setenv("PRICE_API_KEY", "test-key")
    get_settings.cache_clear()
    service = PriceLookupService()
    result = ProcurementPriceResult(id="p-3", project_id="project", candidate_id="c-3", service_name="PriceInfoService", item_name="품목")
    error = HTTPError("https://example.invalid/price", 500, "upstream", {}, None)
    with patch("app.services.price_lookup.urlopen", side_effect=error):
        service.execute(result)
    assert result.lookup_status.startswith("조회 실패")


def test_price_lookup_uses_reference_candidate_without_auto_applying(monkeypatch, tmp_path):
    reference = tmp_path / "15_타건물_기계약단가_참고.csv"
    reference.write_text("original_item,standard_item,standard_unit,building,estimate_unit_price,provenance,restriction\n품목,표준품목,M2,공장동,12345,approved-row,타건물 참고\n", encoding="utf-8-sig")
    monkeypatch.setenv("PREPROCESSING_DIR", str(tmp_path))
    monkeypatch.setenv("PRICE_API_URL", "")
    monkeypatch.setenv("PRICE_API_KEY", "")
    get_settings.cache_clear()
    result = PriceLookupService().execute(ProcurementPriceResult(id="p-4", project_id="project", candidate_id="c-4", service_name="PriceInfoService", item_name="품목", unit="M2"))
    assert result.price == 12345
    assert result.lookup_status.startswith("대체자료 적용 후보")
    assert "fallback" in (result.raw_response or "")


def test_official_csv_is_used_before_api(monkeypatch, tmp_path):
    official = tmp_path / "official.csv"
    official.write_text("품명,규격,단위,단가,발표일\n품목,규격A,M2,9876,2026-01-01\n", encoding="utf-8-sig")
    monkeypatch.setenv("PREPROCESSING_DIR", str(tmp_path))
    monkeypatch.setenv("OFFICIAL_PRICE_CSV", str(official))
    monkeypatch.setenv("STANDARD_MARKET_PRICE_CSV", "")
    monkeypatch.setenv("PRICE_API_URL", "https://example.invalid/price")
    monkeypatch.setenv("PRICE_API_KEY", "test-key")
    get_settings.cache_clear()
    result = PriceLookupService().execute(ProcurementPriceResult(id="p-5", project_id="project", candidate_id="c-5", service_name="PriceInfoService", item_name="품목", specification="규격A", unit="M2"))
    assert result.price == 9876
    assert result.lookup_status.startswith("대체자료 적용 후보 - 공식 CSV")
    assert '"api_skipped": true' in (result.raw_response or "")
