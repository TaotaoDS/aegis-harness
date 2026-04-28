# AegisHarness — 今日工作报告
**日期:** 2026-04-28  
**分支:** `main` → 已推送至 GitHub  
**本次 Commits:** 5 次（`1741153` → `370591c`）

---

## 一、今日完成工作清单

### 1. 知识图谱节点删除功能 (`1741153`)
- **`app/knowledge/page.tsx`** — 实现 `handleDeleteNode` 回调，调用 `DELETE /knowledge/nodes/{id}`，成功后自动清空选中状态并刷新图谱
- **`KnowledgeGraph`** 组件 — 侧边卡片新增「删除」按钮，点击弹出确认对话框（包含节点标题）

### 2. 🌐 联网搜索开关 (`1741153`)
- **`WorkspaceChat.tsx`** — 输入栏新增 🌐 切换按钮（激活时变绿），启用后发送消息走 `/knowledge/web_search` 而非知识图谱问答
- 搜索结果以结果卡片列表渲染，每张卡片有「+ 保存为节点」按钮
- 引入 `WebResultsMsg` 消息类型和 `saveStates` 状态映射

### 3. 中国 IP 自动搜索引擎切换 (`69215e8`)
- **`core_orchestrator/web_browser.py`** — `engine="auto"` 元引擎：
  - 通过 `ip-api.com` geolocate 客户端 IP（1h 内存缓存，私有 IP 跳过）
  - CN + 中文查询 → Bing zh-CN（httpx，服务器 IP 不被 CAPTCHA）
  - CN + 英文 / 非 CN → DuckDuckGo（httpx）→ fallback Bing
- **`api/routes/knowledge.py`** — 提取 `X-Forwarded-For` / `X-Real-IP` 头，传入 `search_web()`

### 4. Brave Search API 集成 + 防封锁加固 (`cc81c32`)
- 新增 `_search_brave_api()` — 官方 API，无 IP 封锁，TOS 合规
- DuckDuckGo CAPTCHA 检测（`anomaly.js`），触发时抛 `retryable=True`
- DDG 广告 URL 过滤（`y.js?ad_domain=`）
- 随机 jitter 延迟（0.3–1.2s）降低 bot 检测风险
- **`docker-compose.yml`** — 新增 `BRAVE_SEARCH_API_KEY` 透传

### 5. Brave Search API Key UI + 错误提示 (`370591c`) ← 今日最新
| 改动 | 说明 |
|------|------|
| `APIKeysTab.tsx` | 新增 Brave Search 🌐 行（amber 徽章，`BSA…` 占位符，申请链接，内嵌提示文字） |
| `settings.py` | 修复 `_mask_api_keys()`：对 api_keys 字典内所有值脱敏（之前仅字段名含 "key" 才脱敏，导致 `brave_search` 值明文返回） |
| `web_browser.py` | `search_web()` 新增 `brave_api_key` 参数；`_search_brave_api()` 新增 `api_key` 参数，调用方 key 优先于环境变量 |
| `knowledge.py` | `web_search` 端点从租户 `api_keys` 设置读取 `brave_search`，传入 `search_web()` |
| `WorkspaceChat.tsx` | 新增 `WebSearchError` 类（`kind: missing_key/quota/other`），HTTP 400 按 detail 分类；新增 amber 警告横幅（含「前往设置」链接，可关闭） |
| `zh.ts / en.ts` | 新增 `webSearchNeedsKey`、`webSearchQuotaExceeded`、`webSearchGoToSettings` |

---

## 二、测试结果（所有测试通过 ✅）

```
T1 Save brave_search key        ✅  HTTP 200
T2 brave_search masked in GET   ✅  Got: '****V9yZ'
T3 Web search auto (Brave API)  ✅  HTTP 200 - 3 hits
T4 Web search bing engine       ✅  HTTP 200 - 2 hits
T5 Web search duckduckgo        ✅  HTTP 200 - 2 hits
T6 Invalid engine → 400         ✅  HTTP 400
T7 Knowledge nodes list         ✅  HTTP 200

Overall: ✅ ALL PASSED
```

---

## 三、系统架构说明（联网搜索路径）

```
用户输入查询
     │
     ▼
WorkspaceChat (webMode=true)
     │  POST /api/proxy/knowledge/web_search
     │  { query, limit, engine:"auto" }
     ▼
knowledge.py web_search endpoint
     │  1. 提取客户端真实 IP（X-Forwarded-For）
     │  2. 从 DB settings.api_keys 读取租户 brave_search key
     │  3. asyncio.to_thread → search_web()
     ▼
web_browser.search_web()
     │
     ├─── 有 brave_api_key？
     │      是 → Brave Search API（优先，无 IP 封锁）
     │           → 429 quota: fallback 到爬虫
     │           → 401/403 bad key: 抛 retryable=False（→ 400）
     │
     └─── engine=auto + 无 Brave key
            │  geolocate client_ip
            ├─ CN + CJK 查询 → Bing zh-CN httpx → fallback DDG
            └─ 其他           → DuckDuckGo httpx  → fallback Bing
                                 CAPTCHA detected → retryable=True
```

---

## 四、当前部署状态

| 服务 | 状态 | 端口 |
|------|------|------|
| PostgreSQL 16 + pgvector | ✅ Healthy | 5432 |
| Backend (FastAPI/Uvicorn) | ✅ Running | 8000 |
| Frontend (Next.js) | ✅ Running | 3000 |

**版本:** v0.0.2  
**GitHub:** `TaotaoDS/aegis-harness` → `main`  
**最新 commit:** `370591c` feat(search): Brave Search API key UI, per-tenant config, and error banners
