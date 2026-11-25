"""get_session runs after-commit actions only when the transaction commits."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.session import get_session
from app.db.unit_of_work import AfterCommit

pytestmark = pytest.mark.integration


def fake_request(engine: AsyncEngine) -> Request:
    state = SimpleNamespace(sessionmaker=async_sessionmaker(engine, expire_on_commit=False))
    return cast(Request, SimpleNamespace(app=SimpleNamespace(state=state)))


async def record(calls: list[str]) -> None:
    calls.append("ran")


async def test_actions_run_after_commit(engine: AsyncEngine) -> None:
    calls: list[str] = []
    after_commit = AfterCommit()
    after_commit.add(lambda: record(calls))

    async with asynccontextmanager(get_session)(fake_request(engine), after_commit):
        assert calls == []

    assert calls == ["ran"]


async def test_actions_skipped_on_rollback(engine: AsyncEngine) -> None:
    calls: list[str] = []
    after_commit = AfterCommit()
    after_commit.add(lambda: record(calls))

    with pytest.raises(RuntimeError):
        async with asynccontextmanager(get_session)(fake_request(engine), after_commit):
            raise RuntimeError("request failed")

    assert calls == []
