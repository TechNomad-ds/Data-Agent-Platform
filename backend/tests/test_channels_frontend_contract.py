"""
Frontend-contract unit tests for the channel integration.

These tests validate the JSON/SSE shapes that the frontend (channels.ts) expects
from the backend.  They cover pure parsing/encoding logic only — no DB, no network.

Run:
    cd backend && python3 -m pytest tests/test_channels_frontend_contract.py -q --noconftest
"""
import asyncio
import json
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field, ValidationError
import pytest


# ─────────────────────────────────────────────────────────────────
# Models that mirror the TypeScript types in api/channels.ts
# ─────────────────────────────────────────────────────────────────

class ChannelStatus(BaseModel):
    id: Literal['lark', 'dingtalk', 'weixin']
    enabled: bool
    connected: bool
    has_credentials: bool


class PairingRequest(BaseModel):
    code: str
    platform: Literal['lark', 'dingtalk', 'weixin']
    platform_user_id: str
    platform_username: str
    expires_at: str  # ISO datetime string


class AuthorizedUser(BaseModel):
    id: str
    platform: Literal['lark', 'dingtalk', 'weixin']
    platform_user_id: str
    platform_username: str
    authorized_at: str  # ISO datetime string


class ChannelSettings(BaseModel):
    default_data_space_id: Optional[str] = None
    default_model: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
# SSE event shapes (backend → frontend via GET /api/channels/weixin/login)
# ─────────────────────────────────────────────────────────────────

class SSEEventQR(BaseModel):
    """event: qr"""
    qr_data_url: str = Field(..., description="base64 PNG data URL: data:image/png;base64,...")


class SSEEventDone(BaseModel):
    """event: done"""
    account_id: str
    bot_token: str


class SSEEventError(BaseModel):
    """event: error"""
    message: str


# ─────────────────────────────────────────────────────────────────
# Enable/test request bodies
# ─────────────────────────────────────────────────────────────────

class EnableChannelBody(BaseModel):
    credentials: dict[str, str]


class LarkCredentials(BaseModel):
    app_id: str
    app_secret: str
    encrypt_key: Optional[str] = None
    verification_token: Optional[str] = None


class DingTalkCredentials(BaseModel):
    client_id: str
    client_secret: str


class ApprovePairingBody(BaseModel):
    code: str


class RejectPairingBody(BaseModel):
    code: str


class RevokeUserBody(BaseModel):
    user_id: str


class TestChannelResponse(BaseModel):
    ok: bool
    detail: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────

class TestChannelStatus:
    def test_valid_lark_status(self):
        s = ChannelStatus(id='lark', enabled=True, connected=False, has_credentials=True)
        assert s.id == 'lark'
        assert s.enabled is True

    def test_valid_all_channels(self):
        for ch in ('lark', 'dingtalk', 'weixin'):
            s = ChannelStatus(id=ch, enabled=False, connected=False, has_credentials=False)
            assert s.id == ch

    def test_invalid_channel_id(self):
        with pytest.raises(ValidationError):
            ChannelStatus(id='telegram', enabled=False, connected=False, has_credentials=False)

    def test_serialise_round_trip(self):
        raw = {'id': 'weixin', 'enabled': True, 'connected': True, 'has_credentials': True}
        s = ChannelStatus(**raw)
        assert s.model_dump() == raw


class TestPairingRequest:
    def test_valid_pairing(self):
        p = PairingRequest(
            code='ABC123',
            platform='lark',
            platform_user_id='ou_abc',
            platform_username='张三',
            expires_at='2026-07-01T10:00:00Z',
        )
        assert p.code == 'ABC123'

    def test_platform_validation(self):
        with pytest.raises(ValidationError):
            PairingRequest(
                code='X',
                platform='telegram',  # type: ignore[arg-type]
                platform_user_id='u1',
                platform_username='u',
                expires_at='2026-07-01T10:00:00Z',
            )


class TestAuthorizedUser:
    def test_valid_user(self):
        u = AuthorizedUser(
            id='user-uuid-1',
            platform='dingtalk',
            platform_user_id='staffId001',
            platform_username='李四',
            authorized_at='2026-06-30T08:00:00Z',
        )
        assert u.platform == 'dingtalk'

    def test_json_parse(self):
        raw = json.dumps({
            'id': 'u1', 'platform': 'weixin',
            'platform_user_id': 'wx123', 'platform_username': '王五',
            'authorized_at': '2026-06-01T00:00:00Z',
        })
        u = AuthorizedUser.model_validate_json(raw)
        assert u.id == 'u1'


class TestChannelSettings:
    def test_empty_settings(self):
        s = ChannelSettings()
        assert s.default_data_space_id is None
        assert s.default_model is None

    def test_partial_settings(self):
        s = ChannelSettings(default_model='gpt-4o')
        assert s.default_model == 'gpt-4o'
        assert s.default_data_space_id is None

    def test_full_settings(self):
        s = ChannelSettings(default_data_space_id='ds-1', default_model='claude-3-5-sonnet')
        assert s.default_data_space_id == 'ds-1'

    def test_put_body_round_trip(self):
        body = {'default_data_space_id': 'ds-42', 'default_model': None}
        s = ChannelSettings(**body)
        dumped = s.model_dump()
        assert dumped['default_data_space_id'] == 'ds-42'
        assert dumped['default_model'] is None


