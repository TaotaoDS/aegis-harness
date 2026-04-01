# CEO Orchestrator Agent - 设计决策与防坑总结

## 概述

在 `core_orchestrator/` 中实现了 CEO 编排器智能体，作为多智能体系统的顶层调度者。核心创新点是**逆向面试（Reverse Interview）机制**——接收需求后先主动提问澄清边界，而不是直接开始执行。

```
状态机: idle -> interviewing -> planning -> delegating -> done

idle ──start_interview()──> interviewing ──answer_question(done=true)──> planning
                                │                                          │
                          ask_question()                            create_plan()
                          用户回答追加上下文                          LLM 拆解子任务
                                                                   写 plan.md
                                                                         │
                                                              delegating ──delegate()──> done
                                                                   │
                                                              写 tasks/*.md
                                                              供下游 Agent 读取
```

## 设计决策

### 1. 状态机驱动，强制流程顺序

5 个状态（idle → interviewing → planning → delegating → done），每个方法在入口处校验当前状态，非法转换抛 `CEOStateError`。

**理由**: 防止调用方跳过面试直接 plan，或跳过 plan 直接 delegate。状态机是最简单的流程控制方式，比 flag 组合更不容易出错。

### 2. 逆向面试通过 JSON 协议与 LLM 通信

LLM 返回 `{"question": "...", "done": false/true}`：
- `done=false`: 继续提问
- `done=true`: 需求已锁定，进入 planning

**理由**: JSON 结构化输出比自然语言更容易解析，避免正则提取的脆弱性。同时给 LLM 明确的"结束面试"决策权。

### 3. 面试上下文累积传递

每轮面试将所有历史 Q&A 注入 system prompt，让 LLM 看到完整对话上下文后决定下一个问题。

```
Context so far:
- Q: Who are the users?
  A: Internal ops team
- Q: What's the deadline?
  A: End of Q2
```

**理由**: LLM 无状态，必须在 prompt 中显式传递历史。这也让每轮回答都能影响后续问题的方向。

### 4. 所有状态持久化到 Workspace

| 文件 | 写入时机 |
|---|---|
| `requirement.md` | `start_interview()` |
| `interview_log.md` | 面试结束时 |
| `plan.md` | `create_plan()` |
| `tasks/task_N.md` | `delegate()` |

**理由**: 复用已有的 `WorkspaceManager`，下游 Agent 通过文件读取任务，无需内存共享。即使 CEO 进程崩溃，已持久化的状态不丢失。

### 5. 复用 LLMGateway，不直接调 LLM

CEO 通过 `LLMGateway.send()` 与 LLM 交互，自动获得 PII 脱敏和 token 溢出管理。

**理由**: 已有的安全中间件栈（Phase 1-3）对所有 LLM 调用统一生效，CEO 不需要自己处理这些。

### 6. `answer_question()` 从 Gateway 历史恢复上一个问题

`answer_question()` 需要知道"上一个问题是什么"来记录 Q&A 对。通过读取 `gateway.history[-1]`（最近一次 LLM 响应）并解析 JSON 获取。

**理由**: 避免在 CEO 层额外维护"待回答的问题"状态。Gateway history 就是 single source of truth。

## 踩坑记录

本次实现 22 个测试一次全绿，无踩坑。归因于：
- 状态机模式清晰，每个方法职责单一
- LLM 交互通过 JSON 协议，mock 测试直接返回 JSON 字符串
- 复用已充分测试的 WorkspaceManager 和 LLMGateway

## 文件清单

| 文件 | 用途 |
|---|---|
| `core_orchestrator/ceo_agent.py` | CEOAgent 实现（状态机 + 面试 + 规划 + 委派） |
| `core_orchestrator/tests/test_ceo_agent.py` | 22 个测试用例 |

## 使用示例

```python
from core_orchestrator import CEOAgent, LLMGateway, WorkspaceManager

wm = WorkspaceManager("./workspaces")
wm.create("project_alpha")
gw = LLMGateway(llm=real_llm_fn)  # 或 mock
ceo = CEOAgent(gateway=gw, workspace=wm, workspace_id="project_alpha")

# 逆向面试
q = ceo.start_interview("构建一个内部数据分析平台")
print(q)  # "目标用户是谁？技术栈有什么偏好？"
q = ceo.answer_question("数据团队，偏好 Python + React")
print(q)  # "需要实时数据还是批处理？"
q = ceo.answer_question("批处理为主，T+1 即可")
# q is None → 面试结束

# 规划
plan = ceo.create_plan()
# → plan.md 已写入 workspace

# 委派
files = ceo.delegate()
# → tasks/task_1.md, tasks/task_2.md, ... 已写入
# 下游 Agent 读取 wm.read("project_alpha", "tasks/task_1.md") 即可开工
```
