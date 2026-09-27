from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://eve:eve@localhost:5432/eve"

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    bcrypt_rounds: int = 12

    # shared secret with the (simulated) payment provider, used to sign webhooks
    webhook_secret: str = "whsec_dev"

    # used by POST /payments/ when the client doesn't force an outcome
    payment_success_rate: float = 0.8

    log_level: str = "INFO"


settings = Settings()
