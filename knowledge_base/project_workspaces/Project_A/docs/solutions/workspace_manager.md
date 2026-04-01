# Shared Workspace Manager - 设计决策与防坑总结

## 概述

在 `core_orchestrator/` 中实现了基于本地文件系统的共享工作区管理器，为多智能体协作提供持久化状态交换机制。

```
workspaces/
  ├── task_001/           # Agent A 的隔离沙盒
  │   ├── plan.md         # 任务计划
  │   ├── feedback.md     # 评审反馈
  │   └── artifacts/      # 生成物
  └── task_002/           # Agent B 的隔离沙盒
      └── ...
```

## 设计决策

### 1. 纯文件系统，不引入数据库

所有状态通过 `.md`、`.json`、`.txt` 等文件持久化，用 `pathlib` 操作。

**理由**: 极简原则。文件系统是最低依赖的持久化方案，可用 `cat`/`ls` 直接调试，且与 Git 版本控制天然兼容。

### 2. workspace_id 是扁平名称，不允许嵌套

`workspace_id` 不允许包含 `/`、`\\`、`..`，只能是单层目录名（如 `task_001`）。

**理由**: 防止工作区 ID 本身成为路径穿越向量。嵌套需求由文件名的子目录解决（如 `artifacts/report.txt`）。

### 3. 双层路径校验

```python
def _safe_path(self, workspace_id, filename=None):
    # 1. resolve() 消除符号链接和 ..
    # 2. startswith(base) 确保落在沙盒内
```

- **workspace 层**: `resolve()` 后检查是否在 `base_dir` 内
- **filename 层**: `resolve()` 后检查是否在 `workspace_dir` 内

**理由**: AGENTS.md 第 3 节"最小权限隔离"要求，也是 OWASP Path Traversal 防御的标准做法。

### 4. create() 是幂等的

重复创建同一个 workspace 不报错（`mkdir(exist_ok=True)`）。

**理由**: 多个智能体可能并发初始化同一工作区，幂等避免竞争条件。

### 5. list_files() 返回相对路径

返回相对于 workspace 根目录的路径列表，递归包含子目录文件。

**理由**: 调用方不需要知道绝对路径，只关心工作区内的文件结构。

## 踩坑记录

本次实现 27 个测试一次全绿，无踩坑。归因于：
- API 极简（6 个方法），逻辑直接映射到 `pathlib` 操作
- 路径安全在设计阶段就定义了专门的 `_safe_path()` 和 `_validate_workspace_id()`

## 文件清单

| 文件 | 用途 |
|---|---|
| `core_orchestrator/workspace_manager.py` | WorkspaceManager 实现（6 个公共方法） |
| `core_orchestrator/tests/test_workspace_manager.py` | 27 个测试用例 |

## 使用示例

```python
from core_orchestrator import WorkspaceManager

wm = WorkspaceManager("./workspaces")

# Agent A: 创建工作区并写入计划
wm.create("task_001")
wm.write("task_001", "plan.md", "# 计划\n1. 分析需求\n2. 编码\n3. 测试")

# Agent B: 读取计划并写入反馈
plan = wm.read("task_001", "plan.md")
wm.write("task_001", "feedback.md", "计划 LGTM，建议增加边界测试")

# 协调器: 查看工作区状态
files = wm.list_files("task_001")
# → ['feedback.md', 'plan.md']
```

## 多智能体协作模式

```
Orchestrator
  ├── create("task_X")
  ├── write("task_X", "plan.md", ...)
  │
  ├── Agent A: read("task_X", "plan.md") → 执行 → write("task_X", "result.md", ...)
  ├── Agent B: read("task_X", "result.md") → 评审 → write("task_X", "feedback.md", ...)
  │
  └── Orchestrator: list_files("task_X") → 汇总 → 决策
```
