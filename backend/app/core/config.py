from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://meridian:meridian@localhost:5432/meridian"
    SYNC_DATABASE_URL: str = "postgresql://meridian:meridian@localhost:5432/meridian"
    API_PREFIX: str = "/api/v1"

    class Config:
        env_file = ".env"


settings = Settings()
