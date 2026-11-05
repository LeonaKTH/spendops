# 技术方案

> 项目：LLM 采购成本智能分析平台（ProcureBI）  
> 版本：v0.2  
> 日期：2026-10-21

---

## 0. 已确定的技术决策

| 项 | 选择 |
|---|---|
| 架构 | 前后端分离 + 模块化单体 |
| 前端 | Vue 3 + Vite + Pinia + Vue Router + ECharts，手写 CSS |
| 后端 | FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic |
| Agent | LangChain + LangGraph |
| 数据库 | PostgreSQL 17（合同检索在 Python 侧，不依赖 pgvector） |
| 缓存 / 状态 | Redis 7 |
| 大模型 | OpenAI 兼容协议，支持 mock 模式 |
| 认证 | JWT（HS256）+ HttpOnly Cookie + bcrypt；角色 admin / viewer |
| 报表导出 | openpyxl（Excel，含原生图表）/ reportlab（PDF，STSong-Light 中文） |
| 开发方式 | Mock-first：先做可点击 Demo，再接后端 |
| 部署 | Docker Compose：nginx + FastAPI + PostgreSQL + Redis |

## 1. 总体架构

```
┌─────────────────────────────────────────────┐
│ Vue 3 SPA                                   │
│ 数据接入 / 数据集 / 智能问数 / BI 报表       │
└──────────────┬──────────────────────────────┘
               │ REST + SSE
┌──────────────▼──────────────────────────────┐
│ FastAPI                                     │
│  api/     路由与参数校验                     │
│  services/ 业务编排                         │
│  ingest/   Excel/PDF 解析、类型推断、DDL     │
│  agent/    LangGraph 状态机与工具            │
│  infra/    SQL 执行器、LLM 适配、Redis       │
└───────┬──────────────────────┬──────────────┘
        │                      │
┌───────▼────────┐   ┌─────────▼───────────┐
│ PostgreSQL 16  │   │ Redis 7             │
│ 业务表 + ds_*  │   │ 会话状态 / 缓存     │
│ pgvector       │   │ 任务进度 / 限流     │
└────────────────┘   └─────────────────────┘
```

## 2. 目录结构

```
ai-data-agent-bi/
├─ docker-compose.yml            # 本地开发依赖
├─ docker-compose.prod.yml       # 生产部署
├─ deploy/                       # Dockerfile.backend / Dockerfile.web / nginx.conf / README
├─ .env.example
├─ docs/
│  ├─ PRD.md
│  └─ TECH_DESIGN.md
├─ backend/
│  ├─ pyproject.toml
│  ├─ alembic.ini
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ cli.py         # 运维命令（重置密码）
│  │  ├─ core/          # config / security
│  │  ├─ api/v1/        # auth / admin / datasets / documents / chat / reports / shared
│  │  ├─ services/      # datasets / query / reports / report_export / report_shares / documents / users / audit
│  │  ├─ agent/         # graph / state / nodes / tools / prompts
│  │  ├─ ingest/        # excel / types / ddl / pdf
│  │  ├─ db/            # models / session / bootstrap
│  │  └─ infra/         # redis / llm / sql_executor / rate_limit
│  ├─ migrations/
│  └─ tests/
├─ frontend/
│  ├─ package.json
│  └─ src/
│     ├─ api/           # client / types / mock / auditLabels
│     ├─ views/         # DataIngest / Datasets / Chat / Reports / Login / Admin
│     ├─ components/
│     ├─ stores/        # auth / datasets / documents
│     └─ styles/
└─ scripts/
   ├─ generate_sample_data.py
   └─ seed_demo_data.py
```

## 3. 数据模型

第一版只保留必要表：

