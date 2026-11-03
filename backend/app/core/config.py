from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Toda la configuración viene del entorno (.env); no hay secretos en el código."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://radar_app:radar_app@postgres:5432/radar"
    jwt_secret: SecretStr = Field(default=SecretStr(""), min_length=0)
    fernet_key: SecretStr = SecretStr("")
    radar_service_key: SecretStr = SecretStr("")
    frontend_origin: str = "http://localhost:8080"
    tz_ui: str = "America/Lima"

    kev_url: str = (
        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    )
    epss_api_url: str = "https://api.first.org/data/v1/epss"
    epss_csv_url: str = "https://epss.empiricalsecurity.com/epss_scores-current.csv.gz"
    nvd_api_url: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    llm_provider: str = "none"
    llm_model: str = "claude-sonnet-5-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
