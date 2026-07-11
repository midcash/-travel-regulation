# 系统目标：用户自然语言提旅行需求，系统自主决策调用多个业务 Agent，输出结构化行程草案。

# 唯一端到端用户故事：用户说“周末北京去上海两天，预算3000”，系统输出 JSON 行程。

# Agent 清单（4个业务 Agent + 1 个主 Orchestrator）：

Orchestrator：接收用户输入，自主决定调用哪些 Agent、何时结束。

PlannerAgent：生成行程草案。

ReviewerAgent：审查并打分/建议。

KnowledgeAgent：查询真实外部信息（天气、交通等）。

# 协作流程：Orchestrator 循环调用，直到决定输出或询问用户。

# 硬约束：全部使用真实 API，禁止任何 stub/mock；每个 Agent 是一个 .py 文件，函数签名尽量简单。
