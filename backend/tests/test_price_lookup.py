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
    # Local demo configuration may point at an explicit reference CSV; this
    # test exercises the legacy preprocessing-directory fallback instead.
    monkeypatch.setenv("PRICE_REFERENCE_CSV", "")
    monkeypatch.setenv("PRICE_API_URL", "")
    monkeypatch.setenv("PRICE_API_KEY", "")
    get_settings.cache_clear()
    result = PriceLookupService().execute(ProcurementPriceResult(id="p-4", project_id="project", candidate_id="c-4", service_name="PriceInfoService", item_name="품목", unit="M2"))
    assert result.price == 12345
    assert result.lookup_status.startswith("대체자료 적용 후보")
    assert "fallback" in (result.raw_response or "")


def test_price_lookup_uses_explicit_reference_csv_path(monkeypatch, tmp_path):
    reference = tmp_path / "approved-reference.csv"
    reference.write_text("original_item,standard_item,standard_unit,building,estimate_unit_price\n품목,표준품목,M2,공장동,54321\n", encoding="utf-8-sig")
    monkeypatch.setenv("PREPROCESSING_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("PRICE_REFERENCE_CSV", str(reference))
    monkeypatch.setenv("PRICE_API_URL", "")
    monkeypatch.setenv("PRICE_API_KEY", "")
    get_settings.cache_clear()
    result = PriceLookupService().execute(ProcurementPriceResult(id="p-4b", project_id="project", candidate_id="c-4b", service_name="PriceInfoService", item_name="품목", unit="M2"))
    assert result.price == 54321
    assert result.lookup_status.startswith("대체자료 적용 후보")


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


def test_cp949_standard_market_csv_uses_total_alias(monkeypatch, tmp_path):
    official = tmp_path / "standard-market.csv"
    official.write_text("발표일,품명,규격,단위,재료비,노무비,경비,합계\n2025-08-04,시스템 판넬,EGI,㎡,0,0,25288,25288\n", encoding="cp949")
    monkeypatch.setenv("PREPROCESSING_DIR", str(tmp_path))
    monkeypatch.setenv("OFFICIAL_PRICE_CSV", str(official))
    monkeypatch.setenv("PRICE_API_URL", "")
    monkeypatch.setenv("PRICE_API_KEY", "")
    monkeypatch.setenv("PUBLIC_DATA_SERVICE_KEY", "")
    get_settings.cache_clear()
    result = PriceLookupService().execute(ProcurementPriceResult(id="p-cp949", project_id="project", candidate_id="c-cp949", service_name="PriceInfoService", item_name="시스템판넬", specification="EGI", unit="㎡"))
    assert result.price == 25288
    assert result.lookup_status.startswith("대체자료 적용 후보 - 공식 CSV")


def test_api_response_preserves_applied_and_component_costs(monkeypatch):
    monkeypatch.setenv("PREPROCESSING_DIR", "missing-preprocessing")
    monkeypatch.setenv("PRICE_REFERENCE_CSV", "")
    monkeypatch.setenv("PRICE_API_URL", "https://example.invalid/price")
    monkeypatch.setenv("PRICE_API_KEY", "test-key")
    get_settings.cache_clear()
    result = ProcurementPriceResult(id="p-6", project_id="project", candidate_id="c-6", service_name="PriceInfoService", item_name="품목", specification="규격A", unit="M2")
    payload = '{"response":{"body":{"items":[{"적용단가":"12,345","재료비":"8,000","노무비":"3,000","경비":"1,345"}]}}}'.encode()
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _limit): return payload
    with patch("app.services.price_lookup.urlopen", return_value=Response()):
        service = PriceLookupService()
        service.execute(result)
    assert result.price == 12345
    assert result.material_cost == 8000
    assert result.labor_cost == 3000
    assert result.expense_cost == 1345
    assert result.lookup_status.startswith("조회 완료")


def test_price_info_service_abbreviated_fields_are_extracted(monkeypatch):
    """실제 PriceInfoService 응답의 축약 필드도 단가로 변환한다."""
    monkeypatch.setenv("PREPROCESSING_DIR", "missing-preprocessing")
    monkeypatch.setenv("PRICE_REFERENCE_CSV", "")
    monkeypatch.setenv("PRICE_API_URL", "https://example.invalid/price")
    monkeypatch.setenv("PRICE_API_KEY", "test-key")
    get_settings.cache_clear()
    result = ProcurementPriceResult(id="p-abbrev", project_id="project", candidate_id="c-abbrev", service_name="PriceInfoService", item_name="시멘트", unit="포")
    payload = '{"response":{"header":{"resultCode":"00"},"body":{"items":[{"prce":"66,900","mtrlcst":"49,404","lbrcst":"17,496","gnrlexpns":"0"}]}}}'.encode()

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _limit): return payload

    with patch("app.services.price_lookup.urlopen", return_value=Response()):
        PriceLookupService().execute(result)
    assert result.price == 66900
    assert result.material_cost == 49404
    assert result.labor_cost == 17496
    assert result.expense_cost == 0
    assert result.lookup_status.startswith("조회 완료")


def test_api_lookup_retries_without_unit_when_first_result_is_empty(monkeypatch):
    monkeypatch.setenv("PREPROCESSING_DIR", "missing-preprocessing")
    monkeypatch.setenv("PRICE_REFERENCE_CSV", "")
    monkeypatch.setenv("PRICE_API_URL", "https://example.invalid/price")
    monkeypatch.setenv("PRICE_API_KEY", "test-key")
    get_settings.cache_clear()
    result = ProcurementPriceResult(id="p-retry", project_id="project", candidate_id="c-retry", service_name="PriceInfoService", item_name="품목", unit="m")
    payloads = [
        '{"response":{"body":{"items":[]}}}'.encode(),
        '{"response":{"body":{"items":[{"적용단가":"9,900"}]}}}'.encode(),
    ]

    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _limit): return self.payload

    with patch("app.services.price_lookup.urlopen", side_effect=[Response(payloads[0]), Response(payloads[1])]) as mocked:
        PriceLookupService().execute(result)
    assert result.price == 9900
    assert mocked.call_count == 2
    assert "unit=m" not in mocked.call_args_list[1].args[0].full_url


def test_legacy_public_data_service_key_uses_price_info_service_default(monkeypatch):
    monkeypatch.setenv("PREPROCESSING_DIR", "missing-preprocessing")
    monkeypatch.setenv("PRICE_REFERENCE_CSV", "")
    monkeypatch.setenv("PRICE_API_URL", "")
    monkeypatch.setenv("PRICE_API_KEY", "")
    monkeypatch.setenv("PUBLIC_DATA_SERVICE_KEY", "legacy-test-key")
    get_settings.cache_clear()
    result = ProcurementPriceResult(id="p-legacy", project_id="project", candidate_id="c-legacy", service_name="PriceInfoService", item_name="품목", unit="M2")
    payload = '{"data":[{"품명":"품목","단위":"M2","합계":"7,500"}]}'.encode()

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _limit): return payload

    with patch("app.services.price_lookup.urlopen", return_value=Response()) as mocked:
        PriceLookupService().execute(result)
    requested_url = mocked.call_args.args[0].full_url
    assert "/1230000/ao/PriceInfoService/getPriceInfoListMrktCnstrctPcBildng" in requested_url
    assert "itemName=%ED%92%88%EB%AA%A9" in requested_url
    assert "unit=M2" in requested_url
    assert "serviceKey=legacy-test-key" in requested_url
    assert result.price == 7500
    assert result.lookup_status.startswith("조회 완료")