```text
datasets
  id uuid pk
  name text
  physical_table text unique
  source_file text
  sheet_name text
  row_count int
  version int
  status text          -- active / archived
  owner_id text null   -- 上传者（管理员）ID
  content_hash varchar(64) null  -- 文件 SHA-256，用于重复上传检测
  quality jsonb null   -- 源行 / 可导入 / 空行 / 重复行 / 异常单元格 / 问题清单
  created_at timestamptz

reports                             -- 同时用于「保存的报表视图」
  id uuid pk
  title text
  question text
  sql text
  chart_spec jsonb
  layout jsonb
  dataset_id uuid
  dataset_name varchar(200)
  owner_id uuid null
  created_by_username varchar(64)
  period_start date null
  period_end date null
  provider varchar(200) null       -- 供应商下钻条件
  created_at / updated_at timestamptz

users
  id uuid pk
  username varchar(64) unique
  display_name varchar(100)
  password_hash varchar(255)          -- bcrypt
  role varchar(20)                    -- admin / viewer
  is_active bool
  token_version int                   -- 改密 / 重置 / 停用时递增
  must_change_password bool
  last_login_at timestamptz null
  created_at / updated_at timestamptz

audit_logs
  id uuid pk
  actor_id uuid null                  -- FK users.id ON DELETE SET NULL
  actor_username varchar(64)          -- 用户删除后仍保留
  action varchar(64)
  target_type varchar(40) null
  target_id varchar(100) null
  status varchar(20)                  -- success / failure
  detail jsonb null                   -- 不含密码、token、文件内容
  ip varchar(64) null
  created_at timestamptz

report_shares
  id uuid pk
  token_hash varchar(64) unique       -- SHA-256(token)，明文 token 只在创建时返回一次
  dataset_id uuid                     -- FK datasets.id ON DELETE CASCADE
  dataset_name varchar(200)
  period_start date null              -- 创建时绑定的期间，访问者不可改
  period_end date null
  provider varchar(200) null          -- 创建时绑定的供应商下钻条件
  created_by uuid null                -- FK users.id ON DELETE SET NULL
  created_by_username varchar(64)
  expires_at timestamptz
  revoked_at timestamptz null
  view_count int default 0
  last_viewed_at timestamptz null
  created_at timestamptz
```

不建独立的字段元数据表。字段信息通过：

- `information_schema.columns` 反射
- `COMMENT ON COLUMN` 保存原始表头与可选的中文描述
- Redis 缓存反射结果

## 4. 动态建表设计

**命名**

- 统一 schema：`ds`
- 表名：`ds.t_<8位随机>`，避免中文和冲突
- 列名：尽量保留原始中文表头；去首尾空格、处理重复列名、截断到 PostgreSQL 标识符上限（63 字节）
- 原始表头写入 `COMMENT ON COLUMN`，即使列名被清洗也能还原展示语义

**类型推断**

| 原始值特征 | 推断类型 |
|---|---|
| 整数 | `bigint` |
| 含小数 / 货币 / 千分位 | `numeric(18,4)` |
| ISO 日期 / 常见日期格式 | `date` |
| 含时间 | `timestamptz` |
| true/false / 是/否 | `boolean` |
| 其他 | `text` |

**处理规则**

- 所有列允许 NULL
- 金额清洗：去掉 `￥`、`$`、`,`、空格；括号负数转负号
- 百分比保留原值或转 numeric，规则写进注释
- 批量插入用 `executemany`，单文件限制 20MB / 5 万行
- 重新上传生成新 `dataset` 与新物理表，旧记录置为 archived

## 5. Agent 设计

### 状态

```python
class AgentState(TypedDict):
    question: str
    dataset_ids: list[str]
    schema_context: str
    route: str            # sql / doc / chat
    sql: str
    columns: list[str]
    rows: list[list]
    error: str
    retries: int
    chart_spec: dict
    answer: str
```

### 图结构（已实现）

```
START → generate_sql
          ├─ skip_sql（问题只涉及合同，模型未生成 SQL）────────→ summarize
          ├─ 校验失败且可重试（≤3 次）──────────────→ generate_sql
          └─ validate_sql → execute_sql → build_chart → summarize
                              │              │
                              └── 可重试 ────┴──→ generate_sql
                                              └──→ fail（不可重试）
```

- `generate_sql`：注入 schema、样例值与合同片段，要求返回 `{sql, explanation, chart}` JSON
- `validate_sql`：`sqlglot` 只读校验与表白名单，通过后推送 `sql` 事件
- `execute_sql`：只读事务执行，推送 `table` 事件；数据库错误标记为可重试
- `build_chart`：后端根据结果列确定图表类型、x 轴与数值列，推送 `chart` 事件
- `summarize`：流式输出 `text` 事件；有合同片段时一并注入，答案可引用文档与页码
- `fail`：推送 `error` 事件，结束本次流

