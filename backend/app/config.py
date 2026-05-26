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

    # Anthropic API (主 LLM 接口)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = 8192
    enable_extended_thinking: bool = False
    enable_prompt_caching: bool = True

    # 检索配置
    retrieval_mode: str = "hybrid"  # vector | bm25 | hybrid | multi_query
    rrf_k: int = 60
    multi_query_count: int = 3

    # 知识图谱
    graph_auto_extract: bool = True
    graph_max_triples_per_file: int = 50

    # 文件存储
    storage_root: str = "./storage"

    # ChromaDB
    chroma_persist_dir: str = "./chroma_data"

    # 额度
    daily_free_credits: int = 100
    max_credits_per_run: int = 50

    # 服务
    backend_host: str = "0.0.0.0"
    backend_port: int = 8002
    frontend_url: str = "http://localhost:5173"

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"


settings = Settings()
