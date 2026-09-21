"""Regression tests for Phase 1 authentication and ownership controls."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError

from backend.api.merge import _assert_job_owner
from backend.core.config import Settings
from backend.core.security import create_media_token, verify_media_token
from backend.main import app
from backend.models.user import PasswordReset, UserCreate
from backend.services.auth_service import AuthService, _utcnow


class MemoryCollection:
    def __init__(self, documents=None):
        self.documents = {d["_id"]: deepcopy(d) for d in (documents or [])}

    async def create_index(self, *_args, **_kwargs):
        return None

    @staticmethod
    def _matches(document, query):
        for key, expected in query.items():
            if key == "$or":
                if not any(MemoryCollection._matches(document, branch) for branch in expected):
                    return False
                continue
            actual = document.get(key)
            if isinstance(expected, dict):
                if "$gt" in expected and not (actual is not None and actual > expected["$gt"]):
                    return False
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
            elif actual != expected:
                return False
        return True

    async def find_one(self, query, *_args):
        return next(
            (deepcopy(d) for d in self.documents.values() if self._matches(d, query)),
            None,
        )

    async def update_one(self, query, update, upsert=False):
        found_key = next(
            (key for key, d in self.documents.items() if self._matches(d, query)),
            None,
        )
        if found_key is None and upsert:
            found_key = query.get("_id")
            self.documents[found_key] = {"_id": found_key}
        if found_key is None:
            return SimpleNamespace(matched_count=0, modified_count=0)
        document = self.documents[found_key]
        document.update(update.get("$set", {}))
        for key, amount in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + amount
        for key in update.get("$unset", {}):
            document.pop(key, None)
        return SimpleNamespace(matched_count=1, modified_count=1)


class MemoryDB(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = MemoryCollection()
        return super().__getitem__(key)


def test_public_signup_schema_has_no_role_field():
    user = UserCreate(email="person@example.com", password="secure1", name="Person")
    assert "role" not in user.model_dump()
    with pytest.raises(ValidationError):
        UserCreate(
            email="attacker@example.com",
            password="secure1",
            name="Attacker",
            role="admin",
        )


def test_password_reset_requires_verified_reset_token():
    with pytest.raises(ValidationError):
        PasswordReset(password="newpass1")


@pytest.mark.asyncio
async def test_password_reset_token_is_expiring_and_single_use():
    users = MemoryCollection([
        {
            "_id": "u1",
            "email": "person@example.com",
            "username": "person",
            "password": "old",
            "auth_version": 0,
        }
    ])
    db = MemoryDB(users=users, history=MemoryCollection(), password_resets=MemoryCollection())
    service = AuthService(db)

    code = await service.create_password_reset("person@example.com")
    assert code and len(code) == 6
    reset_token = await service.verify_reset_code("person@example.com", code)
    assert reset_token

    first = await service.reset_password(reset_token, "newpassword")
    second = await service.reset_password(reset_token, "anotherpassword")
    assert first["success"] is True
    assert second["success"] is False
    assert users.documents["u1"]["auth_version"] == 1


@pytest.mark.asyncio
async def test_expired_reset_code_is_rejected():
    db = MemoryDB(
        users=MemoryCollection(),
        history=MemoryCollection(),
        password_resets=MemoryCollection([
            {
                "_id": "person@example.com",
                "expires_at": _utcnow() - timedelta(seconds=1),
                "attempts_remaining": 5,
                "used": False,
            }
        ]),
    )
    assert await AuthService(db).verify_reset_code("person@example.com", "123456") is None


def test_job_ownership_hides_other_users_jobs():
    _assert_job_owner({"user_id": "owner"}, {"sub": "owner", "role": "user"})
    with pytest.raises(HTTPException) as exc:
        _assert_job_owner({"user_id": "owner"}, {"sub": "attacker", "role": "user"})
    assert exc.value.status_code == 404


def test_media_token_is_scoped_to_job_and_artifact():
    token = create_media_token("job-1", "video", "user-1")
    assert verify_media_token(token, "job-1", "video")
    assert not verify_media_token(token, "job-2", "video")
    assert not verify_media_token(token, "job-1", "audio")


def test_production_rejects_weak_secret():
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="production", SECRET_KEY="secret", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="production", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="replace-with-a-random-secret-of-at-least-32-characters",
            _env_file=None,
        )


def test_sensitive_routes_declare_auth_dependencies():
    protected_paths = {
        "/api/v1/transcript",
        "/api/v1/transcript/summarize",
        "/api/v1/merge/profiles",
        "/api/v1/merge/{job_id}/result",
        "/api/v1/search",
        "/api/v1/chat",
    }
    routes = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path in protected_paths
    }
    assert routes.keys() == protected_paths
    for route in routes.values():
        dependency_names = {
            dependency.call.__name__
            for dependency in route.dependant.dependencies
            if dependency.call
        }
        assert "get_current_user" in dependency_names
