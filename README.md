# TravelPlan Orchestrator

旅游规划多 Agent 编排系统 — 基于混合专家模型（一主多从）的智能行程生成平台。

[![Version](https://img.shields.io/badge/version-1.1.0-blue)](https://github.com/midcash/-travel-regulation/releases/tag/v1.1.0)
[![Tests](https://img.shields.io/badge/tests-661%20passed-green)](https://github.com/midcash/-travel-regulation/actions)
[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)

## 架构

```
用户自然语言输入
      │
      ▼
┌─────────────────────────────────────────────┐
│              Orchestrator (主控)              │
│   parse → decompose → route → assemble       │
│   Quality Gate 0 → 1 → 2 → 3                │
└──────┬──────────────┬──────────────────────┘
       │              │
       ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Planning     │ │ Execution    │ │ Evaluation   │
│ Agent        │ │ Agent        │ │ Agent        │
│              │ │              │ │              │
│ 行程设计      │ │ 可行性验证    │ │ 质量评估      │
│ DeepSeek LLM │ │ 高德 + 途牛   │ │ Mode A/B/C   │
└──────────────┘ └──────────────┘ └──────────────┘
       │              │              │
       └──────────────┼──────────────┘
                      ▼
              Shared Context (黑板模式)
                      │
                      ▼
              FinalTravelPlan
```

## 快速开始

### 环境要求

- Python 3.11+
- Windows / macOS / Linux

### 安装

```bash
git clone https://github.com/midcash/-travel-regulation.git
cd -travel-regulation
python -m venv venv
venv/Scripts/activate       # Windows
# source venv/bin/activate  # macOS / Linux
pip install -r requirements.txt
```

### 配置 API Key

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Key：
#   DEEPSEEK_API_KEY — DeepSeek 平台 (行程生成 LLM)
#   AMAP_API_KEY     — 高德地图开放平台 (地理编码/路径规划)
#   TUNIU_API_KEY    — 途牛 MCP 开放平台 (酒店/机票/门票价格)
```

| 服务 | 用途 | 注册地址 |
|------|------|----------|
| DeepSeek | LLM 行程生成 | [platform.deepseek.com](https://platform.deepseek.com) |
| 高德地图 | 地理编码 + 路线 + 交通时间 | [lbs.amap.com](https://lbs.amap.com) |
| 途牛 MCP | 酒店/机票/门票行情价 | [openapi.tuniu.cn](https://openapi.tuniu.cn) |

> API Key 未配置时，系统自动降级到内置参考数据（stub 模式）。

### 运行测试

```bash
# 运行全部测试 (661 tests)
venv/Scripts/python.exe -m pytest tests/ -v

# 运行单个模块
venv/Scripts/python.exe -m pytest tests/test_real_cases.py -v
```

### 端到端使用

```python
import asyncio
from dotenv import load_dotenv
load_dotenv()

from agents.orchestrator import Orchestrator

async def main():
    orch = Orchestrator()
    result = await orch.process_request(
        "去日本东京5天，2026-12-20出发2026-12-25返回，"
        "2个人，预算15000元，喜欢美食和文化体验"
    )
    print(f"评分: {result['summary']['overall_score']}")
    print(f"降级: {result['summary']['degraded']}")
    for day in result["daily_itinerary"]:
        print(f"\nDay {day['day']}:")
        for act in day["activities"]:
            print(f"  [{act['type']}] {act['name']}")

asyncio.run(main())
```

## 项目结构

```
├── agents/              # 业务 Agent 实现
│   ├── orchestrator.py  # 主控编排器
│   ├── planning_agent.py   # 行程规划 (LLM)
│   ├── execution_agent.py  # 可行性验证 (API tools)
│   └── evaluation_agent.py # 质量评估
├── core/                # 框架内核
│   ├── message.py       # Agent 通信协议
│   ├── context.py       # 共享上下文 (黑板)
│   ├── gate_runner.py   # Quality Gate 0-3
│   ├── orchestration_engine.py  # 任务分解/路由/组装
│   ├── llm_client.py    # DeepSeek LLM 客户端
│   └── config.py        # API 配置中心
├── models/              # 数据模型
│   ├── request.py       # StructuredRequest
│   ├── plan.py          # TravelPlanDraft / FinalTravelPlan
│   ├── validation.py    # ValidationReport
│   ├── quality.py       # PlanQualityReport
│   └── entities.py      # Attraction / Restaurant / Hotel
├── tools/               # 外部 API 工具集 (双轨架构)
│   ├── price_checker.py # 途牛 MCP (酒店/机票/门票价格)
│   ├── geo_checker.py   # 高德地图 (地理编码/绕路检测)
│   ├── time_checker.py  # 高德地图 (路径规划/交通时间)
│   └── risk_checker.py  # 天气/签证/安全风险
├── tests/               # 测试 (661 tests)
├── spec/                # 系统/模块规格
├── playbooks/           # Agent 操作手册
├── evaluation/          # 评估准则/质量门/消融协议
├── devagents/           # 开发 Agent 约束 (Pipeline)
└── progress/            # 进度碎片 + 经验记录
```

## 质量门系统

| Gate | 阶段 | 通过条件 |
|------|------|----------|
| Gate 0 | 用户输入后 | 必填项完整（目的地/日期/预算/人数） |
| Gate 1 | 执行验证后 | blocking_issues == 0 |
| Gate 2 | 评估反馈后 | composite_score ≥ 80，或 ≥ 60 且迭代 ≤ 3 |
| Gate 3 | 最终输出前 | 格式完整 + 必填字段 = 100% |

## 开发工作流 (5 Round Protocol)

```
R1 Context → R2 Plan → R3 Execute → R4 Test → R5 Verify → R5.5 Lessons
```

详见 [CLAUDE.md](CLAUDE.md) 和 [devagents/](devagents/)。

## 版本路线

| 版本 | 里程碑 |
|------|--------|
| v1.0.0 | 基础框架：4 Agent + 4 Gate + stub 数据 |
| **v1.1.0** | **API 全链路接入：DeepSeek + 高德 + 途牛 MCP** |
| v1.2.0 | (计划) Agent 质量升级 — Memory · Reasoning · Protocol · Architecture · Evaluation |

## License

MIT
