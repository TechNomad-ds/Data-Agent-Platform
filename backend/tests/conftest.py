"""测试基础设施 — SQLite 内存数据库 + Mock Redis + 认证 Helper

策略：不 monkey-patch SQLAlchemy 类型。而是用 PostgreSQL 方言的 SQLite 引擎，
通过 render_as_literal / compile 钩子让 SQLite 接受 UUID 和 JSONB。
更简单的做法：直接用 SQLAlchemy 的 create_all 让它自动映射。
"""
import asyncio
import os
import sys
import uuid
from collections import defaultdict
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import event, create_engine, text, String, JSON
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# 设置环境变量，让 app 使用 SQLite 而不是 PostgreSQL
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["DATABASE_URL_SYNC"] = "sqlite://"
os.environ["REDIS_URL"] = "redis://fake:6379/0"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["ANTHROPIC_API_KEY"] = "sk-test-fake"
os.environ["STORAGE_ROOT"] = "/tmp/datamind_test_storage"

# 现在导入 app — 需要处理 PostgreSQL 类型在 SQLite 上的兼容性
# 方法：在 SQLAlchemy 中注册 PostgreSQL 类型到 SQLite 的编译规则
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import TypeDecorator, CHAR


@compiles(PG_UUID, "sqlite")
def compile_pg_uuid(element, compiler, **kw):
    return "VARCHAR(36)"


@compiles(PG_JSONB, "sqlite")
def compile_pg_jsonb(element, compiler, **kw):
    return "JSON"


# SQLite 下 UUID 比较需要把 uuid.UUID 对象转为字符串
import sqlalchemy.dialects.postgresql as pg_dialect

_orig_uuid_bind_processor = PG_UUID.bind_processor


def _patched_uuid_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return None
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(value)
        return process
    return _orig_uuid_bind_processor(self, dialect)


PG_UUID.bind_processor = _patched_uuid_bind_processor


_orig_uuid_result_processor = PG_UUID.result_processor


def _patched_uuid_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return None
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(str(value)) if value else None
        return process
    return _orig_uuid_result_processor(self, dialect, coltype)


PG_UUID.result_processor = _patched_uuid_result_processor


from app.core.database import Base, get_db
from app.main import app
from app.core import redis_client


# ── 测试数据库引擎（SQLite 内存） ──────────────────────

TEST_DB_URL = "sqlite+aiosqlite://"

_test_engine = create_async_engine(TEST_DB_URL, echo=False)
_test_session_factory = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(_test_engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ── Mock Redis ──────────────────────────────────────

class FakeRedis:
    def __init__(self):
        self._store = {}
        self._sorted_sets = defaultdict(dict)

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, **kwargs):
        self._store[key] = value

    async def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)

    async def ping(self):
        return True

    def pipeline(self):
        return FakePipeline(self)

    async def close(self):
        pass


class FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._results = []

    def zremrangebyscore(self, key, min_val, max_val):
        self._results.append(0)
        return self

    def zadd(self, key, mapping):
        self._redis._sorted_sets[key].update(mapping)
        self._results.append(1)
        return self

    def zcard(self, key):
        self._results.append(len(self._redis._sorted_sets.get(key, {})))
        return self

    def expire(self, key, ttl):
        self._results.append(True)
        return self

    async def execute(self):
        return self._results


_fake_redis = FakeRedis()


async def _get_fake_redis():
    return _fake_redis


# ── Fixtures ──────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    os.makedirs("/tmp/datamind_test_storage", exist_ok=True)
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with _test_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    original_get_redis = redis_client.get_redis
    redis_client.get_redis = _get_fake_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    redis_client.get_redis = original_get_redis


# ── 认证 Helper ──────────────────────────────────

async def register_user(client: AsyncClient, email=None, username=None, password="Test123456"):
    email = email or f"test_{uuid.uuid4().hex[:8]}@example.com"
    username = username or f"user_{uuid.uuid4().hex[:8]}"
    return await client.post("/api/auth/register", json={
        "email": email, "username": username, "password": password,
    })


async def login_user(client: AsyncClient, email: str, password="Test123456"):
    return await client.post("/api/auth/login", json={
        "email": email, "password": password,
    })


async def get_auth_headers(client: AsyncClient, email=None, password="Test123456"):
    email = email or f"test_{uuid.uuid4().hex[:8]}@example.com"
    await register_user(client, email=email, password=password)
    login_res = await login_user(client, email=email, password=password)
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email
