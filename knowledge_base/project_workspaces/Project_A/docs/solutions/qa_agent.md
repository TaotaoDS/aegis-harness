# QA Evaluator Agent - 设计决策与防坑总结

## 概述

在 `core_orchestrator/` 中实现了独立 QA 评审智能体，作为 CEO → Architect → **QA** 流水线的质量关卡。QA 绝不修改代码，只做"通过/拒绝"二元判定。

```
artifacts/task_1_solution.md ──LLM 审查──┬── PASS → approved/task_1_solution.md
                                         └── FAIL → feedback/task_1_feedback.md
                                                        ↓
                                                  Architect 重做
```

## 设计决策

### 1. 只判定，绝不修改

QA 的 PASS 路径是**复制原文**到 `approved/`，FAIL 路径是写**反馈文件**到 `feedback/`。永远不写入或修改 `artifacts/`。

**理由**: 职责分离。QA 是审查员不是开发者。修改代码的权力属于 Architect，QA 只提供判定和反馈。这也让审计变得容易：`approved/` 中的文件与 `artifacts/` 中的完全一致，可 diff 验证。

### 2. Feedback 文件结构化且可操作

```markdown
# QA Feedback: task_1

**Verdict:** FAIL
**Notes:** Major gaps.

## Issues
1. Missing authentication
2. No error handling

---
*Action required: Architect must rework this task.*
```

**理由**: Architect 读取 feedback 文件后能明确知道需要修什么。编号 issues 列表比自然语言段落更容易逐条处理。

### 3. `review_all()` 只审查有 artifact 的任务

扫描 `tasks/*.md`，过滤出同时有 `artifacts/{id}_solution.md` 的任务。没有 artifact 的任务被跳过（Architect 可能还没处理到）。

**理由**: 宽容部分完成状态。在真实流水线中，Architect 可能只完成了部分任务，QA 不应因为缺少 artifact 而整体报错。

### 4. `summary()` 累积追踪所有审查结果

`_results` 列表在每次 `review_task()` 后追加，`summary()` 返回 `{"passed": [...], "failed": [...], "total": N}`。

**理由**: 协调器需要全局视角来决定下一步——是全部通过可以发布，还是需要让 Architect 重做失败任务。

### 5. 缺少 task 或 artifact 抛 QAError

`review_task("task_1")` 要求 `tasks/task_1.md` 和 `artifacts/task_1_solution.md` 同时存在，任一缺失抛明确错误。

**理由**: Fail-fast。如果文件缺失说明上游流水线有问题，应该立即暴露而不是静默跳过。

## 踩坑记录

本次实现 18 个测试一次全绿，无踩坑。归因于：
- 审查逻辑是纯读取 + 判定 + 写入，无复杂状态管理
- JSON 协议与 CEO 一致，mock 测试模式已验证成熟

## 文件清单

| 文件 | 用途 |
|---|---|
| `core_orchestrator/qa_agent.py` | QAAgent 实现（3 个公共方法 + summary） |
| `core_orchestrator/tests/test_qa_agent.py` | 18 个测试用例 |

## 完整多智能体流水线

```
CEO (面试→规划→委派)
  └─ tasks/task_N.md

Architect (读任务→生成方案)
  └─ artifacts/task_N_solution.md

QA (审查方案)
  ├─ PASS → approved/task_N_solution.md    ✅ 可交付
  └─ FAIL → feedback/task_N_feedback.md    ❌ 返回 Architect 重做

Orchestrator 读 qa.summary() 决定:
  - 全部 pass → 完成
  - 有 fail → Architect.solve_task(failed_ids) → QA.review_task() → 循环
```