### 工具与能力

```text
list_datasets()            数据集列表
get_schema(dataset_ids)    表结构 + 样例值
run_sql(sql)               只读执行
build_chart(rows, intent)  生成图表配置
search_chunks(query)       合同条款检索
```

### 模型分级

- 路由、总结：小模型
- SQL 生成：强模型
- 所有调用统一走 LLM Adapter，便于切换、记录 token 和成本

## 6. SQL 安全沙箱

1. 使用只读数据库角色（`bi_reader`），或在事务里 `SET TRANSACTION READ ONLY`
2. `sqlglot` 解析：只允许单条 `SELECT`
3. 表白名单：仅允许 `ds.t_*` 和业务视图
4. 自动追加 `LIMIT 500`
5. `SET LOCAL statement_timeout = '10s'`
6. 结果序列化处理 `date`、`Decimal`，限制返回体积
7. 上传文件内容视为不可信数据，防止 Prompt Injection 改变系统指令

## 6.5 合同文档检索（已实现）

- **解析**：`pypdf` 按页抽取 PDF 文本，`python-docx` 读取段落与表格，TXT 直接读取；PDF 保留页码
- **切分**：每 420 字一个片段，重叠 80 字，尽量按段落边界切分
- **存储**：`documents` 保存文档元信息，`document_chunks` 保存片段与页码
- **检索**：中文按字符 bigram、英文按词切分问题，统计各词在候选片段中的文档频率，用 IDF 加权计算「问题词覆盖率」，返回 top 5；低于 0.15 的片段丢弃
- **注入**：检索结果同时进入 SQL 生成 Prompt（用于理解业务口径）与总结 Prompt（用于引用原文），最多 3 段、每段 400 字
- **为什么不用 pg_trgm**：本地 PostgreSQL 以 C locale 初始化时，`pg_trgm` 不会为中文生成三元组，`word_similarity` 恒为 0；个人项目文档量很小，取回后在 Python 侧打分更可靠，也不依赖数据库 locale

## 6.6 登录与权限（已实现）

- **登录态**：JWT（HS256）写入 HttpOnly Cookie `procurebi_session`，`SameSite=Lax`、默认 12 小时；前端脚本读不到 token。
- **为什么不用 localStorage**：HttpOnly 可以挡住 XSS 读取；同源部署（nginx 同时提供页面与 `/api`）下 Cookie 自动携带，SSE 也不需要额外传 token。
- **权限即时生效**：每个请求按 `sub` 回查 `users`，校验 `is_active` 与 `token_version`。禁用、降级、重置密码都会递增版本，旧 Cookie 下一次请求即返回 401。
- **角色**：
  - `viewer`：问数、报表、查看数据集与文档。
  - `admin`：额外可上传 / 删除数据集与文档、进入后台管理。
- **账号来源**：不开放注册。首次启动且库中没有管理员时，按 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 创建一个并标记待改密；之后由管理员在后台创建账号。
- **登录限流**：Redis 计数 `(username, ip)` 5 次、IP 20 次，锁定 5 分钟；Redis 故障时 fail-open，不影响登录。
- **审计**：登录、退出、改密、用户管理、数据集 / 文档写操作写入 `audit_logs`，包含操作人、动作、对象、结果、IP；不记录密码、哈希、token 或文件内容。
- **后台**：概览、用户管理（搜索 / 分页 / 角色 / 启停 / 重置密码 / 删除）、数据集与文档管理、审计日志查询；不能删除、停用或降级自己，也不能移除最后一个启用管理员。

## 6.7 报表期间、导出与分享（已实现）

**期间筛选**

- `GET /reports/summary?dataset_id=&start_date=&end_date=&provider=`，日期为 ISO `YYYY-MM-DD`，两端都包含。
- 期间条件注入到总额、供应商、应用、月度、模型五条 SQL，保证口径一致；`period_label()` 把实际区间写成「2026 年」「2026 年 7-9 月」「2026 年 9 月」或跨年区间，用于 KPI 标题与导出文件名。
- 账单日期列是 `date` 类型时用 `CAST(col AS date)` 比较；是文本 / 未知类型时用 `SUBSTRING(CAST(col AS text) FROM 1 FOR 10)` 与 ISO 字符串做字典序比较，避免脏日期导致查询失败。
- 开始日期晚于结束日期返回 400；所选期间没有数据返回 404，前端提示调整范围。
- 报表「最新月份 / 上月 / 最新季度 / 上季度」以该数据集实际 `period_end` 为锚点，而不是当前系统日期；前端用 UTC 月份偏移计算区间。

