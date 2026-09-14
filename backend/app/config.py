from functools import lru_cache
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://cost_review:change-me@localhost:5432/cost_review"
    preprocessing_dir: Path = Path("../../전처리결과_20260908")
    upload_dir: Path = Path("./uploads")
    export_dir: Path = Path("./exports")
    upload_max_bytes: int = 1024 * 1024 * 1024
    upload_pdf_max_bytes: int = 1024 * 1024 * 1024
    upload_dwg_max_bytes: int = 500 * 1024 * 1024
    upload_spreadsheet_max_bytes: int = 200 * 1024 * 1024
    upload_csv_max_bytes: int = 500 * 1024 * 1024
    preprocessing_max_attempts: int = 5
    cors_origins: str = "http://localhost:3000"
    auth_required: bool = False
    price_api_url: str | None = None
    price_api_key: str | None = None
    price_api_service_name: str = "PriceInfoService"
    # 이전 전처리·PoC에서 사용하던 공공데이터포털 변수명을 계속
    # 인식한다. 운영 키를 새 이름으로 복사하거나 DB에 저장할 필요가 없다.
    price_api_operation: str = "getPriceInfoListMrktCnstrctPcBildng"
    official_price_csv: Path | None = None
    standard_market_price_csv: Path | None = None
    # 승인된 타건물 참고단가 CSV. 비어 있으면 기존 전처리 결과 경로를 사용한다.
    price_reference_csv: Path | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def effective_price_api_key(self) -> str | None:
        """현재 변수 우선, 이전 PoC 변수명을 안전하게 보조 인식한다."""
        return self.price_api_key or os.getenv("PUBLIC_DATA_SERVICE_KEY") or None

    @property
    def effective_price_api_url(self) -> str | None:
        """엔드포인트가 생략된 이전 설정에는 PriceInfoService 기본 경로를 사용한다."""
        if self.price_api_url:
            return self.price_api_url
        legacy_url = os.getenv("PUBLIC_DATA_SERVICE_URL")
        if legacy_url:
            return legacy_url
        if self.effective_price_api_key:
            return f"https://apis.data.go.kr/1230000/ao/PriceInfoService/{self.price_api_operation}"
        return None

    def max_upload_bytes_for(self, extension: str) -> int:
        if extension == ".pdf":
            return min(self.upload_max_bytes, self.upload_pdf_max_bytes)
        if extension == ".dwg":
            return min(self.upload_max_bytes, self.upload_dwg_max_bytes)
        if extension in {".xlsx", ".xlsm", ".xls"}:
            return min(self.upload_max_bytes, self.upload_spreadsheet_max_bytes)
        if extension == ".csv":
            return min(self.upload_max_bytes, self.upload_csv_max_bytes)
        return self.upload_max_bytes


@lru_cache
def get_settings() -> Settings:
    return Settings()
