"""G0 安全与输入预检。

G0 只负责在原始输入进入 LLM 解释前执行确定性检查，不做地名消歧、完整
语义判断或旅行事实核验。原始输入只在本次调用的内存中使用，结果中不保留
原文或敏感内容。
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from src.domain.models.interpretation import SafetyFlag
from src.domain.models.value_objects import StableId

DEFAULT_MAX_INPUT_LENGTH: Final[int] = 4096


class G0IssueCode(str, Enum):
    """G0 可观察的确定性失败代码。"""

    INVALID_INPUT = "INVALID_INPUT"
    INPUT_EMPTY = "INPUT_EMPTY"
    INPUT_TOO_LONG = "INPUT_TOO_LONG"
    CONTROL_CHARACTER = "CONTROL_CHARACTER"
    AUTH_CONTEXT_MISSING = "AUTH_CONTEXT_MISSING"
    AUTH_CONTEXT_INVALID = "AUTH_CONTEXT_INVALID"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    PII_REDACTION_REQUIRED = "PII_REDACTION_REQUIRED"
    DANGEROUS_ACTION = "DANGEROUS_ACTION"
    UNAUTHORIZED_ACTION = "UNAUTHORIZED_ACTION"
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"
    INVALID_DATE_FORMAT = "INVALID_DATE_FORMAT"


class G0SecurityContext(BaseModel):
    """G0 所需的最小认证、授权和脱敏上下文。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    principal_ref: StableId
    authenticated: StrictBool
    authorized: StrictBool
    redacted_input_ref: StableId | None = None


class G0Issue(BaseModel):
    """不包含原始输入的安全预检问题。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    code: G0IssueCode
    safe_message: StrictStr = Field(min_length=1, max_length=256)
    blocking: StrictBool


class G0ValidationResult(BaseModel):
    """G0 预检结果及其安全标记。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: StrictBool
    input_length: StrictInt = Field(ge=0)
    pii_detected: StrictBool
    redacted_input_ref: StableId | None = None
    safety_flags: tuple[SafetyFlag, ...] = ()
    issues: tuple[G0Issue, ...] = ()

    @model_validator(mode="after")
    def validate_passed_state(self) -> G0ValidationResult:
        """确保通过状态与阻断问题保持一致。"""
        has_blocking_issue = any(issue.blocking for issue in self.issues)
        if self.passed == has_blocking_issue:
            raise ValueError("passed must be the inverse of blocking issues")
        if self.pii_detected and SafetyFlag.PII not in self.safety_flags:
            raise ValueError("PII must be represented by a safety flag")
        return self


class G0Validator:
    """执行 G0 的纯确定性安全与格式检查。"""

    def __init__(self, max_input_length: int = DEFAULT_MAX_INPUT_LENGTH) -> None:
        if type(max_input_length) is not int or max_input_length <= 0:
            raise ValueError("max_input_length must be a positive integer")
        self._max_input_length = max_input_length

    def validate(
        self,
        raw_input: object,
        *,
        context: G0SecurityContext | None,
    ) -> G0ValidationResult:
        """对单条用户输入执行 G0 预检。

        Args:
            raw_input: 尚未交给解释器的用户输入；不会被写入结果。
            context: 认证、授权和 PII 脱敏上下文。

        Returns:
            G0ValidationResult: 不包含原始输入的结构化预检结果。
        """
        issues: list[G0Issue] = []
        flags: list[SafetyFlag] = []

        if context is None:
            issues.append(
                _issue(
                    G0IssueCode.AUTH_CONTEXT_MISSING,
                    "authentication and authorization context is required",
                )
            )
            context_ref: str | None = None
        elif not isinstance(context, G0SecurityContext):
            issues.append(
                _issue(
                    G0IssueCode.AUTH_CONTEXT_INVALID,
                    "authentication and authorization context is invalid",
                )
            )
            context_ref = None
        else:
            context_ref = context.redacted_input_ref
            if not context.authenticated:
                issues.append(
                    _issue(
                        G0IssueCode.AUTHENTICATION_REQUIRED,
                        "authenticated principal is required",
                    )
                )
            if not context.authorized:
                issues.append(
                    _issue(
                        G0IssueCode.AUTHORIZATION_DENIED,
                        "request is outside the authorized boundary",
                    )
                )

        if type(raw_input) is not str:
            issues.append(_issue(G0IssueCode.INVALID_INPUT, "input must be a string"))
            return _result(0, flags, issues, context_ref)

        input_length = len(raw_input)
        if not raw_input.strip():
            issues.append(_issue(G0IssueCode.INPUT_EMPTY, "input must not be empty"))
        if input_length > self._max_input_length:
            issues.append(_issue(G0IssueCode.INPUT_TOO_LONG, "input exceeds the maximum length"))
        if _CONTROL_CHARACTER_PATTERN.search(raw_input):
            issues.append(
                _issue(
                    G0IssueCode.CONTROL_CHARACTER,
                    "input contains unsupported control characters",
                )
            )

        pii_detected = bool(_PII_PATTERN.search(raw_input))
        if pii_detected:
            flags.append(SafetyFlag.PII)
            if context_ref is None:
                issues.append(
                    _issue(
                        G0IssueCode.PII_REDACTION_REQUIRED,
                        "PII input requires a redacted input reference",
                    )
                )

        if _PROMPT_INJECTION_PATTERN.search(raw_input):
            flags.append(SafetyFlag.PROMPT_INJECTION)
            issues.append(
                _issue(
                    G0IssueCode.PROMPT_INJECTION_DETECTED,
                    "prompt injection risk detected",
                )
            )

        if _DANGEROUS_ACTION_PATTERN.search(raw_input):
            flags.append(SafetyFlag.DANGEROUS_ACTION)
            issues.append(
                _issue(
                    G0IssueCode.DANGEROUS_ACTION,
                    "dangerous action requires a safety boundary",
                )
            )

        if _UNAUTHORIZED_ACTION_PATTERN.search(raw_input):
            flags.append(SafetyFlag.UNAUTHORIZED_ACTION)
            issues.append(
                _issue(
                    G0IssueCode.UNAUTHORIZED_ACTION,
                    "request contains an unauthorized action",
                )
            )

        if isinstance(context, G0SecurityContext) and not context.authorized:
            flags.append(SafetyFlag.UNAUTHORIZED_ACTION)

        if _contains_invalid_date(raw_input):
            flags.append(SafetyFlag.INVALID_INPUT)
            issues.append(_issue(G0IssueCode.INVALID_DATE_FORMAT, "input contains an invalid date"))

        return _result(input_length, flags, issues, context_ref, pii_detected=pii_detected)


