from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GROQ_API_KEY: str
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    POSTGRES_URL: str = "postgresql://admin:password123@localhost:5432/financial_db"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
