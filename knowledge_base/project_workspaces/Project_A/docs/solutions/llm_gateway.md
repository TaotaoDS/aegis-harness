# LLM Gateway - 设计决策与防坑总结

## 概述

在 `core_orchestrator/` 中实现了极简 LLM 网关，将 PII 脱敏中间件与 LLM 调用串联为完整工作流：

```
user_input -> sanitizer 脱敏 -> [token 溢出检查 -> 历史压缩] -> mock LLM -> response
```

## 设计决策

### 1. 依赖注入，不硬编码

`LLMGateway` 构造函数接收五个可选参数：
- `sanitizer: Sanitizer` — 默认使用 `default_pipeline()`
- `llm: Callable[[str], str]` — 默认使用 echo mock
- `summarizer: Callable[[str], str]` — 历史超限时的总结回调，默认截断
- `max_tokens: int` — token 上限，默认 8192
- `threshold: float` — 触发压缩的比例，默认 0.85

**理由**: 所有行为均可通过构造函数注入，未来接入真实 LLM API 或 LLM 摘要服务时，无需修改 gateway 代码。

### 2. 返回结构化 dict 而非纯字符串

`send()` 返回 `{"original_input", "sanitized_input", "llm_response"}`，保留原始输入和脱敏中间结果。

**理由**: 便于调试和审计。调用方可以对比原始输入和脱敏结果，确认 PII 确实被移除。未来接入日志系统时，只需记录 `sanitized_input`，不记录 `original_input`。

### 3. Mock LLM 使用 echo 而非空实现

`_mock_llm` 直接返回输入文本，而不是返回固定字符串或空字符串。

**理由**: echo 行为让测试可以断言"LLM 收到的确实是脱敏后的文本"（`llm_response == sanitized_input`），这是最核心的安全不变量。

### 4. 复用已有 Sanitizer 类型

Gateway 的 sanitizer 参数类型就是 Phase 1 定义的 `Callable[[str], str]`，无需新接口。

### 5. Token 溢出两阶段压缩策略

历史记录每次 `send()` 后检查 token 预算：

1. **主阈值检查**: 用 `tiktoken`（cl100k_base 编码）精确计算历史总 token 数
2. **触发条件**: 当 token 数 >= `max_tokens * threshold`（默认 85%）
3. **第一阶段 — summarizer 压缩**: 保留最近一轮对话（最后 2 条），将更早的历史交给 `summarizer` 回调处理，结果替换旧记录
4. **第二阶段 — 硬截断兜底**: 若 summarizer 返回结果仍超限（例如最近一轮本身就很长），用 `len(text)//4` 快速字符估算截断点，对 summary 做硬截断并标记 `[TRUNCATED]`

**理由**: 两阶段设计确保不会出现无限循环，同时给 summarizer 优先处理权。快速估算仅用于兜底截断点定位，不用于阈值判断。

### 6. 历史记录只存脱敏后文本

`history` 中只保存经过 sanitizer 处理的文本和 LLM 响应，绝不存原始输入。

**理由**: 避免 PII 在内存中留存，即使被总结/截断也不会泄露原始数据。

## 踩坑记录

### 坑 1: while 循环压缩导致无限循环

- **现象**: 当 `max_tokens` 很小（如 50）时，即使压缩到只剩 3 条记录（summary + 最近 1 轮），总 token 仍超阈值。`while len(history) > 2` 条件永远为 true（=3），_compress_history 反复将 summary 交给 summarizer 但无法减少足够 token
- **根因**: _default_summarizer 保留 800 字符，当最近一轮对话本身就接近或超过 token 上限时，压缩 summary 无济于事
- **修复**: 去掉 while 循环，改为"一次 summarizer 压缩 + 一次硬截断兜底"的两阶段策略。硬截断用 `len//4` 字符估算精确计算 summary 可用预算
- **教训**: 任何带 `while` 的压缩循环都必须有明确的终止保证。当不可压缩部分（最近一轮）已超预算时，循环永远无法收敛

## 文件清单

| 文件 | 用途 |
|---|---|
| `core_orchestrator/llm_gateway.py` | 网关实现 (LLMGateway 类 + mock LLM) |
| `core_orchestrator/tests/test_llm_gateway.py` | 21 个测试用例（含 token 溢出） |
| `core_orchestrator/__init__.py` | 公共 API 导出（新增 LLMGateway） |

## 未来扩展路径

```python
# 接入真实 LLM
from anthropic import Anthropic
client = Anthropic()

def call_claude(text: str) -> str:
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": text}],
    )
    return msg.content[0].text

# 用 LLM 做摘要而非截断
def llm_summarizer(text: str) -> str:
    return call_claude(f"请用一段话总结以下对话历史:\n{text}")

gw = LLMGateway(
    llm=call_claude,
    summarizer=llm_summarizer,
    max_tokens=4096,
)
result = gw.send("我的邮箱是user@test.com")
# PII 已脱敏，历史自动压缩，Claude 永远看不到真实邮箱
```

## 依赖

- `tiktoken` — 精确 token 计数（主阈值检查）
- Python stdlib — 其余全部
