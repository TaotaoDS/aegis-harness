# AegisHarness

> **v0.0.2** — 多智能体代码生成与编排平台  
> 598 项测试全部通过 · 17 供应商 BYOM · 中英双语 · PostgreSQL + pgvector · Kahn BFS 波次调度 · SSE 流式对话 UI · MCP 动态工具管理器

[English](./README.md) | 中文

---

## AegisHarness 是什么？

AegisHarness 是一个生产级自主编码平台。你只需用自然语言描述需求，系统便会自动完成结构化需求访谈、任务分解、代码生成与沙箱验证，并从每一次错误中持续学习——构建一个随时间增长的语义记忆库，让后续每个项目都越来越聪明。

**核心执行循环**：
```
CEO 访谈 → 波次并行执行 → 反思复盘 → 语义记忆写入 → 下一次任务
```

---

## 快速开始

### 方式 A — Docker（推荐）

```bash
git clone <repo>
cd enterprise-harness
cp .env.docker .env       # 填写 API Key（参考 .env.example）
docker compose up --build
```

| 服务 | 地址 |
|---|---|
| Web 控制台 | http://localhost:3000 |
| API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

### 方式 B — 本地开发

**前置依赖**：Python 3.12+、Node 20+

```bash
# 后端
pip install -r requirements.txt
cp .env.example .env      # 填写 API Key
uvicorn api.main:app --reload --port 8000

# 前端（另开一个终端）
cd web
npm install
npm run dev
```

若未配置 `DATABASE_URL`，系统将以**纯文件模式**运行——所有功能正常，但不含数据库持久化与语义搜索。

---

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│              Web 控制台（Next.js 14）                 │
│  /chat  /jobs  /settings（画像/CEO/密钥/MCP）        │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────┐
│         AegisHarness API  v0.0.2  (FastAPI)          │
│  /jobs  /events (SSE)  /settings  /mcp/servers      │
│  Lifespan：DB 初始化 + 崩溃恢复                      │
└──────────────────────┬──────────────────────────────┘
                       │ Python async
┌──────────────────────▼──────────────────────────────┐
│             核心编排器（纯 Python）                   │
│                                                     │
│  CEOAgent ──► ResilienceManager ──► ReflectionAgent │
│                │                                    │
│                ├─ ParallelExecutor（Kahn BFS 波次）  │
│                ├─ RetryUtils（指数退避重试）          │
│                ├─ ArchitectAgent（Tool-Use LLM）     │
│                ├─ Evaluator（沙箱验证）               │
│                └─ QAAgent（代码审查）                │
│                                                     │
│  SolutionStore ◄──────────── VectorStore            │
│  （YAML 经验库）  语义检索    （OpenAI 向量）         │
│                                                     │
│  MCPManager  UserProfile  PIISanitizer  WorkspaceManager │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│       PostgreSQL 16 + pgvector（端口 5432）          │
│  jobs · events · checkpoints · solutions · settings  │
│  solutions.embedding  JSON float[1536]               │
└─────────────────────────────────────────────────────┘
```

完整设计参考请见 [`ARCHITECTURE.md`](./ARCHITECTURE.md)。

---

## v0.0.2 新特性

### BYOM — 自带模型（17 个供应商）

初始化向导全面重构，采用双栏布局：左侧边栏按组列出所有供应商，右侧面板提供三个自由输入字段——**API Key**、**Base URL（接入端点）** 和 **模型标识符**。无任何下拉菜单限制，完全按照各供应商官方文档填写即可。

| 分组 | 供应商 |
|---|---|
| **全球（7 个）** | Anthropic (Claude) · OpenAI · Google Gemini · Mistral AI · Groq · xAI (Grok) · Together AI |
| **中国（8 个）** | DeepSeek · 阿里云通义千问 · 智谱 GLM · Moonshot/Kimi · 百度文心 ERNIE · MiniMax · 零一万物（Yi）· 字节豆包（Doubao）|
| **本地（3 个）** | Ollama · vLLM · Custom（任意 OpenAI 兼容端点）|

本地供应商（`Ollama`、`vLLM`）无需填写 API Key，只需提供端点 URL 和模型名称。

配置过的供应商条目旁会出现绿色指示点，「下一步」按钮实时显示已完成配置的供应商数量 `(N)`。

### i18n — 自动语言检测

整个 Web 控制台根据 `navigator.language` 自动在**简体中文**与**英文**之间切换，顶部导航栏同时提供手动 中文 / EN 切换按钮。所有 18 个组件均已接入 `useT()` 国际化钩子，零硬编码字符串。

### PII 脱敏中间件

```python
from core_orchestrator import default_pipeline
pipeline = default_pipeline()
pipeline("联系我：alice@example.com 或 138-0000-0000")
# → "联系我：[EMAIL_REDACTED] 或 [PHONE_REDACTED]"
```

可组合式流水线，覆盖以下 PII 类型：邮箱地址、电话号码（中国手机号 / 美国格式 / 国际格式）、中国 18 位身份证号、信用卡号。30 项测试全部通过，涵盖边界值、中英混合文本及幂等性场景。

### 数据库配置步骤

在 API Key 配置与模型选择之间新增「连接 PostgreSQL 数据库」步骤（第 2 步 / 共 3 步）。若选择跳过，系统会弹出明确的降级模式警告。后端新增 `POST /settings/test_db_connection` 端点，实时测试连接并返回延迟及 `SELECT 1` 验证结果。

---

## 核心基础设施（v0.0.1）

### 1. PostgreSQL + pgvector 语义搜索

AegisHarness 将所有状态持久化到 PostgreSQL 16。`solutions` 表存储跨项目的经验教训，每条记录包含一个 1536 维 OpenAI 向量嵌入。

```python
# 任务成功后自动写入经验：
store.save({"problem": "...", "solution": "...", "type": "error_fix"})
await vs.upsert(solution_id, problem + " " + solution)   # 向量化并存储

