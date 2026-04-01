# PII Sanitization Middleware - 设计决策与防坑总结

## 概述

在 `core_orchestrator/` 中实现了极简 PII 脱敏中间件，满足 AGENTS.md 第 3 节"PII 脱敏"要求。

## 设计决策

### 1. 纯函数接口，不用类继承

- 接口定义: `Sanitizer = Callable[[str], str]`
- 任何 `str -> str` 函数都是合法 sanitizer，无需导入或继承
- `compose()` 返回的组合结果本身也是 `Sanitizer`，支持嵌套组合

**理由**: 这是最简单的可组合接口。类继承在此场景下增加复杂度但不增加功能。

### 2. 模块级编译正则

所有正则在模块加载时用 `re.compile()` 编译一次，避免每次调用重复编译。

### 3. Pipeline 顺序: id_card 在 credit_card 之前

中国身份证号为 18 位数字，会被信用卡正则（13-19位）部分匹配。先脱敏身份证号，再处理信用卡，避免双重/错误匹配。

## 踩坑记录

### 坑 1: `\b` 在中文环境下失效

- **现象**: `\b` 是 ASCII 单词边界，中文字符（如全角逗号 `，`）不被视为 word boundary，导致紧邻中文的邮箱地址无法匹配
- **例子**: `"邮箱user@test.com，电话..."` 中的邮箱未被检测
- **修复**: 将 `\b...\b` 替换为显式负向断言 `(?<![A-Za-z0-9._%+-])...(?![A-Za-z])`
- **教训**: 涉及中文/多语言文本时，避免使用 `\b`，改用明确的字符集断言

## 文件清单

| 文件 | 用途 |
|---|---|
| `core_orchestrator/pii_sanitizer.py` | 全部生产代码 (4 个 sanitizer + compose + default_pipeline) |
| `core_orchestrator/tests/test_pii_sanitizer.py` | 30 个测试用例 |
| `core_orchestrator/__init__.py` | 公共 API 导出 |

## 扩展指南

添加新的 PII 类型只需:
1. 在 `pii_sanitizer.py` 中添加一个新的 `sanitize_xxx()` 函数
2. 将其加入 `default_pipeline()` 的 `compose()` 调用中（注意顺序）
3. 在测试文件中添加对应测试类
