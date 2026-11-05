# ProcureBI

[![CI](https://github.com/sail2567/procurebi/actions/workflows/ci.yml/badge.svg)](https://github.com/sail2567/procurebi/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776ab?logo=python&logoColor=white)](backend)
[![Vue 3](https://img.shields.io/badge/Vue-3-42b883?logo=vue.js&logoColor=white)](frontend)

面向大模型业务采购场景的 BI 数据智能体：上传采购账单 Excel 自动建表，用自然语言查询成本、用量与比价，自动生成 SQL、图表和结论；PDF / Word 合同会被切分并建立检索索引，提问时自动引用条款原文。

> 示例采购数据与合同均为脚本生成，不含真实业务数据。

## 已实现能力

- **动态建表**：上传 `.xlsx / .xls / .csv`，自动识别表头、推断字段类型、创建物理表并注册数据集，不需要改代码。数据集页可打开「查看数据」弹窗分页浏览原始行，支持页码跳转。
- **NL2SQL 问数**：LangGraph 编排 `生成 SQL → 安全校验 → 只读执行 → 生成图表 → 总结`，失败自动重试（最多 3 次）。
- **合同问答**：解析 `.pdf / .docx / .txt`，按长度切分条款，用「中文 bigram + IDF 覆盖率」检索相关段落，回答时引用文档名与页码。
- **可视化**：后端根据结果确定图表类型与数据，前端用 ECharts 渲染柱状图 / 折线图 / 饼图。
- **BI 报表**：按字段语义自动识别账单与配额数据集，汇总 KPI、供应商 / 应用 / 月度图表和风险洞察；支持切换账单数据集（默认最新账期），并基于模型清单与价目表展示当前在售模型价格结构。换一份同义表头的 Excel 无需改代码。
- **期间筛选**：按全部账期 / 最新月份 / 上月 / 最新季度 / 上季度 / 本年度 / 自定义日期范围重新汇总，KPI、图表、导出内容全部跟随所选期间，标题自动写成年月；带日期范围时同时计算上一等长周期的环比。
- **报表下钻**：点击供应商柱状图即可按供应商重新汇总 KPI、模型结构与应用分布，一键返回全局视图；下钻条件可随报表视图保存。
- **预算与采购底表**：识别年度预算数据集，对比所选期间实际支出并给出预算使用率；汇总报价单、套餐与限流底表，展示在售价格结构。
- **多币种**：账单含币种字段时，USD 金额按 `FX_USD_CNY` 折算为 CNY 汇总，报表页与导出文件均标注折算口径。
- **报表视图**：保存「数据集 + 期间 + 供应商」组合，后续一键恢复；管理员可查看全部视图，viewer 只能管理自己的视图。
- **报表导出**：一键导出 Excel（多工作表 + 原生柱状图 / 折线图）与 PDF（A4、中文排版、分页），文件名带实际账期；Mock 模式明确导出 CSV 演示文件。
- **分享链接**：为指定数据集、期间与供应商生成只读外链，可设 7 / 30 / 90 天有效期；服务端只保存 token 的 SHA-256 哈希，链接可随时撤销，并记录访问次数。公开接口按 IP 与 token 限流，外部访客无需登录即可查看报表与导出。
- **条款引用**：问数回答附带引用的合同与页码，点击可在弹窗中查看原文并切换页码。
- **上传质量报告**：预览阶段展示源行数、可导入行数、空行 / 重复行 / 异常单元格，并给出中文问题清单；相同文件再次上传会返回 409，可选择强制导入副本。
- **流式体验**：SSE 推送 `status / sql / table / chart / text / sources / error / done` 事件，前端实时展示 Agent 过程；SQL 折叠块标注所用数据集与返回行数，答案和 SQL 都可一键复制。
- **SQL 安全**：`sqlglot` 单条 SELECT 校验、`ds` schema 白名单、危险函数黑名单、只读事务、10s 超时、自动 `LIMIT 500`。
- **缓存**：Redis 缓存反射后的 schema（60s），上传 / 删除数据集时主动失效。
- **登录与权限**：JWT（HttpOnly Cookie）+ bcrypt，`admin` / `viewer` 两种角色；账号由管理员创建，不开放注册；Redis 按用户名与 IP 限制登录失败；禁用、改角色、重置密码后旧会话立即失效。
- **后台管理**：概览、用户 CRUD、合同文档管理、操作审计日志；数据集在「数据接入 / 数据集」页维护。
- **Mock-first**：前端默认使用 Mock 数据，可一行配置切换到真实后端。
- **模型采购底表**：内置主流大模型的价格、套餐、限流样例数据，上传后即可做跨供应商比价、涨价识别和成本测算。
- **可部署**：Docker Compose 一键部署 nginx + FastAPI + PostgreSQL + Redis，见 [部署手册](deploy/README.md)。

## 数据流

```text
Excel ──解析/类型推断──> ds.t_* 物理表 + datasets 注册表 ──反射──> schema 上下文
                                                                  │
用户问题 ──SSE──> LangGraph: generate_sql → validate_sql → execute_sql → build_chart → summarize
                    ↑____________ 重试（≤3） ____________│                  │
PDF/Word ──提取/切分──> document_chunks ──bigram+IDF 检索──────────> 注入 SQL / 总结 Prompt
```

## 技术栈

Vue 3 + Vite + TypeScript + Pinia + ECharts · FastAPI · SQLAlchemy 2 (async) · PostgreSQL · Redis · LangChain + LangGraph · DeepSeek（OpenAI 兼容接口）

## 本地开发

### 1. 启动 PostgreSQL 与 Redis

项目使用 `tools/` 下的便携版服务，无需 Docker：

```bash
bash scripts/start_services.sh
```

停止：`bash scripts/stop_services.sh`

### 2. 启动后端

```bash
cd backend
cp .env.example .env          # 首次运行，填写 LLM_API_KEY
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- API 文档：<http://127.0.0.1:8000/docs>
- 若还没有虚拟环境：`python -m venv .venv && .venv/Scripts/python.exe -m pip install -e .`
- 首次启动且数据库中没有管理员时，会按 `.env` 的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 创建管理员；开发环境留空时使用 `admin / admin123456`，并强制首次登录后改密。
- 忘记密码时可在 `backend/` 下执行 `.venv/Scripts/python.exe -m app.cli reset-password admin`。

### 3. 启动前端

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

访问 <http://localhost:5173>。默认使用 Mock 数据；接入真实后端时创建 `frontend/.env.local`：

```text
VITE_USE_MOCK=false
```

Mock 模式内置演示账号：`admin / admin123456`（管理员）、`viewer / viewer123456`（普通用户）。
真实后端模式使用初始化时创建的管理员账号。

### 4. 运行测试

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q
```

当前 151 个测试通过，覆盖 SQL 安全校验与执行上下文、数据集明细分页、Excel 类型推断与上传质量 / 重复文件拦截、图表构建、中文条款检索、报表数据识别与期间筛选 / 环比 / 下钻 / 预算、多币种折算、Excel / PDF 导出、分享链接与限流、报表视图权限、密码哈希与 JWT、用户保护规则、登录限流与审计。

## 主要接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | 公开 | 登录，写入 HttpOnly Cookie |
| POST | `/api/v1/auth/logout` | 登录 | 退出登录 |
| GET | `/api/v1/auth/me` | 登录 | 当前用户信息 |
| POST | `/api/v1/auth/change-password` | 登录 | 修改自己的密码 |
| GET | `/api/v1/datasets` | 登录 | 数据集与字段结构 |
| GET | `/api/v1/datasets/{id}/rows` | 登录 | 分页查看数据集原始行（`limit` / `offset`） |
| POST | `/api/v1/datasets/preview` | 管理员 | 预览 Excel 字段与样例行 |
| POST | `/api/v1/datasets` | 管理员 | 上传并动态建表；相同文件返回 409，可加 `force=true` 强制导入 |
| DELETE | `/api/v1/datasets/{id}` | 管理员 | 删除数据集与物理表 |
| GET | `/api/v1/documents` | 登录 | 合同文档库 |
| POST | `/api/v1/documents` | 管理员 | 上传 PDF / DOCX / TXT |
| GET | `/api/v1/documents/{id}/pages` | 登录 | 按页读取文档原文，用于条款引用预览 |
| DELETE | `/api/v1/documents/{id}` | 管理员 | 删除文档与检索片段 |
| POST | `/api/v1/chat` | 登录 | SSE 流式问数，`sources` 事件返回引用文档与页码 |
| GET | `/api/v1/reports/summary` | 登录 | 自动识别账单 / 配额表并生成报表汇总，可用 `dataset_id`、`start_date`、`end_date`、`provider` 指定范围 |
| GET | `/api/v1/reports/datasets` | 登录 | 可切换的账单数据集与账期列表 |
| GET | `/api/v1/reports/export` | 登录 | 导出当前报表，`format=xlsx\|pdf`，支持 `provider` |
| GET | `/api/v1/reports/views` | 登录 | 已保存的报表视图（管理员看全部，viewer 看自己） |
| POST | `/api/v1/reports/views` | 登录 | 保存数据集 + 期间 + 供应商视图 |
| DELETE | `/api/v1/reports/views/{id}` | 创建者或管理员 | 删除报表视图 |
| POST | `/api/v1/reports/shares` | 登录 | 创建只读分享链接（绑定数据集、期间、供应商与有效期） |
| GET | `/api/v1/reports/shares` | 登录 | 我的 / 全部有效分享 |
| DELETE | `/api/v1/reports/shares/{id}` | 创建者或管理员 | 撤销分享链接 |
| GET | `/api/v1/shared/reports/{token}` | 公开 | 通过分享链接读取报表 |
| GET | `/api/v1/shared/reports/{token}/export` | 公开 | 通过分享链接导出 Excel / PDF |
| GET | `/api/v1/admin/overview` | 管理员 | 后台概览 |
| GET/POST/PATCH/DELETE | `/api/v1/admin/users...` | 管理员 | 用户管理、重置密码 |
| GET | `/api/v1/admin/audit-logs` | 管理员 | 操作审计日志 |

## 目录结构

```text
backend/
  app/agent/        LangGraph 图、LLM 适配、图表构建
  app/ingest/       Excel/CSV/PDF/DOCX 解析与类型推断
  app/services/     动态建表、只读查询、文档检索、报表汇总与导出、分享链接、用户与审计
  app/api/v1/       auth / admin / datasets / documents / chat / reports / shared / health
  app/cli.py        运维命令（重置密码）
frontend/           Vue 3 单页应用（Mock / 真实 API 可切换）
deploy/             生产 Dockerfile、nginx 配置与部署手册
docs/               产品设计与技术方案
scripts/            示例数据生成、演示数据导入、本地服务启停
sample_data/        模拟账单、报价、配额与合同样例
tools/              便携版 PostgreSQL / Redis（不提交）
```

## 示例数据

`sample_data/` 中包含两份账单明细（2025 年历史账期约 2.6 万行、2026 年当前模型账期约 3.9 万行）、报价单、两份配额表、DOCX / PDF 模拟合同，以及四份模型采购底表（模型清单、价格表、订阅套餐、限流），可直接用于演示：

- 「2026 年各供应商采购金额是多少？」
- 「按当前价目表，GPT-6 Astra 和 Claude Fable 5.1 哪个更贵？」
- 「哪些模型比 deepseek-chat 更便宜？」
- 「哪些供应商的合同配额快用完了？」
- 「火山引擎合同的配额预警线是多少？违约责任怎么约定？」
- 「按 100 万输入 + 20 万输出估算，哪些模型单次成本低于 2 美元？」
- 「Claude Opus 5.5 和 Kimi K3 的综合成本差几倍？」
- 「哪些模型会在 2026 年 12 月涨价？」
- 「各供应商最低的付费个人月付套餐是多少美元？」

## 部署

完整步骤见 [deploy/README.md](deploy/README.md)。简版：

```bash
# 服务器上（代码已上传到 /opt/procurebi）
cp .env.example .env.prod    # 填写 JWT_SECRET、POSTGRES_PASSWORD、ADMIN_PASSWORD、LLM_API_KEY
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

默认只暴露 80 端口，nginx 提供前端静态文件并把 `/api` 代理到 FastAPI。
部署后可用 `scripts/seed_demo_data.py` 从本地批量导入示例数据。

## 文档

- [产品设计文档](docs/PRD.md)
- [技术方案](docs/TECH_DESIGN.md)
- [主流模型价格与采购底表](docs/MODEL_PRICING.md)
- [服务器部署手册](deploy/README.md)

## 说明

- `.env` / `.env.prod` 保存本地配置、数据库密码与 LLM API Key，已被 gitignore，不会提交
- 前端不直接调用大模型，API Key 只存在于后端
- 登录态使用 HttpOnly Cookie，前端脚本读不到 token
- `tools/` 是本地便携工具与数据目录，不提交
- 示例采购数据与合同均为脚本生成，仅用于演示

## 开发与测试

```bash
# 后端测试
cd backend
python -m pytest -q

# 前端构建（含 vue-tsc 类型检查）
cd frontend
npm ci
npm run build
```

Push 与 PR 会自动运行同样的检查，见 [.github/workflows/ci.yml](.github/workflows/ci.yml)。

## License

[MIT](LICENSE)
