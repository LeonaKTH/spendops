<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api, USING_MOCK } from '../api'
import type {
  ReportDatasetOption,
  ReportExportFormat,
  ReportSummary,
  ReportView,
} from '../api/types'
import ReportBody from '../components/ReportBody.vue'
import ReportShareDialog from '../components/ReportShareDialog.vue'

type PeriodKey =
  | 'all'
  | 'month'
  | 'quarter'
  | 'year'
  | 'last-month'
  | 'last-quarter'
  | 'custom'

const PERIODS: { value: PeriodKey; label: string }[] = [
  { value: 'all', label: '全部账期' },
  { value: 'month', label: '最新月份' },
  { value: 'last-month', label: '上月' },
  { value: 'quarter', label: '最新季度' },
  { value: 'last-quarter', label: '上季度' },
  { value: 'year', label: '本年度' },
  { value: 'custom', label: '自定义' },
]

const summary = ref<ReportSummary | null>(null)
const datasets = ref<ReportDatasetOption[]>([])
const selectedId = ref('')
const periodKey = ref<PeriodKey>('all')
const customStart = ref('')
const customEnd = ref('')
const loading = ref(false)
const exporting = ref<ReportExportFormat | ''>('')
const error = ref('')
const actionError = ref('')
const shareOpen = ref(false)
const providerFilter = ref('')
const views = ref<ReportView[]>([])
const selectedViewId = ref('')
const saveOpen = ref(false)
const viewTitle = ref('')
const savingView = ref(false)

const selectedOption = computed(
  () => datasets.value.find((item) => item.id === selectedId.value) ?? null,
)

const range = computed(() => resolveRange())

const periodLabel = computed(() => formatRange(range.value.start, range.value.end))

const generatedLabel = computed(() => {
  if (!summary.value) return ''
  const value = new Date(summary.value.generatedAt)
  if (Number.isNaN(value.getTime())) return summary.value.generatedAt
  return value.toLocaleString('zh-CN', { hour12: false })
})

const datasetLabel = computed(() => {
  if (!summary.value) return '基于已启用数据集自动汇总'
  const { dataset } = summary.value
  return `基于数据集 ${dataset.name} · ${dataset.rowCount.toLocaleString('zh-CN')} 行 · 数据截止 ${dataset.periodEnd || '—'} · 报表生成于 ${generatedLabel.value}`
})

const shareDisabled = computed(() => !summary.value || loading.value)

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function monthEnd(year: number, month: number): string {
  const date = new Date(Date.UTC(year, month, 0))
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
}

function resolveRange(): { start?: string; end?: string } {
  const option = selectedOption.value
  if (!option || periodKey.value === 'all') return {}
  if (periodKey.value === 'custom') {
    return {
      start: customStart.value || undefined,
      end: customEnd.value || undefined,
    }
  }
  const anchor = option.periodEnd || option.periodStart
  if (!anchor) return {}
  let year = Number(anchor.slice(0, 4))
  const month = Number(anchor.slice(5, 7))
  if (!Number.isFinite(year) || !Number.isFinite(month)) return {}

  if (periodKey.value === 'month' || periodKey.value === 'last-month') {
    const offset = periodKey.value === 'last-month' ? -1 : 0
    const date = new Date(Date.UTC(year, month - 1 + offset, 1))
    year = date.getUTCFullYear()
    const target = date.getUTCMonth() + 1
    return { start: `${year}-${pad(target)}-01`, end: monthEnd(year, target) }
  }
  if (periodKey.value === 'quarter' || periodKey.value === 'last-quarter') {
    const offset = periodKey.value === 'last-quarter' ? -3 : 0
    const date = new Date(Date.UTC(year, month - 1 + offset, 1))
    year = date.getUTCFullYear()
    const targetMonth = date.getUTCMonth() + 1
    const first = Math.floor((targetMonth - 1) / 3) * 3 + 1
    const last = first + 2
    return { start: `${year}-${pad(first)}-01`, end: monthEnd(year, last) }
  }
  return { start: `${year}-01-01`, end: `${year}-12-31` }
}

function formatRange(start?: string, end?: string): string {
  if (!start && !end) return '全部账期'
  if (start && end && start === end) return start
  if (!start) return `截至 ${end}`
  if (!end) return `${start} 起`
  return `${start} 至 ${end}`
}

async function loadOptions() {
  try {
    datasets.value = await api.listReportDatasets()
  } catch {
    datasets.value = []
  }
}

