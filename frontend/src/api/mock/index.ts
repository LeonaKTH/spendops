export * from './admin'
export * from './auth'

import type {
  ChatEvent,
  Dataset,
  DatasetRows,
  DocumentItem,
  DocumentPages,
  ImportQuality,
  PreviewResult,
  ReportDatasetOption,
  ReportExportFormat,
  ReportExportInput,
  ReportShare,
  ReportShareInput,
  ReportSummary,
  ReportView,
  ReportViewInput,
  TableResult,
} from '../types'
import {
  DEFAULT_ANSWER,
  MOCK_ANSWERS,
  MOCK_DATASETS,
  billColumns,
  type MockAnswer,
} from './data'
import report2026 from './report-2026.json'

const STORAGE_KEY = 'procurebi.mock.datasets'
const HIDDEN_KEY = 'procurebi.mock.hidden'
const DOCUMENT_KEY = 'procurebi.mock.documents'

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const PREVIEW: TableResult = {
  columns: ['账期', '供应商', '模型', '应用', '业务线', '输入token', '金额(元)'],
  rows: [
    ['2025-06-01', 'DeepSeek', 'deepseek-chat', '智能客服', 'ToC', 1284392, 5657.28],
    ['2025-06-01', '火山引擎', 'doubao-pro-32k', '智能客服', 'ToC', 2031774, 6914.03],
    ['2025-06-02', '阿里云百炼', 'qwen-plus', '文档摘要', 'ToB', 846120, 2368.94],
    ['2025-06-02', 'OpenAI', 'gpt-4o-mini', '代码助手', '研发', 512880, 1887.42],
    ['2025-06-03', 'Anthropic', 'claude-sonnet', '文档摘要', 'ToB', 188402, 12973.41],
  ],
}

function columnType(name: string): 'text' | 'number' | 'date' {
  if (/日期|账期|有效期|到期/.test(name)) return 'date'
  if (/token|金额|单价|数量|率|费用|成本/.test(name)) return 'number'
  return 'text'
}

const MOCK_QUALITY: ImportQuality = {
  sourceRows: 1208,
  importedRows: 1200,
  blankRows: 3,
  duplicateRows: 5,
  invalidCells: 2,
  issues: [
    '已跳过 3 个全空行。',
    '发现 5 行完全重复的记录（未自动删除，请确认是否为重复入账）。',
    '字段「账期」有 2 个值无法解析为日期，已按空值导入。',
  ],
}

export async function previewDataset(file: File): Promise<PreviewResult> {
  await sleep(1050)
  const divisor = file.name.toLowerCase().endsWith('.csv') ? 120 : 58
  return {
    sheetName: 'Sheet1',
    rowCount: Math.max(8, Math.round(file.size / divisor)),
    columns: PREVIEW.columns.map((name, index) => ({
      name,
      type: columnType(name),
      sample: String(PREVIEW.rows[0][index] ?? ''),
    })),
    rows: PREVIEW.rows,
    quality: MOCK_QUALITY,
  }
}

function readStored(): Dataset[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Dataset[]) : []
  } catch {
    return []
  }
}

function readHidden(): string[] {
  try {
    const raw = localStorage.getItem(HIDDEN_KEY)
    return raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    return []
  }
}

