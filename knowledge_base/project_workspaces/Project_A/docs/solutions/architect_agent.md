# Architect Agent - 设计决策与防坑总结

## 概述

在 `core_orchestrator/` 中实现了架构师智能体，作为 CEO → Architect 流水线的第二级。从 Workspace 的 `tasks/` 读取子任务，调用 LLM 生成技术方案，写入 `artifacts/`。

```
CEO 写入                      Architect 读取 & 生成                下游消费
tasks/task_1.md  ──read──>  LLM 生成方案  ──write──>  artifacts/task_1_solution.md
tasks/task_2.md  ──read──>  LLM 生成方案  ──write──>  artifacts/task_2_solution.md
```

## 设计决策

### 1. 无状态执行器，不用状态机

CEO 是状态机（idle → interviewing → planning → delegating → done），因为它管理多阶段交互流程。Architect 只做"读 → 生成 → 写"，每次 `solve_task()` 调用彼此独立，不需要状态管理。

**理由**: 无状态设计让 Architect 可以被并发调用、重试单个任务、或部分执行（只解决某些任务），而不会产生状态一致性问题。

### 2. 自动注入 plan.md 上下文

如果 Workspace 中存在 `plan.md`（CEO 写入），Architect 会自动将其注入 LLM prompt 的 "Project Plan" 部分。

**理由**: 每个子任务在整体计划的上下文中才有完整语义。例如 task_2 可能依赖 task_1 的设计决策，plan.md 提供了这个全局视角。

### 3. `list_tasks()` 只匹配 `tasks/*.md`

过滤条件：路径以 `tasks/` 开头且以 `.md` 结尾。忽略 `.gitkeep`、`.txt` 等非任务文件。

**理由**: 明确的约定（Convention over Configuration）。CEO 的 `delegate()` 输出格式固定为 `tasks/{id}.md`，Architect 只需匹配这个模式。

### 4. Artifact 文件包含来源引用

每个 `artifacts/task_N_solution.md` 的头部包含：

```markdown
# Solution: task_1
## Source Task
`tasks/task_1.md`
```

**理由**: 可追溯性。审查 artifact 时可以立即定位到原始任务，不需要靠文件名猜测对应关系。

### 5. 命名约定: `{task_id}_solution.md`

从 `tasks/task_1.md` 提取 `task_1`，生成 `artifacts/task_1_solution.md`。

**理由**: 一对一映射，且文件名排序后与任务顺序一致。

## 踩坑记录

本次实现 16 个测试一次全绿，无踩坑。归因于：
- 无状态设计，逻辑路径极少
- 复用 WorkspaceManager 的路径安全机制
- 复用 LLMGateway 的 PII 脱敏 + token 管理

## 文件清单

| 文件 | 用途 |
|---|---|
| `core_orchestrator/architect_agent.py` | ArchitectAgent 实现（3 个公共方法） |
| `core_orchestrator/tests/test_architect_agent.py` | 16 个测试用例 |

## CEO → Architect 端到端示例

```python
from core_orchestrator import (
    CEOAgent, ArchitectAgent, LLMGateway, WorkspaceManager,
)

wm = WorkspaceManager("./workspaces")
wm.create("project_alpha")
gw = LLMGateway(llm=real_llm_fn)

# CEO: 面试 → 规划 → 委派
ceo = CEOAgent(gateway=gw, workspace=wm, workspace_id="project_alpha")
ceo.start_interview("构建用户管理系统")
# ... 面试若干轮 ...
ceo.create_plan()
ceo.delegate()
# → tasks/task_1.md, tasks/task_2.md, tasks/task_3.md

# Architect: 逐个生成技术方案
arch = ArchitectAgent(gateway=gw, workspace=wm, workspace_id="project_alpha")
artifacts = arch.solve_all()
# → artifacts/task_1_solution.md, artifacts/task_2_solution.md, ...
# 每个 artifact 包含具体代码和技术方案
```
