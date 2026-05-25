"""应用配置 - 基于 Pydantic Settings，从环境变量加载"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/data_agent"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/data_agent"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    secret_key: str = "your-secret-key-change-in-production"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # LLM API 中转站
    llm_api_base_url: str = "https://api.example.com/v1"
    llm_api_key: str = "sk-your-api-key"
    llm_default_model: str = "gpt-4o"

    # 文件存储
    storage_root: str = "./storage"

    # ChromaDB
    chroma_persist_dir: str = "./chroma_data"

    # 额度
    daily_free_credits: int = 100
    max_credits_per_run: int = 50

    # 服务
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:5173"

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"


settings = Settings()
