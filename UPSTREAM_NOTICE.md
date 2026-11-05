# SpendOps 源码来源与归属声明

## 上游基础

本项目（SpendOps）基于以下开源项目二次开发：

- **上游仓库**：`https://github.com/sail2567/procurebi`
- **许可证**：MIT（见 `LICENSE`，原样保留）
- **固定上游 Commit**：`258c74e61a2dfa1ebad103e9a4d7c38baead5f23`
- **获取方式**：因本地网络无法直接 `git clone`，通过 GitHub tarball（`codeload`）下载该 commit 的源码快照。**本项目不包含上游 Git 提交历史**，为独立初始化的 Git 仓库。

## 归属分类（贯穿开发全程）

| 分类 | 含义 | 标记方式 |
|---|---|---|
| 上游原样 | 直接保留、未改动的文件 | 保持原内容，记录于 `UPSTREAM_CHANGES.md` |
| 上游修改 | 在上游文件基础上改动 | `UPSTREAM_CHANGES.md` 记录 diff 摘要与理由 |
| 完全新增 | 本项目原创文件 | 新增文件，模块归属 SpendOps |

## 复用边界（来自 G1 指令）

| 项目 | 复用方式 |
|---|---|
| sail2567/procurebi | 唯一主代码底座（MIT） |
| frappe/erpnext | 仅参考采购订单/收货/发票的业务流程与状态语义，不复制 GPL 业务代码 |
| apache/superset | 仅参考数据集权限、指标管理、报表产品设计 |
| fastapi/full-stack-fastapi-template | 仅参考测试、接口规范、前端工程化 |
| apache/echarts | 正常图表依赖 |
| tobymao/sqlglot | 正常 SQL 解析依赖 |

## 诚信声明

- 上游代码与第三方成熟组件均**不**被声称为原创成果。
- 每次复用第三方代码/组件前，核查对应版本与许可证，并登记来源与改动。
- 所有测试与性能结果必须来自真实运行，禁止伪造。
