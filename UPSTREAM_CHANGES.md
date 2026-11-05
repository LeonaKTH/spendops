# SpendOps 上游代码归属清单

> 上游：`sail2567/procurebi`（MIT），固定 commit `258c74e61a2dfa1ebad103e9a4d7c38baead5f23`
> 本项目基线提交：`96b3bce`

## 一、上游原样保留（未改动）

| 路径 | 说明 |
|---|---|
| `backend/app/core/security.py` | JWT + bcrypt 认证 |
| `backend/app/core/config.py` | 配置（仅新增 `.env` 本地文件，不入库） |
| `backend/app/db/base.py`、`session.py`、`sql.py` | 数据库基础设施 |
| `backend/app/db/models.py` | 上游业务模型（datasets/documents/users 等，仅追加 import） |
| `backend/app/agent/**` | LangGraph NL2SQL Agent |
| `backend/app/services/query.py` | SQL 只读守卫 |
| `backend/app/services/datasets.py`、`documents.py`、`reports.py` 等 | 上游数据/报表服务 |
| `backend/app/ingest/**` | Excel/PDF 解析 |
| `backend/migrations/versions/0001~0005` | 上游迁移 |
| `backend/tests/test_*.py`（16 个文件） | 上游 151 个测试，未修改 |
| `frontend/**`（除下述新增/修改） | 上游 Vue3 前端 |
| `deploy/`、`docker-compose*.yml`、`docs/`、`sample_data/`、`scripts/`（上游部分） | 上游部署/文档/样例 |

## 二、上游修改（保留 + 改动）

| 路径 | 改动 |
|---|---|
| `backend/app/db/models.py` | 末尾追加 `from app.db.purchasing import ...`，纳入 metadata |
| `backend/app/main.py` | 注册 `purchasing_router` |
| `frontend/src/api/client.ts` | 追加采购 API 方法（真实后端） |
| `frontend/src/api/mock/index.ts` | 追加采购 mock 方法（parity 校验） |
| `frontend/src/api/types.ts` | 追加采购类型定义 |
| `frontend/src/router/index.ts` | 追加 `/purchasing` 路由 |
| `frontend/src/components/AppSidebar.vue` | 追加「采购管理」导航 |

## 三、完全新增（本项目原创）

| 路径 | 说明 |
|---|---|
| `backend/app/db/purchasing.py` | 采购领域模型（7 个实体，Decimal 金额） |
| `backend/migrations/versions/0006_purchasing.py` | 采购表迁移 |
| `backend/app/services/purchasing/` | 业务服务层（domain/suppliers/orders/receipts/invoices） |
| `backend/app/api/v1/purchasing.py` | 采购 API 路由 |
| `backend/app/api/v1/purchasing_schemas.py` | 采购 Pydantic 模型 |
| `backend/tests/test_purchasing_domain.py` | 金额计算单元测试 |
| `backend/tests/integration/` | 真实 PG 集成测试（conftest + 20 测试） |
| `backend/pytest.ini` | pytest 配置（asyncio mode） |
| `backend/scripts/e2e_api_test.py` | 端到端 API 验证脚本 |
| `frontend/src/views/PurchasingView.vue` | 采购管理主页面 |
| `frontend/src/views/purchasing/*.vue` | 供应商/订单/收货/发票 4 个 tab 组件 |
| `UPSTREAM_NOTICE.md`、`UPSTREAM_CHANGES.md` | 来源与归属声明 |

## 四、诚信声明

- 上游代码（MIT）与第三方组件均不声称为原创。
- 采购业务逻辑、领域模型、集成测试、前端采购页面均为本项目原创。
- 所有测试与性能数据来自真实运行，未伪造。
