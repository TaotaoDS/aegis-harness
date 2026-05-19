# AegisHarness

**v0.3.0** · 生产级 AI Agent Harness — 为 LLM 工作流提供确定性的身份认证、多租户隔离、语义知识图谱、生成式 UI、跨仓库融合分析、技能动态加载与 MCP 工具管理。

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/) [![Next.js 15](https://img.shields.io/badge/next.js-15-black)](https://nextjs.org/) [![PostgreSQL 16](https://img.shields.io/badge/postgresql-16-336791)](https://www.postgresql.org/) [![测试 1094](https://img.shields.io/badge/测试-1094%20全部通过-brightgreen)]() [![License MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](./README.md) | 中文

---

[产品定位](#产品定位) · [核心特性](#核心特性) · [系统架构](#系统架构) · [快速开始](#快速开始) · [配置说明](#配置说明) · [项目结构](#项目结构) · [开发指南](#开发指南) · [贡献指南](#贡献指南)

> **v0.3.0 新增功能** — Fusion Architect Agent 跨仓库架构分析、技能动态加载（知识→技能流水线）、LLM-as-Judge 质量门、深层上下文压缩（工具输出溢出 + LLM 摘要）、FinOps 计费引擎、沙箱隔离（ContentPreScreener + SandboxFactory）、安全护栏（PromptGuard + ContentModerator）。共 1094 项测试全部通过。

---

## 产品定位

大语言模型本质上是概率性的——它会产生幻觉、遗忘上下文，且对"谁在提问"毫无概念。**AegisHarness 是让 LLM 驱动的 Agent 达到生产就绪状态的基础设施层。**

可以把它理解为赛车引擎外的保护框架：引擎（LLM）本身动力强劲但难以驾驭，而 Harness 提供了车架、转向和安全系统——让动力真正可控、可用。具体而言，AegisHarness 为任意 LLM 后端提供：

| 裸 LLM 缺少的能力 | AegisHarness 提供的解决方案 |
|---|---|
| 没有身份认证 | JWT 多租户——每个请求都绑定到已验证的用户和隔离的租户 |
| 没有记忆 | 语义知识图谱 + 向量检索——Agent 从过往经验和文档中学习 |
| 没有工具 | 热插拔 MCP 工具管理器——Agent 调用外部服务无需重启 |
| 没有容错机制 | 三层故障恢复循环——单次模型失败不会终止整个流水线 |
| 没有人工监督 | HITL 审批门——敏感写入和升级操作暂停等待人工确认 |
| 没有会话连续性 | PostgreSQL 聊天记录——对话跨页面刷新持久化和恢复 |
| 没有质量保障 | LLM-as-Judge——在输出交付前进行幻觉/准确性/相关性评分 |
| 没有跨仓库学习 | Fusion Architect——克隆、分析并综合多个仓库的架构 |
| 没有可复用技能 | 技能动态加载——复合知识自动提升为可发现的 Markdown 技能 |

最终的结果是：**在非确定性的核心外套上确定性的 Harness**——你掌控工作流，LLM 只负责写代码。

---

## 核心特性

### 一、企业级多租户与安全体系

系统中的每一个资源——任务（job）、解决方案（solution）、配置（settings）、MCP 服务器、知识节点——都绑定到一个 `tenant_id`。认证体系提供完整的 JWT 认证和全面的行级数据隔离。

| 能力 | 说明 |
|---|---|
| Token 设计 | HS256 JWT 访问令牌（15 分钟有效期）+ 不透明 UUID 刷新令牌（7 天有效期，以 bcrypt 哈希存储）|
| Cookie 传输 | `aegis_access` + `aegis_refresh`——均为 `httpOnly`，防 CSRF |
| 角色体系 | `super_admin` / `owner` / `admin` / `member`，路由级守卫 |
| 行级数据隔离 | 所有表均含 `tenant_id`；settings 表主键为 `(tenant_id, key)`——每个租户拥有独立配置 |
| 邀请流程 | Owner 生成一次性邀请 token，受邀者自主注册并加入同一租户 |
| 透明 401 恢复 | Next.js 代理自动刷新过期令牌并重试原始请求——前端永不感知 401 |
| 会话过期弹窗 | 刷新也失败时，出现非侵入式登录覆盖层，不清除 UI 状态 |
| API 密钥加密 | Fernet 对称加密静态存储；界面仅显示末四位 |
| **DEV_MODE** | 当 `SECRET_KEY` **未设置**时，认证全部绕过。后端返回合成的 `dev@localhost` Owner 账号，前端永不跳转至 `/login`。零配置即可评估全部功能。|

### 二、BYOM — 自带模型（18+ 家供应商）

每次 LLM 调用均经过 YAML 配置的 `ModelRouter` 路由。切换模型只需修改 `models_config.yaml` 中的一行——无需改代码，无需重启服务。

所有供应商共用一个纯 `urllib` 连接器——除 `openai` 和 `anthropic` 两个官方 SDK 外，无需安装任何额外依赖。

**统一网关**

| 供应商 | 说明 |
|---|---|
| **OpenRouter** ⭐ | 一个 Key → 300+ 模型（Claude / GPT / Gemini / Llama / DeepSeek 等）——推荐起步方案 |

**全球供应商**

| 供应商 | 说明 |
|---|---|
| Anthropic | Claude Sonnet 4、Claude Opus 4 |
| OpenAI | GPT-4o 及任意 OpenAI 兼容端点 |
| Google Gemini | Gemini 2.0 Flash、Gemini Pro 1.5 |
| Mistral AI | mistral-large-2411 |
| Groq | llama-3.3-70b-versatile（超快推理）|
| xAI（Grok）| grok-2-latest |
| Together AI | Meta Llama 及其他开源模型 |
| NVIDIA NIM | 200+ 开源模型；免费层 1,000 次调用 |

**中国生态**

| 供应商 | 说明 |
|---|---|
| DeepSeek | V3 / R1 推理模型；极具性价比 |
| 阿里云通义千问 | Qwen 2.5 72B、Qwen-Max 系列 |
| 智谱 GLM | GLM-5、GLM-5-Turbo、GLM-4.7 |
| Moonshot / Kimi | 8k / 128k 超长上下文 |
| 百度文心 ERNIE | ERNIE 4.5 |
| MiniMax | abab6.5s-chat |
| 零一万物（Yi）| yi-large |
| 字节豆包（Doubao）| doubao-pro-32k |

**本地 / 离线**

| 方式 | 说明 |
|---|---|
| **Ollama** | 完全离线运行；向量嵌入后端同样只使用 `urllib`——零网络依赖 |
| **vLLM** | 自托管 OpenAI 兼容服务器 |
| 任意 OpenAI 兼容接口 | 在 `models_config.yaml` 中配置 `base_url` 即可 |

通过设置界面保存的 Key 会自动通过 `key_injector.py` 桥接到模型路由——无需重启。

### 三、AI 工作空间 — 知识图谱 + 生成式聊天

**AI 工作空间**（`/knowledge`）是主要的用户界面，集成了知识图谱、文档摄取和强大的生成式聊天助手。

**知识图谱**
- 上传 PDF、TXT 文件或抓取 URL——每个文档成为图节点
- LLM 从每个文档提取 5–10 个关键概念，创建链接到源文档的概念节点
- 自动链接：语义相似度搜索在跨文档节点间创建 `related_concept` 和 `semantically_related` 边
- 交互式 D3.js 图谱：平移、缩放、点击节点设置聊天上下文

**生成式聊天（WorkspaceChat）**
- 双窗格布局：左侧知识图谱，右侧聊天（可调节分隔线）
- 输入 `/task <需求>` 即可在聊天内联中启动完整的多 Agent 流水线
- 任务进度以实时 **TaskCard** 渲染，附 SSE 事件流
- 交互卡片内联显示：CEO 访谈问题和 HITL 审批请求直接在聊天中渲染——无需页面跳转
- 已回答/已审批的卡片锁定为只读状态；对话历史保留

**聊天会话持久化**
- 所有对话存储于 PostgreSQL（`chat_sessions` + `chat_messages` 表）
- 跨页面刷新恢复会话——滚动位置和消息历史均保留
- **历史抽屉**：滑入面板列出近期会话；点击任意会话即可恢复
- 新建会话按钮重置聊天，同时保留知识上下文

### 四、高性能并发调度与三层容错恢复

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

### 五、人工在环（HITL）审批

敏感操作需要在执行前获得明确的人工批准。

**触发条件**
- 写入敏感文件（认证、配置、`.env`、密钥）
- 更新模式修改现有项目代码
- ResilienceManager 在最大重试后升级

**流程**
1. Agent 发出 `hitl.approval_required` SSE 事件，包含操作详情和风险等级
2. 内联 `InlineApprovalCard` 出现在 WorkspaceChat 中——无需页面跳转
3. 管理员审查文件列表、可选备注，然后批准或拒绝
4. 卡片锁定为只读已响应状态；流水线继续（已批准）或取消（已拒绝）

### 六、MCP 工具动态管理

MCP（Model Context Protocol）服务器为 Agent 扩展了外部工具能力——网页搜索、代码执行、数据库查询等。

- **热插拔**：通过设置界面或 REST API 添加、更新或删除服务器，无需重启。
- **租户独立注册表**：每个租户维护独立的服务器列表，持久化于 settings 表，首次 API 调用时懒加载恢复。
- **零依赖探测**：`POST /mcp/servers/{id}/probe` 通过 `urllib.request` 发现可用工具——无需额外 HTTP 库。

```bash
# 注册工具服务器
curl -X POST http://localhost:8000/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "my-tools", "url": "http://localhost:9000"}'

# 探测连通性并发现可用工具
curl -X POST http://localhost:8000/mcp/servers/{id}/probe
```

### 七、Fusion Architect — 跨仓库架构分析

Fusion Architect Agent 克隆多个代码仓库，分析其代码库，并综合生成统一的架构报告，融合各仓库的最佳模式。

**流水线阶段**

| 阶段 | 工具 | 说明 |
|---|---|---|
| 1 — 克隆 | `clone_repo` | 克隆任意 HTTPS/SSH Git URL 到隔离沙箱（GitHub、GitLab、Hugging Face、私有服务器）|
| 2 — 探索 | `read_repo_file` / `glob_repo` / `grep_repo` / `analyze_ast` | 递归读取、搜索和 AST 分析每个代码库 |
| 3 — 综合 | LLM | 生成融合架构报告，综合各仓库的最佳元素 |
| 4 — 持久化 | `write_fusion_report` | 通过 ReflectionAgent 自动将报告提升为可复用的 Markdown 技能 |

- **通用 Git Fetcher**：平台无关——支持任何 Git 托管平台。认证令牌嵌入克隆 URL，日志中自动擦除。
- **沙箱强制**：所有文件操作限定在单一 `repos_root` 目录中；路径穿越尝试会抛出 `ValueError`。
- **AST 分析**：Python 文件获得完整的 `ast` 结构分析（导入、类、函数、调用点）；其他语言回退到正则表达式。

### 八、技能动态加载

复合知识自动提升为可发现、可复用的技能。

- **SkillManifest**（`skills/manifest.yaml`）：所有技能文件的轻量级关键词索引。任务到达时 O(n) 匹配。
- **SkillLoader**：按需 Markdown 技能文件读取器。只加载匹配的文件——无匹配时不注入噪声。
- **复合知识→技能流水线**：`ReflectionAgent` 提取经验 → 将高价值模式提升为 `skills/{category}/` 下的 Markdown 文件 → 更新 manifest → 未来的 CEO/Architect Agent 通过 `SkillLoader.load_matched()` 发现并使用。
- 优雅降级：manifest 或技能文件缺失时静默返回空字符串。

### 九、LLM-as-Judge 质量门

一个强模型在输出交付用户之前，从三个维度对每个 Agent 输出进行评分：

| 维度 | 评分范围 | 衡量内容 |
|---|---|---|
| **幻觉** | 0.0–1.0 | 基于任务/上下文 vs. 编造的事实、不存在的 API |
| **准确性** | 0.0–1.0 | 正确实现且符合需求 |
| **相关性** | 0.0–1.0 | 直接针对任务 vs. 偏题 |

低于阈值的评分会通过现有弹性循环触发静默重试。集成点：在 `ResilienceManager.run_task_loop()` 中 QA 通过后调用。

### 十、深层上下文压缩

三层系统，确保多轮工具使用会话保持在上下文窗口限制内：

| 层级 | 模块 | 策略 |
|---|---|---|
| **1 — 工具输出溢出** | `tool_output_store.py` | 大型工具结果（>1200 字符）溢出到磁盘；消息中只保留头尾预览。模型可通过 `recall_tool_output` 按需取回完整内容。|
| **2 — LLM 摘要** | `context_summarizer.py` | 当消息历史达到上下文窗口的 85% 时，早期轮次由 LLM 压缩为简洁段落，保留关键决策和事实。|
| **3 — 任务交接压缩** | `context_compressor.py` | 在任务中途切换模型时，构建紧凑的简报（~1200 字符），包含目标、已完成文件、错误摘要和继续指令。|

### 十一、安全与沙箱

**沙箱隔离**（`sandbox.py`）
- `ContentPreScreener.check_file()` 在执行前筛查文件
- `SandboxFactory` 创建 `ResourceLimitSandbox`（本地）或 `DockerSandbox`（容器）
- 禁止对生成代码直接调用 `subprocess.run()`

**安全护栏**（`guardrails.py`）
- `PromptGuard.check_input()` 检测任务输入中的提示注入模式
- `ContentModerator.screen_output()` 筛查 LLM 生成的文件内容中的凭证和载荷
- `GuardRailViolation` 不可重试——绕过弹性重试循环

### 十二、FinOps 计费引擎

基于租户信用额度的计费系统，使用线程本地侧信道：

1. `job_runner` 加载租户 `credit_balance` 并在流水线启动前安装 `BillingContext`
2. 每次 LLM API 调用后，连接器记录一条 `LLMUsage` 事件
3. `ModelRouter` 在每次 API 调用前调用 `check_credit()`——余额耗尽时抛出 `InsufficientCreditError`（HTTP 402）
4. 流水线完成后，`flush_context()` 持久化计费事件并从信用余额中扣除

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│  浏览器（Next.js 15 · App Router · Tailwind CSS）                    │
│                                                                      │
│  /knowledge  ──► KnowledgeGraph · WorkspaceChat · TaskCard          │
│                  InlineInterviewCard · InlineApprovalCard            │
│                  HistoryDrawer（会话恢复）                            │
│  /dashboard  ──► 任务历史                                            │
│  /settings   ──► APIKeysTab · ModelsTab · MCPTab · ProfileTab       │
│  /console    ──► SystemStatusCards · TenantStatsPanel · TrendChart  │
│  /login /register /invite/[token] /pending   （认证路由）            │
│                                                                      │
│  SessionExpiredModal（401 时覆盖显示，不清除状态）                    │
└───────────────────────┬─────────────────────────────────────────────┘
                        │  HTTPS + httpOnly Cookie
                        │  /api/proxy/**（401→刷新→重试代理）
┌───────────────────────▼─────────────────────────────────────────────┐
│  FastAPI（Uvicorn · 异步）                                           │
│                                                                      │
│  /auth          注册 · 登录 · 刷新 · 邀请 · 个人信息                │
│  /jobs          创建 · 列表 · 详情 · 取消                           │
│  /jobs/{id}/stream   SSE 流（每 15 秒保活心跳）                     │
│  /knowledge     聊天 · 会话 · 搜索 · 上传 · 摄取 · 图谱            │
│  /approvals     HITL 人工审批门（批准 / 拒绝）                      │
│  /interview     CEO 访谈答案提交                                     │
│  /settings      API 密钥 · 模型配置 · CEO 配置（按租户隔离）        │
│  /mcp           服务器 CRUD + 探测                                   │
│  /console       统计 · 趋势（仅管理员）                              │
│                                                                      │
│  key_injector.py — DB api_keys → os.environ 运行时桥接              │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────────┐
│  核心编排器（纯 Python · 无框架依赖）                                │
│                                                                      │
│  CEOAgent          （≥95% 置信度需求访谈）                          │
│    └─► ArchitectAgent  （Tool-Use 代码生成）                        │
│          └─► Evaluator     （ast · pyflakes · subprocess 沙箱）     │
│                └─► QAAgent     （代码审查）                          │
│                      └─► ReflectionAgent（经验提炼）                │
│                                                                      │
│  FusionArchitect   （跨仓库克隆→探索→综合→技能）                    │
│  SkillLoader       （manifest 关键词匹配→按需 Markdown）            │
│  Judge             （LLM-as-Judge: 幻觉/准确性/相关性）             │
│  ModelRouter       （YAML 路由 · 30 秒缓存 · ${VAR} 插值）         │
│  LLMConnector      （OpenAI / Anthropic 适配器 · urllib）           │
│  ParallelExecutor  （Kahn BFS 波次 · ThreadPoolExecutor）           │
│  ResilienceManager （三层升级 · token 预算熔断器）                   │
│  HITLManager       （敏感文件门 · 更新模式门）                      │
│  MCPManager        （热插拔 · 租户独立 · urllib 探测）              │
│  KnowledgeIngestion（PDF/URL → Markdown → 概念 → 图谱 → 嵌入）     │
│  KnowledgeRetriever（预任务解决方案注入 · 关键词回退）              │
│  VectorStore       （pgvector 写入 · Python 余弦相似度兜底）        │
│  SolutionStore     （YAML 经验库 · 工作空间级别）                   │
│  ToolOutputStore   （大型工具输出溢出到磁盘 + 召回）                │
│  ContextSummarizer （LLM 驱动的对话压缩，85% 阈值）                │
│  ContextCompressor （任务中途模型切换的紧凑简报）                   │
│  Sandbox           （ContentPreScreener + SandboxFactory）          │
│  Guardrails        （PromptGuard + ContentModerator）               │
│  BillingEngine     （按租户信用额度 · 线程本地使用量）              │
│  PIISanitizer      （可组合脱敏流水线）                              │
└───────────────────────┬─────────────────────────────────────────────┘
                        │  asyncpg · SQLAlchemy 2.0 异步
┌───────────────────────▼─────────────────────────────────────────────┐
│  PostgreSQL 16 + pgvector                                            │
│                                                                      │
│  tenants · users · refresh_tokens · workspaces                      │
│  jobs · job_events · checkpoints                                     │
│  solutions  （embedding 1536 维，pgvector）                          │
│  knowledge_nodes · knowledge_edges  （图谱表）                      │
│  chat_sessions · chat_messages  （会话持久化）                      │
│  settings   主键：(tenant_id, key)                                   │
└─────────────────────────────────────────────────────────────────────┘
```

**请求流——AI 工作空间聊天 `/task` 命令**

1. 用户在 WorkspaceChat 中输入 `/task build <需求>`。
2. `callChat` 发送 `POST /knowledge/chat`，携带当前 `session_id`（新会话为 null）。
3. 后端自动创建或恢复会话；持久化用户消息。
4. 后台 `job_runner` 线程启动流水线；TaskCard 注入聊天流。
5. CEOAgent 进行结构化访谈；每个问题通过 SSE 发出 `ceo.question` 事件。
6. `InlineInterviewCard` 出现在聊天流中；用户内联回答。
7. Architect 分解工作；`wave_schedule` 计算并行波次。
8. 每个任务并发执行；Evaluator + QA 对每个输出设门；ResilienceManager 处理失败。
9. 若需写入敏感文件，`InlineApprovalCard` 出现以获取 HITL 确认。
10. ReflectionAgent 提取经验；嵌入向量更新至 pgvector。
11. 完成后流水线摘要内联显示；完整会话持久化至数据库。

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
> 知识图谱和语义记忆等所有功能。
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
alembic upgrade head            # 执行全部 11 个 Schema 迁移

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
2. **`.env` 文件**——启动时通过 `load_dotenv` 加载。
3. **系统环境变量**——适用于 Docker 和 CI 流水线。

| 变量名 | 供应商 |
|---|---|
| `OPENROUTER_API_KEY` | OpenRouter（一个 Key → 300+ 模型）⭐ 推荐 |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `OPENAI_API_KEY` | OpenAI GPT |
| `NVIDIA_API_KEY` + `NVIDIA_BASE_URL` | NVIDIA NIM |
| `DEEPSEEK_API_KEY` + `DEEPSEEK_BASE_URL` | DeepSeek V3 / R1 |
| `ZHIPU_API_KEY` + `ZHIPU_BASE_URL` | 智谱 GLM |
| `MOONSHOT_API_KEY` + `MOONSHOT_BASE_URL` | Moonshot / Kimi |
| `BRAVE_SEARCH_API_KEY` | Brave Search（网页搜索；免费层 2,000 次/月）|

> 通过界面保存的密钥均以 Fernet 对称加密存储于数据库中。
> 它们通过 `api/key_injector.py` 在请求时注入 `os.environ`，
> 模型路由始终使用最新保存的值，无需重启。

### 模型路由（`models_config.yaml`）

```yaml
models:
  openrouter-claude-sonnet:
    provider: openai                              # OpenRouter 使用 OpenAI 协议
    model_id: anthropic/claude-sonnet-4
    api_key_env: OPENROUTER_API_KEY
    base_url: https://openrouter.ai/api/v1
    max_tokens: 8192
    temperature: 0.7
    tier: standard

  my-local-model:
    provider: openai
    model_id: llama3                              # Ollama 中注册的模型名
    api_key_env: LOCAL_API_KEY                    # Ollama 需要任意非空值
    base_url_env: LOCAL_BASE_URL                  # http://localhost:11434/v1
    max_tokens: 8192
    temperature: 0.7

routes:
  - match: {}                                     # 兜底默认；第一个有有效 Key 的模型胜出
    model: openrouter-claude-sonnet
  - match: {}
    model: my-local-model

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
├── core_orchestrator/         # 纯 Python 业务逻辑（36 个模块）
│   ├── ceo_agent.py           # 需求访谈（≥95% 置信度阈值）
│   ├── architect_agent.py     # Tool-Use 代码生成
│   ├── fusion_architect_agent.py  # 跨仓库架构分析 + 综合
│   ├── git_fetcher.py         # 通用 Git 克隆 + 5 个代码分析工具
│   ├── qa_agent.py            # 代码审查 Agent
│   ├── evaluator.py           # 沙箱：ast · pyflakes · subprocess
│   ├── reflection_agent.py    # 经验提炼 → SolutionStore → 技能提升
│   ├── judge.py               # LLM-as-Judge（幻觉/准确性/相关性）
│   ├── ce_orchestrator.py     # 流水线协调器（CEO→Architect→QA→Reflect）
│   ├── resilience_manager.py  # 三层升级 + token 预算熔断器
│   ├── parallel_executor.py   # Kahn BFS 波次调度 + ThreadPoolExecutor
│   ├── retry_utils.py         # 指数退避重试（tenacity 可选，优雅降级）
│   ├── model_router.py        # YAML 多供应商路由（30 秒 TTL 缓存）
│   ├── llm_connector.py       # OpenAI / Anthropic 适配器协议 + 注册表
│   ├── llm_gateway.py         # 翻译网关（自动检测语言）
│   ├── skill_loader.py        # SkillManifest 关键词匹配 + 按需 Markdown 加载器
│   ├── mcp_manager.py         # 热插拔 MCP 服务器注册表（urllib 探测）
│   ├── knowledge_ingestion.py # PDF/URL → Markdown → 概念 → 图谱 → 嵌入
│   ├── knowledge_manager.py   # 知识图谱 CRUD + 语义搜索
│   ├── knowledge_retriever.py # 预任务解决方案注入（向量 + 关键词）
│   ├── vector_store.py        # pgvector 写入 + Python 余弦相似度兜底
│   ├── solution_store.py      # YAML 经验库（工作空间级别）
│   ├── tool_output_store.py   # 大型工具输出溢出到磁盘 + 召回
│   ├── context_compressor.py  # 任务中途模型切换的紧凑简报
│   ├── context_summarizer.py  # LLM 驱动的对话压缩
│   ├── sandbox.py             # ContentPreScreener + SandboxFactory（Docker/本地）
│   ├── guardrails.py          # PromptGuard + ContentModerator
│   ├── billing.py             # FinOps 计费引擎（按租户信用额度）
│   ├── pii_sanitizer.py       # 可组合 PII 脱敏流水线
│   ├── web_browser.py         # 无头网页抓取 + 内容提取
│   ├── web_crawler.py         # URL → Markdown（markdownify）
│   └── tests/                 # 覆盖全部模块的 1094 项 pytest 测试
│
├── api/                       # FastAPI 应用（12 个路由模块）
│   ├── main.py                # 应用工厂 · Lifespan 钩子 · CORS · 崩溃恢复
│   ├── auth.py                # JWT 创建/验证 · DEV_MODE 逻辑
│   ├── deps.py                # FastAPI Depends：CurrentUser · require_admin · require_owner
│   ├── job_runner.py          # 后台流水线线程（DB 密钥注入 + 编排器）
│   ├── job_store.py           # 内存任务状态 + DB 持久化桥接
│   ├── event_labels.py        # 人类可读的 SSE 事件标签映射（英文）
│   ├── event_bridge.py        # SSE 事件路由（任务 → 已连接客户端）
│   ├── hitl_manager.py        # HITL 门：敏感文件 + 更新模式审批
│   ├── interview_manager.py   # CEO 访谈答案桥接（Agent ↔ API）
│   ├── key_injector.py        # DB api_keys → os.environ 桥接（无需重启）
│   ├── metrics.py             # Prometheus 指标注册表 + /metrics 端点
│   ├── quota.py               # QuotaManager — 按租户每日 token 预算
│   ├── rate_limit.py          # slowapi 限流器（认证 10/min，任务 60/min）
│   ├── settings_service.py    # Settings CRUD（PostgreSQL 后端）
│   └── routes/                # auth · jobs · stream · approvals · interview
│                              # knowledge · settings · mcp · console · setup · admin
│
├── db/                        # 数据库层
│   ├── models.py              # SQLAlchemy ORM（12+ 张表）
│   ├── repository.py          # 异步 CRUD — 所有函数接受 AsyncSession
│   ├── connection.py          # asyncpg 引擎 · Session 工厂 · URL 标准化
│   └── migrations/            # Alembic 迁移文件 001–011（11 个迁移）
│       ├── 001–005            # 核心表结构、嵌入向量、认证、工作空间、租户作用域
│       ├── 006–008            # 租户配额、计费表、超级管理员设置
│       └── 009–011            # 知识图谱表、向量维度调整、聊天会话
│
├── web/                       # Next.js 15 前端
│   ├── app/
│   │   ├── knowledge/         # AI 工作空间（主界面）
│   │   │   ├── page.tsx       # 可调节双窗格布局
│   │   │   └── components/
│   │   │       ├── WorkspaceChat.tsx     # 生成式聊天 + 任务派发
│   │   │       ├── KnowledgeGraph.tsx    # D3.js 交互式图谱
│   │   │       ├── TaskCard.tsx          # 实时流水线进度（SSE）
│   │   │       ├── InlineInterviewCard.tsx  # CEO 问题卡片（内联）
│   │   │       ├── InlineApprovalCard.tsx   # HITL 审批卡片（内联）
│   │   │       ├── HistoryDrawer.tsx     # 会话历史 + 恢复
│   │   │       ├── KnowledgeChat.tsx     # 图谱关联的 Q&A 聊天
│   │   │       └── UploadPanel.tsx       # 拖放上传摄取
│   │   ├── dashboard/         # 任务历史列表
│   │   ├── jobs/[id]/         # 任务详情 + 审批操作
│   │   ├── settings/          # APIKeysTab · ModelsTab · MCPTab · CEOTab · ProfileTab
│   │   ├── console/           # 管理员面板（统计 · 趋势 · 租户列表）
│   │   ├── admin/             # 用户审批（仅 super_admin）
│   │   └── onboarding/        # 首次运行设置向导
│   ├── components/
│   │   ├── Shell.tsx          # 认证守卫布局包装器
│   │   ├── Sidebar.tsx        # 导航 + 工作空间切换器 + 主题切换
│   │   ├── SessionExpiredModal.tsx  # 重新登录覆盖层（无状态丢失）
│   │   ├── ApprovalModal.tsx  # 全页 HITL 审批（jobs/[id] 路由）
│   │   ├── InterviewPanel.tsx # 全页 CEO 访谈（jobs/[id] 路由）
│   │   ├── Timeline.tsx       # SSE 事件日志时间线
│   │   └── generative/        # EventCard · FileCard · QAVerdict
│   ├── lib/
│   │   ├── auth/
│   │   │   ├── context.tsx    # AuthProvider + 会话过期事件监听
│   │   │   ├── client.ts      # API 客户端（登录 · 登出 · 注册 · 刷新）
│   │   │   └── sessionGuard.ts  # window.fetch 猴子补丁 → aegis:session-expired 事件
│   │   ├── i18n/              # useT() 钩子 · en.ts · zh.ts（双语 UI）
│   │   ├── eventLabels.ts     # 前端 SSE 事件标签映射 + 事件集合
│   │   └── theme/             # 深色/浅色主题上下文
│   └── hooks/
│       └── useApproval.ts     # HITL 审批轮询钩子
│
├── skills/                    # 可复用 Markdown 技能文件（从知识自动提升）
│   ├── manifest.yaml          # SkillLoader 快速匹配的关键词索引
│   ├── python/                # Python / FastAPI / 架构技能
│   ├── frontend/              # React / Next.js 技能
│   ├── database/              # SQL / 迁移技能
│   ├── devops/                # Docker / CI / 部署技能
│   └── architecture/          # 跨仓库融合架构报告
│
├── workspaces/                # 生成的代码产物（volume 挂载 · git-ignored）
├── knowledge_base/            # 精选经验库（预训练）
├── models_config.yaml         # LLM 路由配置（18+ 供应商预配置）
├── docker-compose.yml         # 生产部署栈（postgres · 后端 · 前端）
├── docker-compose.override.yml # 本地开发覆盖（热重载）
├── Dockerfile                 # 后端多阶段镜像（非 root 用户 uid 1000）
├── .env.example               # 环境变量模板（含所有供应商）
├── ARCHITECTURE.md            # 完整系统设计参考
├── AGENTS.md                  # Agent 操作手册
└── CHANGELOG.md               # 版本历史
```

---

## 开发指南

### 运行测试

```bash
pytest                            # 全量 1094 项测试
pytest core_orchestrator/tests/   # 仅运行编排器单元测试
pytest -k test_resilience         # 按名称过滤
pytest -k test_fusion             # Fusion Architect + Git Fetcher 测试
pytest -k test_skill              # 技能加载器测试
pytest -k test_judge              # LLM-as-Judge 测试
pytest --cov=core_orchestrator --cov-report=term-missing  # 覆盖率报告
```

### 数据库迁移

```bash
alembic upgrade head                                   # 应用全部 11 个迁移
alembic revision --autogenerate -m "描述本次变更"       # 生成新的迁移文件
alembic downgrade -1                                   # 回滚一个版本
alembic current                                        # 查看当前迁移版本
```

### 添加新的 LLM 供应商

1. 在 `models_config.yaml` 的 `models:` 下添加条目，使用 `provider: openai`。所有 OpenAI 兼容 API 无需任何代码改动即可使用。
2. 若供应商需要非标准认证方式，在 `core_orchestrator/llm_connector.py` 中实现 `LLMConnector` 协议，并调用 `register_connector("my-provider", MyConnector())` 注册。
3. 在 `.env.example` 中添加 API Key 环境变量，在 `api/key_injector.py` 的 `_DB_KEY_TO_ENV` 映射中添加条目，并更新初始化向导的供应商目录（`web/app/onboarding/providers.ts`）。

### SSE 事件参考

| 事件类型 | 关键 Payload 字段 | 说明 |
|---|---|---|
| `pipeline.start` | `job_id` | 流水线开始 |
| `ceo.interviewing` | — | CEO 正在澄清需求 |
| `ceo.question` | `question` | CEO 向用户提问（触发 InlineInterviewCard）|
| `ceo.plan_created` | `task_count` | 开发计划就绪 |
| `architect.solving` | `task_id` | Architect 正在为任务编写代码 |
| `architect.file_written` | `filepath` | 文件已提交至工作空间 |
| `hitl.approval_required` | `reason`、`files`、`risk` | 需要人工审批（触发 InlineApprovalCard）|
| `hitl.approved` / `hitl.rejected` | `note` | HITL 决策已收到 |
| `evaluator.pass` / `evaluator.fail` | — | 沙箱验证结果 |
| `qa.pass` / `qa.fail` | — | 代码审查结果 |
| `pipeline.complete` | `artifacts` | 全部任务完成 |
| `pipeline.error` | `error` | 不可恢复的失败 |
| `pipeline.rejected` | — | 用户已取消 |

---

## 贡献指南

**零副作用原则**——每次改动后，系统必须至少与改动前同等可用。

- **测试先行**：在修改生产代码前，先添加或更新测试。1094 项测试套件是回归防线，所有测试必须在合并前通过。
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