class TestSSEEventShapes:
    def test_qr_event_valid(self):
        evt = SSEEventQR(qr_data_url='data:image/png;base64,iVBORw0KGgo=')
        assert evt.qr_data_url.startswith('data:image/png;base64,')

    def test_qr_event_must_have_url(self):
        with pytest.raises(ValidationError):
            SSEEventQR()  # type: ignore[call-arg]

    def test_done_event_valid(self):
        evt = SSEEventDone(account_id='acc-1', bot_token='tok-abc123')
        assert evt.account_id == 'acc-1'
        assert evt.bot_token == 'tok-abc123'

    def test_done_event_from_json(self):
        raw = '{"account_id": "acc-2", "bot_token": "t-xyz"}'
        evt = SSEEventDone.model_validate_json(raw)
        assert evt.bot_token == 't-xyz'

    def test_error_event_valid(self):
        evt = SSEEventError(message='QR code expired')
        assert 'expired' in evt.message

    def test_sse_format_parsing(self):
        """Simulate frontend SSE parser reading lines."""
        sse_bytes = (
            b'event: qr\n'
            b'data: {"qr_data_url": "data:image/png;base64,abc"}\n\n'
            b'event: scanned\n'
            b'data: {}\n\n'
            b'event: done\n'
            b'data: {"account_id": "a1", "bot_token": "t1"}\n\n'
        )
        events: list[tuple[str, dict]] = []
        current_event = ''
        for line in sse_bytes.decode().split('\n'):
            if line.startswith('event: '):
                current_event = line[7:].strip()
            elif line.startswith('data: '):
                payload = json.loads(line[6:].strip())
                events.append((current_event, payload))
                current_event = ''

        assert events[0][0] == 'qr'
        assert 'qr_data_url' in events[0][1]
        assert events[1][0] == 'scanned'
        assert events[2][0] == 'done'
        assert events[2][1]['account_id'] == 'a1'

        # Validate each with pydantic models
        qr_evt = SSEEventQR(**events[0][1])
        done_evt = SSEEventDone(**events[2][1])
        assert qr_evt.qr_data_url == 'data:image/png;base64,abc'
        assert done_evt.bot_token == 't1'


class TestRequestBodies:
    def test_enable_lark_body(self):
        body = EnableChannelBody(credentials={'app_id': 'cli_x', 'app_secret': 'sec_y'})
        creds = LarkCredentials(**body.credentials)
        assert creds.app_id == 'cli_x'
        assert creds.encrypt_key is None

    def test_enable_lark_with_optional(self):
        body = EnableChannelBody(credentials={
            'app_id': 'cli_x',
            'app_secret': 'sec_y',
            'encrypt_key': 'ek_z',
            'verification_token': 'vt_w',
        })
        creds = LarkCredentials(**body.credentials)
        assert creds.encrypt_key == 'ek_z'
        assert creds.verification_token == 'vt_w'

    def test_enable_dingtalk_body(self):
        body = EnableChannelBody(credentials={'client_id': 'ding_id', 'client_secret': 'ding_sec'})
        creds = DingTalkCredentials(**body.credentials)
        assert creds.client_id == 'ding_id'

    def test_approve_pairing(self):
        body = ApprovePairingBody(code='CODE42')
        assert body.code == 'CODE42'

    def test_reject_pairing(self):
        body = RejectPairingBody(code='CODE42')
        assert body.code == 'CODE42'

    def test_revoke_user(self):
        body = RevokeUserBody(user_id='user-uuid-99')
        assert body.user_id == 'user-uuid-99'

    def test_test_channel_response_success(self):
        r = TestChannelResponse(ok=True)
        assert r.ok is True
        assert r.detail is None

    def test_test_channel_response_failure(self):
        r = TestChannelResponse(ok=False, detail='Invalid app_id or app_secret')
        assert r.ok is False
        assert 'Invalid' in (r.detail or '')


class TestAsyncCompatibility:
    """Verify async patterns work with asyncio.run (no pytest-asyncio needed)."""

    def test_async_parse_sse(self):
        async def parse():
            events = []
            lines = [
                'event: qr',
                'data: {"qr_data_url": "data:image/png;base64,xyz"}',
                '',
                'event: done',
                'data: {"account_id": "a", "bot_token": "b"}',
                '',
            ]
            current = ''
            for line in lines:
                if line.startswith('event: '):
                    current = line[7:]
                elif line.startswith('data: '):
                    payload = json.loads(line[6:])
                    events.append((current, payload))
                    current = ''
            return events

        result = asyncio.run(parse())
        assert len(result) == 2
        assert result[0][0] == 'qr'
        assert result[1][1]['account_id'] == 'a'
