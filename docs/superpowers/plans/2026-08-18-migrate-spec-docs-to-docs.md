# 将规格文档迁移到 docs 的实施计划

> 本计划用于一次性完成文档目录迁移，不引入新的规格驱动开发流程。

**目标：** 将 `.codex/rules` 下的项目架构、路线图、阶段文档、修订说明、ADR 和技术解析迁移到 `docs`，让 `.codex` 不再承载会被默认读取的大量业务文档。

**处理方式：** 保留文档内容和历史决策，改变文件位置；同步修改 `AGENTS.md` 及迁移后文档中的路径引用。开发约束改为按任务选择性查阅文档，最终以代码、测试和运行结果为准。

**验证方式：** 检查旧目录不再包含规格文档，搜索仓库中的旧路径和“必须阅读 Spec/Plan”的强制表述，确认迁移后的链接指向存在；不修改业务代码，不重跑外部 API。

## 迁移范围

- `.codex/rules/架构.md` → `docs/architecture/架构.md`
- `.codex/rules/roadmap/` → `docs/roadmap/`
- `.codex/rules/adr/` → `docs/adr/`
- `.codex/rules/技术文档解析/` → `docs/technical-notes/`
- `.codex/project-log/` → `docs/project-log/`
- `.codex/hooks.json` 和 `.codex/hooks/` 删除

## 执行步骤

- [x] 迁移上述文档目录，保留已有 `docs/adr` 内容。
- [x] 修改 `AGENTS.md` 的文档入口、阶段推进和规格驱动开发表述。
- [x] 修改迁移后文档中的旧路径引用，并把总架构文档的开发流程改成任务与测试驱动。
- [x] 搜索旧路径、旧目录和强制 SDD 表述，修复遗漏。
- [x] 检查 Git 状态和 Markdown 引用，确认没有业务代码变更。
