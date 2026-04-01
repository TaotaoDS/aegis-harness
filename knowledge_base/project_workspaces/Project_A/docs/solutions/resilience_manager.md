# Resilience Manager - 设计决策与防坑总结

## 概述

在 `core_orchestrator/` 中实现了弹性管理器，监控 Architect-QA 交互循环并实施三层递进防御，防止死循环和资源耗尽。

```
ResilienceManager.run_task_loop("task_1")
  │
  ├─ Attempt 1: Architect(standard) → QA → FAIL
  │   └─ Layer 1: 创建全新 gateway（history 清零），注入 feedback
  │
  ├─ Attempt 2: Architect(standard, fresh) → QA → FAIL
  │   └─ Layer 2: 切换到 escalated_gateway_factory（高级模型）
  │
  ├─ Attempt 3: Architect(advanced) → QA → FAIL
  │   └─ Layer 3: 强制中断，写 escalation.md，请求人类介入
  │
  └─ (任何时刻) token_usage >= 80% budget → Layer 3 立即触发
```

## 三层防御机制

### Layer 1: Context Reset（第 1 次失败后）

- **动作**: 调用 `gateway_factory()` 创建全新 `LLMGateway` 实例
- **效果**: history 天然为空，Architect 被迫换思路而非在旧上下文中纠缠
- **为什么不是 `gateway.history.clear()`**: 工厂模式更干净，避免对 gateway 内部状态的假设

### Layer 2: Model Escalation（第 2 次失败后）

- **动作**: 切换到 `escalated_gateway_factory()`，返回配置了高级推理模型的 gateway
- **效果**: 从低成本模型（如 claude-sonnet）自动升级到高推理模型（如 claude-opus）
- **与 ModelRouter 的关系**: 调用方通过 `router.as_llm(task="reasoning")` 构建 escalated factory

### Layer 3: Graceful Degradation（第 3 次失败 OR token 预算 >= 80%）

- **动作**: 停止循环，写 `escalations/task_N_escalation.md` 请求人类介入
- **保留最佳产物**: 最后一次 Architect 生成的 artifact 保留在 `artifacts/` 中
- **Token 预算检查**: 每次 attempt 开始前检查，确保不会在超预算后继续浪费资源

## 设计决策

### 1. gateway_factory 而非固定 gateway

构造函数接收 `Callable[[], LLMGateway]` 而非 `LLMGateway` 实例。

**理由**: Layer 1 需要"创建全新 gateway"来实现 context reset。如果传入固定实例，清空 history 是侵入性操作且可能有副作用。工厂模式让每次 reset 都返回一个干净的对象。

### 2. QA 使用独立 gateway

QA 的 gateway 不受 Architect 的模型升级影响。

**理由**: QA 的审查标准应该一致——不能因为 Architect 升级了模型就降低审查门槛。独立 gateway 保证 QA 的判断独立于 Architect 的模型选择。

### 3. Token 追踪累加而非精确

每次 attempt 后遍历 gateway.history 累加 token 数。

**理由**: 精确追踪需要拦截每次 LLM 调用，但我们的 gateway 已有 history 记录。遍历 history 虽有重复计数风险（前几轮的 history 可能已被 token overflow 压缩），但作为预算预警已足够准确。过度精确不值得增加的复杂度。

### 4. escalation_level 记录在返回值中

每个任务的结果包含 `escalation_level`（0=无升级, 1=context reset, 2=model escalation, 3=人类介入）。

**理由**: 协调器需要知道任务的解决难度——全部 level 0 说明架构良好，频繁 level 2+ 说明任务拆解可能有问题，需要反馈给 CEO 调整。

## 踩坑记录

### 坑 1: escalated LLM 的 mock 索引独立

- **现象**: 测试 `test_best_artifact_preserved` 期望 attempt 3 的 artifact 包含 "v3 best"，但实际是 "v1"
- **根因**: `build_manager` 中 `esc_llm` 有独立计数器 `esc_idx` 从 0 开始。当 `escalated_architect_responses` 默认复用 `architect_responses` 时，attempt 3 取的是 `esc_responses[0]`（即 "v1"），不是 `[2]`
- **修复**: 显式传入 `escalated_architect_responses=["v3 best"]`
- **教训**: 多套 mock 共享响应列表但有独立索引时，必须意识到它们各自从 0 开始计数。这也验证了生产代码中 "escalated 是全新 gateway" 的设计正确性

## 文件清单

| 文件 | 用途 |
|---|---|
| `core_orchestrator/resilience_manager.py` | ResilienceManager（3 层防御 + token 预算） |
| `core_orchestrator/tests/test_resilience_manager.py` | 15 个测试用例 |

## 完整流水线（含弹性管理）

```python
from core_orchestrator import (
    LLMGateway, ModelRouter, WorkspaceManager,
    CEOAgent, ResilienceManager,
)

router = ModelRouter("core_orchestrator/models_config.yaml")
wm = WorkspaceManager("./workspaces")
wm.create("project_alpha")

# CEO 阶段
ceo_gw = LLMGateway(llm=router.as_llm(customer="enterprise"))
ceo = CEOAgent(gateway=ceo_gw, workspace=wm, workspace_id="project_alpha")
ceo.start_interview("构建用户管理系统")
# ... 面试 → 规划 → 委派 ...

# Architect-QA 弹性循环
rm = ResilienceManager(
    workspace=wm, workspace_id="project_alpha",
    gateway_factory=lambda: LLMGateway(llm=router.as_llm(customer="enterprise")),
    escalated_gateway_factory=lambda: LLMGateway(llm=router.as_llm(task="reasoning")),
    qa_gateway=LLMGateway(llm=router.as_llm(customer="enterprise")),
    token_budget=50000,
)
results = rm.run_all()
status = rm.status()
# status = {"completed": ["task_1", "task_2"], "escalated": ["task_3"], "token_usage": 12345}
```
