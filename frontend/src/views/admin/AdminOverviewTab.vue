<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '../../api'
import { actionLabel, formatTime } from '../../api/auditLabels'
import type { AdminOverview } from '../../api/types'

const overview = ref<AdminOverview | null>(null)
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    overview.value = await api.getAdminOverview()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="view-stack">
    <div class="view-toolbar">
      <p class="view-note">最近 24 小时的关键操作与当前数据资产概况。</p>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="loading" @click="load">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </div>

    <p v-if="error" class="inline-error">{{ error }}</p>

    <div v-if="overview" class="stat-grid">
      <article class="card stat-card">
        <span class="stat-card-label">用户总数</span>
        <strong class="stat-card-value">{{ overview.users }}</strong>
        <span class="stat-card-hint">{{ overview.activeUsers }} 个启用账号</span>
      </article>
      <article class="card stat-card">
        <span class="stat-card-label">管理员</span>
        <strong class="stat-card-value">{{ overview.admins }}</strong>
        <span class="stat-card-hint">启用状态</span>
      </article>
      <article class="card stat-card">
        <span class="stat-card-label">数据集</span>
        <strong class="stat-card-value">{{ overview.datasets }}</strong>
        <span class="stat-card-hint">{{ overview.activeDatasets }} 个已就绪</span>
      </article>
      <article class="card stat-card">
        <span class="stat-card-label">合同文档</span>
        <strong class="stat-card-value">{{ overview.documents }}</strong>
        <span class="stat-card-hint">PDF / Word / TXT</span>
      </article>
      <article class="card stat-card">
        <span class="stat-card-label">24h 操作</span>
        <strong class="stat-card-value">{{ overview.auditEvents24h }}</strong>
        <span class="stat-card-hint">含登录与写操作</span>
      </article>
    </div>

    <div v-else-if="loading" class="card">
      <div class="empty-state">
        <span class="spinner"></span>
        <p class="empty-title">正在加载概览…</p>
      </div>
    </div>

    <section v-if="overview" class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">最近操作</h2>
          <p class="card-sub">最新 {{ overview.recentAudit.length }} 条审计记录</p>
        </div>
      </div>

      <div v-if="overview.recentAudit.length === 0" class="empty-state compact">
        <p class="empty-desc">还没有操作记录。</p>
      </div>
      <ul v-else class="activity-list">
        <li v-for="item in overview.recentAudit" :key="item.id" class="activity-item">
          <span class="activity-dot" :class="item.status"></span>
          <div class="activity-body">
            <p class="activity-title">
              <strong>{{ item.actorUsername || '匿名' }}</strong>
              {{ actionLabel(item.action) }}
            </p>
            <p class="activity-meta">
              {{ formatTime(item.createdAt) }}
              <span v-if="item.ip">· {{ item.ip }}</span>
            </p>
          </div>
          <span class="status-badge" :class="item.status === 'success' ? '' : 'failed'">
            {{ item.status === 'success' ? '成功' : '失败' }}
          </span>
        </li>
      </ul>
    </section>
  </div>
</template>
