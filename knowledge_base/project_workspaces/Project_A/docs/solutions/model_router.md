# Multi-Model Router (BYOM) - 设计决策与防坑总结

## 概述

在 `core_orchestrator/` 中实现了企业级多模型适配器与动态路由，支持从 YAML 配置按客户/任务维度选择模型，API Key 全部从环境变量读取。

```
LLMGateway(llm=router.as_llm(customer="enterprise", task="reasoning"))
    └── ModelRouter.resolve() → 匹配路由 → 选择模型
        └── ModelRouter.call() → 读 env API key → 调用 provider 适配器
```

## 设计决策

### 1. 零侵入桥接现有 Gateway

`as_llm(**context)` 返回 `Callable[[str], str]`，直接注入 `LLMGateway(llm=...)`。Gateway 的 sanitizer、token overflow 等逻辑完全不受影响。

**理由**: 遵循开闭原则——扩展新能力而不修改已有代码。

### 2. YAML 配置只存环境变量名，不存密钥

```yaml
models:
  claude-sonnet:
    api_key_env: ANTHROPIC_API_KEY   # 只是变量名
```

运行时通过 `os.environ[api_key_env]` 读取真实密钥。配合 `.env` + `.gitignore` 确保密钥不进版本控制。

**理由**: AGENTS.md 安全红线要求。即使 YAML 被泄露也不暴露密钥。

### 3. 路由规则顺序匹配 + 空 match 兜底

```yaml
routes:
  - match: { customer: "enterprise", task: "reasoning" }  # 最具体
    model: claude-opus
  - match: {}                                               # 兜底
    model: claude-sonnet
```

匹配逻辑：遍历 routes，`match` 中所有 key-value 都存在于 context 中则命中，第一个命中的胜出。

**理由**: 简单直观，规则优先级由声明顺序决定，无需额外权重字段。

### 4. Provider 适配器延迟导入

```python
def _adapter_openai(*, model_id, api_key, text, max_tokens):
    from openai import OpenAI    # 仅在实际调用时 import
    ...
```

**理由**: 不强制安装所有 SDK。只用 Anthropic 的客户不需要装 openai 包，反之亦然。

### 5. Provider 注册用 dict 而非 if/elif

```python
_ADAPTERS = {"openai": _adapter_openai, "anthropic": _adapter_anthropic}
```

**理由**: 新增 provider 只需添加一个函数 + 一行 dict 注册，不改路由逻辑。

## 踩坑记录

### 坑 1: patch 模块级函数不影响 dict 引用

- **现象**: `_ADAPTERS` dict 在模块加载时存了函数引用。`patch("module._adapter_openai")` 替换的是模块属性，但 dict 里仍指向原始函数，导致 mock 无效、触发真实 `from openai import OpenAI`
- **修复**: 改用 `patch.dict("module._ADAPTERS", {"openai": mock})` 直接替换 dict 中的值
- **教训**: 当函数通过 dict/list 间接引用时，patch 必须作用于容器本身，不能 patch 模块属性

## 文件清单

| 文件 | 用途 |
|---|---|
| `core_orchestrator/model_router.py` | 路由器实现 (ModelRouter + provider 适配器) |
| `core_orchestrator/models_config.yaml` | 模型/路由规则 YAML 配置 |
| `core_orchestrator/tests/test_model_router.py` | 26 个测试用例（全 mock，不发真实请求） |
| `.env.example` | API Key 占位模板 |
| `.gitignore` | 排除 .env 和缓存文件 |

## 使用示例

```python
from core_orchestrator import LLMGateway, ModelRouter

# 1. 创建路由器（自动从 .env 加载 API Key）
router = ModelRouter("core_orchestrator/models_config.yaml")

# 2. 按业务上下文生成 LLM callable
llm_fn = router.as_llm(customer="enterprise", task="reasoning")
# → 匹配到 claude-opus

# 3. 注入 Gateway（PII 脱敏 + token 管理自动生效）
gw = LLMGateway(llm=llm_fn)
result = gw.send("分析用户 zhang@corp.com 的行为")
# sanitized_input: "分析用户 [EMAIL_REDACTED] 的行为"
# llm_response: claude-opus 的真实回复
```

## 扩展指南

**新增 provider**:
1. 在 `model_router.py` 中添加 `_adapter_xxx()` 函数
2. 注册到 `_ADAPTERS` dict
3. 在 YAML 中使用 `provider: xxx`

**新增路由维度** (如 `region`):
- 直接在 YAML 的 `match` 中添加字段，代码无需改动
- 调用时传入: `router.as_llm(customer="vip", task="chat", region="cn")`
