export type ColumnType = 'text' | 'number' | 'date'

export interface ColumnMeta {
  name: string
  type: ColumnType
  sample: string
}

export interface ImportQuality {
  sourceRows: number
  importedRows: number
  blankRows: number
  duplicateRows: number
  invalidCells: number
  issues: string[]
}

export interface Dataset {
  id: string
  name: string
  sourceFile: string
  sheetName?: string
  rowCount: number
  columns: ColumnMeta[]
  createdAt: string
  status: 'active' | 'archived'
  ownerId?: string | null
  quality?: ImportQuality | null
}

export type CellValue = string | number | null

export interface DatasetRows {
  columns: string[]
  rows: CellValue[][]
  total: number
  offset: number
  limit: number
}

export interface TableResult {
  columns: string[]
  rows: CellValue[][]
  /** 结果超过安全上限（500 行）时由后端标记。 */
  truncated?: boolean
}

export interface DocumentItem {
  id: string
  name: string
  sourceFile: string
  docType: string
  pageCount: number
  charCount: number
  chunkCount: number
  createdAt: string
  status: 'active' | 'archived'
}

export interface PreviewResult {
  sheetName: string
  rowCount: number
  columns: ColumnMeta[]
  rows: CellValue[][]
  quality?: ImportQuality | null
}

export interface DocumentPages {
  id: string
  name: string
  pageCount: number
  pages: { page: number; content: string }[]
}

export interface ChatSource {
  documentId: string
  document: string
  page: number | null
  snippet: string
}

export interface ChartSeries {
  name: string
  data: number[]
}

export interface ChartSpec {
  type: 'bar' | 'line' | 'pie'
  title: string
  x?: string[]
  series?: ChartSeries[]
  data?: { name: string; value: number }[]
  unit?: string
}

export type ChatEvent =
  | { type: 'status'; data: { stage: string } }
  | { type: 'sql'; data: { sql: string; datasets?: string[] } }
  | { type: 'table'; data: TableResult }
  | { type: 'chart'; data: ChartSpec }
  | { type: 'text'; data: { delta: string } }
  | { type: 'sources'; data: { items: ChatSource[] } }
  | { type: 'error'; data: { message: string } }
  | { type: 'done'; data: Record<string, never> }

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sql?: string
  datasets?: string[]
  table?: TableResult
  chart?: ChartSpec
  sources?: ChatSource[]
  status?: string
  loading?: boolean
  error?: string
}

export interface ReportKpi {
  label: string
  value: string
  unit: string
  delta: string
  warn: boolean
}

export interface ReportInsight {
  title: string
  meta: string
  tag: string
}

export interface ReportDataset {
  id: string
  name: string
  sourceFile: string
  rowCount: number
  periodStart: string
  periodEnd: string
}

export interface ReportDatasetOption {
  id: string
  name: string
  rowCount: number
  periodStart: string
  periodEnd: string
}

export interface ReportCatalog {
  totalModels: number
  providerCount: number
  summary: string
  table: TableResult
}

export type Role = 'admin' | 'viewer'