**环比**

- 起止日期都提供时，`previous_period(start, end)` 取紧邻的等长区间（含两端），再跑一条总额 SQL；`change_pct` 在上一周期为 0 时为 `null`。
- 前端展示上一周期区间、金额与环比百分比；KPI `delta` 文本也会前置「环比 ±x.x%」。

**供应商下钻**

- `provider` 参数转成 `WHERE <provider_col> = '<literal>'`（单引号转义），再与期间条件合并；供应商、应用、模型、月度、总额查询全部复用。
- 下钻时供应商图切换为「该供应商各模型采购金额」，洞察补一条模型占比；错误信息改为「供应商「X」在所选期间没有账单数据」。
- 前端点击供应商柱子触发 `select-provider`，工具栏显示可清除的供应商 chip。

**预算与采购底表**

- 语义识别年度预算表（供应商 + 年度预算），按供应商名称归一化后与所选期间实际支出对比，输出总额、已用、使用率与明细表；使用率 ≥90% 追加风险洞察。
- 语义识别报价表（供应商 / 模型 / 输入价 / 输出价 / 折扣 / 有效期），取前 10 行；同时统计套餐（`plan / 套餐 / 订阅`）与限流（`rate / 限流`）数据集。

**多币种**

- 账单含币种列时，金额表达式为 `CASE WHEN UPPER(currency) IN ('USD','US$','$','美元') THEN amount * FX_USD_CNY ELSE amount END`，所有聚合统一使用 `_amount_expr()`。
- `currency_note` 在报表与导出中说明折算汇率；未识别币种列时不显示。

**上传质量与幂等**

- 预览与上传返回 `quality`：源行数、可导入行数、空行、重复行、异常单元格（源非空但转换失败）与中文问题清单；重复行不导入。
- 上传计算文件 SHA-256；已存在 active 数据集时返回 409 与已有数据集名称，`force=true` 时跳过检查。

**报表视图**

- 复用 `reports` 表保存 `dataset_id / period_start / period_end / provider / title / owner_id`；打开时按当前数据实时重算，不保存报表快照。
- 管理员可见全部视图，viewer 只能看到并删除自己的；创建 / 删除写审计 `report.view.create` / `report.view.delete`。

**导出**

- `GET /reports/export?format=xlsx|pdf`，权限与 `GET /reports/summary` 相同，按同一期间生成。
- Excel：`报表概览 / 供应商 / 应用 / 月度 / 模型价格 / 合同配额` 六个工作表，表头样式统一，供应商与月度页写入原生 BarChart / LineChart。
- PDF：reportlab A4，`UnicodeCIDFont("STSong-Light")` 输出中文；概览、图表数据表、洞察、模型价格、合同配额分页排版。
- 响应使用 `Content-Disposition: attachment`，文件名形如 `procurebi-report-2026-07-01-2026-09-30.xlsx`。

**分享链接**

- `POST /reports/shares` 绑定 `dataset_id` 与可选期间、`provider`、有效期（7 / 30 / 90 天），返回一次明文 token 与 `/share/{token}` 路径。
- 服务端只保存 `SHA-256(token)`；列表接口不返回 token（`path` 为空），因此链接泄露面仅限创建的那一刻。
- `GET /api/v1/shared/reports/{token}` 与 `.../export` 为公开只读端点，不要求登录；每次成功打开递增 `view_count` 并更新 `last_viewed_at`。
- 公开接口按 IP 与 token 末 24 位各自计数（`share_rate_max_requests` / `share_rate_window_seconds`），超限返回 429 + `Retry-After`；Redis 故障时放行。
- 响应带 `Referrer-Policy: no-referrer`，全局中间件另加 `X-Content-Type-Options: nosniff` 与 `X-Frame-Options: DENY`。
- 过期、已撤销、不存在统一返回 404「分享链接不存在、已过期或已被撤销。」；撤销仅限创建者或管理员。
- 分享页 `/share/:token` 使用 `meta.public + allowAuthenticated`，已登录用户也可以直接打开外链；分享页关闭下钻交互。

