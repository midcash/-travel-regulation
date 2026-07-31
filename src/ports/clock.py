"""Clock Port — 为所有时间依赖点提供可注入的时间源。

M3 要求所有时间逻辑依赖 Clock Port，禁止硬编码 ``datetime.now()``。
测试通过 FakeClock 精确控制时间推进，复现 TTL 边界行为。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """提供当前时间，供领域逻辑和基础设施层注入使用。"""

    def now(self) -> datetime:
        """返回当前时间。"""
        ...


class SystemClock:
    """生产环境使用的真实时钟，返回 UTC 时间。"""

    def now(self) -> datetime:
        """返回当前 UTC 时间。"""
        return datetime.now(UTC)


class FakeClock:
    """测试用可控时钟。

    初始时间固定为 ``2026-07-01T00:00:00+00:00``，
    通过 ``advance()`` / ``set_now()`` 精确控制时间推进，
    用于验证 TTL 边界、过期判定等时间敏感行为。
    """

    def __init__(self, *, start: datetime | None = None) -> None:
        """创建一个 FakeClock。

        Args:
            start: 初始时间，默认为 ``2026-07-01T00:00:00+00:00``。
        """
        self._now = start if start is not None else datetime(2026, 7, 1, tzinfo=UTC)

    def now(self) -> datetime:
        """返回当前设定的时间。"""
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        """将时钟推进指定的时间增量。

        Args:
            delta: 推进的时间量。

        Returns:
            推进后的新当前时间。
        """
        self._now = self._now + delta
        return self._now

    def set_now(self, value: datetime) -> None:
        """显式设置当前时间。

        Args:
            value: 新的当前时间（必须带时区信息）。

        Raises:
            ValueError: value 缺少时区信息。
        """
        if value.tzinfo is None:
            raise ValueError("set_now requires timezone-aware datetime")
        self._now = value