export interface AuthUser {
  id: string
  username: string
  displayName: string
  role: Role
  isActive: boolean
  mustChangePassword: boolean
  lastLoginAt: string | null
  createdAt: string
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface AdminOverview {
  users: number
  activeUsers: number
  admins: number
  datasets: number
  activeDatasets: number
  documents: number
  auditEvents24h: number
  recentAudit: AuditLogItem[]
}

export interface AuditLogItem {
  id: string
  actorUsername: string
  action: string
  targetType: string | null
  targetId: string | null
  status: 'success' | 'failure'
  detail: Record<string, unknown> | null
  ip: string | null
  createdAt: string
}

export interface ListUsersParams {
  page?: number
  pageSize?: number
  q?: string
  role?: Role
  isActive?: boolean
}

export interface AuditLogParams {
  page?: number
  pageSize?: number
  action?: string
  status?: 'success' | 'failure'
  actor?: string
  start?: string
  end?: string
}

export interface CreateUserInput {
  username: string
  password: string
  role: Role
  displayName?: string
}

export interface UpdateUserInput {
  displayName?: string
  role?: Role
  isActive?: boolean
}

export interface ReportMom {
  previousStart: string
  previousEnd: string
  previousAmount: number
  changePct: number | null
}

export interface ReportBudget {
  summary: string
  table: TableResult
  annualTotal: number
  usedTotal: number
  usagePct: number
}

export interface ReportPurchasing {
  summary: string
  quoteTable: TableResult
  planCount: number
  rateLimitCount: number
}

export interface ReportSummary {
  generatedAt: string
  dataset: ReportDataset
  kpis: ReportKpi[]
  providerChart: ChartSpec
  appChart?: ChartSpec
  monthlyChart?: ChartSpec
  quotaTable: TableResult
  catalog?: ReportCatalog
  providerSummary: string
  appSummary: string
  monthlySummary: string
  quotaSummary: string
  insights: ReportInsight[]
  modelCount: number
  appCount: number
  providerFilter?: string | null
  mom?: ReportMom
  budget?: ReportBudget
  purchasing?: ReportPurchasing
  currencyNote?: string | null
}

export type ReportExportFormat = 'xlsx' | 'pdf'

export interface ReportExportInput {
  datasetId?: string
  startDate?: string
  endDate?: string
  provider?: string
  format: ReportExportFormat
}

export interface ReportShareInput {
  datasetId: string
  startDate?: string
  endDate?: string
  provider?: string
  expiresInDays: number
}

export interface ReportShare {
  id: string
  datasetId: string
  datasetName: string
  periodStart?: string | null
  periodEnd?: string | null
  provider?: string | null
  /** 创建时返回，列表接口为空字符串。 */
  path: string
  active: boolean
  expiresAt: string
  createdAt: string
  createdByUsername: string
  viewCount: number
  lastViewedAt?: string | null
}

export interface ReportViewInput {
  title: string
  datasetId: string
  startDate?: string
  endDate?: string
  provider?: string
}

export interface ReportView {
  id: string
  title: string
  datasetId: string
  datasetName: string
  periodStart?: string | null
  periodEnd?: string | null
  provider?: string | null
  createdByUsername: string
  createdAt: string
  updatedAt: string
}

// ===== SpendOps 采购业务类型 =====

export type SupplierStatus = 'active' | 'inactive' | 'blocked'

export interface Supplier {
  id: string
  code: string
  name: string
  contactName?: string | null
  contactPhone?: string | null
  email?: string | null
  address?: string | null
  status: SupplierStatus
  remark?: string | null
  createdAt: string
  updatedAt: string
}

export interface SupplierInput {
  code: string
  name: string
  contactName?: string | null
  contactPhone?: string | null
  email?: string | null
  address?: string | null
  remark?: string | null
}

export type OrderStatus = 'draft' | 'submitted' | 'partially_received' | 'received' | 'cancelled'

export interface OrderLineInput {
  itemCode: string
  itemName: string
  quantity: string
  unit: string
  unitPrice: string
  taxRate: string
}

export interface PurchaseOrderInput {
  orderNo: string
  supplierId: string
  orderDate: string
  lines: OrderLineInput[]
  remark?: string | null
}

export interface OrderLine {
  id: string
  lineNo: number
  itemCode: string
  itemName: string
  quantity: string
  unit: string
  unitPrice: string
  taxRate: string
  amount: string
  receivedQty: string
  invoicedQty: string
}

export interface PurchaseOrder {
  id: string
  orderNo: string
  supplierId: string
  supplierName: string
  orderDate: string
  status: OrderStatus
  currency: string
  totalAmount: string
  remark?: string | null
  lines: OrderLine[]
  createdAt: string
  updatedAt: string
}

export interface ReceiptLineInput {
  orderLineId: string
  quantity: string
}

export interface GoodsReceiptInput {
  receiptNo: string
  orderId: string
  receiptDate: string
  lines: ReceiptLineInput[]
  remark?: string | null
}

export interface ReceiptLine {
  id: string
  lineNo: number
  orderLineId: string
  itemName: string
  quantity: string
  unitPrice: string
  amount: string
}

export interface GoodsReceipt {
  id: string
  receiptNo: string
  orderId: string
  orderNo: string
  supplierId: string
  supplierName: string
  receiptDate: string
  status: string
  totalQuantity: string
  totalAmount: string
  remark?: string | null
  lines: ReceiptLine[]
  createdAt: string
}

export interface InvoiceLineInput {
  orderLineId?: string | null
  itemName: string
  quantity: string
  unitPrice: string
  taxRate: string
}

export interface PurchaseInvoiceInput {
  invoiceNo: string
  orderId?: string | null
  supplierId: string
  invoiceDate: string
  lines: InvoiceLineInput[]
  remark?: string | null
}

export interface InvoiceLine {
  id: string
  lineNo: number
  orderLineId?: string | null
  itemName: string
  quantity: string
  unitPrice: string
  amount: string
}

export interface PurchaseInvoice {
  id: string
  invoiceNo: string
  orderId?: string | null
  orderNo: string
  supplierId: string
  supplierName: string
  invoiceDate: string
  status: string
  currency: string
  totalAmount: string
  taxAmount: string
  remark?: string | null
  lines: InvoiceLine[]
  createdAt: string
}

// ===== SpendOps G2 数据导入类型 =====

export type ImportTaskType = 'supplier' | 'purchase_order' | 'goods_receipt' | 'purchase_invoice'

export type ImportTaskStatus =
  | 'uploaded'
  | 'awaiting_confirm'
  | 'importing'
  | 'completed'
  | 'partial_failed'
  | 'failed'
  | 'cancelled'

export interface ImportErrorItem {
  rowNumber: number
  errorType: string
  field: string | null
  message: string | null
  suggestion: string
}

export interface ImportErrorsResult {
  total: number
  offset: number
  limit: number
  errors: ImportErrorItem[]
}

export interface ImportPreviewRow {
  rowNumber: number
  raw: Record<string, string | null>
  mapped: Record<string, string | null> | null
  status: string
  errorType: string | null
  errorField: string | null
  errorMessage: string | null
}

export interface ImportTask {
  id: string
  taskType: ImportTaskType
  originalName: string
  fileHash: string
  fileSize: number
  status: ImportTaskStatus
  totalRows: number
  processedRows: number
  successRows: number
  failedRows: number
  errorSummary: Record<string, number> | null
  createdByUsername: string
  lastError: string | null
  createdAt: string | null
  startedAt: string | null
  finishedAt: string | null
  preview?: ImportPreviewRow[]
}

// ===== SpendOps G3 经营指标类型 =====

export interface MetricsOverview {
  orderAmount: string
  receiptAmount: string
  invoiceAmount: string
  invoiceTaxAmount: string
  pendingVerificationAmount: string
  supplierCount: number
  deliveryRate: string | null
  deliveryOntimeCount: number
  deliveryJudgedCount: number
}

export interface SupplierRankingItem {
  code: string
  name: string
  amount: string
  share: string
}

export interface SupplierRanking {
  ranking: SupplierRankingItem[]
  topAmount: string
  totalAmount: string
  concentration: string
}

export interface TrendPoint {
  month: string
  orderAmount: string
  receiptAmount: string
  invoiceAmount: string
}

export interface TrendResult {
  months: string[]
  series: TrendPoint[]
}

export interface DeliveryResult {
  ontime: number
  late: number
  judged: number
  excluded: number
  rate: string | null
}

export interface CategoryItem {
  category: string
  amount: string
  share: string
}

export interface CategoryResult {
  total: string
  items: CategoryItem[]
}

export interface DiscrepancyItem {
  orderNo: string
  supplierCode: string
  itemName: string
  quantity: string
  receivedQty: string
  invoicedQty: string
  orderAmount: string
  receiptAmount: string
  invoiceAmount: string
  discrepancyKinds: string[]
}

export interface DiscrepancyResult {
  items: DiscrepancyItem[]
  total: number
}

// ===== SpendOps G5 受控经营问数类型 =====

export type AnalysisMode = 'offline' | 'llm'

export interface AnalysisResult {
  question: string
  mode: AnalysisMode
  intent: string
  intentLabel: string
  timeRange: { start: string; end: string }
  supplier: { id: string; code: string; name: string } | null
  metricName: string
  metricDefinition: string
  facts: Record<string, unknown>
  explanation: string
  observations: string[]
  generatedAt: string
  limitations: string[]
}