async function load() {
  actionError.value = ''
  if (periodKey.value === 'custom') {
    if (!customStart.value || !customEnd.value) {
      actionError.value = '自定义期间需要同时填写开始日期和结束日期。'
      return
    }
    if (customStart.value > customEnd.value) {
      actionError.value = '开始日期不能晚于结束日期。'
      return
    }
  }

  loading.value = true
  error.value = ''
  try {
    const next = await api.getReportSummary(
      selectedId.value || undefined,
      range.value.start,
      range.value.end,
      providerFilter.value || undefined,
    )
    summary.value = next
    selectedId.value = next.dataset.id
    providerFilter.value = next.providerFilter ?? ''
    if (!datasets.value.some((item) => item.id === next.dataset.id)) {
      await loadOptions()
    }
  } catch (cause) {
    summary.value = null
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

function onDatasetChange() {
  periodKey.value = 'all'
  providerFilter.value = ''
  selectedViewId.value = ''
  const option = selectedOption.value
  customStart.value = option?.periodStart ?? ''
  customEnd.value = option?.periodEnd ?? ''
  void load()
}

function selectProvider(name: string) {
  const value = name.trim()
  if (!value || value === providerFilter.value) return
  providerFilter.value = value
  selectedViewId.value = ''
  void load()
}

function clearProvider() {
  if (!providerFilter.value) return
  providerFilter.value = ''
  void load()
}

function onPeriodChange() {
  actionError.value = ''
  if (periodKey.value !== 'custom') void load()
}

async function exportReport(format: ReportExportFormat) {
  if (!summary.value || exporting.value) return
  exporting.value = format
  actionError.value = ''
  try {
    await api.downloadReportExport({
      datasetId: summary.value.dataset.id,
      startDate: range.value.start,
      endDate: range.value.end,
      provider: providerFilter.value || undefined,
      format,
    })
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    exporting.value = ''
  }
}

async function loadViews() {
  try {
    views.value = await api.listReportViews()
  } catch {
    views.value = []
  }
}

function openSaveView() {
  if (!summary.value) return
  actionError.value = ''
  const scope = providerFilter.value ? `${providerFilter.value} · ` : ''
  viewTitle.value = `${scope}${formatRange(range.value.start, range.value.end)}`
  saveOpen.value = true
}

async function saveView() {
  const title = viewTitle.value.trim()
  if (!title) {
    actionError.value = '请填写视图名称。'
    return
  }
  if (!summary.value || savingView.value) return
  savingView.value = true
  actionError.value = ''
  try {
    const view = await api.createReportView({
      title,
      datasetId: summary.value.dataset.id,
      startDate: range.value.start,
      endDate: range.value.end,
      provider: providerFilter.value || undefined,
    })
    views.value = [view, ...views.value]
    selectedViewId.value = view.id
    saveOpen.value = false
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    savingView.value = false
  }
}

function onViewChange() {
  const view = views.value.find((item) => item.id === selectedViewId.value)
  if (view) applyView(view)
}

function applyView(view: ReportView) {
  selectedViewId.value = view.id
  actionError.value = ''
  selectedId.value = view.datasetId
  providerFilter.value = view.provider ?? ''
  const start = view.periodStart ?? ''
  const end = view.periodEnd ?? ''
  if (start && end) {
    periodKey.value = 'custom'
    customStart.value = start
    customEnd.value = end
  } else {
    periodKey.value = 'all'
  }
  void load()
}

async function removeSelectedView() {
  const view = views.value.find((item) => item.id === selectedViewId.value)
  if (!view) return
  if (!window.confirm(`确定删除报表视图「${view.title}」？`)) return
  actionError.value = ''
  try {
    await api.deleteReportView(view.id)
    views.value = views.value.filter((item) => item.id !== view.id)
    selectedViewId.value = ''
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

onMounted(async () => {
  await loadOptions()
  const option = selectedOption.value ?? datasets.value[0]
  if (option) {
    selectedId.value = option.id
    customStart.value = option.periodStart
    customEnd.value = option.periodEnd
  }
  await Promise.all([load(), loadViews()])
})
</script>

<template>
  <div class="view-stack">
    <div class="view-toolbar">
      <div class="toolbar-main">
        <label v-if="datasets.length" class="toolbar-select">
          <span>账单数据集</span>
          <select
            v-model="selectedId"
            class="select-input"
            :disabled="loading"
            @change="onDatasetChange"
          >
            <option v-for="item in datasets" :key="item.id" :value="item.id">
              {{ item.name }} · {{ item.periodStart }} 至 {{ item.periodEnd }} ·
              {{ item.rowCount.toLocaleString('zh-CN') }} 行
            </option>
          </select>
        </label>
        <label class="toolbar-select">
          <span>统计期间</span>
          <select
            v-model="periodKey"
            class="select-input select-period"
            :disabled="loading || !datasets.length"
            @change="onPeriodChange"
          >
            <option v-for="item in PERIODS" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
        </label>
        <div v-if="periodKey === 'custom'" class="period-custom">
          <input v-model="customStart" class="input" type="date" :disabled="loading" />
          <span>至</span>
          <input v-model="customEnd" class="input" type="date" :disabled="loading" />
          <button class="btn btn-ghost btn-sm" type="button" :disabled="loading" @click="load">
            应用
          </button>
        </div>
        <label v-if="views.length" class="toolbar-select">
          <span>报表视图</span>
          <select
            v-model="selectedViewId"
            class="select-input select-view"
            :disabled="loading"
            @change="onViewChange"
          >
            <option value="">当前筛选</option>
            <option v-for="view in views" :key="view.id" :value="view.id">
              {{ view.title }}
            </option>
          </select>
        </label>
        <button
          class="btn btn-ghost btn-sm"
          type="button"
          :disabled="!summary || loading"
          @click="openSaveView"
        >
          保存为视图
        </button>
        <button
          v-if="selectedViewId"
          class="btn btn-ghost btn-sm"
          type="button"
          :disabled="loading"
          @click="removeSelectedView"
        >
          删除视图
        </button>
        <button
          v-if="providerFilter"
          class="chip active provider-chip"
          type="button"
          :disabled="loading"
          :title="`清除供应商筛选：${providerFilter}`"
          @click="clearProvider"
        >
          供应商：{{ providerFilter }} <span aria-hidden="true">×</span>
        </button>
        <p class="view-note">{{ datasetLabel }}</p>
      </div>
      <div class="toolbar-actions">
        <span class="tag">{{ USING_MOCK ? 'Mock 数据' : '数据快照' }}</span>
        <button class="btn btn-ghost btn-sm" type="button" :disabled="loading" @click="load">
          刷新
        </button>
        <button
          v-if="USING_MOCK"
          class="btn btn-ghost btn-sm"
          type="button"
          :disabled="!summary || Boolean(exporting)"
          @click="exportReport('xlsx')"
        >
          {{ exporting ? '导出中…' : '导出 CSV（演示）' }}
        </button>
        <template v-else>
          <button
            class="btn btn-ghost btn-sm"
            type="button"
            :disabled="!summary || Boolean(exporting)"
            @click="exportReport('xlsx')"
          >
            {{ exporting === 'xlsx' ? '导出中…' : '导出 Excel' }}
          </button>
          <button
            class="btn btn-ghost btn-sm"
            type="button"
            :disabled="!summary || Boolean(exporting)"
            @click="exportReport('pdf')"
          >
            {{ exporting === 'pdf' ? '导出中…' : '导出 PDF' }}
          </button>
        </template>
        <button
          class="btn btn-primary btn-sm"
          type="button"
          :disabled="shareDisabled"
          @click="shareOpen = true"
        >
          分享
        </button>
      </div>
    </div>

    <p v-if="actionError" class="form-error">{{ actionError }}</p>

    <div v-if="loading" class="card">
      <div class="empty-state">
        <span class="spinner"></span>
        <p class="empty-title">正在汇总账单与合同数据…</p>
      </div>
    </div>

    <div v-else-if="error" class="card">
      <div class="empty-state">
        <p class="empty-title">暂时无法生成报表</p>
        <p class="empty-desc">{{ error }}</p>
        <div class="toolbar-actions">
          <button class="btn btn-ghost btn-sm" type="button" @click="load">重试</button>
          <RouterLink to="/ingest" class="btn btn-primary btn-sm">上传账单数据</RouterLink>
        </div>
      </div>
    </div>

    <ReportBody
      v-else-if="summary"
      :summary="summary"
      @select-provider="selectProvider"
      @clear-provider="clearProvider"
    />

    <ReportShareDialog
      :open="shareOpen"
      :dataset-id="summary?.dataset.id ?? ''"
      :dataset-name="summary?.dataset.name ?? ''"
      :start-date="range.start"
      :end-date="range.end"
      :provider="providerFilter"
      :range-label="periodLabel"
      @close="shareOpen = false"
    />

    <Teleport to="body">
      <div v-if="saveOpen" class="modal-backdrop" @click.self="saveOpen = false">
        <div class="modal save-view-modal" role="dialog" aria-modal="true">
          <div class="modal-head">
            <h2>保存报表视图</h2>
            <button class="modal-close" type="button" aria-label="关闭" @click="saveOpen = false">
              ×
            </button>
          </div>
          <div class="modal-body">
            <p class="modal-context">
              {{ summary?.dataset.name }} · {{ periodLabel }}
              <template v-if="providerFilter"> · 供应商 {{ providerFilter }}</template>
            </p>
            <label class="field">
              <span>视图名称</span>
              <input
                v-model="viewTitle"
                class="input"
                maxlength="80"
                placeholder="例如：9 月 Anthropic 成本"
                @keyup.enter="saveView"
              />
            </label>
            <p class="field-hint">
              保存后可在报表页直接切换回这套数据集、期间与供应商筛选。
            </p>
            <div class="modal-actions">
              <button class="btn btn-ghost" type="button" @click="saveOpen = false">取消</button>
              <button
                class="btn btn-primary"
                type="button"
                :disabled="savingView"
                @click="saveView"
              >
                {{ savingView ? '保存中…' : '保存视图' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
