from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    POSTGRES_DSN: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    QUEUE_MAX_SIZE: int = 50000
    RATE_LIMIT_PER_SECOND: int = 500
    LOG_LEVEL: str = "INFO"

settings = Settings()
