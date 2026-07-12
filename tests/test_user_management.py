import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import main
from main import (
    ChangePasswordRequest,
    CreateUserRequest,
    ResetPasswordRequest,
    SetUserActiveRequest,
    SetUserRoleRequest,
    auth_change_password,
    auth_create_user,
    auth_reset_user_password,
    auth_set_user_active,
    auth_set_user_role,
)


class _Req:
    """Request stand-in exposing state.user like the auth middleware sets it."""

    def __init__(self, user=None):
        self.state = type("S", (), {})()
        self.state.user = user
        self.headers = {}
        self.client = None
        self.cookies = {}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(main, "_auth_enabled", lambda: True)
    monkeypatch.setattr(main, "_audit", lambda *a, **k: None)


ADMIN = {"id": 1, "username": "admin", "is_admin": True}
NON_ADMIN = {"id": 2, "username": "bob", "is_admin": False}


def test_non_admin_cannot_create_user():
    with pytest.raises(HTTPException) as exc:
        auth_create_user(CreateUserRequest(username="x", password="start123"), _Req(NON_ADMIN))
    assert exc.value.status_code == 403


def test_admin_created_user_must_change_password(monkeypatch):
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return {"id": 9, "username": kwargs["username"], "is_active": True,
                "is_admin": kwargs.get("is_admin"), "must_change_password": kwargs.get("must_change_password")}

    monkeypatch.setattr(main, "create_app_user", _create)
    result = auth_create_user(
        CreateUserRequest(username="neu", password="start123", is_admin=True), _Req(ADMIN)
    )
    assert result["ok"] is True
    assert captured["must_change_password"] is True
    assert captured["is_admin"] is True
    assert result["user"]["must_change_password"] is True


def test_reset_password_forces_change(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "get_app_user_by_id", lambda uid: {"id": uid, "username": "bob"})

    def _set(uid, *, password_hash, must_change_password):
        captured["uid"] = uid
        captured["must_change_password"] = must_change_password
        return {"id": uid, "username": "bob", "is_active": True, "is_admin": False,
                "must_change_password": must_change_password}

    monkeypatch.setattr(main, "set_app_user_password", _set)
    result = auth_reset_user_password(2, ResetPasswordRequest(new_password="reset999"), _Req(ADMIN))
    assert result["ok"] is True
    assert captured["must_change_password"] is True


def test_cannot_demote_last_admin(monkeypatch):
    monkeypatch.setattr(main, "get_app_user_by_id", lambda uid: {"id": uid, "username": "admin", "is_admin": True})
    monkeypatch.setattr(main, "count_app_admins", lambda **k: 1)
    with pytest.raises(HTTPException) as exc:
        auth_set_user_role(1, SetUserRoleRequest(is_admin=False), _Req(ADMIN))
    assert exc.value.status_code == 400


def test_can_demote_when_other_admin_exists(monkeypatch):
    monkeypatch.setattr(main, "get_app_user_by_id", lambda uid: {"id": uid, "username": "dragan", "is_admin": True})
    monkeypatch.setattr(main, "count_app_admins", lambda **k: 2)
    monkeypatch.setattr(main, "set_app_user_admin", lambda uid, *, is_admin: {
        "id": uid, "username": "dragan", "is_active": True, "is_admin": is_admin, "must_change_password": False})
    result = auth_set_user_role(3, SetUserRoleRequest(is_admin=False), _Req(ADMIN))
    assert result["user"]["is_admin"] is False


def test_cannot_deactivate_self(monkeypatch):
    monkeypatch.setattr(main, "get_app_user_by_id", lambda uid: {"id": uid, "username": "admin", "is_admin": True})
    monkeypatch.setattr(main, "count_app_admins", lambda **k: 2)
    with pytest.raises(HTTPException) as exc:
        auth_set_user_active(1, SetUserActiveRequest(is_active=False), _Req(ADMIN))
    assert exc.value.status_code == 400


def test_change_password_wrong_current(monkeypatch):
    stored = main._hash_password("richtig1")
    monkeypatch.setattr(main, "get_app_user_by_id", lambda uid: {"id": uid, "username": "bob", "password_hash": stored})
    with pytest.raises(HTTPException) as exc:
        auth_change_password(ChangePasswordRequest(current_password="falsch1", new_password="neu12345"), _Req(NON_ADMIN))
    assert exc.value.status_code == 403


def test_change_password_success_clears_flag(monkeypatch):
    stored = main._hash_password("altpass1")
    monkeypatch.setattr(main, "get_app_user_by_id", lambda uid: {"id": uid, "username": "bob", "password_hash": stored})
    captured = {}

    def _set(uid, *, password_hash, must_change_password):
        captured["must_change_password"] = must_change_password
        return {"id": uid}

    monkeypatch.setattr(main, "set_app_user_password", _set)
    result = auth_change_password(
        ChangePasswordRequest(current_password="altpass1", new_password="neupass9"), _Req(NON_ADMIN)
    )
    assert result["ok"] is True
    assert captured["must_change_password"] is False


def test_change_password_rejects_same_password(monkeypatch):
    stored = main._hash_password("samepass1")
    monkeypatch.setattr(main, "get_app_user_by_id", lambda uid: {"id": uid, "username": "bob", "password_hash": stored})
    with pytest.raises(HTTPException) as exc:
        auth_change_password(ChangePasswordRequest(current_password="samepass1", new_password="samepass1"), _Req(NON_ADMIN))
    assert exc.value.status_code == 400