function writeStored(items: Dataset[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
}

function pickAnswer(question: string): MockAnswer {
  return MOCK_ANSWERS.find((item) => item.keywords.some((kw) => question.includes(kw))) ?? DEFAULT_ANSWER
}

const MOCK_TABLE_NAMES: Record<string, string> = {
  'ds.t_bills_2025': '2025 年模型采购账单',
  'ds.t_quotes': '供应商报价单',
  'ds.t_quotas': '合同配额与用量',
}

function mockUsedDatasets(sql: string): string[] {
  const lowered = sql.toLowerCase()
  return Object.entries(MOCK_TABLE_NAMES)
    .filter(([table]) => lowered.includes(table))
    .map(([, name]) => name)
}

export async function listDatasets(): Promise<Dataset[]> {
  await sleep(260)
  const hidden = new Set(readHidden())
  const stored = readStored().filter((item) => !hidden.has(item.id))
  return [...stored, ...MOCK_DATASETS].filter((item) => !hidden.has(item.id))
}

export async function getDatasetRows(
  datasetId: string,
  limit = 20,
  offset = 0,
): Promise<DatasetRows> {
  await sleep(220)
  const hidden = new Set(readHidden())
  const dataset = [...readStored(), ...MOCK_DATASETS].find(
    (item) => item.id === datasetId && !hidden.has(item.id),
  )
  if (!dataset) throw new Error('数据集不存在或已被删除。')

  const total = dataset.rowCount
  const count = Math.max(0, Math.min(limit, total - offset))
  const rows = Array.from({ length: count }, (_, index) => {
    const line = offset + index + 1
    return dataset.columns.map((column, columnIndex) => {
      if (column.type === 'date') {
        const month = String((line % 12) + 1).padStart(2, '0')
        const day = String((line % 27) + 1).padStart(2, '0')
        return `2025-${month}-${day}`
      }
      if (column.type === 'number') {
        return Math.round((line * 137 + columnIndex * 29) % 90000) / 10 + 0.1
      }
      return column.sample || `${dataset.name}-${line}`
    })
  })

  return {
    columns: dataset.columns.map((column) => column.name),
    rows,
    total,
    offset,
    limit,
  }
}

export async function uploadDataset(file: File, force = false): Promise<Dataset> {
  await sleep(1100)
  const stored = readStored()
  const existing = stored.find((item) => item.sourceFile === file.name)
  if (existing && !force) {
    throw new Error(`该文件已导入为数据集「${existing.name}」。如需重复导入请选择强制导入。`)
  }
  const rowCount = 1200 + Math.floor(Math.random() * 4200)
  const dataset: Dataset = {
    id: `ds-${Date.now()}`,
    name: file.name.replace(/\.(xlsx|xls|csv)$/i, ''),
    sourceFile: file.name,
    sheetName: 'Sheet1',
    rowCount,
    columns: billColumns.slice(0, 7),
    createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
    status: 'active',
    quality: {
      sourceRows: rowCount + 8,
      importedRows: rowCount,
      blankRows: 3,
      duplicateRows: 5,
      invalidCells: 2,
      issues: MOCK_QUALITY.issues,
    },
  }
  writeStored([dataset, ...stored])
  return dataset
}

function readDocuments(): DocumentItem[] {
  try {
    const raw = localStorage.getItem(DOCUMENT_KEY)
    return raw ? (JSON.parse(raw) as DocumentItem[]) : []
  } catch {
    return []
  }
}

function writeDocuments(items: DocumentItem[]) {
  localStorage.setItem(DOCUMENT_KEY, JSON.stringify(items))
}

export async function listDocuments(): Promise<DocumentItem[]> {
  await sleep(200)
  return readDocuments()
}

export async function uploadDocument(file: File): Promise<DocumentItem> {
  await sleep(1200)
  const docType = file.name.split('.').pop()?.toLowerCase() ?? 'pdf'
  const document: DocumentItem = {
    id: `doc-${Date.now()}`,
    name: file.name.replace(/\.(pdf|docx|txt)$/i, ''),
    sourceFile: file.name,
    docType,
    pageCount: docType === 'pdf' ? Math.max(1, Math.round(file.size / 60000)) : 0,
    charCount: Math.round(file.size * 1.4),
    chunkCount: Math.max(1, Math.round(file.size / 900)),
    createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
    status: 'active',
  }
  writeDocuments([document, ...readDocuments()])
  return document
}

export async function removeDocument(id: string): Promise<void> {
  await sleep(200)
  writeDocuments(readDocuments().filter((item) => item.id !== id))
}

export async function getDocumentPages(id: string): Promise<DocumentPages> {
  await sleep(260)
  const document = readDocuments().find((item) => item.id === id)
  if (!document) {
    return {
      id: 'doc-mock',
      name: '火山引擎采购合同',
      pageCount: 4,
      pages: [
        {
          page: 3,
          content:
            '第 3 条 配额与预警\n\n甲方承诺年度采购金额不低于人民币 574 万元。当配额使用率达到 90% 时，乙方应提前 10 个工作日书面通知甲方采购负责人，并共同评估续约或扩容方案。',
        },
      ],
    }
  }
  return {
    id: document.id,
    name: document.name,
    pageCount: document.pageCount,
    pages: [
      {
        page: 1,
        content: `${document.name}\n\n（Mock 模式仅展示示例条款原文，真实模式下会按页返回解析后的合同内容。）\n\n第 1 条 合作范围\n第 2 条 价格与结算\n第 3 条 配额与预警：当配额使用率达到 90% 时，双方应启动续约评估。`,
      },
    ],
  }
}

export async function removeDataset(id: string): Promise<void> {
  await sleep(180)
  const hidden = new Set(readHidden())
  hidden.add(id)
  localStorage.setItem(HIDDEN_KEY, JSON.stringify([...hidden]))
  writeStored(readStored().filter((item) => item.id !== id))
}

export async function listReportDatasets(): Promise<ReportDatasetOption[]> {
  await sleep(120)
  const latest = report2026.dataset
  return [
    {
      id: latest.id,
      name: latest.name,
      rowCount: latest.rowCount,
      periodStart: latest.periodStart,
      periodEnd: latest.periodEnd,
    },
    {
      id: 'ds-bills-2025',
      name: 'bills_2025',
      rowCount: 26280,
      periodStart: '2025-01-01',
      periodEnd: '2025-12-31',
    },
  ]
}

function periodLabel(start?: string, end?: string): string {
  if (!start || !end) return '本期'
  const startYear = start.slice(0, 4)
  const endYear = end.slice(0, 4)
  const startMonth = Number(start.slice(5, 7))
  const endMonth = Number(end.slice(5, 7))
  if (startYear === endYear) {
    if (startMonth === 1 && endMonth === 12) return `${startYear} 年`
    if (startMonth === endMonth) return `${startYear} 年 ${startMonth} 月`
    return `${startYear} 年 ${startMonth}-${endMonth} 月`
  }
  return `${start} 至 ${end}`
}

function applyPeriod(summary: ReportSummary, start?: string, end?: string): ReportSummary {
  if (!start || !end) return summary
  const next: ReportSummary = {
    ...summary,
    generatedAt: new Date().toISOString(),
    dataset: { ...summary.dataset, periodStart: start, periodEnd: end },
    kpis: summary.kpis.map((item) => ({ ...item })),
  }
  next.kpis[0] = {
    ...next.kpis[0],
    label: `${periodLabel(start, end)}采购总成本`,
  }
  if (next.kpis[1]) {
    next.kpis[1] = { ...next.kpis[1], delta: `${start} 至 ${end}` }
  }
  if (next.monthlyChart?.x) {
    const startMonth = Number(start.slice(5, 7))
    const endMonth = Number(end.slice(5, 7))
    next.monthlyChart = {
      ...next.monthlyChart,
      x: next.monthlyChart.x.filter((label) => {
        const month = Number.parseInt(label, 10)
        return Number.isFinite(month) && month >= startMonth && month <= endMonth
      }),
    }
  }
  return next
}

function totalWan(summary: ReportSummary): number {
  const value = Number(summary.kpis[0]?.value.replaceAll(',', '') ?? 0)
  return Number.isFinite(value) ? value : 0
}

function decorate(summary: ReportSummary, startDate?: string, endDate?: string): ReportSummary {
  const total = totalWan(summary)
  const providerRows = (summary.providerChart.x ?? []).map((name, index) => ({
    name,
    amount: summary.providerChart.series?.[0]?.data[index] ?? 0,
  }))
  const annualTotal = Math.round(total * 1.45 * 10000)
  const usedTotal = Math.round(total * 10000)
  const budget = providerRows.length
    ? {
        summary: `所选期间实际支出 ${(usedTotal / 10000).toLocaleString('zh-CN')} 万元，对应年度预算 ${(annualTotal / 10000).toLocaleString('zh-CN')} 万元，整体使用率 ${total ? ((usedTotal / annualTotal) * 100).toFixed(1) : '0.0'}%。`,
        table: {
          columns: ['供应商', '年度预算(万元)', '所选期间已用(万元)', '预算使用率'],
          rows: providerRows
            .map((row) => {
              const annual = row.amount * 1.45
              return [
                row.name,
                Number(annual.toFixed(2)),
                Number(row.amount.toFixed(2)),
                `${annual ? ((row.amount / annual) * 100).toFixed(1) : '0.0'}%`,
              ]
            })
            .sort((left, right) =>
              Number(String(right[3]).replace('%', '')) - Number(String(left[3]).replace('%', '')),
            ),
        },
        annualTotal,
        usedTotal,
        usagePct: annualTotal ? Number(((usedTotal / annualTotal) * 100).toFixed(1)) : 0,
      }
    : undefined

  const catalogRows = summary.catalog?.table.rows ?? []
  const purchasing = {
    summary: '28 条报价；6 个套餐；12 条限流规则。报价单按输入价从高到低展示前 10 条。',
    quoteTable: {
      columns: ['供应商', '模型', '输入价', '输出价', '商务折扣', '有效期'],
      rows: catalogRows
        .slice(0, 6)
        .map((row) => [row[0], row[1], row[2], row[3], '9.5 折', '2026-12-31']),
    },
    planCount: 6,
    rateLimitCount: 12,
  }

  const mom =
    startDate && endDate
      ? {
          previousStart: startDate,
          previousEnd: endDate,
          previousAmount: Math.round(total * 0.93 * 10000),
          changePct: 7.5,
        }
      : undefined

  return {
    ...summary,
    currencyNote: '账单中的 USD 金额已按 1 USD = 7.2 CNY 折算为人民币，其余币种按原值统计。',
    budget,
    purchasing,
    mom,
  }
}

function applyProviderFilter(summary: ReportSummary, provider?: string): ReportSummary {
  if (!provider) return summary
  const names = summary.providerChart.x ?? []
  const values = summary.providerChart.series?.[0]?.data ?? []
  const index = names.findIndex((name) => name === provider)
  if (index < 0) return summary

  const amount = values[index] ?? 0
  const models = (summary.catalog?.table.rows ?? [])
    .filter((row) => row[0] === provider)
    .slice(0, 5)
    .map((row) => String(row[1]))
  const x = models.length >= 2 ? models : [`${provider} 主力模型`, `${provider} 备用模型`]
  const data = x.map((_, modelIndex) =>
    Number((amount * (modelIndex === 0 ? 0.62 : 0.38 / Math.max(1, x.length - 1))).toFixed(2)),
  )

  return {
    ...summary,
    providerFilter: provider,
    providerChart: {
      type: 'bar',
      title: `${provider} 各模型采购金额`,
      x,
      series: [{ name: '采购金额', data }],
      unit: '万元',
    },
    providerSummary: `${provider} 下 ${x[0]} 占成本 ${amount ? ((data[0] / amount) * 100).toFixed(1) : '0.0'}%，共 ${x.length} 个模型产生费用`,
    kpis: summary.kpis.map((item, kpiIndex) =>
      kpiIndex === 0 ? { ...item, label: `${provider} ${item.label}` } : item,
    ),
  }
}

export async function getReportSummary(
  datasetId?: string,
  startDate?: string,
  endDate?: string,
  provider?: string,
): Promise<ReportSummary> {
  await sleep(420)
  if (datasetId !== 'ds-bills-2025') {
    const base = applyPeriod(
      {
        ...(report2026 as unknown as ReportSummary),
        generatedAt: new Date().toISOString(),
      },
      startDate,
      endDate,
    )
    return applyProviderFilter(decorate(base, startDate, endDate), provider)
  }
  return applyProviderFilter(
    decorate(applyPeriod(legacyReportSummary(), startDate, endDate), startDate, endDate),
    provider,
  )
}

const SHARE_KEY = 'procurebi.mock.reportShares'

interface MockShareRecord extends ReportShare {
  token: string
  revokedAt?: string | null
}

function readShares(): MockShareRecord[] {
  try {
    const raw = localStorage.getItem(SHARE_KEY)
    return raw ? (JSON.parse(raw) as MockShareRecord[]) : []
  } catch {
    return []
  }
}

function writeShares(items: MockShareRecord[]) {
  localStorage.setItem(SHARE_KEY, JSON.stringify(items))
}

function shareActive(share: MockShareRecord): boolean {
  return !share.revokedAt && new Date(share.expiresAt).getTime() > Date.now()
}

function publicShare(share: MockShareRecord, withPath = false): ReportShare {
  return {
    id: share.id,
    datasetId: share.datasetId,
    datasetName: share.datasetName,
    periodStart: share.periodStart,
    periodEnd: share.periodEnd,
    provider: share.provider,
    path: withPath ? share.path : '',
    active: shareActive(share),
    expiresAt: share.expiresAt,
    createdAt: share.createdAt,
    createdByUsername: share.createdByUsername,
    viewCount: share.viewCount,
    lastViewedAt: share.lastViewedAt,
  }
}

export async function createReportShare(input: ReportShareInput): Promise<ReportShare> {
  await sleep(260)
  const id = `share-${Date.now()}`
  const token = `mock-${Math.random().toString(36).slice(2, 10)}`
  const options = await listReportDatasets()
  const dataset = options.find((item) => item.id === input.datasetId) ?? options[0]
  const record: MockShareRecord = {
    id,
    token,
    datasetId: input.datasetId,
    datasetName: dataset?.name ?? input.datasetId,
    periodStart: input.startDate ?? dataset?.periodStart ?? null,
    periodEnd: input.endDate ?? dataset?.periodEnd ?? null,
    provider: input.provider ?? null,
    path: `/share/${token}`,
    active: true,
    expiresAt: new Date(Date.now() + input.expiresInDays * 86400000).toISOString(),
    createdAt: new Date().toISOString(),
    createdByUsername: 'admin',
    viewCount: 0,
    lastViewedAt: null,
  }
  writeShares([record, ...readShares()])
  return publicShare(record, true)
}

export async function listReportShares(datasetId?: string): Promise<ReportShare[]> {
  await sleep(180)
  return readShares()
    .filter((item) => shareActive(item))
    .filter((item) => !datasetId || item.datasetId === datasetId)
    .map((item) => publicShare(item))
}

export async function revokeReportShare(id: string): Promise<void> {
  await sleep(160)
  writeShares(
    readShares().map((item) =>
      item.id === id ? { ...item, revokedAt: new Date().toISOString() } : item,
    ),
  )
}

const VIEW_KEY = 'procurebi.mock.reportViews'

function readViews(): ReportView[] {
  try {
    const raw = localStorage.getItem(VIEW_KEY)
    return raw ? (JSON.parse(raw) as ReportView[]) : []
  } catch {
    return []
  }
}

function writeViews(items: ReportView[]) {
  localStorage.setItem(VIEW_KEY, JSON.stringify(items))
}

export async function listReportViews(): Promise<ReportView[]> {
  await sleep(160)
  return readViews()
}

export async function createReportView(input: ReportViewInput): Promise<ReportView> {
  await sleep(220)
  const options = await listReportDatasets()
  const dataset = options.find((item) => item.id === input.datasetId) ?? options[0]
  const now = new Date().toISOString()
  const view: ReportView = {
    id: `view-${Date.now()}`,
    title: input.title,
    datasetId: input.datasetId,
    datasetName: dataset?.name ?? input.datasetId,
    periodStart: input.startDate ?? null,
    periodEnd: input.endDate ?? null,
    provider: input.provider ?? null,
    createdByUsername: 'admin',
    createdAt: now,
    updatedAt: now,
  }
  writeViews([view, ...readViews()])
  return view
}

export async function deleteReportView(id: string): Promise<void> {
  await sleep(140)
  writeViews(readViews().filter((item) => item.id !== id))
}

export async function getSharedReport(token: string): Promise<ReportSummary> {
  await sleep(360)
  const shares = readShares()
  const index = shares.findIndex((item) => item.token === token)
  if (index < 0 || !shareActive(shares[index])) {
    throw new Error('分享链接不存在、已过期或已被撤销。')
  }
  const share = shares[index]
  shares[index] = {
    ...share,
    viewCount: share.viewCount + 1,
    lastViewedAt: new Date().toISOString(),
  }
  writeShares(shares)
  return getReportSummary(
    share.datasetId,
    share.periodStart ?? undefined,
    share.periodEnd ?? undefined,
    share.provider ?? undefined,
  )
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function summaryCsv(summary: ReportSummary): string {
  const lines = [
    'ProcureBI 报表（Mock 导出）',
    `数据集,${summary.dataset.name}`,
    `统计期间,${summary.dataset.periodStart},${summary.dataset.periodEnd}`,
    '',
    '核心指标',
    '指标,数值,单位,说明',
    ...summary.kpis.map((item) =>
      [item.label, item.value, item.unit, item.delta]
        .map((cell) => `"${String(cell).replaceAll('"', '""')}"`)
        .join(','),
    ),
    '',
    '供应商,采购金额(万元)',
    ...(summary.providerChart.x ?? []).map((name, index) =>
      [name, summary.providerChart.series?.[0]?.data[index] ?? 0]
        .map((cell) => `"${String(cell).replaceAll('"', '""')}"`)
        .join(','),
    ),
    '',
    '自动洞察',
    ...summary.insights.map((item) =>
      [item.tag, item.title, item.meta]
        .map((cell) => `"${String(cell).replaceAll('"', '""')}"`)
        .join(','),
    ),
  ]
  return `﻿${lines.join('\r\n')}`
}

export async function downloadReportExport(input: ReportExportInput): Promise<void> {
  const summary = await getReportSummary(
    input.datasetId,
    input.startDate,
    input.endDate,
    input.provider,
  )
  downloadBlob(
    new Blob([summaryCsv(summary)], { type: 'text/csv;charset=utf-8' }),
    'procurebi-report-mock.csv',
  )
}

export async function downloadSharedReportExport(
  token: string,
  _format: ReportExportFormat,
): Promise<void> {
  const summary = await getSharedReport(token)
  downloadBlob(
    new Blob([summaryCsv(summary)], { type: 'text/csv;charset=utf-8' }),
    'procurebi-report-shared-mock.csv',
  )
}

function legacyReportSummary(): ReportSummary {
  return {
    generatedAt: new Date().toISOString(),
    dataset: {
      id: 'ds-bills-2025',
      name: 'bills_2025',
      sourceFile: 'bills_2025.xlsx',
      rowCount: 26280,
      periodStart: '2025-01-01',
      periodEnd: '2025-12-31',
    },
    kpis: [
      {
        label: '2025 年采购总成本',
        value: '22,619.82',
        unit: '万元',
        delta: '覆盖 5 家供应商 · 8 个模型',
        warn: true,
      },
      {
        label: '累计调用量',
        value: '310.3',
        unit: '亿 tokens',
        delta: '2025-01-01 至 2025-12-31',
        warn: false,
      },
      {
        label: '平均综合单价',
        value: '7.29',
        unit: '元/千token',
        delta: '账单金额 ÷（输入 + 输出 token）',
        warn: false,
      },
      {
        label: '高风险配额合同',
        value: '1',
        unit: '份',
        delta: '火山引擎已用 92.1%',
        warn: true,
      },
    ],
    providerChart: {
      type: 'bar',
      title: '各供应商采购金额',
      x: ['Anthropic', 'DeepSeek', '阿里云百炼', 'OpenAI', '火山引擎'],
      series: [{ name: '采购金额', data: [14610.15, 4951.61, 1846.62, 682.92, 528.53] }],
      unit: '万元',
    },
    appChart: {
      type: 'pie',
      title: '成本按应用分布',
      data: [
        { name: '智能客服', value: 11673.3 },
        { name: '代码助手', value: 6202.74 },
        { name: '文档摘要', value: 4743.78 },
      ],
      unit: '万元',
    },
    monthlyChart: {
      type: 'line',
      title: '2025 年月度采购成本',
      x: ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
      series: [
        {
          name: '成本',
          data: [
            1574.56, 1531.57, 1699.05, 1675.6, 1816.38, 1816.16, 1921.42, 1966.81, 2125.6,
            2202.49, 2077.59, 2212.59,
          ],
        },
      ],
      unit: '万元',
    },
    quotaTable: {
      columns: ['供应商', '承诺金额(万元)', '已用金额(万元)', '使用率', '到期日'],
      rows: [
        ['火山引擎', 574, 528.53, '92.1%', '2026-09-28'],
        ['DeepSeek', 6348, 4951.61, '78.0%', '2026-05-28'],
        ['阿里云百炼', 3078, 1846.62, '60.0%', '2026-11-28'],
        ['OpenAI', 1518, 682.92, '45.0%', '2026-07-28'],
        ['Anthropic', 48700, 14610.15, '30.0%', '2026-03-28'],
      ],
    },
    catalog: (report2026 as unknown as ReportSummary).catalog,
    providerSummary: 'Anthropic 占 64.6%，前两家合计 86.5%',
    appSummary: '智能客服是最大成本中心，占 51.6%',
    monthlySummary: '2025-03 环比 +10.9%，为统计期内最大单月增幅',
    quotaSummary: '火山引擎已用 92.1%，已进入高风险区间',
    insights: [
      {
        title: 'Anthropic 占采购成本 64.6%',
        meta: '前两家供应商合计 86.5%，金额 14,610.15 万元；集中度偏高时建议保留第二供应商的议价空间。',
        tag: '成本结构',
      },
      {
        title: '3 月成本环比 +10.9%',
        meta: '当月成本 1,699.05 万元，为统计周期内最大单月增幅，建议结合调用量与单价变化归因。',
        tag: '趋势变化',
      },
      {
        title: '火山引擎配额已用 92.1%',
        meta: '已用 528.53 / 574.00 万元，到期日 2026-09-28；已进入高风险区间时建议提前启动续约询价。',
        tag: '配额风险',
      },
      {
        title: 'doubao-lite-32k 单位成本仅为 claude-sonnet 的 0.9%',
        meta: 'doubao-lite-32k 0.37 元/千token，claude-sonnet 41.53 元/千token；高成本模型应优先评估可替代的低价模型。',
        tag: '比价建议',
      },
    ],
    modelCount: 8,
    appCount: 3,
  }
}

export async function askQuestion(
  question: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
  _datasetIds: string[] = [],
): Promise<void> {
  const answer = pickAnswer(question)

  onEvent({ type: 'status', data: { stage: '理解问题意图' } })
  await sleep(320)
  if (signal?.aborted) return

  onEvent({ type: 'status', data: { stage: '检索数据集与相关字段' } })
  await sleep(380)
  if (signal?.aborted) return

  onEvent({ type: 'status', data: { stage: answer.stage } })
  await sleep(260)
  if (signal?.aborted) return

  if (/合同|条款|配额|违约|付款|续约/.test(question)) {
    onEvent({
      type: 'sources',
      data: {
        items: [
          {
            documentId: 'doc-mock',
            document: '火山引擎采购合同',
            page: 3,
            snippet:
              '当配额使用率达到 90% 时，乙方应提前 10 个工作日书面通知甲方采购负责人，并共同评估续约或扩容方案。',
          },
        ],
      },
    })
    await sleep(180)
    if (signal?.aborted) return
  }

  onEvent({ type: 'sql', data: { sql: answer.sql, datasets: mockUsedDatasets(answer.sql) } })
  await sleep(360)
  if (signal?.aborted) return

  if (answer.table) {
    onEvent({ type: 'table', data: answer.table })
    await sleep(220)
  }
  if (answer.chart) {
    onEvent({ type: 'chart', data: answer.chart })
    await sleep(260)
  }

  onEvent({ type: 'status', data: { stage: '生成解读' } })
  await sleep(200)

  const text = answer.text
  let cursor = 0
  while (cursor < text.length) {
    if (signal?.aborted) return
    const step = 2 + Math.floor(Math.random() * 3)
    onEvent({ type: 'text', data: { delta: text.slice(cursor, cursor + step) } })
    cursor += step
    await sleep(16)
  }

  onEvent({ type: 'done', data: {} })
}

// ===== SpendOps 采购业务 Mock（localStorage）=====

import type {
  GoodsReceipt,
  GoodsReceiptInput,
  PurchaseInvoice,
  PurchaseInvoiceInput,
  PurchaseOrder,
  PurchaseOrderInput,
  Supplier,
  SupplierInput,
} from '../types'

const SKEY = 'spendops.mock.suppliers'
const OKEY = 'spendops.mock.orders'
const RKEY = 'spendops.mock.receipts'
const IKEY = 'spendops.mock.invoices'

function read<T>(key: string): T[] {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T[]) : []
  } catch {
    return []
  }
}

