import type { ChartSpec, ColumnMeta, Dataset, TableResult } from '../types'

export const billColumns: ColumnMeta[] = [
  { name: '账期', type: 'date', sample: '2025-06-15' },
  { name: '供应商', type: 'text', sample: 'DeepSeek' },
  { name: '模型', type: 'text', sample: 'deepseek-chat' },
  { name: '应用', type: 'text', sample: '智能客服' },
  { name: '业务线', type: 'text', sample: 'ToC' },
  { name: '输入token', type: 'number', sample: '1,284,392' },
  { name: '输出token', type: 'number', sample: '386,110' },
  { name: '输入单价(元/千token)', type: 'number', sample: '2.0000' },
  { name: '输出单价(元/千token)', type: 'number', sample: '8.0000' },
  { name: '金额(元)', type: 'number', sample: '5,657.28' },
  { name: '币种', type: 'text', sample: 'CNY' },
]

export const quoteColumns: ColumnMeta[] = [
  { name: '供应商', type: 'text', sample: '阿里云百炼' },
  { name: '模型', type: 'text', sample: 'qwen-plus' },
  { name: '输入单价(元/千token)', type: 'number', sample: '0.8000' },
  { name: '输出单价(元/千token)', type: 'number', sample: '2.0000' },
  { name: '承诺量(万元)', type: 'number', sample: '80' },
  { name: '阶梯折扣', type: 'text', sample: '满100万 9折' },
  { name: '有效期', type: 'date', sample: '2026-12-31' },
]

export const quotaColumns: ColumnMeta[] = [
  { name: '合同编号', type: 'text', sample: 'HT-2025-001' },
  { name: '供应商', type: 'text', sample: '火山引擎' },
  { name: '承诺金额(元)', type: 'number', sample: '56,650,000' },
  { name: '已用金额(元)', type: 'number', sample: '52,120,000' },
  { name: '使用率', type: 'number', sample: '0.9200' },
  { name: '到期日', type: 'date', sample: '2026-08-28' },
]

export const MOCK_DATASETS: Dataset[] = [
  {
    id: 'ds-bills',
    name: '2025 年模型采购账单',
    sourceFile: 'bills_2025.xlsx',
    sheetName: '账单明细',
    rowCount: 26280,
    columns: billColumns,
    createdAt: '2025-12-31 18:20',
    status: 'active',
  },
  {
    id: 'ds-quotes',
    name: '供应商报价单',
    sourceFile: 'quotes.xlsx',
    sheetName: '报价单',
    rowCount: 8,
    columns: quoteColumns,
    createdAt: '2025-12-31 18:21',
    status: 'active',
  },
  {
    id: 'ds-quotas',
    name: '合同配额与用量',
    sourceFile: 'quotas.xlsx',
    sheetName: '配额',
    rowCount: 5,
    columns: quotaColumns,
    createdAt: '2025-12-31 18:22',
    status: 'active',
  },
]

export const PROVIDER_TOTALS: TableResult = {
  columns: ['供应商', '采购金额(万元)', '占比'],
  rows: [
    ['DeepSeek', 6485, '28.7%'],
    ['火山引擎', 5212, '23.0%'],
    ['阿里云百炼', 4176, '18.5%'],
    ['OpenAI', 3894, '17.2%'],
    ['Anthropic', 2852.8, '12.6%'],
  ],
}

const providerChart: ChartSpec = {
  type: 'bar',
  title: '2025 年各供应商采购金额',
  x: ['DeepSeek', '火山引擎', '阿里云百炼', 'OpenAI', 'Anthropic'],
  series: [{ name: '金额(万元)', data: [6485, 5212, 4176, 3894, 2852.8] }],
  unit: '万元',
}

const monthlyChart: ChartSpec = {
  type: 'line',
  title: '2025 年月度采购成本',
  x: ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
  series: [
    {
      name: '成本(万元)',
      data: [1350, 1480, 1560, 1650, 1740, 2310, 1820, 1930, 2010, 2090, 2180, 2500],
    },
  ],
  unit: '万元',
}

const appPie: ChartSpec = {
  type: 'pie',
  title: '成本按应用分布',
  data: [
    { name: '智能客服', value: 57 },
    { name: '代码助手', value: 27 },
    { name: '文档摘要', value: 16 },
  ],
}

const juneDays = Array.from({ length: 30 }, (_, index) => `6/${index + 1}`)
const juneCost = juneDays.map((_, index) =>
  index >= 9 && index <= 24 ? 138 + (index % 5) * 13 : 56 + (index % 4) * 4,
)

const anomalyChart: ChartSpec = {
  type: 'line',
  title: '6 月日成本（万元）',
  x: juneDays,
  series: [{ name: '日成本(万元)', data: juneCost }],
  unit: '万元',
}

const priceTable: TableResult = {
  columns: ['模型', '供应商', '输入单价', '输出单价', '相对成本'],
  rows: [
    ['doubao-lite-32k', '火山引擎', 0.3, 0.6, '约 0.18x'],
    ['qwen-plus', '阿里云百炼', 0.8, 2.0, '约 0.4x'],
    ['doubao-pro-32k', '火山引擎', 0.8, 2.0, '约 0.4x'],
    ['gpt-4o-mini', 'OpenAI', 1.1, 4.4, '约 0.55x'],
    ['deepseek-chat', 'DeepSeek', 2.0, 8.0, '1.0x'],
    ['qwen-max', '阿里云百炼', 2.4, 9.6, '约 1.2x'],
    ['deepseek-reasoner', 'DeepSeek', 4.0, 16.0, '2.0x'],
    ['claude-sonnet', 'Anthropic', 21.0, 105.0, '约 11x'],
  ],
}

