"""API 配置管理 — API key/endpoint/rate_limit 集中管理。

支持环境变量注入，不硬编码任何密钥。所有外部 API 配置统一入口。

来源: handoff.md §5.6, spec/agent_contract.md §5
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 尝试加载 .env 文件（不强制依赖 python-dotenv）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ============================================================
# 模块级常量
# ============================================================

API_TIMEOUT = 15          # API 调用超时 (agent_contract.md §5.1)
MAX_RETRIES = 3            # 最大重试次数 (agent_contract.md §5.2)
RETRY_BACKOFF = [1, 2, 4]  # 指数退避 (秒)


# ============================================================
# APIConfig
# ============================================================


@dataclass
class APIConfig:
    """API 配置集中管理。

    所有 API key 从环境变量读取，禁止在源码中硬编码。
    每个外部服务有独立的配置段。

    Usage:
        config = APIConfig.from_env()
        if config.is_configured("amap"):
            client = AmapClient(config)
    """

    # === 高德地图 (免费层: 5,000 次/天) ===
    amap_api_key: Optional[str] = None
    amap_base_url: str = "https://restapi.amap.com"

    # === 途牛 MCP 开放平台 (酒店/机票/门票，JSON-RPC 2.0) ===
    tuniu_api_key: Optional[str] = None
    tuniu_mcp_hotel: str = "https://openapi.tuniu.cn/mcp/hotel"
    tuniu_mcp_flight: str = "https://openapi.tuniu.cn/mcp/flight"
    tuniu_mcp_ticket: str = "https://openapi.tuniu.cn/mcp/ticket"

    # === 通用 API 设置 ===
    api_timeout: int = 15       # agent_contract.md §5.1
    max_retries: int = 3        # agent_contract.md §5.2
    retry_backoff: List[float] = field(default_factory=lambda: [1.0, 2.0, 4.0])

    # ============================================================
    # 工厂方法
    # ============================================================

    @classmethod
    def from_env(cls) -> "APIConfig":
        """从环境变量加载全部配置。

        Returns:
            配置实例。缺失的 API key 为 None，由调用方降级处理。
        """
        return cls(
            amap_api_key=os.environ.get("AMAP_API_KEY"),
            tuniu_api_key=os.environ.get("TUNIU_API_KEY"),
            api_timeout=int(os.environ.get("API_TIMEOUT", "15")),
            max_retries=int(os.environ.get("API_MAX_RETRIES", "3")),
        )

    # ============================================================
    # 查询方法
    # ============================================================

    def is_configured(self, service: str) -> bool:
        """检查指定服务是否已配置（API key 已设置）。

        Args:
            service: 服务名 — "amap" | "tuniu"

        Returns:
            True 如果该服务的必需凭据已设置。
        """
        checks: Dict[str, bool] = {
            "amap": bool(self.amap_api_key),
            "tuniu": bool(self.tuniu_api_key),
        }
        return checks.get(service, False)

    def auth_params(self, service: str) -> Dict[str, str]:
        """获取指定服务的认证查询参数。

        高德使用 key 查询参数认证。

        Args:
            service: 服务名

        Returns:
            认证参数字典。
        """
        if service == "amap":
            return {"key": self.amap_api_key or ""}
        return {}


# ============================================================
# 模块级便捷函数
# ============================================================


def get_config() -> APIConfig:
    """获取全局 API 配置（懒加载 + 缓存）。"""
    global _config_cache
    if _config_cache is None:
        _config_cache = APIConfig.from_env()
    return _config_cache


_config_cache: Optional[APIConfig] = None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "APIConfig",
    "get_config",
    "API_TIMEOUT",
    "MAX_RETRIES",
    "RETRY_BACKOFF",
]
