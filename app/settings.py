from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 서버 간 인증 토큰 등 추후 추가 예정
    ALLOWED_ORIGINS: str = "*"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
