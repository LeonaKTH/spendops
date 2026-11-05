<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { api, USING_MOCK } from '../api'
import type { ReportExportFormat, ReportSummary } from '../api/types'
import ReportBody from '../components/ReportBody.vue'

const route = useRoute()
const token = computed(() => String(route.params.token ?? ''))
const summary = ref<ReportSummary | null>(null)
const loading = ref(true)
const error = ref('')
const exporting = ref<ReportExportFormat | ''>('')

const generatedLabel = computed(() => {
  if (!summary.value) return ''
  const value = new Date(summary.value.generatedAt)
  if (Number.isNaN(value.getTime())) return summary.value.generatedAt
  return value.toLocaleString('zh-CN', { hour12: false })
})

const periodLabel = computed(() => {
  if (!summary.value) return ''
  const { periodStart, periodEnd } = summary.value.dataset
  if (!periodStart && !periodEnd) return '全部账期'
  if (periodStart === periodEnd) return periodStart
  return `${periodStart} 至 ${periodEnd}`
})

async function load() {
  if (!token.value) {
    error.value = '分享链接不完整。'
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    summary.value = await api.getSharedReport(token.value)
  } catch (cause) {
    summary.value = null
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function exportReport(format: ReportExportFormat) {
  if (exporting.value) return
  exporting.value = format
  try {
    await api.downloadSharedReportExport(token.value, format)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    exporting.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="share-page">
    <header class="share-topbar">
      <div class="share-brand">
        <span class="brand-mark">P</span>
        <div>
          <p class="share-brand-name">ProcureBI</p>
          <p class="share-brand-sub">LLM PROCUREMENT INTELLIGENCE</p>
        </div>
        <span class="share-badge">只读分享</span>
      </div>
      <div class="toolbar-actions">
        <span v-if="USING_MOCK" class="pill pill-mock">Mock 数据</span>
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
        <RouterLink to="/login" class="btn btn-primary btn-sm">进入工作台</RouterLink>
      </div>
    </header>

    <main class="share-main">
      <div v-if="loading" class="card">
        <div class="empty-state">
          <span class="spinner"></span>
          <p class="empty-title">正在加载分享报表…</p>
        </div>
      </div>

      <div v-else-if="error" class="card">
        <div class="empty-state">
          <p class="empty-title">无法打开这份报表</p>
          <p class="empty-desc">{{ error }}</p>
          <p class="empty-desc">链接可能已过期或被创建者撤销，请联系分享人重新生成。</p>
        </div>
      </div>

      <template v-else-if="summary">
        <div class="share-report-head">
          <div>
            <p class="eyebrow">SHARED REPORT</p>
            <h1 class="share-title">{{ summary.dataset.name }} 采购分析</h1>
            <p class="view-note">
              {{ periodLabel }} · {{ summary.dataset.rowCount.toLocaleString('zh-CN') }} 行 ·
              生成于 {{ generatedLabel }}
            </p>
          </div>
          <span class="tag">{{ periodLabel }}</span>
        </div>

        <ReportBody :summary="summary" :can-navigate="false" :interactive="false" />
        <p class="share-footer">
          本页由 ProcureBI 生成，仅包含报表数据，不提供原始明细导出以外的操作权限。
        </p>
      </template>
    </main>
  </div>
</template>
