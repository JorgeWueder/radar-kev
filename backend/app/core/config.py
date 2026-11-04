from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Toda la configuración viene del entorno (.env); no hay secretos en el código."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    enable_docs: bool = True  # Swagger/ReDoc en desarrollo
    enable_docs_explicit: bool = False  # ENABLE_DOCS_EXPLICIT=true los habilita también en producción
    database_url: str = "postgresql+psycopg://radar_app:radar_app@postgres:5432/radar"
    jwt_secret: SecretStr = Field(default=SecretStr(""), min_length=0)
    fernet_key: SecretStr = SecretStr("")
    radar_service_key: SecretStr = SecretStr("")
    frontend_origin: str = "http://localhost:8080"
    tz_ui: str = "America/Lima"
    trust_proxy_headers: bool = False
    seed_on_start: bool = False
    seed_demo_password: SecretStr = SecretStr("")

    kev_url: str = (
        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    )
    epss_api_url: str = "https://api.first.org/data/v1/epss"
    epss_csv_url: str = "https://epss.empiricalsecurity.com/epss_scores-current.csv.gz"
    nvd_api_url: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    app_url: str = "http://localhost:8080"
    n8n_webhook_url: str = "http://n8n:5678/webhook/radar-manual"
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "radar@localhost"
    alert_email_to: str = ""
    alert_webhook_url: SecretStr = SecretStr("")

    llm_provider: str = "ollama"  # ollama | anthropic | openai | none
    llm_model: str = "qwen2.5:3b"
    llm_timeout: int = 120
    llm_concurrency: int = 0  # 0 = automático: 1 con Ollama (una GPU), 4 con proveedores en la nube
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    ollama_base_url: str = "http://ollama:11434"
    langflow_url: str = "http://langflow:7860"
    langflow_superuser: str = ""
    langflow_superuser_password: SecretStr = SecretStr("")
    langflow_api_key: SecretStr = SecretStr("")
    langflow_enrich_flow: str = "ticket-enrichment"


@lru_cache
def get_settings() -> Settings:
    return Settings()