## 7. Redis 使用

| Key | 用途 | TTL |
|---|---|---|
| `procurebi:schema:v1` | 表结构反射缓存 | 60 秒；上传 / 删除数据集时主动失效 |
| `procurebi:auth:fail:{username}:{ip}` | 单个账号 + IP 的登录失败计数 | 锁定 300 秒 |
| `procurebi:auth:fail:ip:{ip}` | 单个 IP 的登录失败计数 | 锁定 300 秒 |
| `procurebi:share:ip:{ip}` | 分享公开接口 IP 访问计数 | 300 秒窗口 |
| `procurebi:share:token:{token_tail}` | 单个分享链接访问计数 | 300 秒窗口 |

## 8. API 契约

```text
POST   /api/v1/auth/login              登录（公开），写入 HttpOnly Cookie
POST   /api/v1/auth/logout             退出（登录）
GET    /api/v1/auth/me                 当前用户（登录）
POST   /api/v1/auth/change-password    修改自己的密码（登录）

POST   /api/v1/datasets/preview        预览 Excel（管理员，返回 quality）
POST   /api/v1/datasets                上传 Excel（管理员；重复文件 409，?force=true 强制）
GET    /api/v1/datasets                数据集列表（登录）
GET    /api/v1/datasets/{id}/rows      分页查看数据集原始行（登录，limit<=100）
DELETE /api/v1/datasets/{id}           删除数据集（管理员）
POST   /api/v1/documents               上传合同（管理员）
GET    /api/v1/documents               文档列表（登录）
GET    /api/v1/documents/{id}/pages    按页读取合同原文（登录）
DELETE /api/v1/documents/{id}          删除文档（管理员）
POST   /api/v1/chat                    SSE 流式问答（登录，含 sources 事件）
GET    /api/v1/reports/summary         自动识别账单/配额表并汇总报表（登录，?dataset_id=&start_date=&end_date=&provider=）
GET    /api/v1/reports/datasets        可切换的账单数据集与账期（登录）
GET    /api/v1/reports/export          导出报表 xlsx / pdf（登录，?format=&dataset_id=&start_date=&end_date=&provider=）
GET    /api/v1/reports/views           报表视图列表（登录；管理员可见全部）
POST   /api/v1/reports/views           保存报表视图（登录）
DELETE /api/v1/reports/views/{id}      删除报表视图（创建者或管理员）
POST   /api/v1/reports/shares          创建只读分享链接（登录，可绑定 provider）
GET    /api/v1/reports/shares          有效分享列表（登录；管理员可见全部）
DELETE /api/v1/reports/shares/{id}     撤销分享（创建者或管理员）
GET    /api/v1/shared/reports/{token}  公开读取分享报表（公开，无需登录）
GET    /api/v1/shared/reports/{token}/export  公开导出分享报表（公开）
GET    /api/v1/health                  健康检查（公开）

GET    /api/v1/admin/overview          后台概览（管理员）
GET    /api/v1/admin/users             用户列表（管理员）
POST   /api/v1/admin/users             创建用户（管理员）
PATCH  /api/v1/admin/users/{id}        更新用户（管理员）
POST   /api/v1/admin/users/{id}/reset-password
DELETE /api/v1/admin/users/{id}
GET    /api/v1/admin/audit-logs        审计日志（管理员）
```

请求体使用 snake_case（如 `display_name`、`new_password`），响应使用 camelCase（如 `displayName`），由 Pydantic `serialization_alias` 完成转换。

SSE 事件：

```text
event: status   data: {"stage": "retrieving"}
event: sql      data: {"sql": "SELECT ..."}
event: table    data: {"columns": [...], "rows": [...]}
event: chart    data: {"type": "bar", "x": "...", "y": "...", "series": [...]}
event: text     data: {"delta": "..."}
event: sources  data: {"items": [{"documentId": "...", "document": "...", "page": 3, "snippet": "..."}]}
event: error    data: {"message": "..."}
event: done     data: {}
```

## 9. 前端设计

