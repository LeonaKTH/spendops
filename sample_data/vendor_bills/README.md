# 供应商账单样例（2026-09）

真实供应商账单属于客户私有数据，网上没有可直接下载的完整发票。这里的文件按照
OpenAI、Anthropic、Azure OpenAI、阿里云百炼、DeepSeek 公开的用量导出 / 账单明细
字段格式构造，token 数量、单价、金额彼此自洽，可直接上传到 ProcureBI 测试。

由 `scripts/generate_vendor_bills.py` 生成，固定随机种子，可复现。

| 文件 | 供应商 | 币种 | 行数 | 金额合计 | 说明 |
|---|---|---|---|---|---|
| `llm_consolidated_invoice_2026-09.xlsx` | 6 家合并 | CNY | 900 | 约 ¥510,129 | **推荐**：一次上传即可出完整 BI 报表 |
| `openai_usage_2026-09.csv` | OpenAI | USD | 270 | 约 $18,466 | 用量导出风格，含缓存 token 与明细费用 |
| `anthropic_usage_2026-09.csv` | Anthropic | USD | 270 | 约 $23,238 | 含 cache write / cache read token |
| `azure_openai_cost_2026-09.csv` | Azure OpenAI | USD | 120 | 约 $3,444 | Cost Management 导出风格，按 1K token 计费 |
| `aliyun_bailian_bill_2026-09.csv` | 阿里云百炼 | CNY | 180 | 约 ¥80,246 | 中文账单明细，UTF-8 BOM，Excel 可直接打开 |
| `deepseek_bill_2026-09.csv` | DeepSeek | CNY | 180 | 约 ¥90,840 | 中文账单明细 |

每份 CSV 都同时提供内容相同的同名 `.xlsx`，可直接用 Excel / WPS 打开，上传效果一致。


## 使用建议

1. 登录后进入「数据接入」，上传 `llm_consolidated_invoice_2026-09.xlsx`。
2. 打开「BI 报表」，在数据集下拉中选择 `llm_consolidated_invoice_2026-09`。
3. 可再单独上传某一家供应商的 CSV，对比不同表头（中 / 英文）下的字段识别。

## 注意事项

- 英文账单的金额单位是 USD，当前报表统一按数值展示并标注「元」，不会做汇率换算。
  需要人民币口径时请使用合并账单。
- 文件中的发票号、订阅号、账单编号均为虚构，仅用于演示。
- 真实上传测试前请确认 `frontend/.env.local` 中 `VITE_USE_MOCK=false`，否则前端不会调用后端。
