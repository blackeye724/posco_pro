from functools import lru_cache
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
    official_price_csv: Path | None = None
    standard_market_price_csv: Path | None = None
    # 승인된 타건물 참고단가 CSV. 비어 있으면 기존 전처리 결과 경로를 사용한다.
    price_reference_csv: Path | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
