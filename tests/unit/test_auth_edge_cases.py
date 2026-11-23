import asyncio
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from jose import jwt

from app.auth import jwt as auth_jwt
from app.auth import redis as auth_redis
from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.models.user import User
from app.schemas.token import TokenType


def _run(coroutine):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def test_dependency_accepts_minimal_payloads():
    user_id = uuid4()
    with patch.object(User, "verify_token", side_effect=[{"sub": str(user_id)}, user_id]):
        minimal_payload_user = get_current_user(token="minimal-payload")
        uuid_user = get_current_user(token="uuid-payload")

    assert minimal_payload_user.id == uuid_user.id == user_id
    assert minimal_payload_user.username == "unknown"
    assert uuid_user.email == "unknown@example.com"


@pytest.mark.parametrize("payload", [{"sub": "not-a-uuid"}, "unexpected"])
def test_dependency_rejects_unusable_payloads(payload):
    with patch.object(User, "verify_token", return_value=payload):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(token="unusable")
    assert exc_info.value.status_code == 401


@pytest.mark.parametrize(
    "user",
    [None, MagicMock(verify_password=MagicMock(return_value=False))],
)
def test_authentication_rejects_missing_user_or_wrong_password(user):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user
    assert User.authenticate(db, "testuser", "wrong-password") is None


@pytest.mark.parametrize("subject", [None, "not-a-uuid"])
def test_verify_token_rejects_missing_or_invalid_subject(subject):
    payload = {"type": TokenType.ACCESS.value}
    if subject is not None:
        payload["sub"] = subject
    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    assert User.verify_token(token) is None


def test_create_refresh_token_with_uuid_and_explicit_expiry():
    user_id = uuid4()
    token = auth_jwt.create_token(
        user_id,
        TokenType.REFRESH,
        expires_delta=timedelta(minutes=5),
    )

    payload = jwt.decode(
        token,
        settings.JWT_REFRESH_SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )
    assert payload["sub"] == str(user_id)
    assert payload["type"] == TokenType.REFRESH.value


def test_create_token_wraps_encode_errors():
    with patch.object(auth_jwt.jwt, "encode", side_effect=ValueError("encode failed")):
        with pytest.raises(HTTPException) as exc_info:
            auth_jwt.create_token("user-id", TokenType.ACCESS)
    assert exc_info.value.status_code == 500
    assert "encode failed" in exc_info.value.detail


def test_decode_token_accepts_valid_token():
    token = auth_jwt.create_token("user-id", TokenType.ACCESS)
    with patch.object(auth_jwt, "is_blacklisted", new=AsyncMock(return_value=False)):
        payload = _run(auth_jwt.decode_token(token, TokenType.ACCESS))
    assert payload["sub"] == "user-id"


def test_decode_token_rejects_wrong_type_and_blacklisted_tokens():
    wrong_type_token = jwt.encode(
        {
            "sub": "user-id",
            "type": TokenType.REFRESH.value,
            "jti": "wrong-type",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    with patch.object(auth_jwt, "is_blacklisted", new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException, match="Invalid token type"):
            _run(auth_jwt.decode_token(wrong_type_token, TokenType.ACCESS))

    valid_token = auth_jwt.create_token("user-id", TokenType.ACCESS)
    with patch.object(auth_jwt, "is_blacklisted", new=AsyncMock(return_value=True)):
        with pytest.raises(HTTPException, match="Token has been revoked"):
            _run(auth_jwt.decode_token(valid_token, TokenType.ACCESS))


@pytest.mark.parametrize(
    ("token", "expected_detail"),
    [
        ("not-a-jwt", "Could not validate credentials"),
        (
            jwt.encode(
                {
                    "sub": "expired",
                    "type": TokenType.ACCESS.value,
                    "jti": "expired",
                    "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
                },
                settings.JWT_SECRET_KEY,
                algorithm=settings.ALGORITHM,
            ),
            "Token has expired",
        ),
    ],
)
def test_decode_token_rejects_invalid_or_expired_tokens(token, expected_detail):
    with pytest.raises(HTTPException) as exc_info:
        _run(auth_jwt.decode_token(token, TokenType.ACCESS))
    assert exc_info.value.detail == expected_detail


def test_current_user_dependency_returns_active_user():
    user = SimpleNamespace(id=uuid4(), is_active=True)
    query = MagicMock()
    query.filter.return_value.first.return_value = user
    db = MagicMock()
    db.query.return_value = query

    with patch.object(
        auth_jwt, "decode_token", new=AsyncMock(return_value={"sub": str(user.id)})
    ):
        result = _run(auth_jwt.get_current_user(token="valid", db=db))
    assert result is user


@pytest.mark.parametrize(
    ("user", "detail"),
    [
        (None, "404: User not found"),
        (SimpleNamespace(is_active=False), "400: Inactive user"),
    ],
)
def test_current_user_dependency_wraps_user_lookup_errors(user, detail):
    query = MagicMock()
    query.filter.return_value.first.return_value = user
    db = MagicMock()
    db.query.return_value = query

    with patch.object(
        auth_jwt, "decode_token", new=AsyncMock(return_value={"sub": "user-id"})
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run(auth_jwt.get_current_user(token="valid", db=db))
    assert exc_info.value.status_code == 401
    assert detail in exc_info.value.detail


def test_current_user_dependency_wraps_decode_errors():
    with patch.object(
        auth_jwt,
        "decode_token",
        new=AsyncMock(side_effect=HTTPException(status_code=401, detail="bad token")),
    ):
        with pytest.raises(HTTPException, match="bad token"):
            _run(auth_jwt.get_current_user(token="invalid", db=MagicMock()))


def test_redis_client_is_cached_and_blacklist_operations_use_it(monkeypatch):
    if hasattr(auth_redis.get_redis, "redis"):
        delattr(auth_redis.get_redis, "redis")
    client = MagicMock()
    client.exists = AsyncMock(return_value=1)
    client.set = AsyncMock()
    monkeypatch.setattr(auth_redis.redis_asyncio, "from_url", MagicMock(return_value=client))

    assert _run(auth_redis.get_redis()) is client
    assert _run(auth_redis.get_redis()) is client
    _run(auth_redis.add_to_blacklist("jti", 123))
    assert _run(auth_redis.is_blacklisted("jti")) == 1

    client.set.assert_awaited_once_with("blacklist:jti", "1", ex=123)
    client.exists.assert_awaited_once_with("blacklist:jti")
    if hasattr(auth_redis.get_redis, "redis"):
        delattr(auth_redis.get_redis, "redis")


def test_get_db_closes_session():
    from app import database

    session = MagicMock()
    with patch.object(database, "SessionLocal", return_value=session):
        db_generator = database.get_db()
        assert next(db_generator) is session
        with pytest.raises(StopIteration):
            next(db_generator)
    session.close.assert_called_once_with()
