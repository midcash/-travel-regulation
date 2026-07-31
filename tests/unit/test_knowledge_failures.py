from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.ports.tool_errors import ToolConfigurationError, ToolTimeoutError
from src.tool import knowledge
from tests.support.clock_fakes import FakeClock
from tests.support.provider_fakes import FakeGeoProvider, FakeStayProvider


def _facade(
    *,
    geo_provider: FakeGeoProvider | None = None,
    stay_provider: FakeStayProvider | None = None,
) -> knowledge.KnowledgeFacade:
    return knowledge.KnowledgeFacade(
        clock=FakeClock(datetime(2026, 8, 1, 9, tzinfo=UTC)),
        trace_id="trace-knowledge-1",
        timeout_seconds=Decimal("3"),
        geo_provider=geo_provider,
        stay_provider=stay_provider,
        synchronous_runner=_run,
    )


def _run(coroutine: Any) -> Any:
    """无事件循环地驱动无挂起的 Provider Fake 协程。"""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    coroutine.close()
    raise AssertionError("Provider Fake coroutine unexpectedly suspended")


def _install(
    monkeypatch: pytest.MonkeyPatch,
    facade: knowledge.KnowledgeFacade | None,
) -> None:
    monkeypatch.setattr(knowledge, "_legacy_facade", facade)


def test_unconfigured_legacy_entrypoint_fails_without_default_adapter_or_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, None)

    with pytest.raises(ToolConfigurationError) as raised:
        knowledge.TOOL_EXECUTORS["amap_geocode"]("Hangzhou")

    assert raised.value.provider == "knowledge_facade"
    assert raised.value.operation == "legacy_entrypoint"


def test_missing_synchronous_runner_fails_without_creating_an_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = knowledge.KnowledgeFacade(
        clock=FakeClock(datetime(2026, 8, 1, 9, tzinfo=UTC)),
        trace_id="trace-knowledge-1",
        timeout_seconds=Decimal("3"),
    )
    _install(monkeypatch, facade)

    with pytest.raises(ToolConfigurationError) as raised:
        knowledge._exec_amap_geocode("Hangzhou")

    assert raised.value.provider == "knowledge_facade"
    assert raised.value.operation == "legacy_entrypoint"
    assert raised.value.trace_id == "trace-knowledge-1"


def test_missing_capability_fails_before_a_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _facade())

    with pytest.raises(ToolConfigurationError) as raised:
        knowledge._exec_amap_geocode("Hangzhou")

    assert raised.value.provider == "amap"
    assert raised.value.operation == "geo_search"
    assert raised.value.trace_id == "trace-knowledge-1"
    assert raised.value.query_id is not None


def test_provider_timeout_propagates_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = ToolTimeoutError(
        provider="amap",
        operation="geo_search",
        trace_id="trace-knowledge-1",
        query_id="provider-query-1",
        safe_message="provider request timed out",
    )
    geo = FakeGeoProvider([failure])
    _install(monkeypatch, _facade(geo_provider=geo))

    with pytest.raises(ToolTimeoutError) as raised:
        knowledge._exec_amap_geocode("Hangzhou")

    assert raised.value is failure
    assert len(geo.calls) == 1


def test_invalid_hotel_date_fails_before_the_provider_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stay = FakeStayProvider()
    _install(monkeypatch, _facade(stay_provider=stay))

    with pytest.raises(ValueError, match="checkOut must be later than checkIn"):
        knowledge._exec_tuniu_hotel_search("Hangzhou", "2026-08-10", "2026-08-10")

    assert stay.calls == []
