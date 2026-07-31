"""Clock Port 与 FakeClock 契约测试。

覆盖：正常获取时间、FakeClock 时间推进、时区安全、Protocol 合规。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.ports.clock import Clock, FakeClock, SystemClock


# ── SystemClock ──────────────────────────────────────────────

def test_system_clock_now_returns_utc_datetime() -> None:
    """SystemClock.now() 返回带 UTC 时区的 datetime。"""
    clock = SystemClock()
    result = clock.now()

    assert isinstance(result, datetime)
    assert result.tzinfo is UTC


def test_system_clock_now_is_monotonic() -> None:
    """连续两次调用 SystemClock.now() 时间不倒退。"""
    clock = SystemClock()
    first = clock.now()
    second = clock.now()

    assert second >= first


# ── FakeClock 默认初始时间 ──────────────────────────────────

def test_fake_clock_default_start_is_utc() -> None:
    """FakeClock 默认初始时间带 UTC 时区。"""
    clock = FakeClock()
    result = clock.now()

    assert result == datetime(2026, 7, 1, tzinfo=UTC)


def test_fake_clock_custom_start() -> None:
    """FakeClock 接受自定义初始时间。"""
    start = datetime(2025, 1, 15, 12, 30, tzinfo=UTC)
    clock = FakeClock(start=start)

    assert clock.now() == start


# ── FakeClock advance ────────────────────────────────────────

def test_fake_clock_advance_returns_new_time() -> None:
    """advance 返回推进后的时间。"""
    clock = FakeClock()
    new = clock.advance(timedelta(hours=1))

    assert new == datetime(2026, 7, 1, 1, 0, 0, tzinfo=UTC)


def test_fake_clock_advance_updates_now() -> None:
    """advance 后 now() 返回新时间。"""
    clock = FakeClock()
    clock.advance(timedelta(days=3))

    assert clock.now() == datetime(2026, 7, 4, 0, 0, 0, tzinfo=UTC)


def test_fake_clock_multiple_advances_accumulate() -> None:
    """多次 advance 累加时间。"""
    clock = FakeClock()
    clock.advance(timedelta(hours=5))
    clock.advance(timedelta(minutes=30))

    assert clock.now() == datetime(2026, 7, 1, 5, 30, 0, tzinfo=UTC)


def test_fake_clock_advance_across_month_boundary() -> None:
    """advance 跨越月份边界正确。"""
    clock = FakeClock()
    clock.advance(timedelta(days=32))

    assert clock.now() == datetime(2026, 8, 2, 0, 0, 0, tzinfo=UTC)


# ── FakeClock set_now ────────────────────────────────────────

def test_fake_clock_set_now_explicit_time() -> None:
    """set_now 精确设置当前时间。"""
    clock = FakeClock()
    target = datetime(2026, 12, 25, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    clock.set_now(target)

    assert clock.now() == target


def test_fake_clock_set_now_rejects_naive_datetime() -> None:
    """set_now 拒绝无时区信息的 datetime。"""
    clock = FakeClock()
    naive = datetime(2026, 7, 1, 12, 0)

    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set_now(naive)


# ── Protocol 合规 ────────────────────────────────────────────

def test_system_clock_satisfies_clock_protocol() -> None:
    """SystemClock 是 Clock Protocol 的运行时实例。"""
    assert isinstance(SystemClock(), Clock)


def test_fake_clock_satisfies_clock_protocol() -> None:
    """FakeClock 是 Clock Protocol 的运行时实例。"""
    assert isinstance(FakeClock(), Clock)


def test_clock_protocol_not_satisfied_by_other() -> None:
    """没有 now() 方法的对象不满足 Clock Protocol。"""
    assert not isinstance(object(), Clock)


# ── TTL 边界场景（为 Step 9 预热）────────────────────────────

def test_fake_clock_ttl_stale_detection() -> None:
    """模拟 TTL 过期：observed_at + TTL < now → stale。"""
    clock = FakeClock()
    observed_at = clock.now()  # 2026-07-01T00:00:00Z
    ttl = timedelta(hours=24)

    # 未过期
    clock.advance(timedelta(hours=12))
    assert clock.now() - observed_at < ttl

    # 恰好过期
    clock.advance(timedelta(hours=12))
    assert clock.now() - observed_at >= ttl


def test_fake_clock_reproducible_time() -> None:
    """同一初始时间的两个 FakeClock 返回相同时间。"""
    a = FakeClock()
    b = FakeClock()

    assert a.now() == b.now()

    a.advance(timedelta(seconds=30))
    b.advance(timedelta(seconds=30))

    assert a.now() == b.now()