def validate_g0(
    raw_input: object,
    *,
    context: G0SecurityContext | None,
    max_input_length: int = DEFAULT_MAX_INPUT_LENGTH,
) -> G0ValidationResult:
    """使用默认 G0 Validator 执行一次预检。"""
    return G0Validator(max_input_length=max_input_length).validate(
        raw_input,
        context=context,
    )


def _issue(code: G0IssueCode, safe_message: str, *, blocking: bool = True) -> G0Issue:
    return G0Issue(code=code, safe_message=safe_message, blocking=blocking)


def _result(
    input_length: int,
    flags: list[SafetyFlag],
    issues: list[G0Issue],
    redacted_input_ref: str | None,
    *,
    pii_detected: bool = False,
) -> G0ValidationResult:
    unique_flags = tuple(dict.fromkeys(flags))
    return G0ValidationResult(
        passed=not any(issue.blocking for issue in issues),
        input_length=input_length,
        pii_detected=pii_detected,
        redacted_input_ref=redacted_input_ref,
        safety_flags=unique_flags,
        issues=tuple(issues),
    )


_CONTROL_CHARACTER_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PII_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[\dXx](?!\d))"
)
_PROMPT_INJECTION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:忽略(?:(?:之前|上文)(?:的)?(?:所有)?|所有(?:(?:之前|上文)(?:的)?)?)"
    r"(?:指令|规则|提示)|忘记(?:之前|上文)(?:的)?(?:所有)?(?:指令|规则)|"
    r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)|"
    r"(?:system\s+prompt|developer\s+message|reveal\s+(?:your\s+)?prompt))",
    re.IGNORECASE,
)
_DANGEROUS_ACTION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:直接(?:付款|支付|转账|扣款)|立即(?:付款|支付|转账)|绕过(?:确认|安全检查)|"
    r"(?:炸弹|爆炸物|武器|毒品|伤害他人))",
    re.IGNORECASE,
)
_UNAUTHORIZED_ACTION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:未经(?:授权|允许|同意)|绕过(?:权限|认证|授权)|窃取(?:账号|凭证|密码)|"
    r"他人的(?:账号|账户|行程|订单|证件)|(?:without|bypass)\s+(?:permission|authorization))",
    re.IGNORECASE,
)
_NUMERIC_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)"
)
_CHINESE_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日?(?!\d)"
)


def _contains_invalid_date(text: str) -> bool:
    for pattern in (_NUMERIC_DATE_PATTERN, _CHINESE_DATE_PATTERN):
        for match in pattern.finditer(text):
            year, month, day = (int(part) for part in match.groups())
            try:
                date(year, month, day)
            except ValueError:
                return True
    return False