# 规划下一个任务前自动检索：
context = store.semantic_search("async database pooling")  # 余弦相似度 top-5
```

- **嵌入模型**：`text-embedding-3-small`（1536 维）
- **相似度计算**：纯 Python 余弦距离——不依赖 pgvector PG 扩展
- **优雅降级**：当 `OPENAI_API_KEY` 或 `DATABASE_URL` 缺失时静默跳过，不影响其他功能

数据库 Schema 由 Alembic 管理：
```bash
alembic upgrade head   # 应用 001_initial_schema + 002_add_embedding_column
```

### 2. Kahn BFS 波次调度器 + ThreadPoolExecutor

任务在计划文件中声明依赖关系：
```markdown
- **Depends on:** task_1, task_2
```

`wave_schedule()` 使用 Kahn 拓扑排序的 BFS 实现将无依赖任务分组为并发波次：
```
depends_on = {"task_1": [], "task_2": ["task_1"], "task_3": ["task_1"], "task_4": ["task_2", "task_3"]}
waves      = [["task_1"], ["task_2", "task_3"], ["task_4"]]
```

`ParallelExecutor(workers=N)` 将每个波次提交给 `ThreadPoolExecutor`，等待所有 Future 完成后再推进。默认 `workers=1` 保持顺序执行，向后兼容。

### 3. SSE 流式对话 UI

`/chat` 通过 Server-Sent Events 提供实时对话界面：

- **阶段状态机**：`idle → creating → streaming → done | error`
- CEO 访谈问题渲染为带**可点击选项按钮**的对话气泡，便于非技术用户操作
- 系统事件（计划就绪、任务通过/失败、执行完成）以内联状态标签呈现
- 自动滚动、输入框自动伸缩、键盘快捷键（Enter 提交 / Shift+Enter 换行）

### 4. MCP 动态工具管理器

无需重新部署即可注册任意 MCP 兼容工具服务器：

```bash
# 通过 API 注册
curl -X POST http://localhost:8000/mcp/servers \
  -d '{"name": "my-tools", "url": "http://localhost:9000"}'

# 探测连通性并发现可用工具
curl -X POST http://localhost:8000/mcp/servers/{id}/probe
```

也可在 Web 控制台的 **设置 → 🔧 MCP 工具** 页面进行管理。注册信息在重启后保持持久。

### 5. 三层弹性机制 + 指数退避

所有 LLM 调用在遭遇瞬时错误（429、5xx、连接超时）时自动重试：
```
第 1 次 → 失败（RateLimitError） → 等待 1s
第 2 次 → 失败（503）           → 等待 2s
第 3 次 → 失败                  → 等待 4s
第 4 次 → 成功
```

Architect → QA 循环具备三层升级机制：
1. **上下文重置** — 注入失败反馈，以相同模型重试
2. **模型升级** — 切换至更高级别的模型
3. **人工升级** — 写入升级文件并通知操作人员

---

## 配置说明

### API Key（`.env`）

```bash
# ── 全球供应商（至少配置一个）────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...
GOOGLE_API_KEY=AIzaSy...
MISTRAL_API_KEY=...
GROQ_API_KEY=gsk_...
XAI_API_KEY=xai-...
TOGETHER_API_KEY=...

# ── 中国供应商 ────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...        # 阿里云通义千问
ZHIPUAI_API_KEY=...             # 智谱 GLM
MOONSHOT_API_KEY=sk-...         # Moonshot / Kimi
BAIDU_API_KEY=...               # 百度文心 ERNIE
MINIMAX_API_KEY=...
YI_API_KEY=...                  # 零一万物
ARK_API_KEY=...                 # 字节豆包 Doubao

# ── 本地供应商：无需 Key，在向导中配置 Base URL 即可 ─────────────────────
# Ollama 默认端点：http://localhost:11434/v1
# vLLM  默认端点：http://localhost:8000/v1

