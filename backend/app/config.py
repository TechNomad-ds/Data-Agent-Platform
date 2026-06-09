"""应用配置 - 基于 Pydantic Settings，从环境变量加载"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/datamind"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/datamind"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    secret_key: str = "your-secret-key-change-in-production"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    def validate_secret_key(self) -> None:
        if self.secret_key == "your-secret-key-change-in-production":
            import warnings
            warnings.warn(
                "⚠️  SECRET_KEY 使用了默认值，请在 .env 中设置安全的随机密钥！"
                "  生成方式: python -c \"import secrets; print(secrets.token_urlsafe(32))\"",
                stacklevel=2,
            )

    # Anthropic API (主 LLM 接口)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = 8192
    enable_extended_thinking: bool = False
    enable_prompt_caching: bool = True

    # OpenAI 兼容接口（备选，当 llm_backend=openai 时使用）
    llm_backend: str = "anthropic"  # anthropic | openai
    openai_api_base: str = ""  # 如 https://api.deepseek.com/v1
    openai_api_key: str = ""
    openai_model: str = ""  # 如 deepseek-chat

    # OCR（PaddleOCR-VL 远程接口，用于 PDF/图片解析）
    # 运行时优先读 Redis（管理后台可改），这里是回退默认值
    ocr_api_base: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    ocr_api_key: str = ""
    ocr_model: str = "PaddleOCR-VL-1.6"

    # 检索配置
    retrieval_mode: str = "hybrid"  # vector | bm25 | hybrid | multi_query
    rrf_k: int = 60
    multi_query_count: int = 3

    # 文件存储
    storage_root: str = "./storage"

    # ChromaDB
    chroma_persist_dir: str = "./chroma_data"

    # 知识图谱
    graph_auto_extract: bool = True
    graph_max_triples_per_file: int = 50

    # 额度
    daily_free_credits: int = 20
    max_credits_per_run: int = 50

    # 资源上限（每用户）
    max_spaces_per_user: int = 20
    max_conversations_per_user: int = 200
    max_files_per_space: int = 50

    # 服务
    backend_host: str = "0.0.0.0"
    backend_port: int = 8002
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = ""  # 逗号分隔的额外允许域名，如 "https://app.example.com,https://admin.example.com"

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"


settings = Settings()
settings.validate_secret_key()