const quotaTable: TableResult = {
  columns: ['供应商', '承诺金额(万元)', '已用金额(万元)', '使用率', '到期日'],
  rows: [
    ['火山引擎', 5665, 5212, '92.0%', '2026-08-28'],
    ['DeepSeek', 8300, 6485, '78.1%', '2026-10-28'],
    ['阿里云百炼', 6960, 4176, '60.0%', '2026-04-28'],
    ['OpenAI', 8650, 3894, '45.0%', '2026-12-28'],
    ['Anthropic', 9500, 2852.8, '30.0%', '2026-02-28'],
  ],
}

export interface MockAnswer {
  keywords: string[]
  stage: string
  sql: string
  chart?: ChartSpec
  table?: TableResult
  text: string
}

export const MOCK_ANSWERS: MockAnswer[] = [
  {
    keywords: ['供应商', '哪家', '占比', '最多', '花了多少', '汇总'],
    stage: '按供应商汇总采购金额',
    sql: `SELECT 供应商,
       ROUND(SUM("金额(元)") / 10000, 2) AS 采购金额_万元,
       ROUND(SUM("金额(元)") / 226198208.86 * 100, 1) AS 占比
FROM ds.t_bills_2025
GROUP BY 供应商
ORDER BY 采购金额_万元 DESC;`,
    chart: providerChart,
    table: PROVIDER_TOTALS,
    text: `2025 年总采购成本约 22,619.8 万元（2.26 亿元）。DeepSeek 与火山引擎合计占 51.7%，供应商集中度偏高。

建议：火山引擎配额已使用 92%，应尽快评估续约或切换部分流量；同时保留阿里云百炼作为第二供应源，降低单一供应商风险。`,
  },
  {
    keywords: ['趋势', '每月', '月份', '变化', '增长'],
    stage: '计算月度成本趋势',
    sql: `SELECT LEFT(账期, 7) AS 月份,
       ROUND(SUM("金额(元)") / 10000, 2) AS 成本_万元
FROM ds.t_bills_2025
GROUP BY LEFT(账期, 7)
ORDER BY 月份;`,
    chart: monthlyChart,
    text: `全年成本整体呈上升趋势。6 月达到 2,310 万元，环比增长 32.8%，是全年最明显的异常峰值；12 月达到 2,500 万元，为正常增长下的全年最高点。

6 月峰值与智能客服在火山引擎 doubao-pro-32k 上的重试风暴高度相关，详见异常归因。`,
  },
  {
    keywords: ['异常', '突增', '为什么', '6月', '六月', '峰值'],
    stage: '定位成本异常并归因',
    sql: `SELECT 账期, 应用, SUM("金额(元)") / 10000 AS 日成本_万元
FROM ds.t_bills_2025
WHERE 账期 BETWEEN '2025-06-01' AND '2025-06-30'
GROUP BY 账期, 应用
ORDER BY 日成本_万元 DESC
LIMIT 20;`,
    chart: anomalyChart,
    text: `6 月 10 日至 25 日出现了持续两周的成本异常：日成本从约 60 万元升至 140–190 万元。

归因结果：
• 主要应用：智能客服（占增量 81%）
• 主要模型：火山引擎 doubao-pro-32k
• 主要业务线：ToC
• 调用量约为平日的 2.8 倍，单价正常，判断为上游重试风暴导致的重复调用，而非涨价。

建议：为智能客服增加调用去重与重试上限，并对 doubao-pro-32k 设置日预算告警。`,
  },
  {
    keywords: ['比价', '便宜', '替换', '性价比', '单价', '报价'],
    stage: '对比各模型单价与替换空间',
    sql: `SELECT 模型, 供应商,
       "输入单价(元/千token)" AS 输入单价,
       "输出单价(元/千token)" AS 输出单价
FROM ds.t_quotes
ORDER BY 输入单价 ASC;`,
    table: priceTable,
    text: `从单价看，doubao-lite-32k 和 qwen-plus 明显低于 deepseek-chat，约为其 0.18–0.4 倍。

如果只是把智能客服中 30% 的简单问答流量切到 doubao-lite-32k，按当前用量估算每月可节省约 180 万元；复杂问题仍保留 deepseek-chat。建议先用 5% 流量做一周质量对比，再逐步放量。`,
  },
  {
    keywords: ['配额', '合同', '到期', '承诺', '续约'],
    stage: '检查合同配额与使用率',
    sql: `SELECT 供应商, 承诺金额, 已用金额,
       ROUND(已用金额 / 承诺金额 * 100, 1) AS 使用率,
       到期日
FROM ds.t_quotas
WHERE 已用金额 / 承诺金额 >= 0.6
ORDER BY 使用率 DESC;`,
    table: quotaTable,
    text: `火山引擎使用率已达 92.0%（5,212 / 5,665 万元），按当前增速预计 1 个月内触顶，需要优先处理；DeepSeek 使用率 78.1%，处于健康区间但也要开始规划续约。

建议本周内完成火山引擎续约询价，并把 2026 年的承诺金额拆分成两个阶梯，避免一次性大额承诺。`,
  },
]

export const DEFAULT_ANSWER: MockAnswer = {
  keywords: [],
  stage: '生成成本总览',
  sql: `SELECT 供应商, 应用, 模型,
       ROUND(SUM("金额(元)") / 10000, 2) AS 成本_万元
FROM ds.t_bills_2025
GROUP BY 供应商, 应用, 模型
ORDER BY 成本_万元 DESC
LIMIT 20;`,
  chart: providerChart,
  table: PROVIDER_TOTALS,
  text: `已基于 2025 年账单生成成本总览：全年总成本 2.26 亿元，DeepSeek、火山引擎、阿里云百炼位列前三。

你可以继续追问：按应用拆分、查看月度趋势、分析 6 月异常，或对比各模型单价。`,
}

export const APP_PIE = appPie