- 路由页面：`/login`（公开）、`/share/:token`（公开只读分享，已登录也可打开）、`/chat`、`/datasets`、`/reports`、`/ingest`（管理员）、`/admin`（管理员）
- 路由守卫：先调用 `auth.restore()`（`GET /auth/me`）；未登录跳 `/login?redirect=`；viewer 访问管理页跳 `/chat`；`redirect` 只接受站内路径，避免开放重定向
- 组件：FileDropzone、ParsePreview、DatasetCard、DataTable、SqlBlock、ChartRenderer（`clickable` 时抛 `item-click`）、ChatMessage（条款引用 chip）、DocumentPreviewDialog（按页预览原文）、ChangePasswordDialog、ReportBody（报表正文，登录页与分享页共用；含环比 / 预算 / 采购底表 / 下钻事件）、ReportShareDialog（分享创建 / 列表 / 撤销）
- 报表页：数据集 / 期间 / 供应商 / 报表视图四个筛选入口；保存视图弹窗复用 Modal 样式；Mock 模式只显示「导出 CSV（演示）」
- 状态：Pinia 管理认证状态、数据集列表与当前会话；`api` 在编译期校验 Mock 与真实实现签名一致
- 样式：CSS Variables 管理色板、间距、圆角、暗色模式；不引入重组件库
- API 层统一封装，组件不直接调 `fetch`；所有请求带 `credentials: 'include'`

## 10. Mock-first 策略

```text
frontend/src/api/
  client.ts       真实请求
  mock/
    index.ts      mock 实现
    datasets.json
    chat.json
  datasets.ts    根据 VITE_USE_MOCK 选择实现
```

- Mock 与真实接口使用同一套 TypeScript 类型
- 模拟 300–800ms 延迟、错误态、空状态
- 流式回答用定时器模拟 SSE
- 后端就绪后只改环境变量，组件不改

## 11. 示例数据生成

`scripts/generate_sample_data.py`：

- 固定随机种子，结果可复现
- 生成：账单明细 2 万行、报价单、配额表、合同 PDF
- 埋入演示点：成本突增、配额告急、可替代低价模型、异常单价
- 同时输出 Excel（`sample_data/`）和前端 Mock JSON（`frontend/src/mock/`）
- 保证勾稽关系：金额 = token × 单价，汇总 = 明细合计

## 12. 开发与部署

```yaml
services:
  db:     postgres:17-alpine          # 数据卷 pgdata
  redis:  redis:7-alpine              # AOF 持久化，数据卷 redisdata
  api:    deploy/Dockerfile.backend   # 启动时自动 alembic upgrade head
  web:    deploy/Dockerfile.web       # Node 构建 + nginx，仅暴露 80
```

- 开发期：Vite dev server + FastAPI `--reload`，Vite 代理 `/api`
- 生产：`docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`
- nginx 同源提供页面并代理 `/api`，SSE 关闭 `proxy_buffering`；数据库与 Redis 不对公网暴露
- 配置通过 `.env` / `.env.prod`，仓库只提交 `.env.example`
- 数据库变更一律用 Alembic；部署细节见 `deploy/README.md`

## 13. 里程碑

| 阶段 | 内容 | 预计 |
|---|---|---|
| M0 | 骨架、Docker Compose、接口契约、数据生成器 | 1–2 天 |
| M1 | 前端 4 页面 + Mock，可完整点击演示 | 2–3 天 |
| M2 | 后端垂直切片：上传建表 → 问数 → 图表 | 3–5 天 |
| M3 | LangGraph 纠错、多轮、Redis、评测集 | 3–4 天 |
| M4 | 报表、PDF/RAG（选做）、部署、README | 2–3 天 |

## 14. 主要风险

| 风险 | 应对 |
|---|---|
| Excel 脏数据导致解析失败 | 模板 + 逐列容错 + 解析报告 |
| NL2SQL 准确率低 | 列注释、样例值、schema 筛选、gold question 评测 |
| LLM 调用成本与延迟 | 模型分级、缓存、限制重试次数 |
| Agent 输出不稳定 | 图表用 Pydantic 校验，失败降级为表格 |
| 范围膨胀 | P1 功能全部后置，先保证垂直切片可演示 |
