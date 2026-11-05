<script setup lang="ts">
import { computed } from 'vue'

import type { ReportSummary } from '../api/types'
import ChartRenderer from './ChartRenderer.vue'
import DataTable from './DataTable.vue'

const props = withDefaults(
  defineProps<{
    summary: ReportSummary
    canNavigate?: boolean
    interactive?: boolean
  }>(),
  { canNavigate: true, interactive: true },
)

const emit = defineEmits<{
  'select-provider': [name: string]
  'clear-provider': []
}>()

const periodTag = computed(() => {
  const { periodStart, periodEnd } = props.summary.dataset
  if (!periodStart && !periodEnd) return '全部账期'
  if (periodStart === periodEnd) return periodStart
  return `${periodStart} ~ ${periodEnd}`
})

const providerFilter = computed(() => props.summary.providerFilter ?? '')

const momLabel = computed(() => {
  const mom = props.summary.mom
  if (!mom || mom.changePct === null) return ''
  const sign = mom.changePct > 0 ? '+' : ''
  return `${sign}${mom.changePct.toFixed(1)}%`
})

function money(value: number): string {
  return `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function providerClick(name: string) {
  if (!props.interactive || providerFilter.value) return
  emit('select-provider', name)
}

function budgetWidth(pct: number): string {
  const value = Math.max(0, Math.min(pct, 100))
  return `${value.toFixed(1)}%`
}
</script>

<template>
  <div class="kpi-grid">
    <div v-for="kpi in summary.kpis" :key="kpi.label" class="kpi">
      <p class="kpi-label">{{ kpi.label }}</p>
      <p class="kpi-value">
        {{ kpi.value }}<small>{{ kpi.unit }}</small>
      </p>
      <p class="kpi-delta" :class="{ warn: kpi.warn }">{{ kpi.delta }}</p>
    </div>
  </div>

  <div v-if="summary.mom || summary.currencyNote" class="report-strip">
    <template v-if="summary.mom">
      <span class="tag" :class="{ 'tag-warn': (summary.mom.changePct ?? 0) > 0 }">
        环比 {{ momLabel || '—' }}
      </span>
      <span>
        上一周期 {{ summary.mom.previousStart }} 至 {{ summary.mom.previousEnd }}：
        {{ money(summary.mom.previousAmount) }}
      </span>
    </template>
    <span v-if="summary.currencyNote" class="muted">{{ summary.currencyNote }}</span>
  </div>

  <div class="report-grid">
    <section class="report-card">
      <div class="report-card-head">
        <div>
          <h3 class="card-title">
            {{ providerFilter ? `${providerFilter} 各模型采购金额` : '供应商采购结构' }}
          </h3>
          <p class="card-sub">{{ summary.providerSummary }}。</p>
        </div>
        <button
          v-if="providerFilter"
          class="btn btn-ghost btn-sm"
          type="button"
          @click="emit('clear-provider')"
        >
          返回供应商视图
        </button>
        <span v-else class="tag">{{ periodTag }}</span>
      </div>
      <ChartRenderer
        :spec="summary.providerChart"
        :clickable="interactive && !providerFilter"
        @item-click="providerClick"
      />
      <p v-if="interactive && !providerFilter" class="field-hint">
        点击柱子可下钻查看该供应商的模型与应用分布。
      </p>
    </section>

    <section class="report-card">
      <div class="report-card-head">
        <div>
          <h3 class="card-title">成本按应用分布</h3>
          <p class="card-sub">{{ summary.appSummary }}。</p>
        </div>
        <span class="tag">占比</span>
      </div>
      <ChartRenderer v-if="summary.appChart" :spec="summary.appChart" />
      <div v-else class="empty-state compact">
        <p class="empty-desc">账单中缺少应用 / 业务线字段。</p>
      </div>
    </section>
  </div>

  <div class="report-grid">
    <section class="report-card">
      <div class="report-card-head">
        <div>
          <h3 class="card-title">月度成本趋势</h3>
          <p class="card-sub">{{ summary.monthlySummary }}。</p>
        </div>
        <span class="tag">趋势</span>
      </div>
      <ChartRenderer v-if="summary.monthlyChart" :spec="summary.monthlyChart" />
      <div v-else class="empty-state compact">
        <p class="empty-desc">账单中缺少可识别的账期字段。</p>
      </div>
    </section>

    <section class="report-card">
      <div class="report-card-head">
        <div>
          <h3 class="card-title">自动洞察</h3>
          <p class="card-sub">
            基于 {{ summary.modelCount }} 个模型与 {{ summary.appCount }} 个应用的成本结构生成。
          </p>
        </div>
      </div>
      <div class="report-list">
        <div v-for="item in summary.insights" :key="item.title" class="report-item">
          <div>
            <p class="report-item-title">{{ item.title }}</p>
            <p class="report-item-meta">{{ item.meta }}</p>
          </div>
          <span class="tag">{{ item.tag }}</span>
        </div>
      </div>
    </section>
  </div>

  <section v-if="summary.catalog" class="report-card">
    <div class="report-card-head">
      <div>
        <h3 class="card-title">当前模型采购结构</h3>
        <p class="card-sub">{{ summary.catalog.summary }}</p>
      </div>
      <span class="tag">在售 {{ summary.catalog.totalModels }}</span>
    </div>
    <DataTable :result="summary.catalog.table" :max-rows="12" max-height="360px" />
    <p class="card-sub catalog-note">
      价格取自模型清单与价目表的最新有效档位，单位为美元 / 百万 token，可直接用于跨供应商比价。
    </p>
  </section>

  <section v-if="summary.budget" class="report-card">
    <div class="report-card-head">
      <div>
        <h3 class="card-title">年度预算执行</h3>
        <p class="card-sub">{{ summary.budget.summary }}</p>
      </div>
      <span class="tag" :class="{ 'tag-warn': summary.budget.usagePct >= 90 }">
        已用 {{ summary.budget.usagePct.toFixed(1) }}%
      </span>
    </div>
    <div class="budget-bar" role="img" :aria-label="`预算使用率 ${summary.budget.usagePct.toFixed(1)}%`">
      <span
        class="budget-bar-fill"
        :class="{ warn: summary.budget.usagePct >= 90 }"
        :style="{ width: budgetWidth(summary.budget.usagePct) }"
      ></span>
    </div>
    <p class="card-sub budget-total">
      年度预算 {{ money(summary.budget.annualTotal) }} · 所选期间已用
      {{ money(summary.budget.usedTotal) }}
    </p>
    <DataTable :result="summary.budget.table" :max-rows="12" max-height="320px" />
  </section>

  <section class="report-card">
    <div class="report-card-head">
      <div>
        <h3 class="card-title">合同配额使用情况</h3>
        <p class="card-sub">{{ summary.quotaSummary }}。</p>
      </div>
      <span class="tag">合同</span>
    </div>
    <DataTable
      v-if="summary.quotaTable.rows.length"
      :result="summary.quotaTable"
      :max-rows="10"
      max-height="300px"
    />
    <div v-else class="empty-state compact">
      <p class="empty-desc">尚未上传包含「承诺金额 / 已用金额」的合同配额表。</p>
      <RouterLink v-if="canNavigate" to="/ingest" class="btn btn-ghost btn-sm">
        上传配额数据
      </RouterLink>
    </div>
  </section>

  <section v-if="summary.purchasing" class="report-card">
    <div class="report-card-head">
      <div>
        <h3 class="card-title">采购底表与在售价格</h3>
        <p class="card-sub">{{ summary.purchasing.summary }}</p>
      </div>
      <span class="tag">
        套餐 {{ summary.purchasing.planCount }} · 限流 {{ summary.purchasing.rateLimitCount }}
      </span>
    </div>
    <DataTable
      v-if="summary.purchasing.quoteTable.rows.length"
      :result="summary.purchasing.quoteTable"
      :max-rows="10"
      max-height="320px"
    />
    <div v-else class="empty-state compact">
      <p class="empty-desc">尚未上传报价单（quotes）数据。</p>
    </div>
  </section>
</template>
