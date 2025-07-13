from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings.
    """

    GOOGLE_APPLICATION_CREDENTIALS: str
    FIREBASE_PROJECT_ID: str
    GEMINI_API_KEY: str
    REDIS_URL: str

    class Config:
        env_file = ".env"


settings = Settings()
