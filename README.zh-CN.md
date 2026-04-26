# AegisHarness

**v0.1.0** · 生产级 AI Agent Harness — 为 LLM 工作流提供确定性的身份认证、多租户隔离、语义记忆持久化与 MCP 工具管理。

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/) [![Next.js 15](https://img.shields.io/badge/next.js-15-black)](https://nextjs.org/) [![PostgreSQL 16](https://img.shields.io/badge/postgresql-16-336791)](https://www.postgresql.org/) [![测试 598](https://img.shields.io/badge/测试-598%20全部通过-brightgreen)]() [![License MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](./README.md) | 中文

---

[产品定位](#产品定位) · [核心特性](#核心特性) · [系统架构](#系统架构) · [快速开始](#快速开始) · [配置说明](#配置说明) · [项目结构](#项目结构) · [开发指南](#开发指南) · [贡献指南](#贡献指南)

---

## 产品定位

大语言模型本质上是概率性的——它会产生幻觉、遗忘上下文，且对"谁在提问"毫无概念。**AegisHarness 是让 LLM 驱动的 Agent 达到生产就绪状态的基础设施层。**

可以把它理解为赛车引擎外的保护框架：引擎（LLM）本身动力强劲但难以驾驭，而 Harness 提供了车架、转向和安全系统——让动力真正可控、可用。具体而言，AegisHarness 为任意 LLM 后端提供：

| 裸 LLM 缺少的能力 | AegisHarness 提供的解决方案 |
|---|---|
| 没有身份认证 | JWT 多租户——每个请求都绑定到已验证的用户和隔离的租户 |
| 没有记忆 | 语义向量检索历史解决方案——Agent 从过往经验中学习，而不只是依赖当前上下文窗口 |
| 没有工具 | 热插拔 MCP 工具管理器——Agent 调用外部服务无需重启 |
| 没有容错机制 | 三层故障恢复循环——单次模型失败不会终止整个流水线 |

最终的结果是：**在非确定性的核心外套上确定性的 Harness**——你掌控工作流，LLM 只负责写代码。

---

## 核心特性

### 一、企业级多租户与安全体系

系统中的每一个资源——任务（job）、解决方案（solution）、配置（settings）、MCP 服务器——都绑定到一个 `tenant_id`。v0.1.0 的 Sprint A–D 完整交付了基于 JWT 的认证体系与全面的行级数据隔离。

| 能力 | 说明 |
|---|---|
| Token 设计 | HS256 JWT 访问令牌（15 分钟有效期）+ 不透明 UUID 刷新令牌（7 天有效期，以 bcrypt 哈希存储）|
| Cookie 传输 | `aegis_access` + `aegis_refresh`——均为 `httpOnly`，防 CSRF |
| 角色体系 | `owner` / `admin` / `member`，路由级守卫（`require_admin`、`require_owner`）|
| 行级数据隔离 | 所有表均含 `tenant_id`；settings 表主键为 `(tenant_id, key)`——每个租户拥有独立配置 |
| 邀请流程 | Owner 生成一次性邀请 token，受邀者自主注册并加入同一租户 |
| 向后兼容 | 历史数据自动回填至 `BOOTSTRAP_TENANT_ID`，零迁移成本 |
| API 密钥加密 | Fernet 对称加密静态存储；界面仅显示末四位 |
| **DEV_MODE** | 当 `SECRET_KEY` **未设置**时，认证全部绕过。后端返回合成的 `dev@localhost` Owner 账号，前端永不跳转至 `/login`。零配置即可评估全部功能。|

### 二、BYOM — 自带模型（17 家供应商）

每次 LLM 调用均经过 YAML 配置的 `ModelRouter` 路由。切换模型只需修改 `models_config.yaml` 中的一行——无需改代码，无需重启服务。

所有供应商共用一个纯 `urllib` 连接器——除 `requirements.txt` 中已有的 `openai` 和 `anthropic` 两个官方 SDK 外，无需安装任何额外依赖。

**全球（7 家）**

| 供应商 | 说明 |
|---|---|
| Anthropic | Claude Sonnet、Claude Opus |
| OpenAI | GPT-4o 及任意 OpenAI 兼容端点 |
| Google Gemini | 通过 OpenAI 兼容代理接入 |
| Mistral AI | 通过 OpenAI 兼容端点接入 |
| Groq | 通过 OpenAI 兼容端点接入 |
| xAI（Grok）| 通过 OpenAI 兼容端点接入 |
| Together AI | 通过 OpenAI 兼容端点接入 |

**中国生态（8 家）**

| 供应商 | 说明 |
|---|---|
| DeepSeek | V3 / R1 推理模型 |
| 阿里云通义千问 | Qwen-Long / Qwen-Max |
| 智谱 GLM | GLM-5、GLM-5-Turbo、GLM-4.7 |
| Moonshot / Kimi | 8k / 128k 超长上下文 |
| 百度文心 ERNIE | 通过 OpenAI 兼容代理接入 |
| MiniMax | 通过 OpenAI 兼容端点接入 |
| 零一万物（Yi）| 通过 OpenAI 兼容端点接入 |
| 字节豆包（Doubao）| 通过 OpenAI 兼容端点接入 |

**本地 / 离线（3 种）**

| 方式 | 说明 |
|---|---|
| **Ollama** | 完全离线运行；向量嵌入后端同样只使用 `urllib`——零网络依赖 |
| **vLLM** | 自托管 OpenAI 兼容服务器 |
| 任意 OpenAI 兼容接口 | 在 `models_config.yaml` 中配置 `base_url` 即可 |

本地供应商无需 API Key，仅需提供端点 URL 与模型标识符。

### 三、高性能并发调度与三层容错恢复

编排器将每个项目分解为带依赖关系的任务图，并将独立任务以并行波次执行。

**调度策略——Kahn BFS（`parallel_executor.py`）**

```
任务依赖图  →  wave_schedule()  →  [ [A], [B, C], [D] ]
                                        ↑     ↑       ↑
                                     第1波  第2波   第3波
```

`wave_schedule()` 使用 Kahn 算法的 BFS 实现对任务进行拓扑排序，生成并发波次。`ParallelExecutor` 将每个波次提交至 `ThreadPoolExecutor`，等待所有 Future 完成后再推进至下一波次。循环依赖会被检测并抛出清晰的 `ValueError`。

**三层容错恢复（`resilience_manager.py`）**

| 层级 | 触发条件 | 处理动作 |
|---|---|---|
| **第一层——上下文重置** | 首次代码审查失败 | 注入评估器反馈，以相同模型重试 |
| **第二层——模型升级** | 第二次连续失败 | 切换至更高级别的 `escalated_tool_llm` |
| **第三层——人工介入** | 第三次失败**或** token 预算使用率 ≥ 80% | 将升级报告写入工作空间，暂停等待 HITL 审批 |

所有 LLM 调用还额外包装了 `tenacity` 指数退避重试（1 s → 60 s，最多 4 次）。若 `tenacity` 未安装，调用将执行一次且不抛出任何导入错误——零副作用。

### 四、MCP 工具动态管理

MCP（Model Context Protocol）服务器为 Agent 扩展了外部工具能力——网页搜索、代码执行、数据库查询等。

- **热插拔**：通过设置界面或 REST API 添加、更新或删除服务器，无需重启。
- **租户独立注册表**：每个租户维护独立的服务器列表，持久化于 settings 表，重启后懒加载恢复。
- **零依赖探测**：`POST /mcp/servers/{id}/probe` 通过 `urllib.request` 发现可用工具——无需额外 HTTP 库。

```bash
# 注册工具服务器
curl -X POST http://localhost:8000/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "my-tools", "url": "http://localhost:9000"}'

# 探测连通性并发现可用工具
curl -X POST http://localhost:8000/mcp/servers/{id}/probe
```

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│  浏览器（Next.js 15 · App Router · Tailwind CSS）               │
│                                                                  │
│  Shell.tsx ──► 路由守卫（useAuth）                               │
│  /chat     ──► SSE 事件流 ──► MessageBubble / Timeline          │
│  /settings ──► APIKeysTab · ModelsTab · MCPTab · ProfileTab     │
│  /login /register /invite/[token]   （公开路由）                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │  HTTPS + httpOnly Cookie
                            │  /api/proxy/**（携带 Cookie 的反向代理）
┌───────────────────────────▼─────────────────────────────────────┐
│  FastAPI（Uvicorn · 2 workers · async）                         │
│                                                                  │
│  /auth        注册 · 登录 · 刷新 · 邀请 · 个人信息              │
│  /jobs        创建 · 列表 · 详情 · 取消                         │
│  /jobs/{id}/stream   SSE 流（每 15 秒保活心跳）                  │
│  /approvals          HITL 人工审批门                            │
│  /settings           API 密钥 · 模型配置（按租户隔离）           │
│  /mcp                服务器 CRUD + 探测                         │
│                                                                  │
│  Lifespan: init_db() · _recover_jobs_from_db() · close_db()    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  核心编排器（纯 Python · 无框架依赖）                            │
│                                                                  │
│  CEOAgent          （≥95% 置信度需求访谈）                      │
│    └─► ArchitectAgent  （Tool-Use 代码生成）                    │
│          └─► Evaluator     （ast · pyflakes · subprocess）      │
│                └─► QAAgent     （代码审查）                      │
│                      └─► ReflectionAgent（经验提炼）            │
│                                                                  │
│  ModelRouter       （YAML 路由 · 30 秒缓存 · ${VAR} 插值）      │
│  LLMConnector      （OpenAI / Anthropic 适配器 · urllib）       │
│  ParallelExecutor  （Kahn BFS 波次 · ThreadPoolExecutor）       │
│  ResilienceManager （三层升级 · token 预算熔断器）               │
│  MCPManager        （热插拔 · 租户独立 · urllib 探测）           │
│  VectorStore       （pgvector 写入 · Python 余弦相似度兜底）     │
│  SolutionStore     （YAML 经验库 · 工作空间级别）                │
│  PIISanitizer      （可组合脱敏流水线）                          │
└───────────────────────────┬─────────────────────────────────────┘
                            │  asyncpg · SQLAlchemy 2.0 异步
┌───────────────────────────▼─────────────────────────────────────┐
│  PostgreSQL 16 + pgvector                                       │
│                                                                  │
│  tenants · users · refresh_tokens · workspaces                  │
│  jobs · job_events · checkpoints                                │
│  solutions  （embedding JSONB 1536 维，为 pgvector v2 预留）    │
│  settings   主键：(tenant_id, key)                              │
└─────────────────────────────────────────────────────────────────┘
```

**请求流（成功路径）**

1. 浏览器携带 `aegis_access` Cookie 发送 `POST /api/proxy/jobs`。
2. Next.js 代理转发至 FastAPI；`get_current_user` 验证 JWT 并解析 `tenant_id`。
3. CEOAgent 进行结构化需求访谈，直至置信度 ≥ 95%。
4. ArchitectAgent 将工作分解为依赖图；`wave_schedule` 计算并发波次。
5. 每个波次并发执行；Evaluator + QAAgent 对每个任务设门；ResilienceManager 处理失败。
6. ReflectionAgent 将经验写入 SolutionStore；语义向量嵌入并更新至 pgvector。
7. SSE 流全程向浏览器实时推送事件。

完整的设计参考请见 [`ARCHITECTURE.md`](./ARCHITECTURE.md)。

---

## 快速开始

### 方式 A — Docker（推荐）

```bash
git clone <repo-url>
cd enterprise-harness

# 复制 Docker 环境模板。
# API Key 为可选项——请参阅下方 DEV_MODE 说明。
cp .env.docker .env

# 一键启动 postgres、后端、前端
docker compose up --build
```

| 服务 | 地址 |
|---|---|
| Web 控制台 | http://localhost:3000 |
| API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

> **DEV_MODE — 零回归保证**
>
> 若 `.env` 中**未设置** `SECRET_KEY`，后端将进入开发模式：
> 所有认证检查被绕过，每个请求均返回合成的 `dev@localhost` Owner 账号，
> 前端永不跳转至 `/login`。
>
> 无需任何 API Key 或凭证，即可使用多租户配置、MCP 工具、完整编排流水线、
> 语义记忆等所有功能。
>
> 如需启用生产级认证，请在 `.env` 中添加：
> ```bash
> SECRET_KEY=$(openssl rand -hex 32)
> ```

### 方式 B — 本地开发

前置依赖：Python 3.12+、Node 20+、PostgreSQL 16

```bash
# 1. Python 后端
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # 设置 DATABASE_URL 和 API Key
alembic upgrade head            # 执行全部 5 个 Schema 迁移

uvicorn api.main:app --reload --port 8000

# 2. Next.js 前端（另开一个终端）
cd web
npm install
npm run dev                     # http://localhost:3000
```

若未配置 `DATABASE_URL`，系统将以**纯文件模式**运行——完整编排功能可用，但不含数据库持久化与语义搜索。

### 方式 C — CLI（仅编排器，无 Web UI）

```bash
python main.py                                     # 新建工作空间 + 交互式 CEO 访谈
python main.py --workspace <id>                    # 恢复已有工作空间
python main.py --workspace <id> --update "修复 X"  # 增量更新运行
python main.py --workspace <id> --reset            # 清除检查点，从头重新运行
```

---

## 配置说明

### API 密钥

密钥可通过以下三种方式设置（优先级：DB 配置 > `.env` 文件 > 系统环境变量）：

1. **设置界面** → API Keys 标签页——读取时脱敏显示（仅显示末四位）。
2. **`.env` 文件**——启动时加载。
3. **系统环境变量**——适用于 Docker 和 CI 流水线。

| 变量名 | 供应商 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `OPENAI_API_KEY` | OpenAI GPT |
| `NVIDIA_API_KEY` + `NVIDIA_BASE_URL` | NVIDIA NIM |
| `DEEPSEEK_API_KEY` + `DEEPSEEK_BASE_URL` | DeepSeek V3 / R1 |
| `ZHIPU_API_KEY` + `ZHIPU_BASE_URL` | 智谱 GLM |
| `MOONSHOT_API_KEY` + `MOONSHOT_BASE_URL` | Moonshot / Kimi |

> 通过界面保存的密钥均以 Fernet 对称加密存储于数据库中，不会发送至任何第三方服务器。

### 模型路由（`models_config.yaml`）

```yaml
models:
  my-model:
    provider: openai               # "openai" 覆盖所有 OpenAI 兼容 API
    model_name: gpt-4o
    api_key_env: OPENAI_API_KEY    # 环境变量名，或 ${VAR} 内联插值
    base_url: null                 # null = 使用供应商默认端点
    max_tokens: 8192
    temperature: 0.2

routes:
  - match: { role: architect }
    model: my-model
  - match: {}                      # 兜底默认路由
    model: my-model

execution:
  max_retries: 3          # Architect 每个任务的最大重试次数
  eval_timeout: 30        # Evaluator 沙箱超时时间（秒）
  token_budget: 100000    # 每次流水线运行的全局 token 上限
  token_threshold: 0.8    # token 使用率 ≥ 80% 时触发人工升级

embedding:
  provider: openai                 # 设置 "ollama" 可完全离线运行
  model: text-embedding-3-small
  api_key_env: OPENAI_API_KEY
```

### 认证与多租户

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | _（未设置）_ | JWT 签名密钥。缺失 = DEV_MODE（绕过所有认证）。|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | 访问令牌有效期 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | 刷新令牌有效期 |

### 通过 Web 控制台配置

所有设置持久化至数据库，**修改后无需重启**。

| 标签页 | 功能说明 |
|---|---|
| 👤 用户画像 | 姓名、职位、技术水平——CEOAgent 据此自动调整访谈风格 |
| 🤖 CEO 配置 | Agent 显示名称 + 自定义系统提示词前缀 |
| 🔑 API Key | 供应商密钥管理（Fernet 静态加密，界面脱敏显示）|
| ⚡ 模型 | 默认路由模型选择 |
| 🔧 MCP 工具 | 注册 / 探测 / 删除 MCP 工具服务器 |

### 离线 / 断网部署

在 `models_config.yaml` 中设置 `embedding.provider: ollama`，并将所有模型路由指向本地 Ollama 或 vLLM 实例。向量嵌入客户端仅使用 Python 标准库 `urllib.request`——无需 OpenAI SDK，无需网络连接。

---

## 项目结构

```
enterprise-harness/
├── core_orchestrator/         # 纯 Python 业务逻辑（22 个模块 · 48 个测试文件）
│   ├── ceo_agent.py           # 需求访谈（≥95% 置信度阈值）
│   ├── architect_agent.py     # Tool-Use 代码生成
│   ├── qa_agent.py            # 代码审查 Agent
│   ├── evaluator.py           # 沙箱：ast · pyflakes · subprocess
│   ├── reflection_agent.py    # 经验提炼 → SolutionStore
│   ├── ce_orchestrator.py     # 流水线协调器（CEO→Architect→QA→Reflect）
│   ├── resilience_manager.py  # 三层升级 + token 预算熔断器
│   ├── parallel_executor.py   # Kahn BFS 波次调度 + ThreadPoolExecutor
│   ├── retry_utils.py         # 指数退避重试（tenacity 可选，优雅降级）
│   ├── model_router.py        # YAML 多供应商路由（30 秒 TTL 缓存）
│   ├── llm_connector.py       # OpenAI / Anthropic 适配器协议 + 注册表
│   ├── mcp_manager.py         # 热插拔 MCP 服务器注册表（urllib 探测）
│   ├── vector_store.py        # pgvector 写入 + Python 余弦相似度兜底
│   ├── solution_store.py      # YAML 经验库（工作空间级别）
│   ├── pii_sanitizer.py       # 可组合 PII 脱敏流水线（30 项测试）
│   └── tests/                 # 覆盖全部模块的 598 项 pytest 测试
│
├── api/                       # FastAPI 应用（8 个模块）
│   ├── main.py                # 应用工厂 · Lifespan 钩子 · CORS · 崩溃恢复
│   ├── auth.py                # JWT 创建/验证 · DEV_MODE 逻辑
│   ├── deps.py                # FastAPI Depends：CurrentUser · require_admin · require_owner
│   └── routes/                # auth · jobs · stream · approvals · interview · settings · mcp
│
├── db/                        # 数据库层
│   ├── models.py              # SQLAlchemy ORM（10 张表，含认证与工作空间）
│   ├── repository.py          # 异步 CRUD（15k 行）
│   ├── connection.py          # asyncpg 引擎 · Session 工厂
│   └── migrations/            # Alembic 迁移文件 001–005
│       ├── 001_initial_schema.py
│       ├── 002_add_embedding_column.py
│       ├── 003_add_auth_tables.py
│       ├── 004_add_workspaces.py
│       └── 005_tenant_scope_existing_tables.py
│
├── web/                       # Next.js 15 前端
│   ├── app/                   # App Router：仪表盘 · 对话 · 任务 · 设置 · 认证 · 初始化向导
│   ├── components/            # Shell · Sidebar · MessageBubble · InterviewPanel · Timeline
│   ├── lib/auth/              # AuthProvider · useAuth() · token 刷新
│   ├── lib/i18n/              # useT() 钩子 · en.ts · zh.ts（18 个已国际化组件）
│   └── hooks/                 # useEventStream（SSE · 自动重连 · 事件去重）
│
├── workspaces/                # 生成的代码产物（volume 挂载 · git-ignored）
├── knowledge_base/            # 精选经验库（预训练）
├── models_config.yaml         # LLM 路由配置
├── docker-compose.yml         # 生产部署栈（postgres · 后端 · 前端）
├── docker-compose.override.yml # 本地开发覆盖（热重载）
├── Dockerfile                 # 后端多阶段镜像（非 root 用户 harness uid 1000）
├── .env.example               # 环境变量模板
├── ARCHITECTURE.md            # 完整系统设计参考
└── AGENTS.md                  # Agent 操作手册
```

---

## 开发指南

### 运行测试

```bash
pytest                            # 全量 598 项测试
pytest core_orchestrator/tests/   # 仅运行编排器单元测试
pytest -k test_resilience         # 按名称过滤
pytest --cov=core_orchestrator --cov-report=term-missing  # 覆盖率报告
```

### 数据库迁移

```bash
alembic upgrade head                                   # 应用全部待执行迁移
alembic revision --autogenerate -m "描述本次变更"       # 生成新的迁移文件
alembic downgrade -1                                   # 回滚一个版本
alembic current                                        # 查看当前迁移版本
```

### 添加新的 LLM 供应商

1. 在 `models_config.yaml` 的 `models:` 下添加条目，使用 `provider: openai`。所有 OpenAI 兼容 API 无需任何代码改动即可使用。
2. 若供应商需要非标准认证方式，在 `core_orchestrator/llm_connector.py` 中实现 `LLMConnector` 协议，并调用 `register_connector("my-provider", MyConnector())` 注册。
3. 在 `.env.example` 中添加 API Key 环境变量，并更新初始化向导的供应商目录（`web/app/onboarding/providers.ts`）。

### SSE 事件参考

| 事件 | 关键 Payload 字段 | 说明 |
|---|---|---|
| `pipeline.start` | `job_id` | 流水线开始 |
| `agent.thinking` | `agent`、`message` | Agent 正在输出 |
| `task.complete` | `task_id`、`output` | 单个任务完成 |
| `hitl.required` | `task_id`、`reason` | 人工审批门触发 |
| `pipeline.complete` | `artifacts` | 全部任务完成，产物可用 |
| `pipeline.error` | `error` | 不可恢复的失败 |

---

## 贡献指南

**零副作用原则**——每次改动后，系统必须至少与改动前同等可用。

- **测试先行**：在修改生产代码前，先添加或更新测试。598 项测试套件是回归防线，所有测试必须在合并前通过。
- **优雅降级**：若引入可选依赖，系统在该依赖不可用时必须能正常运行。参考 `tenacity` 和 `pgvector` 的集成模式。
- **无全局状态**：所有变更均限定在工作空间或租户作用域内。线程安全仅保证在单个任务的执行上下文内。
- **维护 API 契约**：后端路由签名和 SSE 事件结构由前端消费。破坏性改动需同步更新两层。

Pull Request 需包含：
1. 问题描述与解决思路。
2. 新增行为的测试覆盖。
3. 在 `CHANGELOG.md` 的 `[Unreleased]` 下添加条目。

---

## 许可证

MIT
