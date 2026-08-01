[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$MainArgs = @(),

    [string]$EnvFile,

    [switch]$ValidateOnly,

    [switch]$LiveSmoke,

    [switch]$LiveTool
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path $projectRoot '.env'
}

$allowedVariables = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
@(
    'DEEPSEEK_API_KEY'
    'DEEPSEEK_MODEL'
    'DEEPSEEK_MAX_TOKENS'
    'AMAP_API_KEY'
    'TUNIU_API_KEY'
    'AMAP_GEOCODE_URL'
    'TUNIU_HOTEL_URL'
    'TUNIU_FLIGHT_URL'
    'TUNIU_TICKET_URL'
    'AMAP_LIVE_EMPTY_TEXT'
    'TUNIU_LIVE_EMPTY_DESTINATION'
    'STRICT_MODE'
    'RETRY_COUNT'
    'CACHE_READS'
    'FALLBACKS'
    'PARTIAL_SUCCESS'
    'LLM_TIMEOUT_SECONDS'
    'EXTERNAL_API_TIMEOUT_SECONDS'
    'MAX_REVISION_ROUNDS'
    'LOG_LEVEL'
    'CONSOLE_SPAN_EXPORTER'
) | ForEach-Object {
    [void]$allowedVariables.Add($_)
}

function ConvertFrom-DotEnvValue {
    param(
        [Parameter(Mandatory)]
        [string]$RawValue
    )

    $value = $RawValue.Trim()
    if ($value.Length -ge 2) {
        $first = $value[0]
        $last = $value[$value.Length - 1]
        if (($first -eq '"' -and $last -eq '"') -or
            ($first -eq "'" -and $last -eq "'")) {
            return $value.Substring(1, $value.Length - 2)
        }
    }
    return $value
}

function Test-PlaceholderValue {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

    return (
        $Value -match '(?i)x{6,}' -or
        $Value -match '(?i)replace[_-]?me' -or
        $Value -match '^<.+>$'
    )
}

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "本地配置文件不存在：$EnvFile。请先复制 .env.example 为 .env 并填入真实密钥。"
}

$loadedNames = [System.Collections.Generic.List[string]]::new()
$lineNumber = 0
foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding utf8) {
    $lineNumber += 1
    $trimmed = $line.Trim()

    if (-not $trimmed -or $trimmed.StartsWith('#')) {
        continue
    }
    if ($trimmed.StartsWith('export ')) {
        $trimmed = $trimmed.Substring(7).TrimStart()
    }

    $separator = $trimmed.IndexOf('=')
    if ($separator -le 0) {
        throw ".env 第 $lineNumber 行不是有效的 KEY=VALUE 格式。"
    }

    $name = $trimmed.Substring(0, $separator).Trim()
    if ($name -notmatch '^[A-Z][A-Z0-9_]*$') {
        throw ".env 第 $lineNumber 行包含非法变量名。"
    }
    if (-not $allowedVariables.Contains($name)) {
        continue
    }

    $value = ConvertFrom-DotEnvValue -RawValue $trimmed.Substring($separator + 1)
    if ([string]::IsNullOrWhiteSpace($value)) {
        continue
    }

    # 显式设置为 Process 作用域，Python 子进程会继承；不写入用户或系统环境。
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    $loadedNames.Add($name)
}

$deepseekKey = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'Process')
if (-not $LiveTool) {
    if ([string]::IsNullOrWhiteSpace($deepseekKey)) {
        throw 'DEEPSEEK_API_KEY 未进入进程环境，拒绝启动。'
    }
    if (Test-PlaceholderValue -Value $deepseekKey) {
        throw 'DEEPSEEK_API_KEY 仍是占位符，拒绝启动。'
    }
}

if ($ValidateOnly -and ($LiveSmoke -or $LiveTool)) {
    throw '-ValidateOnly 不能与 Live 模式同时使用。'
}
if ($LiveSmoke -and $LiveTool) {
    throw '-LiveSmoke 与 -LiveTool 不能同时使用。'
}
if (($LiveSmoke -or $LiveTool) -and $MainArgs.Count -gt 0) {
    throw 'Live 模式不接受主流程参数。'
}

if ($LiveTool) {
    foreach ($toolName in @('AMAP_API_KEY', 'TUNIU_API_KEY')) {
        $toolKey = [Environment]::GetEnvironmentVariable($toolName, 'Process')
        if ([string]::IsNullOrWhiteSpace($toolKey)) {
            throw "$toolName 未进入进程环境，拒绝启动。"
        }
        if (Test-PlaceholderValue -Value $toolKey) {
            throw "$toolName 仍是占位符，拒绝启动。"
        }
    }
}

$loadedDisplay = ($loadedNames | Sort-Object -Unique) -join ', '
Write-Host "已将本地配置载入进程环境：$loadedDisplay"
Write-Host '密钥值不会显示，环境变量仅在当前 PowerShell 进程及其子进程中有效。'
Write-Host 'Output channels: human CLI -> stdout; application JSONL -> stderr.'
$consoleSpanValue = [Environment]::GetEnvironmentVariable('CONSOLE_SPAN_EXPORTER', 'Process')
if ([string]::IsNullOrWhiteSpace($consoleSpanValue)) {
    $consoleSpanValue = 'false'
}
Write-Host "Console Span exporter: $consoleSpanValue (disabled by default; enabled output -> stderr)."

if ($ValidateOnly) {
    Write-Host '本地启动配置验证通过；未启动 Python，未调用外部 API。'
    exit 0
}

$pythonPath = Join-Path $projectRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "未找到项目 Python：$pythonPath"
}
if ($LiveSmoke) {
    Write-Host '已启用 Live Smoke 模式：将在当前进程环境中运行真实 LLM Smoke 测试。'
    Push-Location $projectRoot
    try {
        & $pythonPath -m pytest -m 'slow and live_llm'
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
if ($LiveTool) {
    Write-Host '已启用 Live Tool 模式：将在当前进程环境中运行真实高德/途牛合同测试。'
    Push-Location $projectRoot
    try {
        & $pythonPath -m pytest -m 'slow and live_tool'
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
$mainPath = Join-Path $projectRoot 'main.py'

if (-not (Test-Path -LiteralPath $mainPath -PathType Leaf)) {
    throw "未找到项目入口：$mainPath"
}

Push-Location $projectRoot
try {
    & $pythonPath $mainPath @MainArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
