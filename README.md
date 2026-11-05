# SpendOps — AI-Enhanced Procurement Analytics Platform

面向采购运营与财务分析的企业级数据管理与智能经营分析平台。

**技术栈**：Python 3.12+ · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · Vue3 · TypeScript · Vite · Pinia · ECharts · sqlglot

> 本项目以 [sail2567/procurebi](https://github.com/sail2567/procurebi)（MIT，commit `258c74e`）为代码底座，在其上完成了采购业务领域建模、数据接入、经营指标与受控 AI 问数的完整闭环。上游原始说明见 [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)，模块归属见 [UPSTREAM_CHANGES.md](UPSTREAM_CHANGES.md) 与 [UPSTREAM_NOTICE.md](UPSTREAM_NOTICE.md)。

---

## 一、项目定位

SpendOps 是一个**能真实运行、可测试、前后端完整联动**的企业采购经营分析系统，核心不是「再接入一个 AI」，而是「构建一套供业务人员真实操作、分析和管理数据的完整软件系统」。

业务主线：

```
供应商管理 → 采购订单 → 采购收货 → 采购发票 → 数据核对 → 经营指标 → Web 分析工作台 → 受控 AI 问数
```

数据链路：

```
Excel/CSV 上传 → 解析与字段映射 → 数据质量校验 → 暂存 → 确认 → 独立 Worker 异步入库 → 经营指标 SQL → 工作台 / AI 问数
```

## 二、核心系统架构

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | Vue3 + TypeScript + Vite + Pinia + ECharts | 采购管理、数据导入、经营分析、受控 AI 问数四个工作台 |
| API | FastAPI + Pydantic v2 | 业务 API / 指标 API / 导入 API / AI 分析 API，JWT(HttpOnly Cookie) + RBAC |
| 业务服务 | SQLAlchemy 2 Async | 领域服务层（金额计算、状态机、数量约束、幂等）与 API 层分离 |
| 数据 | PostgreSQL 16 | 唯一权威存储；migrator/app/ro 三角色最小权限 |
| 异步任务 | PostgreSQL 持久队列 + 独立 Worker | `FOR UPDATE SKIP LOCKED` 认领、租约续期、超时重认领、崩溃恢复 |
| 指标 | 统一 SQL 聚合 | 在正确业务粒度分别聚合，避免多表 JOIN 重复放大 |
| AI | 受控问数（规则意图解析 + 可信指标计算） | 不生成/不执行任意 SQL，模型不生成数字 |

数据库角色隔离（最小权限）：

- `spendops_migrator`：DDL（迁移）
- `spendops_app`：业务 DML（无 DDL / 无 TRUNCATE）
- `spendops_ro`：SELECT 只读（用于 SQL 安全测试的防御性兜底，非运行时业务连接）

> 说明（如实区分数据库层与应用层只读）：经营指标与受控 AI 问数在**应用层只读**——只执行确定性 SELECT 聚合、无任何写路径（有零写副作用测试），但运行时连接使用 `spendops_app`（具备 DML）。`spendops_ro` 是独立的 SELECT-only 角色，目前用于 SQL 安全测试验证「数据库层只读」兜底，并非 AI 问数的运行时账号。

## 三、采购业务闭环

7 个领域实体：`Supplier` / `PurchaseOrder` / `PurchaseOrderLine` / `GoodsReceipt` / `GoodsReceiptLine` / `PurchaseInvoice` / `PurchaseInvoiceLine`。

- 金额一律 `Decimal`（`Numeric`），确定性计算（`数量 × 单价`），单币种 CNY、未税口径。
- 收货数量不能超过订单数量（事务内行锁 + `with_for_update`）；已取消订单不能收货。
- 发票可追溯到订单明细，开票数量受累计约束；提前开票标记为 `pending_verification`（待核对），需人工核对（`verify_invoice`，写入审计日志）后才能转为 `posted`。
- 关键写操作支持 `Idempotency-Key` + SHA-256 内容指纹，同 key 同内容重试返回原结果。

## 四、Excel/CSV 导入与 Worker

- 支持 CSV / XLSX、中文列名、UTF-8 / UTF-8 BOM / GBK，日期 / Decimal 金额 / 数量。
- 字段映射（中文列名 → 系统字段）+ 字段级校验，错误报告含**行号 / 字段 / 错误类型 / 修复建议**，不静默跳过错误行。
- 持久任务队列（`import_tasks`）+ 暂存行（`import_staging_rows`）+ 独立 Worker（`python -m app.worker`）。
- 可靠性：任务状态持久化、`FOR UPDATE SKIP LOCKED` 防重复认领、租约续期（时间驱动 30s）、超时重认领、取消中止、进度对账（从暂存表统计，崩溃重试计数准确）。
- 事务策略（明确）：**单据内原子、单据间独立（部分成功）**，不假装同时原子与部分成功。

## 五、经营指标与 Gold 验证

统一指标口径（`services/metrics.py`），前端/后端不各自重写公式：

- 采购订单金额 = Σ 订单明细金额，排除已取消订单，时间按订单日期。
- 实际收货金额 = Σ 收货明细金额，排除已取消收货单，时间按收货日期。
- 已开票金额（未税）/ 税额 / 待核对金额，在发票头粒度聚合。
- 供应商排名与 Top N 集中度、月度趋势（订单/收货/发票三种金额独立聚合）、交货及时率（仅统计约定交期非空明细，缺失交期返回「不可计算」）、品类占比、三单差异。

**关键正确性保证**：订单/收货/发票金额在各自正确粒度分别聚合，绝不跨表 JOIN 后 SUM。`tests/integration/test_metrics.py` 用人工核算的独立 Gold 常量验证，包含「一条订单明细两次收货 + 三次开票」不重复放大的专项测试。

## 六、G4 性能对照（真实实测）

专用性能库 `spendops_perf`：100 供应商 / 10,000 订单 / 24,908 明细 / 16,442 收货 / 9,942 发票（45 MB，种子 20261106）。

| 查询/操作 | 优化前 | 优化后 | 说明 |
|---|---|---|---|
| 采购订单列表 | 1859 ms | 82 ms | 无分页全量加载 → limit/offset（22 倍） |
| 经营总览 overview | 845 ms | 401 ms | 及时率 Python 循环 → SQL FILTER 聚合（2 倍） |
| 差异分析 | 82 ms | 86 ms | 相关子查询 → CTE（当前规模收益不明显，为更大规模可扩展性保留） |

> 本机 C 盘 fsync 较慢，写入类操作受磁盘 I/O 限制；上述写入相关数字为环境特征，非代码可优化范围。**未宣称高并发生产 SLA。**

## 七、受控 AI 问数与安全边界

- **不生成、不执行任意 SQL**：AI 只解析「意图 + 时间范围 + 供应商」，然后调用可信的确定性指标计算，金额/数量/比例一律以数据库结果为准。
- **两种模式**：离线确定性分析（无需 API Key，规则解析 + 规则化解释）与可选 LLM 解释（环境变量配置，无 key / 失败 / 超时自动降级离线）。
- **支持的问题类型**（8 类）：经营总览、供应商排名、月度趋势、供应商金额变化、交付延期、待核对发票、收货开票差异、月度变化观察。
- **安全约束**：模型零写权限；不接触用户/密码/审计等敏感表；意图枚举白名单；结果可溯源（意图、时间范围、指标定义、原始计算值、限制说明）；原因类表述区分「数据事实」与「推测」。
- **只读边界（如实说明）**：AI 问数为**应用层只读**（仅执行确定性 SELECT，有零写副作用测试），运行时数据库连接为 `spendops_app`（具备 DML），并非 SELECT-only 账号；`spendops_ro` 只读角色用于 SQL 安全测试兜底。
- 未做 NL2SQL 攻击面（不开放 schema 给模型），因此无 SQL 注入/越权风险面。

## 八、本地启动

前置：Python 3.12+、Node 20+、PostgreSQL 16（本项目使用便携版，见下）。

```bash
# 1. 数据库（便携版 PostgreSQL 16，独立端口/数据目录，不写系统服务）
/d/pgsql16/pgsql/bin/pg_ctl.exe -D "C:/Users/<you>/spendops_pgdata" -o "-p 5433" start

# 2. 后端（backend/.env 配置 DATABASE_URL 等）
cd backend
python -m venv .venv && .venv/Scripts/pip install -r <deps>
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 导入 Worker（独立进程）
.venv/Scripts/python -m app.worker

# 4. 前端
cd frontend
echo "VITE_USE_MOCK=false" > .env.local
npm ci && npm run dev

# 5. 演示数据（固定种子，可复现）
.venv/Scripts/python scripts/generate_demo_data.py
```

登录：`admin / admin123456`（仅本地演示；首次登录会提示改密）。默认打开 `http://localhost:5173`。

## 九、测试

```bash
cd backend
.venv/Scripts/python -m pytest -q          # 251 passed（含真实 PG 集成测试）
```

分层：领域/解析单元测试 · 真实 PostgreSQL 集成测试（迁移/约束/事务/只读角色/指标 Gold/Worker 可靠性/受控问数）· HTTP 端到端 · 前端 `vue-tsc` + 生产构建 · 浏览器 E2E（复用系统 Chrome）。

## 十、未实现 / 未验证 / 非生产声明（诚实清单）

- 未做真实 LLM 效果评测（本轮未授权付费 API，仅离线确定性 + 协议/降级测试）。
- 未做 5 万订单规模压测；并发 >10 未测；峰值内存/CPU 未可靠测量。
- 差异分析 CTE 在 1 万订单规模无显著加速（保留为更大规模可扩展性）。
- Redis 未引入（G1 约定）；登录限流在 Redis 缺失时仅 `APP_ENV=dev` 放行。
- 本项目为求职展示型工程，**不是高并发生产平台**，不做支付、不做真实会计结算、不接真实企业系统。

## 十一、模块归属

- **上游（sail2567/procurebi）**：认证/用户/审计、数据集动态建表、NL2SQL Agent（LangGraph）、报表/分享、前端工程化骨架。详见 [UPSTREAM_CHANGES.md](UPSTREAM_CHANGES.md)。
- **SpendOps 新增**：采购领域模型、数据导入 + 持久 Worker、经营指标体系、受控 AI 问数、采购/导入/分析工作台前端、大规模合成数据与性能测试。
