<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { api } from '../api'
import { ApiError } from '../api/errors'
import type {
  CategoryResult,
  DeliveryResult,
  DiscrepancyResult,
  MetricsOverview,
  Supplier,
  SupplierRanking,
  TrendResult,
  ChartSpec,
} from '../api/types'
import ChartRenderer from '../components/ChartRenderer.vue'
import AiAnalysisPanel from './AiAnalysisPanel.vue'

const ORDER_STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'submitted', label: '已提交' },
  { value: 'partially_received', label: '部分收货' },
  { value: 'received', label: '已收货' },
  { value: 'cancelled', label: '已取消' },
]

function fmtMoney(v: string | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtRate(v: string | null | undefined): string {
  if (v === null || v === undefined) return '不可计算'
  return `${(Number(v) * 100).toFixed(1)}%`
}

function num(v: string): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

const filters = reactive({
  start: '2026-01-01',
  end: '2026-12-31',
  supplierId: '' as string,
  orderStatus: '' as string,
})

const suppliers = ref<Supplier[]>([])
const overview = ref<MetricsOverview | null>(null)
const ranking = ref<SupplierRanking | null>(null)
const trend = ref<TrendResult | null>(null)
const delivery = ref<DeliveryResult | null>(null)
const categories = ref<CategoryResult | null>(null)
const discrepancies = ref<DiscrepancyResult | null>(null)
const loading = ref(false)
const error = ref('')

async function loadSuppliers() {
  try {
    suppliers.value = await api.listSuppliers()
  } catch {
    suppliers.value = []
  }
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const start = filters.start
    const end = filters.end
    const supplierId = filters.supplierId || null
    const orderStatus = filters.orderStatus || null
    const [ov, rk, tr, dv, cat, disc] = await Promise.all([
      api.getMetricsOverview({ start, end, supplierId, orderStatus }),
      api.getSupplierRanking(start, end, 10),
      api.getMetricsTrend(start, end, supplierId),
      api.getDeliveryPerformance(start, end, supplierId),
      api.getCategoryBreakdown(start, end),
      api.getDiscrepancies(start, end),
    ])
    overview.value = ov
    ranking.value = rk
    trend.value = tr
    delivery.value = dv
    categories.value = cat
    discrepancies.value = disc
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

const trendSpec = computed<ChartSpec | null>(() => {
  if (!trend.value) return null
  return {
    type: 'line',
    title: '采购金额趋势（未税）',
    x: trend.value.months,
    unit: '元',
    series: [
      { name: '订单金额', data: trend.value.series.map((s) => num(s.orderAmount)) },
      { name: '收货金额', data: trend.value.series.map((s) => num(s.receiptAmount)) },
      { name: '发票金额', data: trend.value.series.map((s) => num(s.invoiceAmount)) },
    ],
  }
})

const rankingSpec = computed<ChartSpec | null>(() => {
  if (!ranking.value || ranking.value.ranking.length === 0) return null
  const top = [...ranking.value.ranking].reverse()
  return {
    type: 'bar',
    title: `供应商采购金额 Top ${ranking.value.ranking.length}`,
    x: top.map((r) => r.name),
    unit: '元',
    series: [{ name: '采购金额', data: top.map((r) => num(r.amount)) }],
  }
})

const categorySpec = computed<ChartSpec | null>(() => {
  if (!categories.value || categories.value.items.length === 0) return null
  return {
    type: 'pie',
    title: '品类采购占比（未税）',
    unit: '元',
    data: categories.value.items.map((c) => ({ name: c.category, value: num(c.amount) })),
  }
})

function selectSupplier(name: string) {
  const item = ranking.value?.ranking.find((r) => r.name === name)
  if (item) {
    const sup = suppliers.value.find((s) => s.name === name || s.code === item.code)
    filters.supplierId = sup ? sup.id : filters.supplierId
  }
}

function resetSupplier() {
  filters.supplierId = ''
}

function exportCsv() {
  if (!discrepancies.value || discrepancies.value.items.length === 0) return
  const header = ['订单号', '供应商', '物料', '数量', '已收', '已开票', '订单金额', '收货金额', '发票金额', '差异']
  const rows = discrepancies.value.items.map((d) => [
    d.orderNo, d.supplierCode, d.itemName, d.quantity, d.receivedQty, d.invoicedQty,
    d.orderAmount, d.receiptAmount, d.invoiceAmount, d.discrepancyKinds.join('|'),
  ])
  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n')
  // 公式注入防护：以 = + - @ 开头的单元格加前缀 '
  const safe = csv.replace(/"(?=[=+\-@])/g, '"\'')
  const blob = new Blob(['\ufeff' + safe], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `spendops-discrepancies-${filters.start}-${filters.end}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

const DISCREPANCY_LABEL: Record<string, string> = {
  unreceived: '未收货',
  partial_received: '部分收货',
  received_not_invoiced: '已收货未开票',
  pre_invoiced: '提前开票',
}

watch(filters, loadAll)
onMounted(() => {
  loadSuppliers()
  loadAll()
})
</script>

<template>
  <main class="app-main">
    <header class="page-head">
      <div>
        <h1 class="page-title">经营分析</h1>
        <p class="page-sub">采购订单、收货与发票的真实经营指标（金额未税，币种 CNY）</p>
      </div>
    </header>

    <!-- AI 受控问数 -->
    <AiAnalysisPanel />

    <!-- 筛选栏 -->
    <section class="filter-bar">
      <label class="field">
        <span>开始日期</span>
        <input v-model="filters.start" type="date" class="input" />
      </label>
      <label class="field">
        <span>结束日期</span>
        <input v-model="filters.end" type="date" class="input" />
      </label>
      <label class="field">
        <span>供应商</span>
        <select v-model="filters.supplierId" class="input">
          <option value="">全部供应商</option>
          <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </label>
      <label class="field">
        <span>订单状态</span>
        <select v-model="filters.orderStatus" class="input">
          <option v-for="o in ORDER_STATUS_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>
      <button v-if="filters.supplierId" class="btn btn-small" type="button" @click="resetSupplier">
        清除供应商
      </button>
    </section>

    <p v-if="error" class="inline-error">{{ error }}</p>
    <div v-if="loading" class="empty-state">加载中…</div>

    <template v-else-if="overview">
      <!-- KPI 总览 -->
      <section class="kpi-grid">
        <div class="kpi-card">
          <span class="kpi-label">采购订单金额</span>
          <span class="kpi-value">{{ fmtMoney(overview.orderAmount) }}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">已收货金额</span>
          <span class="kpi-value">{{ fmtMoney(overview.receiptAmount) }}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">已开票金额（未税）</span>
          <span class="kpi-value">{{ fmtMoney(overview.invoiceAmount) }}</span>
        </div>
        <div class="kpi-card warn">
          <span class="kpi-label">待核对发票金额</span>
          <span class="kpi-value">{{ fmtMoney(overview.pendingVerificationAmount) }}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">供应商数量</span>
          <span class="kpi-value">{{ overview.supplierCount }}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">交货及时率</span>
          <span class="kpi-value">{{ fmtRate(overview.deliveryRate) }}</span>
          <span class="kpi-sub">及时 {{ overview.deliveryOntimeCount }} / 判定 {{ overview.deliveryJudgedCount }}</span>
        </div>
      </section>

      <!-- 图表 -->
      <section class="chart-grid">
        <div class="chart-card wide">
          <h3 class="card-title">{{ trendSpec?.title }}</h3>
          <ChartRenderer v-if="trendSpec" :spec="trendSpec" class="chart-lg" />
        </div>
        <div class="chart-card">
          <h3 class="card-title">{{ rankingSpec?.title }}</h3>
          <ChartRenderer v-if="rankingSpec" :spec="rankingSpec" class="chart-lg" />
        </div>
        <div class="chart-card">
          <h3 class="card-title">{{ categorySpec?.title }}</h3>
          <ChartRenderer v-if="categorySpec" :spec="categorySpec" class="chart-lg" />
        </div>
      </section>

      <!-- 供应商排名表（下钻） -->
      <section class="card">
        <h3 class="card-title">供应商采购金额与集中度（点击下钻筛选）</h3>
        <div v-if="ranking && ranking.ranking.length" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>供应商编码</th>
                <th>供应商名称</th>
                <th>采购金额</th>
                <th>占比</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in ranking.ranking"
                :key="r.code"
                class="drillable"
                :class="{ active: filters.supplierId === suppliers.find((s) => s.code === r.code)?.id }"
                @click="selectSupplier(r.name)"
              >
                <td class="mono">{{ r.code }}</td>
                <td>{{ r.name }}</td>
                <td>{{ fmtMoney(r.amount) }}</td>
                <td>{{ fmtRate(r.share) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="ranking" class="hint">Top {{ ranking.ranking.length }} 集中度：{{ fmtRate(ranking.concentration) }}</p>
      </section>

      <!-- 差异分析 + 导出 -->
      <section class="card">
        <div class="card-head">
          <h3 class="card-title">订单 / 收货 / 发票差异分析</h3>
          <button class="btn btn-small" type="button" @click="exportCsv">导出 CSV</button>
        </div>
        <div v-if="discrepancies && discrepancies.items.length" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>订单号</th>
                <th>供应商</th>
                <th>物料</th>
                <th>数量</th>
                <th>已收</th>
                <th>已开票</th>
                <th>差异</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(d, i) in discrepancies.items" :key="i">
                <td class="mono">{{ d.orderNo }}</td>
                <td>{{ d.supplierCode }}</td>
                <td>{{ d.itemName }}</td>
                <td>{{ d.quantity }}</td>
                <td>{{ d.receivedQty }}</td>
                <td>{{ d.invoicedQty }}</td>
                <td>
                  <span
                    v-for="k in d.discrepancyKinds"
                    :key="k"
                    class="chip status-err"
                  >{{ DISCREPANCY_LABEL[k] ?? k }}</span>
                  <span v-if="d.discrepancyKinds.length === 0" class="chip status-ok">匹配</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state">
          <p class="empty-title">当前筛选下暂无差异记录</p>
        </div>
      </section>
    </template>
  </main>
</template>

<style scoped>
.filter-bar {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 16px;
}
.filter-bar .field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.filter-bar .field span {
  font-size: 12px;
  color: var(--muted, #888);
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.kpi-card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kpi-card.warn {
  border-color: #f59e0b;
}
.kpi-label {
  font-size: 12px;
  color: var(--muted, #888);
}
.kpi-value {
  font-size: 20px;
  font-weight: 650;
}
.kpi-sub {
  font-size: 11px;
  color: var(--muted, #888);
}
.chart-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}
.chart-card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  padding: 14px 16px;
}
.chart-card.wide {
  grid-column: 1 / -1;
}
.card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 10px;
}
.chart-lg {
  height: 260px;
  width: 100%;
}
.drillable {
  cursor: pointer;
}
.drillable:hover {
  background: var(--bg-hover, #f3f4f6);
}
.drillable.active {
  background: #e0f2fe;
}
.table-wrap {
  overflow-x: auto;
}
.chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  margin-right: 4px;
}
.status-ok {
  background: #e8f5e9;
  color: #1b7f3b;
}
.status-err {
  background: #fdecea;
  color: #c0392b;
}
.hint {
  font-size: 12px;
  color: var(--muted, #888);
  margin-top: 8px;
}
.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.inline-error {
  color: #c0392b;
  font-size: 13px;
  margin: 10px 0;
}
.empty-state {
  padding: 24px;
  text-align: center;
  color: var(--muted, #888);
}
.empty-title {
  margin: 0;
  font-weight: 600;
}
</style>