function write<T>(key: string, items: T[]) {
  localStorage.setItem(key, JSON.stringify(items))
}

export async function listSuppliers(status?: string): Promise<Supplier[]> {
  await sleep(160)
  const items = read<Supplier>(SKEY)
  return status ? items.filter((s) => s.status === status) : items
}

export async function createSupplier(input: SupplierInput): Promise<Supplier> {
  await sleep(260)
  const supplier: Supplier = {
    id: `sup-${Date.now()}`,
    code: input.code,
    name: input.name,
    contactName: input.contactName ?? null,
    contactPhone: input.contactPhone ?? null,
    email: input.email ?? null,
    address: input.address ?? null,
    status: 'active',
    remark: input.remark ?? null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
  write(SKEY, [supplier, ...read<Supplier>(SKEY)])
  return supplier
}

export async function updateSupplier(id: string, input: Partial<SupplierInput> & { status?: Supplier['status'] }): Promise<Supplier> {
  await sleep(200)
  const items = read<Supplier>(SKEY)
  const idx = items.findIndex((s) => s.id === id)
  if (idx < 0) throw new Error('供应商不存在。')
  items[idx] = { ...items[idx], ...input, updatedAt: new Date().toISOString() } as Supplier
  write(SKEY, items)
  return items[idx]
}

export async function listOrders(status?: string, supplierId?: string, limit = 100, offset = 0): Promise<{ items: PurchaseOrder[]; total: number }> {
  await sleep(160)
  let items = read<PurchaseOrder>(OKEY)
  if (status) items = items.filter((o) => o.status === status)
  if (supplierId) items = items.filter((o) => o.supplierId === supplierId)
  return { items: items.slice(offset, offset + limit), total: items.length }
}

export async function getOrder(id: string): Promise<PurchaseOrder> {
  await sleep(160)
  const order = read<PurchaseOrder>(OKEY).find((o) => o.id === id)
  if (!order) throw new Error('采购订单不存在。')
  return order
}

export async function createOrder(input: PurchaseOrderInput): Promise<PurchaseOrder> {
  await sleep(300)
  const lines = input.lines.map((l, i) => ({
    id: `ol-${Date.now()}-${i}`,
    lineNo: i + 1,
    itemCode: l.itemCode,
    itemName: l.itemName,
    quantity: l.quantity,
    unit: l.unit,
    unitPrice: l.unitPrice,
    taxRate: l.taxRate,
    amount: (Number(l.quantity) * Number(l.unitPrice)).toFixed(2),
    receivedQty: '0',
    invoicedQty: '0',
  }))
  const total = lines.reduce((sum, l) => sum + Number(l.amount), 0).toFixed(2)
  const order: PurchaseOrder = {
    id: `po-${Date.now()}`,
    orderNo: input.orderNo,
    supplierId: input.supplierId,
    supplierName: read<Supplier>(SKEY).find((s) => s.id === input.supplierId)?.name ?? '',
    orderDate: input.orderDate,
    status: 'submitted',
    currency: 'CNY',
    totalAmount: total,
    remark: input.remark ?? null,
    lines,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
  write(OKEY, [order, ...read<PurchaseOrder>(OKEY)])
  return order
}

export async function cancelOrder(id: string): Promise<PurchaseOrder> {
  await sleep(200)
  const items = read<PurchaseOrder>(OKEY)
  const idx = items.findIndex((o) => o.id === id)
  if (idx < 0) throw new Error('采购订单不存在。')
  items[idx] = { ...items[idx], status: 'cancelled', updatedAt: new Date().toISOString() }
  write(OKEY, items)
  return items[idx]
}

export async function listReceipts(orderId?: string): Promise<GoodsReceipt[]> {
  await sleep(160)
  const items = read<GoodsReceipt>(RKEY)
  return orderId ? items.filter((r) => r.orderId === orderId) : items
}

export async function createReceipt(input: GoodsReceiptInput): Promise<GoodsReceipt> {
  await sleep(300)
  const order = read<PurchaseOrder>(OKEY).find((o) => o.id === input.orderId)
  const lines = input.lines.map((l, i) => {
    const ol = order?.lines.find((x) => x.id === l.orderLineId)
    return {
      id: `rl-${Date.now()}-${i}`,
      lineNo: i + 1,
      orderLineId: l.orderLineId,
      itemName: ol?.itemName ?? '',
      quantity: l.quantity,
      unitPrice: ol?.unitPrice ?? '0',
      amount: (Number(l.quantity) * Number(ol?.unitPrice ?? 0)).toFixed(2),
    }
  })
  const receipt: GoodsReceipt = {
    id: `gr-${Date.now()}`,
    receiptNo: input.receiptNo,
    orderId: input.orderId,
    orderNo: order?.orderNo ?? '',
    supplierId: order?.supplierId ?? '',
    supplierName: order?.supplierName ?? '',
    receiptDate: input.receiptDate,
    status: 'posted',
    totalQuantity: lines.reduce((s, l) => s + Number(l.quantity), 0).toFixed(3),
    totalAmount: lines.reduce((s, l) => s + Number(l.amount), 0).toFixed(2),
    remark: input.remark ?? null,
    lines,
    createdAt: new Date().toISOString(),
  }
  write(RKEY, [receipt, ...read<GoodsReceipt>(RKEY)])
  return receipt
}

export async function listInvoices(orderId?: string): Promise<PurchaseInvoice[]> {
  await sleep(160)
  const items = read<PurchaseInvoice>(IKEY)
  return orderId ? items.filter((i) => i.orderId === orderId) : items
}

export async function createInvoice(input: PurchaseInvoiceInput): Promise<PurchaseInvoice> {
  await sleep(300)
  const lines = input.lines.map((l, i) => ({
    id: `il-${Date.now()}-${i}`,
    lineNo: i + 1,
    orderLineId: l.orderLineId ?? null,
    itemName: l.itemName,
    quantity: l.quantity,
    unitPrice: l.unitPrice,
    amount: (Number(l.quantity) * Number(l.unitPrice)).toFixed(2),
  }))
  const total = lines.reduce((s, l) => s + Number(l.amount), 0).toFixed(2)
  const tax = lines.reduce((s, l) => s + Number(l.amount) * Number(input.lines.find((x) => x.itemName === l.itemName)?.taxRate ?? 0), 0).toFixed(2)
  const invoice: PurchaseInvoice = {
    id: `inv-${Date.now()}`,
    invoiceNo: input.invoiceNo,
    orderId: input.orderId ?? null,
    orderNo: read<PurchaseOrder>(OKEY).find((o) => o.id === input.orderId)?.orderNo ?? '',
    supplierId: input.supplierId,
    supplierName: read<Supplier>(SKEY).find((s) => s.id === input.supplierId)?.name ?? '',
    invoiceDate: input.invoiceDate,
    status: 'posted',
    currency: 'CNY',
    totalAmount: total,
    taxAmount: tax,
    remark: input.remark ?? null,
    lines,
    createdAt: new Date().toISOString(),
  }
  write(IKEY, [invoice, ...read<PurchaseInvoice>(IKEY)])
  return invoice
}

// ===== SpendOps G2 数据导入 Mock =====

import type { ImportErrorsResult, ImportTask, ImportTaskType } from '../types'

const IMPKEY = 'spendops.mock.imports'

function readImports(): ImportTask[] {
  try {
    const raw = localStorage.getItem(IMPKEY)
    return raw ? (JSON.parse(raw) as ImportTask[]) : []
  } catch {
    return []
  }
}

function writeImports(items: ImportTask[]) {
  localStorage.setItem(IMPKEY, JSON.stringify(items))
}

export async function uploadImport(file: File, taskType: ImportTaskType): Promise<ImportTask> {
  await sleep(500)
  const task: ImportTask = {
    id: `imp-${Date.now()}`,
    taskType,
    originalName: file.name,
    fileHash: `mock-${Date.now()}`,
    fileSize: file.size,
    status: 'awaiting_confirm',
    totalRows: 3,
    processedRows: 0,
    successRows: 0,
    failedRows: 1,
    errorSummary: { missing_required: 1 },
    createdByUsername: 'admin',
    lastError: null,
    createdAt: new Date().toISOString(),
    startedAt: null,
    finishedAt: null,
    preview: [
      { rowNumber: 2, raw: { 供应商编码: 'S001', 供应商名称: '供应商甲' }, mapped: { code: 'S001', name: '供应商甲' }, status: 'valid', errorType: null, errorField: null, errorMessage: null },
      { rowNumber: 3, raw: { 供应商编码: 'S002', 供应商名称: '' }, mapped: null, status: 'error', errorType: 'missing_required', errorField: 'name', errorMessage: '必填字段「供应商名称」为空。' },
    ],
  }
  writeImports([task, ...readImports()])
  return task
}

export async function listImports(): Promise<ImportTask[]> {
  await sleep(180)
  return readImports()
}

export async function getImport(id: string): Promise<ImportTask> {
  await sleep(160)
  const task = readImports().find((t) => t.id === id)
  if (!task) throw new Error('导入任务不存在。')
  return task
}

export async function getImportErrors(_id: string, limit = 100, offset = 0): Promise<ImportErrorsResult> {
  await sleep(180)
  const errors = [
    { rowNumber: 3, errorType: 'missing_required', field: 'name', message: '必填字段「供应商名称」为空。', suggestion: '请在源文件中补全该必填列的值后重新导入。' },
  ]
  return { total: errors.length, offset, limit, errors: errors.slice(offset, offset + limit) }
}

export async function confirmImport(id: string): Promise<ImportTask> {
  await sleep(300)
  const items = readImports()
  const idx = items.findIndex((t) => t.id === id)
  if (idx < 0) throw new Error('导入任务不存在。')
  items[idx] = { ...items[idx], status: 'importing' }
  writeImports(items)
  // 模拟异步完成后状态
  setTimeout(() => {
    const cur = readImports()
    const i = cur.findIndex((t) => t.id === id)
    if (i >= 0) {
      cur[i] = { ...cur[i], status: 'partial_failed', successRows: 2, failedRows: 1, processedRows: 3, finishedAt: new Date().toISOString() }
      writeImports(cur)
    }
  }, 2000)
  return items[idx]
}

export async function cancelImport(id: string): Promise<ImportTask> {
  await sleep(200)
  const items = readImports()
  const idx = items.findIndex((t) => t.id === id)
  if (idx < 0) throw new Error('导入任务不存在。')
  items[idx] = { ...items[idx], status: 'cancelled', finishedAt: new Date().toISOString() }
  writeImports(items)
  return items[idx]
}

// ===== SpendOps G3 经营指标 Mock =====

import type {
  CategoryResult,
  DeliveryResult,
  DiscrepancyResult,
  MetricsOverview,
  SupplierRanking,
  TrendResult,
} from '../types'

export async function getMetricsOverview(_params: { start: string; end: string; supplierId?: string | null; orderStatus?: string | null; topN?: number }): Promise<MetricsOverview> {
  await sleep(220)
  return {
    orderAmount: '2800.00',
    receiptAmount: '2500.00',
    invoiceAmount: '2400.00',
    invoiceTaxAmount: '312.00',
    pendingVerificationAmount: '1000.00',
    supplierCount: 2,
    deliveryRate: '0.6',
    deliveryOntimeCount: 3,
    deliveryJudgedCount: 5,
  }
}

export async function getSupplierRanking(_start: string, _end: string, _topN = 10): Promise<SupplierRanking> {
  await sleep(220)
  return {
    ranking: [
      { code: 'S1', name: '供应商甲', amount: '2100.00', share: '0.75' },
      { code: 'S2', name: '供应商乙', amount: '700.00', share: '0.25' },
    ],
    topAmount: '2100.00',
    totalAmount: '2800.00',
    concentration: '0.75',
  }
}

export async function getMetricsTrend(_start: string, _end: string, _supplierId?: string | null): Promise<TrendResult> {
  await sleep(220)
  const months = ['2026-01', '2026-02', '2026-03', '2026-04']
  return {
    months,
    series: months.map((m) => ({ month: m, orderAmount: '0', receiptAmount: '0', invoiceAmount: '0' })),
  }
}

export async function getDeliveryPerformance(_start: string, _end: string, _supplierId?: string | null): Promise<DeliveryResult> {
  await sleep(200)
  return { ontime: 3, late: 2, judged: 5, excluded: 0, rate: '0.6' }
}

export async function getCategoryBreakdown(_start: string, _end: string): Promise<CategoryResult> {
  await sleep(200)
  return {
    total: '2800.00',
    items: [
      { category: '电子', amount: '1700.00', share: '0.6071' },
      { category: '机械', amount: '1100.00', share: '0.3929' },
    ],
  }
}

export async function getDiscrepancies(_start: string, _end: string): Promise<DiscrepancyResult> {
  await sleep(200)
  return { items: [], total: 0 }
}

// ===== SpendOps G5 受控经营问数 Mock =====

import type { AnalysisMode, AnalysisResult } from '../types'

const MOCK_ANALYSIS: AnalysisResult = {
  question: '',
  mode: 'offline',
  intent: 'overview',
  intentLabel: '经营总览（订单/收货/开票金额）',
  timeRange: { start: '2026-01-01', end: '2026-12-31' },
  supplier: null,
  metricName: '经营总览',
  metricDefinition: '采购订单金额 = Σ 订单明细金额（数量×单价），排除已取消订单。',
  facts: {
    orderAmount: '2800.00',
    receiptAmount: '2500.00',
    invoiceAmount: '2400.00',
    pendingVerificationAmount: '1000.00',
    supplierCount: 2,
  },
  explanation: '采购订单金额 ¥2,800.00，已收货金额 ¥2,500.00，已开票金额（未税）¥2,400.00，待核对金额 ¥1,000.00，供应商 2 家。以上金额与比例均为数据库确定性计算，模型未参与生成数字。',
  observations: [],
  generatedAt: '2026-11-05',
  limitations: ['金额为未税、单币种 CNY。'],
}

export async function askAnalysis(question: string, _mode: AnalysisMode = 'offline'): Promise<AnalysisResult> {
  await sleep(500)
  return { ...MOCK_ANALYSIS, question, mode: _mode }
}

export async function getAnalysisExamples(): Promise<string[]> {
  await sleep(120)
  return [
    '2026 年采购订单金额是多少？',
    '哪些供应商采购金额最高？',
    '哪些订单存在交付延期？',
  ]
}
