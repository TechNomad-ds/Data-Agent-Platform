"""应用配置 - 基于 Pydantic Settings，从环境变量加载"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/datamind"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/datamind"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50

    # 数据库连接池（按 worker 计算；4 workers * (10 + 5) = 60，低于默认 PostgreSQL 100）
    db_pool_size: int = 10
    db_max_overflow: int = 5

    # JWT
    secret_key: str = "please-change-this-in-production"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # 内置管理员账号（首次启动自动创建）。生产环境务必在 .env 覆盖密码，
    # 切勿把真实密码写进代码或提交到版本库。
    admin_username: str = "admin"
    admin_email: str = "admin@datamind.local"
    admin_password: str = "please-change-this-admin-password"

    def validate_secret_key(self) -> None:
        if self.secret_key == "please-change-this-in-production":
            import warnings
            warnings.warn(
                "⚠️  SECRET_KEY 使用了默认值，请在 .env 中设置安全的随机密钥！"
                "  生成方式: python -c \"import secrets; print(secrets.token_urlsafe(32))\"",
                stacklevel=2,
            )

    def validate_admin_password(self) -> None:
        if self.admin_password == "please-change-this-admin-password":
            import warnings
            warnings.warn(
                "⚠️  ADMIN_PASSWORD 使用了默认值，请在 .env 中设置强密码！"
                "  否则任何知道默认值的人都能登录管理员账号。",
                stacklevel=2,
            )

    # Anthropic API (主 LLM 接口)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = 8192
    enable_extended_thinking: bool = False
    enable_prompt_caching: bool = True

    # 上下文管理（混合 compaction）
    # 历史消息（不含系统提示）的 token 预算：超过则保留最近窗口，
    # 仍超时对更早消息做一次 LLM 总结兜底。
    context_token_budget: int = 60000
    # 无论预算如何，至少完整保留最近这么多轮（user→assistant→tools）的消息
    context_min_recent_messages: int = 6
    # 单条工具结果在写入历史/重建上下文时的截断上限（字符）
    context_tool_result_max_chars: int = 4000
    # 触发 LLM 总结兜底（保留窗口本身仍超预算时）
    context_enable_summary_fallback: bool = True

    # LLM 调用韧性（重试 + 降级）
    # 可重试错误（网络/超时/429/5xx）的最大重试次数（不含首次尝试）
    llm_max_retries: int = 2
    # 指数退避基准秒数：第 n 次重试等待 base * 2^(n-1) 秒
    llm_retry_base_delay: float = 1.0

    # 取数结果自检（对齐 codex completion audit）
    # 默认关闭，避免模型把内部核对过程复述给用户；如需更强取数保守性可用环境变量开启。
    enable_answer_self_check: bool = False

    # 单回合 canonical 持久化的总字符上限（防长任务把单个 JSONB 行撑大、
    # 拖慢下一轮全量历史加载）。超限丢弃更早的工具记录，保住最终答案。
    canonical_max_total_chars: int = 60000

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

    # 并发保护
    max_concurrent_streams_per_user: int = 3
    max_concurrent_streams_global: int = 24
    max_preprocessing_tasks: int = 2
    max_embedding_tasks: int = 2
    max_ocr_tasks: int = 2
    max_graph_tasks: int = 2

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
settings.validate_admin_password()
