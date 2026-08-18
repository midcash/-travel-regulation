# M3 knowledge.py 兼容迁移

## 决策

`src/tool/knowledge.py` 仅保留临时兼容 Facade。它接收组合根已经装配完成的
Provider Port、`Clock`、`trace_id`、显式超时预算，以及旧同步入口所需的执行器；它不
读取环境变量、不创建 `Settings`、Adapter、默认 Key、Fake 或事件循环，也不执行重试、
缓存或供应商切换。

旧的 `TOOL_EXECUTORS` 和工具 Schema 名称继续可用，并保持同步返回值。组合根必须为
旧入口显式注入同步执行器，再通过 `configure_legacy_facade()` 安装 `KnowledgeFacade`；
Facade 不创建事件循环。未安装 Facade、未注入执行器或缺少能力都会抛出
`ToolConfigurationError`。Provider 的类型化错误原样向上传播。

旧 `SYSTEM_PROMPT` 中的硬编码“今天”已删除。Facade 为每个兼容调用通过注入的
`Clock` 生成查询标识，不读取系统时间。

## 当前调用者

截至 M3 第 11 步，仓库内没有生产代码导入 `src.tool.knowledge`。仅以下兼容测试
引用该模块：

- `tests/unit/test_knowledge_entrypoints.py`
- `tests/unit/test_knowledge_failures.py`

新模块必须依赖 Provider Port、Evidence Registry 和 Candidate Pool，禁止新增对
`src.tool.knowledge` 的导入。

## 当前实现限制

旧门票入口保留 `(scenic, city)` 签名，但现有 M3 `PlaceQuery` 与途牛 Adapter 只
支持以景点名作为 `destination` 的 `ticket` 查询，无法传递旧接口的城市字段。Facade
仍校验该字段并将其纳入查询标识，避免静默丢弃输入；M4 不应继续使用此入口，而应从
结构化约束构造新的 `PlaceQuery`。

## M4 删除计划

当 M4 Research Agent 已直接通过 Provider Port 查询，并将结果写入 Evidence Registry
与 Candidate Pool 后：

1. 确认生产代码对 `src.tool.knowledge` 的导入仍为零；
2. 将遗留测试改为 Agent/Port 层测试；
3. 删除 `src/tool/knowledge.py`、其兼容测试以及本迁移说明中的临时入口描述。

在以上条件未满足前，Facade 只作为 M3 兼容边界，不得成为新功能依赖。
