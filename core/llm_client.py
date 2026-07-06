"""LLM 统一调用客户端 — 所有 Agent 通过此模块调用 Claude API。

职责:
- 封装 Anthropic SDK 调用，提供统一的 generate() 异步接口
- 超时(30s) + 重试(3次指数退避 [1,2,4]s)
- JSON 响应解析 + 可选 schema 校验
- API key 从环境变量注入，不硬编码
- 不可用时 graceful degrade（由调用方的 _llm_or_stub 处理）

来源: handoff.md §4.1, spec/agent_contract.md §5
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 模块级常量
# ============================================================

LLM_TIMEOUT = 30          # LLM 调用超时 (秒) — handoff.md §4.1
DEFAULT_MODEL = "claude-3-haiku-20240307"
ENV_API_KEY = "ANTHROPIC_API_KEY"
MAX_RETRIES = 3           # 最大重试次数
RETRY_BACKOFF = [1, 2, 4] # 指数退避序列 (秒)

# 检测 anthropic SDK 是否可用
try:
    import anthropic
    _anthropic_available = True
except ImportError:
    _anthropic_available = False
    logger.warning("anthropic SDK 未安装，LLMClient 将不可用。安装: pip install anthropic>=0.18.0")


# ============================================================
# 自定义异常层次
# ============================================================

class LLMError(Exception):
    """LLM 调用相关异常的基类。"""
    pass


class LLMTimeoutError(LLMError):
    """LLM 调用超时 (>30s)。可重试。"""
    pass


class LLMRateLimitError(LLMError):
    """API 限流 (HTTP 429)。可重试。"""
    pass


class LLMParseError(LLMError):
    """LLM 响应 JSON 解析失败。不可重试(内容问题)。"""
    pass


class LLMEmptyResponseError(LLMError):
    """LLM 返回空响应。不可重试。"""
    pass


class LLMSchemaValidationError(LLMError):
    """LLM 返回的 JSON schema 校验失败。不可重试。"""
    pass


# ============================================================
# LLMClient
# ============================================================

class LLMClient:
    """LLM 统一调用客户端。

    所有 Agent 通过此客户端调用 LLM，禁止裸调 Anthropic SDK。
    支持超时、重试、JSON 解析和 schema 校验。

    Usage:
        client = LLMClient()  # 从 ANTHROPIC_API_KEY 环境变量读取 key
        result = await client.generate(
            system_prompt="你是专家...",
            user_prompt="请推荐...",
        )
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: int = LLM_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ):
        """初始化 LLM 客户端。

        Args:
            api_key: Anthropic API key。默认从环境变量 ANTHROPIC_API_KEY 读取。
                     为 None 且环境变量也未设置时，客户端降级为不可用状态。
            model: 模型 ID，默认 claude-3-haiku-20240307。
            timeout: 单次调用超时 (秒)，默认 30s。
            max_retries: 最大重试次数，默认 3。
        """
        self._api_key = api_key or os.environ.get(ENV_API_KEY)
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = None

        if not _anthropic_available:
            logger.warning("anthropic SDK 未安装，LLMClient 不可用")
        elif not self._api_key:
            logger.warning(
                f"环境变量 {ENV_API_KEY} 未设置且未传入 api_key，"
                f"LLMClient 不可用"
            )

    # -- 公共 API --

    @property
    def available(self) -> bool:
        """客户端是否可用（SDK 已安装 + API key 已配置）。"""
        return _anthropic_available and bool(self._api_key)

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发送 prompt 到 LLM，返回解析后的 JSON dict。

        内置重试 + 超时 + JSON 解析。output_schema 非 None 时额外做 schema 校验。

        Args:
            system_prompt: 系统提示词。
            user_prompt: 用户提示词。
            output_schema: 可选的输出 JSON schema，用于校验必填字段和类型。

        Returns:
            解析后的 JSON dict。

        Raises:
            LLMError: 各种 LLM 调用异常（超时/限流/解析失败/schema校验失败）。
            RuntimeError: 客户端不可用时调用。
        """
        if not self.available:
            raise RuntimeError("LLMClient 不可用: SDK 未安装或 API key 未配置")

        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries):
            try:
                raw_text = await self._call_with_timeout(system_prompt, user_prompt)
                result = self._parse_json_response(raw_text)

                if output_schema is not None:
                    violations = self._validate_schema(result, output_schema)
                    if violations:
                        raise LLMSchemaValidationError(
                            f"Schema 校验失败: {'; '.join(violations)}"
                        )

                return result

            except LLMRateLimitError:
                last_error = LLMRateLimitError(
                    f"API 限流 (429)，已重试 {attempt + 1}/{self._max_retries} 次"
                )
                if attempt < self._max_retries - 1:
                    backoff = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                    logger.warning(
                        f"LLM 限流 (429)，{backoff}s 后重试 (第 {attempt + 2} 次)"
                    )
                    await asyncio.sleep(backoff)
                    continue
                break

            except (LLMParseError, LLMEmptyResponseError, LLMSchemaValidationError):
                # 内容/格式问题，重试无意义
                raise

            except LLMTimeoutError:
                last_error = LLMTimeoutError(
                    f"LLM 调用超时，已重试 {attempt + 1}/{self._max_retries} 次"
                )
                if attempt < self._max_retries - 1:
                    backoff = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                    logger.warning(
                        f"LLM 超时 ({self._timeout}s)，{backoff}s 后重试 (第 {attempt + 2} 次)"
                    )
                    continue
                break

        raise last_error  # type: ignore[misc]

    # -- 内部方法 --

    async def _call_with_timeout(
        self, system_prompt: str, user_prompt: str
    ) -> str:
        """带超时的 LLM API 调用。"""
        return await asyncio.wait_for(
            self._call_anthropic(system_prompt, user_prompt),
            timeout=self._timeout,
        )

    async def _call_anthropic(
        self, system_prompt: str, user_prompt: str
    ) -> str:
        """底层 Anthropic API 调用。"""
        client = self._get_client()
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            # 提取文本内容
            content = response.content
            if not content:
                raise LLMEmptyResponseError("LLM 返回空响应")
            text = ""
            for block in content:
                if hasattr(block, "text"):
                    text += block.text
            if not text.strip():
                raise LLMEmptyResponseError("LLM 返回空文本")
            return text
        except (LLMEmptyResponseError,):
            raise
        except Exception as exc:
            error_str = str(exc).lower()
            if "429" in error_str or "rate" in error_str:
                raise LLMRateLimitError(str(exc)) from exc
            if "timeout" in error_str:
                raise LLMTimeoutError(str(exc)) from exc
            raise LLMError(f"Anthropic API 调用失败: {exc}") from exc

    def _get_client(self):
        """获取或创建 Anthropic 客户端实例。"""
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """从 LLM 文本响应中提取 JSON。

        支持:
        - ```json ... ``` 代码块
        - ``` ... ``` 代码块
        - 裸 JSON 字符串

        Raises:
            LLMParseError: 无法提取有效 JSON。
        """
        text = text.strip()

        # 尝试提取 ```json 代码块
        json_block_match = re.search(
            r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL
        )
        if json_block_match:
            json_str = json_block_match.group(1).strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as exc:
                raise LLMParseError(
                    f"JSON 代码块解析失败: {exc}. "
                    f"原始内容(前500字符): {json_str[:500]}"
                ) from exc

        # 尝试裸 JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试找到第一个 { 和最后一个 }
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                try:
                    return json.loads(text[brace_start:brace_end + 1])
                except json.JSONDecodeError as exc:
                    raise LLMParseError(
                        f"裸 JSON 提取失败: {exc}. "
                        f"原始内容(前500字符): {text[:500]}"
                    ) from exc

        raise LLMParseError(
            f"无法从 LLM 响应中提取 JSON。"
            f"原始内容(前500字符): {text[:500]}"
        )

    @staticmethod
    def _validate_schema(
        data: Dict[str, Any], schema: Dict[str, Any]
    ) -> List[str]:
        """校验 data 是否符合 schema 定义的必填字段和类型。

        schema 格式:
        {
            "type": "object",
            "required": ["field1", "field2"],
            "properties": {
                "field1": {"type": "string"},
                "field2": {"type": "number"},
                "nested": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [...],
                        "properties": {...}
                    }
                }
            }
        }

        Returns:
            违规描述列表，空列表表示通过。
        """
        violations: List[str] = []

        if not isinstance(data, dict):
            violations.append(f"期望 object 类型, 实际 {type(data).__name__}")
            return violations

        # 检查必填字段
        required: List[str] = schema.get("required", [])
        properties: Dict[str, Any] = schema.get("properties", {})

        for field in required:
            if field not in data:
                violations.append(f"缺少必填字段: {field}")
            elif data[field] is None:
                violations.append(f"必填字段为 null: {field}")

        # 检查字段类型
        for field, value in data.items():
            if field in properties:
                prop_schema = properties[field]
                expected_type = prop_schema.get("type")

                if expected_type == "string" and not isinstance(value, str):
                    violations.append(
                        f"字段 {field} 期望 string, 实际 {type(value).__name__}"
                    )
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    violations.append(
                        f"字段 {field} 期望 number, 实际 {type(value).__name__}"
                    )
                elif expected_type == "array" and not isinstance(value, list):
                    violations.append(
                        f"字段 {field} 期望 array, 实际 {type(value).__name__}"
                    )
                elif expected_type == "object" and not isinstance(value, dict):
                    violations.append(
                        f"字段 {field} 期望 object, 实际 {type(value).__name__}"
                    )

                # 递归校验嵌套数组元素
                if expected_type == "array" and isinstance(value, list):
                    items_schema = prop_schema.get("items")
                    if items_schema and isinstance(items_schema, dict):
                        for i, item in enumerate(value):
                            if isinstance(item, dict):
                                nested_violations = LLMClient._validate_schema(
                                    item, items_schema
                                )
                                for nv in nested_violations:
                                    violations.append(f"{field}[{i}].{nv}")

        return violations


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMParseError",
    "LLMEmptyResponseError",
    "LLMSchemaValidationError",
    "LLM_TIMEOUT",
    "DEFAULT_MODEL",
    "ENV_API_KEY",
    "MAX_RETRIES",
    "RETRY_BACKOFF",
]
