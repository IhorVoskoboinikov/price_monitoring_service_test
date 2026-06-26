from pydantic import PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Application ─────────────────────────────────────────
    app_env: str = "dev"
    app_secret_key: str
    debug: bool = False
    run_seed_on_startup: bool = False

    # ── Database ────────────────────────────────────────────
    database_url: PostgresDsn
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ── Redis ───────────────────────────────────────────────
    redis_url: RedisDsn
    redis_ttl_exchange_rate: int = 3600
    redis_ttl_product_prices: int = 3600
    redis_ttl_user_products: int = 300

    # ── Celery ──────────────────────────────────────────────
    celery_broker_url: RedisDsn
    celery_result_backend: RedisDsn
    fetch_prices_interval_hours: int = 4
    check_alerts_interval_minutes: int = 60
    sync_rates_cron_hour: int = 8

    # ── Email ───────────────────────────────────────────────
    # email_enabled=false -> console mode: emails are logged, not sent.
    # The project runs without real SMTP; to send emails set EMAIL_ENABLED=true.
    email_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@pricetracker.com"
    smtp_use_tls: bool = True

    # ── NBU API (Ukraine central bank) ──────────────────────
    nbu_api_url: str = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
    nbu_historical_years: int = 5

    # ── External shop APIs ──────────────────────────────────
    dummyjson_url: str = "https://dummyjson.com"
    fakestore_url: str = "https://fakestoreapi.com"
    shop_api_timeout: int = 10
    shop_api_retry_attempts: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # ignore infra vars (POSTGRES_*, PGADMIN_*)
    )


settings = Settings()
