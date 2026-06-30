"""连接管理器 + 入站调度 (backend/app/channels/manager.py)

IMPORTANT — 部署约束: 必须作为单一进程运行，不能在每个 gunicorn worker 各起一份。
  原因：每个已配置的 IM app 对应一条常驻出站连接（WSS / HTTP 长轮询）。
  若多个 worker 并发运行，同一条消息会被多次处理、credits 多次扣除。

  解决方案（主控/部署层，本模块不负责）:
    · 推荐：独立容器 / 独立进程：python -m app.channels.manager
      （调用本文件底部的 run_manager() 入口）
    · 或：gunicorn post_fork 只在 worker 0 里调 asyncio.run(_run_manager_async())
    · enable/disable 通过 REST API → start_one/stop_one
      （主进程把请求转发到 manager 进程可用 Redis Pub/Sub 或 UNIX socket）

对外暴露:
  ChannelManager          — 进程级单例，生命周期管理
  Dispatcher              — 入站消息分发器（可注入依赖，便于隔离单测）
  ChannelConfigSnapshot   — dispatch 所需的配置快照（无 SQLAlchemy 对象）
  run_manager()           — 独立进程入口
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, ClassVar, Optional, Protocol

from app.channels.bridge import AgentBridge
from app.channels.contracts import ChannelAdapter, InboundMessage, OutboundMessage
from app.channels.pairing import PairingService

logger = logging.getLogger(__name__)

# 未配置 default_model 时的全局后备模型
_FALLBACK_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 值对象：dispatch 所需的渠道配置快照（不含 SQLAlchemy Row）
# ---------------------------------------------------------------------------

@dataclass
class ChannelConfigSnapshot:
    """轻量渠道配置快照，不引用任何 ORM 对象。"""
    user_id: uuid.UUID
    channel: str
    default_data_space_id: Optional[uuid.UUID]
    default_model: str


# ---------------------------------------------------------------------------
# Protocol: IdentityRepo — 外部身份 + 渠道配置查询
# ---------------------------------------------------------------------------

class IdentityRepo(Protocol):
    """外部身份与渠道配置查询契约；可内存实现（测试）或 DB 实现（生产）。"""

    async def find_user_id(
        self, channel: str, platform_user_id: str
    ) -> Optional[uuid.UUID]:
        """返回已绑定的内部 user_id；未绑定返回 None。"""
        ...

    async def get_channel_config(
        self, user_id: uuid.UUID, channel: str
    ) -> Optional[ChannelConfigSnapshot]:
        """返回该用户的渠道配置快照；未配置返回 None。"""
        ...

    async def set_default_space(
        self, user_id: uuid.UUID, channel: str, space_id: uuid.UUID
    ) -> None:
        """更新用户该渠道的默认数据空间。"""
        ...


# ---------------------------------------------------------------------------
# Protocol: ConversationRepo — 会话查找 / 创建 / 消息落库
# ---------------------------------------------------------------------------

class ConversationRepo(Protocol):
    """会话管理契约；可内存实现（测试）或 DB 实现（生产）。"""

    async def find_or_create(
        self,
        user_id: uuid.UUID,
        channel: str,
        chat_id: str,
        default_space_id: Optional[uuid.UUID],
        default_model: str,
    ) -> uuid.UUID:
        """返回现有会话 ID（按 channel+chat_id 滚动复用），不存在则新建。"""
        ...

    async def create_new(
        self,
        user_id: uuid.UUID,
        channel: str,
        chat_id: str,
        default_space_id: Optional[uuid.UUID],
        default_model: str,
    ) -> uuid.UUID:
        """/new 命令：强制新建会话（旧会话保留不动）。"""
        ...

    async def save_messages(
        self,
        conv_id: uuid.UUID,
        user_text: str,
        assistant_text: str,
    ) -> None:
        """落库 user + assistant 两条消息（仿 routers/chat.py 写法）。"""
        ...


# ---------------------------------------------------------------------------
# Dispatcher — 入站调度核心（依赖注入，无 DB / 无真实 LLM 依赖）
# ---------------------------------------------------------------------------

class Dispatcher:
    """入站消息分发器。

    路由逻辑（参考 同类引擎 orchestrator.rs handle_message / action.rs）:
      1. external_identities 查 (channel, platform_user_id) → user_id
      2. 未绑定 → PairingService.issue() → adapter.send("配对码 XXXXXX")
      3. 已绑定 →
           /new   → 新建会话 + 回复"已开启新对话"
           /space <uuid> → 更新默认空间 + 回复确认
           其他   → find_or_create 会话 → AgentLoop.run() → AgentBridge.run_and_reply()
                    → save_messages 落库
    """

    def __init__(
        self,
        *,
        identity_repo: IdentityRepo,
        conversation_repo: ConversationRepo,
        pairing_service: PairingService,
        agent_factory: Callable[[], Any],
        bridge: Optional[AgentBridge] = None,
    ) -> None:
        self._identity = identity_repo
        self._convs = conversation_repo
        self._pairing = pairing_service
        self._agent_factory = agent_factory
        self._bridge = bridge or AgentBridge()

    async def _ingest_attachments(
        self,
        adapter: ChannelAdapter,
        inbound: InboundMessage,
        user_id: uuid.UUID,
        space_id: Optional[uuid.UUID],
    ) -> None:
        """下载入站附件并入库到默认数据空间，统一回告用户。任意渠道共用。"""
        chat_id = inbound.chat_id
        if space_id is None:
            await adapter.send(chat_id, OutboundMessage(
                text="请先在网页端为该渠道设置「默认数据空间」，再发送文件/图片。",
                is_final=True))
            return
        download = getattr(adapter, "download_attachment", None)
        if download is None:
            await adapter.send(chat_id, OutboundMessage(
                text="当前渠道暂不支持接收文件/图片。", is_final=True))
            return
        try:
            files = [
                (att.name, await download(att))
                for att in inbound.attachments
            ]
        except Exception as exc:
            logger.exception("attachment download failed: channel=%s: %s", inbound.channel, exc)
            await adapter.send(chat_id, OutboundMessage(
                text=f"文件下载失败：{exc}", is_final=True))
            return
        from app.services.channel_ingest import ingest_files_to_space
        ingested = await ingest_files_to_space(user_id, space_id, files)
        names = "、".join(f["filename"] for f in ingested)
        await adapter.send(chat_id, OutboundMessage(
            text=f"已导入 {len(ingested)} 个文件到数据空间：{names}\n"
                 f"正在解析索引，稍后即可直接提问分析。", is_final=True))

    async def _ingest_feishu_links(
        self,
        adapter: ChannelAdapter,
        inbound: InboundMessage,
        user_id: uuid.UUID,
        space_id: Optional[uuid.UUID],
    ) -> None:
        """抓取消息里的飞书云文档链接并入库。飞书文档需飞书 token，与消息来自哪个渠道无关：
        来自飞书渠道则复用在线 adapter；其他渠道（如微信）则用用户配置的飞书应用凭据临时构造抓取器。"""
        chat_id = inbound.chat_id
        if space_id is None:
            await adapter.send(chat_id, OutboundMessage(
                text="请先在网页端为该渠道设置「默认数据空间」，再分享文档。", is_final=True))
            return
        from app.services.feishu_doc import try_ingest_feishu_doc, FeishuDocError

        transient = None
        if inbound.channel == "feishu":
            fetcher: Any = adapter  # 在线飞书 adapter，自带有效 token
        else:
            # 非飞书渠道发飞书链接：用用户自己的飞书应用凭据抓取（同一账号配的飞书 app）
            from app.channels import store
            result = await store.get_config(user_id, "feishu")
            if result is None or not result[0].credentials_encrypted:
                await adapter.send(chat_id, OutboundMessage(
                    text="要解析飞书文档，请先在「远程连接」里配置并连接你的飞书应用。",
                    is_final=True))
                return
            _cfg, creds = result  # get_config 返回的 creds 已解密
            from app.channels.adapters.feishu import FeishuAdapter
            try:
                fetcher = FeishuAdapter(app_id=creds["app_id"], app_secret=creds["app_secret"])
            except Exception as exc:
                await adapter.send(chat_id, OutboundMessage(
                    text=f"飞书凭据无效：{exc}", is_final=True))
                return
            transient = fetcher

        try:
            ingested = await try_ingest_feishu_doc(fetcher, inbound, user_id, space_id)
        except FeishuDocError as exc:
            await adapter.send(chat_id, OutboundMessage(text=f"文档拉取失败：{exc}", is_final=True))
            return
        except Exception as exc:
            logger.exception("feishu doc ingest failed: %s", exc)
            await adapter.send(chat_id, OutboundMessage(
                text=f"文档拉取失败：{exc}\n（请确认该文档已授权给你的飞书应用、且应用已开通云文档读权限）",
                is_final=True))
            return
        finally:
            if transient is not None:
                try:
                    await transient._http.aclose()
                except Exception:
                    pass

        names = "、".join(f["filename"] for f in ingested)
        await adapter.send(chat_id, OutboundMessage(
            text=f"已导入 {len(ingested)} 个文件到数据空间：{names}\n"
                 f"正在解析索引，稍后即可直接提问分析。", is_final=True))

    async def dispatch(self, adapter: ChannelAdapter, inbound: InboundMessage) -> None:
        """分发一条入站消息。遇不可恢复错误 raise（禁 fallback 兜底）。

        agent 执行异常会先向渠道发错误消息，再 re-raise。
        """
        channel = inbound.channel
        platform_user_id = inbound.platform_user_id
        chat_id = inbound.chat_id
        text = inbound.text.strip()

        # ── Step 1: 查身份 ──────────────────────────────────────────────
        user_id = await self._identity.find_user_id(channel, platform_user_id)

        if user_id is None:
            # ── Step 2: 未绑定 → 签发配对码 ────────────────────────────
            code = await self._pairing.issue(channel, platform_user_id)
            await adapter.send(
                chat_id,
                OutboundMessage(text=f"请在网页端输入配对码 {code} 绑定", is_final=True),
            )
            logger.info(
                "pairing code issued: channel=%s platform_user=%s code=%s",
                channel, platform_user_id, code,
            )
            return

        # ── Step 3: 已绑定 → 获取渠道配置 ──────────────────────────────
        cfg = await self._identity.get_channel_config(user_id, channel)
        space_id = cfg.default_data_space_id if cfg else None
        model_id = (cfg.default_model if cfg else None) or _FALLBACK_MODEL

        # ── Step 3·附件: 文件/图片 → 抓取并入库（任意渠道，统一路径）────────
        if inbound.attachments:
            await self._ingest_attachments(adapter, inbound, user_id, space_id)
            return

        # ── Step 3a: 命令处理 ────────────────────────────────────────────
        if text == "/new":
            await self._convs.create_new(user_id, channel, chat_id, space_id, model_id)
            await adapter.send(
                chat_id,
                OutboundMessage(text="已开启新对话", is_final=True),
            )
            logger.info("new conversation created: user=%s channel=%s chat=%s", user_id, channel, chat_id)
            return

        if text.startswith("/space"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                await adapter.send(
                    chat_id,
                    OutboundMessage(text="用法：/space <数据空间ID>", is_final=True),
                )
                return
            raw_id = parts[1].strip()
            try:
                new_space_id = uuid.UUID(raw_id)
            except ValueError:
                await adapter.send(
                    chat_id,
                    OutboundMessage(text=f"无效的数据空间 ID：{raw_id}", is_final=True),
                )
                return
            await self._identity.set_default_space(user_id, channel, new_space_id)
            await adapter.send(
                chat_id,
                OutboundMessage(text=f"已切换默认数据空间为 {new_space_id}", is_final=True),
            )
            logger.info("default space updated: user=%s channel=%s space=%s", user_id, channel, new_space_id)
            return

        # ── Step 3c: 飞书云文档链接 → 抓取并入库（任意渠道，用用户配置的飞书凭据）──
        from app.services.feishu_doc import extract_feishu_doc_links
        if extract_feishu_doc_links(text):
            await self._ingest_feishu_links(adapter, inbound, user_id, space_id)
            return

        # ── Step 3b: 普通消息 → agent 处理 ──────────────────────────────
        conv_id = await self._convs.find_or_create(
            user_id, channel, chat_id, space_id, model_id
        )

        agent = self._agent_factory()
        try:
            events: AsyncGenerator[dict[str, Any], None] = agent.run(
                conversation_id=conv_id,
                user_id=user_id,
                data_space_id=space_id,
                model_id=model_id,
                user_message=text,
                is_admin=False,
            )
            final = await self._bridge.run_and_reply(adapter, chat_id, events)
        except Exception as exc:
            logger.exception(
                "Agent error: conv=%s user=%s channel=%s: %s",
                conv_id, user_id, channel, exc,
            )
            # 发错误通知给用户，再 re-raise（禁止静默吞掉）
            try:
                await adapter.send(
                    chat_id,
                    OutboundMessage(text=f"执行出错：{exc}", is_final=True),
                )
            except Exception:
                pass
            raise

        # ── 落库 user + assistant 消息（仿 routers/chat.py）────────────
        try:
            await self._convs.save_messages(conv_id, text, final.text)
        except Exception as exc:
            # 消息保存失败不影响已回复的用户，但 log 出来
            logger.error("save_messages failed: conv=%s: %s", conv_id, exc)


# ---------------------------------------------------------------------------
# DB-backed IdentityRepo 实现（懒加载：仅在生产路径实例化时 import）
# ---------------------------------------------------------------------------

class _DbIdentityRepo:
    """生产用：查 external_identities + channel_configs 表（SQLAlchemy 异步）。"""

    async def find_user_id(
        self, channel: str, platform_user_id: str
    ) -> Optional[uuid.UUID]:
        # 懒加载，避免 module 级触发 DB 初始化
        from sqlalchemy import select
        from app.core.database import get_session_factory
        from app.models.external_identity import ExternalIdentity

        async with get_session_factory()() as db:
            result = await db.execute(
                select(ExternalIdentity.user_id).where(
                    ExternalIdentity.channel == channel,
                    ExternalIdentity.platform_user_id == platform_user_id,
                )
            )
            return result.scalar_one_or_none()

    async def get_channel_config(
        self, user_id: uuid.UUID, channel: str
    ) -> Optional[ChannelConfigSnapshot]:
        from sqlalchemy import select
        from app.core.database import get_session_factory
        from app.models.channel_config import ChannelConfig

        async with get_session_factory()() as db:
            result = await db.execute(
                select(ChannelConfig).where(
                    ChannelConfig.user_id == user_id,
                    ChannelConfig.channel == channel,
                )
            )
            cfg = result.scalar_one_or_none()
            if cfg is None:
                return None
            return ChannelConfigSnapshot(
                user_id=user_id,
                channel=channel,
                default_data_space_id=cfg.default_data_space_id,
                default_model=cfg.default_model or _FALLBACK_MODEL,
            )

    async def set_default_space(
        self, user_id: uuid.UUID, channel: str, space_id: uuid.UUID
    ) -> None:
        from datetime import datetime, timezone
        from sqlalchemy import select
        from app.core.database import get_session_factory
        from app.models.channel_config import ChannelConfig

        async with get_session_factory()() as db:
            result = await db.execute(
                select(ChannelConfig).where(
                    ChannelConfig.user_id == user_id,
                    ChannelConfig.channel == channel,
                )
            )
            cfg = result.scalar_one_or_none()
            if cfg is None:
                raise RuntimeError(
                    f"channel_config not found: user={user_id} channel={channel}"
                )
            cfg.default_data_space_id = space_id
            cfg.updated_at = datetime.now(timezone.utc)
            await db.commit()


# ---------------------------------------------------------------------------
# DB-backed ConversationRepo 实现
# ---------------------------------------------------------------------------

class _DbConversationRepo:
    """生产用：查 / 建 conversations + messages 表（SQLAlchemy 异步）。"""

    async def find_or_create(
        self,
        user_id: uuid.UUID,
        channel: str,
        chat_id: str,
        default_space_id: Optional[uuid.UUID],
        default_model: str,
    ) -> uuid.UUID:
        from sqlalchemy import select
        from app.core.database import get_session_factory
        from app.models.conversation import Conversation

        async with get_session_factory()() as db:
            result = await db.execute(
                select(Conversation)
                .where(
                    Conversation.user_id == user_id,
                    Conversation.channel == channel,
                    Conversation.channel_thread_id == chat_id,
                )
                .order_by(Conversation.created_at.desc())
                .limit(1)
            )
            conv = result.scalar_one_or_none()
            if conv is not None:
                return conv.id

            conv = Conversation(
                user_id=user_id,
                channel=channel,
                channel_thread_id=chat_id,
                data_space_id=default_space_id,
                model_id=default_model,
                title="渠道对话",
            )
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
            return conv.id

    async def create_new(
        self,
        user_id: uuid.UUID,
        channel: str,
        chat_id: str,
        default_space_id: Optional[uuid.UUID],
        default_model: str,
    ) -> uuid.UUID:
        from app.core.database import get_session_factory
        from app.models.conversation import Conversation

        async with get_session_factory()() as db:
            conv = Conversation(
                user_id=user_id,
                channel=channel,
                channel_thread_id=chat_id,
                data_space_id=default_space_id,
                model_id=default_model,
                title="渠道对话（新）",
            )
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
            return conv.id

    async def save_messages(
        self,
        conv_id: uuid.UUID,
        user_text: str,
        assistant_text: str,
    ) -> None:
        from app.core.database import get_session_factory
        from app.models.conversation import Message

        async with get_session_factory()() as db:
            db.add(Message(conversation_id=conv_id, role="user", content=user_text))
            db.add(Message(conversation_id=conv_id, role="assistant", content=assistant_text))
            await db.commit()


# ---------------------------------------------------------------------------
# 列出所有已启用的渠道配置（跨所有用户）
# ---------------------------------------------------------------------------

async def _list_all_enabled_configs() -> list[tuple[Any, dict]]:
    """从 DB 读取所有 enabled=True 的 ChannelConfig，返回 [(cfg, creds_dict)]。"""
    from sqlalchemy import select
    from app.core.database import get_session_factory
    from app.models.channel_config import ChannelConfig
    from app.channels import store

    async with get_session_factory()() as db:
        result = await db.execute(
            select(ChannelConfig).where(ChannelConfig.enabled.is_(True))
        )
        configs = list(result.scalars().all())

    out = []
    for cfg in configs:
        if not cfg.credentials_encrypted:
            logger.warning(
                "channel_config %s (user=%s channel=%s) enabled but no credentials, skipping",
                cfg.id, cfg.user_id, cfg.channel,
            )
            continue
        try:
            creds = store.decrypt_creds(cfg.credentials_encrypted)
        except Exception as exc:
            logger.error(
                "failed to decrypt credentials for channel_config %s: %s, skipping",
                cfg.id, exc,
            )
            continue
        out.append((cfg, creds))
    return out


# ---------------------------------------------------------------------------
# Adapter 工厂（懒加载 adapter 模块，避免 httpx/websockets 在测试时被 import）
# ---------------------------------------------------------------------------

def _make_adapter(channel: str, creds: dict) -> Any:
    """根据渠道名称和凭据字典实例化对应的 adapter。未知渠道 raise ValueError。"""
    if channel == "feishu":
        from app.channels.adapters.feishu import FeishuAdapter
        return FeishuAdapter(
            app_id=creds["app_id"],
            app_secret=creds["app_secret"],
        )
    if channel == "weixin":
        from app.channels.adapters.weixin import WeixinAdapter
        return WeixinAdapter(
            bot_token=creds["bot_token"],
            account_id=creds["account_id"],
        )
    raise ValueError(f"未知渠道：{channel!r}，不知道如何构造 adapter")


# ---------------------------------------------------------------------------
# ChannelManager — 进程级单例
# ---------------------------------------------------------------------------

class ChannelManager:
    """连接管理器：为每个已启用的渠道配置持有一条常驻出站连接。

    IMPORTANT: 必须在单一进程中运行，见模块级文档字符串。

    生产初始化流程:
      manager = await ChannelManager.create()  # 读 DB、加载全部 enabled 配置
      await manager.start_all()                # 逐一 start() 各 adapter

    用户 enable/disable 渠道时:
      await manager.start_one(user_id, channel)
      await manager.stop_one(user_id, channel)
    """

    _instance: ClassVar[Optional["ChannelManager"]] = None

    def __init__(self, dispatcher: Dispatcher) -> None:
        self._dispatcher = dispatcher
        # key = f"{user_id}:{channel}"  value = (adapter, asyncio.Task)
        self._adapters: dict[str, tuple[Any, asyncio.Task]] = {}  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # 单例获取
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "ChannelManager":
        """获取进程级单例。未初始化时 raise RuntimeError。"""
        if cls._instance is None:
            raise RuntimeError(
                "ChannelManager 尚未初始化，请先调用 await ChannelManager.create()"
            )
        return cls._instance

    # ------------------------------------------------------------------
    # 工厂：初始化 DB 依赖并设置单例
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls) -> "ChannelManager":
        """工厂方法：构造 DB-backed Dispatcher，设置单例并返回实例。

        调用前确保 app.core.database.get_session_factory() 已可用。
        """
        from app.agent.loop import AgentLoop

        identity_repo = _DbIdentityRepo()
        conversation_repo = _DbConversationRepo()
        pairing_store = _load_pairing_store()
        pairing_service = PairingService(pairing_store)
        agent_factory: Callable[[], Any] = lambda: AgentLoop(abort_check=lambda: False)
        bridge = AgentBridge()

        dispatcher = Dispatcher(
            identity_repo=identity_repo,
            conversation_repo=conversation_repo,
            pairing_service=pairing_service,
            agent_factory=agent_factory,
            bridge=bridge,
        )
        instance = cls(dispatcher)
        cls._instance = instance
        return instance

    # ------------------------------------------------------------------
    # 批量启动
    # ------------------------------------------------------------------

    async def start_all(self) -> None:
        """从 DB 读取所有 enabled 配置并逐一启动 adapter。"""
        configs = await _list_all_enabled_configs()
        logger.info("start_all: found %d enabled channel configs", len(configs))

        async def _safe_start(cfg: Any, creds: dict) -> None:
            # 每条独立 try/except，保留逐渠道的容错隔离与日志上下文。
            try:
                await self._start(cfg.user_id, cfg.channel, creds)
            except Exception as exc:
                logger.error(
                    "failed to start adapter user=%s channel=%s: %s",
                    cfg.user_id, cfg.channel, exc,
                )

        # 各渠道启动相互独立（含独立的 set_connected DB 写），并发启动避免逐条串行阻塞。
        await asyncio.gather(*(_safe_start(cfg, creds) for cfg, creds in configs))

    # ------------------------------------------------------------------
    # 单条启动 / 停止（供 REST API 调用）
    # ------------------------------------------------------------------

    async def start_one(self, user_id: uuid.UUID, channel: str) -> None:
        """启动指定用户 + 渠道的 adapter（先从 DB 读配置）。

        若已在运行则先停止再重启（凭据可能已更新）。
        """
        # 读最新配置（复用 store 的取配置 + 解密逻辑）
        from app.channels import store

        result = await store.get_config(user_id, channel)
        if result is None or not result[0].credentials_encrypted:
            raise RuntimeError(
                f"channel_config not found or has no credentials: user={user_id} channel={channel}"
            )
        _cfg, creds = result

        # 若已运行则停掉
        key = _adapter_key(user_id, channel)
        if key in self._adapters:
            await self.stop_one(user_id, channel)

        await self._start(user_id, channel, creds)

    async def stop_one(self, user_id: uuid.UUID, channel: str) -> None:
        """优雅停止指定 adapter；不存在时 no-op。"""
        key = _adapter_key(user_id, channel)
        entry = self._adapters.pop(key, None)
        if entry is None:
            return
        adapter, task = entry
        try:
            await adapter.stop()
        except Exception as exc:
            logger.warning("error stopping adapter %s: %s", key, exc)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("adapter stopped: %s", key)

    async def stop_all(self) -> None:
        """停止所有正在运行的 adapter（进程关闭时调用）。"""
        keys = list(self._adapters.keys())
        for key in keys:
            try:
                uid_str, ch = key.split(":", 1)
                await self.stop_one(uuid.UUID(uid_str), ch)
            except Exception as exc:
                logger.warning("error stopping adapter %s: %s", key, exc)

    # ------------------------------------------------------------------
    # 内部启动
    # ------------------------------------------------------------------

    async def _start(
        self, user_id: uuid.UUID, channel: str, creds: dict
    ) -> None:
        """实例化 adapter 并在后台 Task 中 start()，注册到 self._adapters。"""
        adapter = _make_adapter(channel, creds)
        dispatcher = self._dispatcher

        async def _on_message(inbound: InboundMessage) -> None:
            """每条入站消息的回调：在独立 Task 里分发，不阻塞 adapter 收消息。"""
            asyncio.create_task(
                _safe_dispatch(dispatcher, adapter, inbound),
                name=f"dispatch:{channel}:{inbound.chat_id}",
            )

        # adapter.start() 本身是非阻塞的（内部 create_task）
        await adapter.start(_on_message)

        # 保持一个哨兵 Task 以便后续 cancel
        sentinel = asyncio.create_task(asyncio.Event().wait(), name=f"sentinel:{channel}")

        key = _adapter_key(user_id, channel)
        self._adapters[key] = (adapter, sentinel)

        # 回写 connected=True
        try:
            from app.channels.store import set_connected
            await set_connected(user_id, channel, connected=True)
        except Exception as exc:
            logger.warning("set_connected failed for %s: %s", key, exc)

        logger.info("adapter started: %s", key)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _adapter_key(user_id: uuid.UUID, channel: str) -> str:
    return f"{user_id}:{channel}"


async def _safe_dispatch(
    dispatcher: Dispatcher, adapter: ChannelAdapter, inbound: InboundMessage
) -> None:
    """顶层 dispatch wrapper：捕获所有未处理异常，只 log 不 crash。"""
    try:
        await dispatcher.dispatch(adapter, inbound)
    except Exception as exc:
        logger.exception(
            "unhandled error dispatching message: channel=%s user=%s chat=%s: %s",
            inbound.channel, inbound.platform_user_id, inbound.chat_id, exc,
        )


def _load_pairing_store():
    """配对码 store：Redis 共享（manager 进程出码、web worker 审批必须同一份）。"""
    from app.channels.pairing import RedisPairingStore
    return RedisPairingStore()


# ---------------------------------------------------------------------------
# 独立进程入口
# ---------------------------------------------------------------------------

async def _run_manager_async() -> None:
    """连接管理进程主循环（独立进程里运行，不在 gunicorn worker 里）。"""
    import signal as _signal

    logging.basicConfig(level=logging.INFO)
    logger.info("ChannelManager process starting")

    manager = await ChannelManager.create()
    await manager.start_all()
    logger.info("ChannelManager ready; waiting for stop signal")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (_signal.SIGTERM, _signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows 不支持 add_signal_handler

    await stop_event.wait()
    logger.info("ChannelManager shutting down")
    await manager.stop_all()
    logger.info("ChannelManager stopped")


def run_manager() -> None:
    """独立进程入口点。

    用法:
      python -m app.channels.manager          # 直接运行
      或在 Dockerfile CMD / supervisord 里调

    必须在单一进程中运行（见模块级文档字符串）。
    """
    asyncio.run(_run_manager_async())


if __name__ == "__main__":
    run_manager()