# ── PostgreSQL（可选，省略则以纯文件模式运行）─────────────────────────────
DATABASE_URL=postgresql://harness:harness_secret@localhost:5432/harness
```

> **提示**：以上所有配置均可通过首次启动时的初始化向导（`/onboarding`）完成。
> Key 仅保存在本地数据库中，不会发送至任何第三方服务器。

### 模型路由（`models_config.yaml`）

```yaml
# AegisHarness — 模型配置
roles:
  ceo:       claude-3-5-sonnet-20241022
  architect: gpt-4o
  qa:        gpt-4o-mini
  escalated: claude-3-5-opus-20241022

execution:
  max_retries: 3
  parallel_workers: 1
```

### 通过 Web 控制台配置

所有设置持久化到数据库，修改后**无需重启服务**：

| 标签页 | 功能说明 |
|---|---|
| 👤 用户画像 | 姓名、职位、技术水平——CEO 据此自动调整访谈风格 |
| 🤖 CEO 配置 | Agent 称呼 + 自定义系统提示词前缀 |
| 🔑 API Key | 供应商 API Key 管理（界面仅显示末四位脱敏内容）|
| ⚡ 模型 | 默认路由模型选择 |
| 🔧 MCP 工具 | 注册 / 探测 / 删除 MCP 工具服务器 |

---

## 项目结构

```
enterprise-harness/           ← 仓库根目录（AegisHarness v0.0.2）
├── core_orchestrator/        ← 业务逻辑（纯 Python）
│   ├── ceo_agent.py          ← 需求访谈 + 任务规划
│   ├── resilience_manager.py ← 三层升级 + 波次执行
│   ├── parallel_executor.py  ← Kahn BFS + ThreadPoolExecutor
│   ├── retry_utils.py        ← 指数退避重试（tenacity）
│   ├── pii_sanitizer.py      ← 可组合 PII 脱敏中间件（新增）
│   ├── vector_store.py       ← OpenAI 向量嵌入 + 余弦检索
│   ├── solution_store.py     ← YAML 经验库 + 语义桥接
│   ├── mcp_manager.py        ← MCP 服务器注册表
│   └── tests/                ← 598 项 pytest 测试
├── api/                      ← FastAPI 后端
│   ├── main.py               ← 应用工厂 + Lifespan + 崩溃恢复
│   └── routes/               ← jobs、stream、settings、mcp、approvals
├── db/                       ← 数据库层
│   ├── models.py             ← SQLAlchemy ORM（5 张表）
│   ├── repository.py         ← 异步 CRUD
│   └── migrations/           ← Alembic 迁移文件
├── web/                      ← Next.js 14 前端
│   ├── lib/i18n/             ← zh.ts + en.ts + React Context（新增）
│   ├── components/
│   │   ├── Nav.tsx           ← 带中英切换的顶部导航（新增）
│   │   └── Providers.tsx     ← LocaleProvider 客户端包装（新增）
│   └── app/
│       ├── chat/             ← SSE 流式对话 UI
│       ├── onboarding/
│       │   ├── providers.ts  ← 17 供应商目录 + 类型定义（新增）
│       │   └── components/   ← StepWelcome/APIKeys/Database/Model/Done
│       └── settings/         ← 五标签页设置面板
├── Dockerfile                ← 后端多阶段镜像
├── docker-compose.yml        ← postgres + backend + frontend
├── ARCHITECTURE.md           ← 完整系统设计参考
└── AGENTS.md                 ← Agent 操作手册
```

---

## 开发指南

### 运行测试

```bash
# 全量测试——所有提交前必须全部通过
python -m pytest core_orchestrator/tests/ -v

# 单模块测试
python -m pytest core_orchestrator/tests/test_resilience_manager.py -v

# 覆盖率报告
python -m pytest core_orchestrator/tests/ --cov=core_orchestrator --cov-report=term-missing
```

**当前状态**：**598 项测试，全部通过**（AegisHarness v0.0.2）。

### 数据库迁移

```bash
alembic upgrade head              # 应用全部待执行迁移
alembic revision -m "add_column"  # 创建新迁移文件
alembic current                   # 查看当前迁移版本
```

### CLI 用法

```bash
# 从终端运行完整流水线
python main.py --workspace my_project

# Update 模式（修改现有交付物）
python main.py --workspace my_project --update "为所有接口添加输入验证"

# 全新开始（丢弃检查点）
python main.py --workspace my_project --reset
```

---

## 贡献指南

1. **零副作用原则**：任何改动后，598 项测试必须全部通过。
2. **测试先行**：先写测试，再写实现。
3. **优雅降级**：每个新集成模块在其依赖不可用时必须静默跳过，不影响主流程。
4. 结构性改动前请先阅读 **`ARCHITECTURE.md`**。
5. 了解 Agent 操作规范和常见陷阱请阅读 **`AGENTS.md`**。

---

## 许可证

MIT
