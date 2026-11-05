<script setup lang="ts">
import { ref } from 'vue'

import type { Dataset } from '../api/types'
import DatasetPreviewDialog from '../components/DatasetPreviewDialog.vue'
import { useAuthStore } from '../stores/auth'
import { useDatasetStore } from '../stores/datasets'

const store = useDatasetStore()
const auth = useAuthStore()

const busyId = ref('')
const actionError = ref('')
const previewOpen = ref(false)
const previewDataset = ref<Dataset | null>(null)

function openPreview(dataset: Dataset) {
  previewDataset.value = dataset
  previewOpen.value = true
}

function formatRows(rows: number) {
  return rows >= 10000 ? `${(rows / 10000).toFixed(2)} 万` : rows.toLocaleString('zh-CN')
}

async function remove(dataset: Dataset) {
  const ok = window.confirm(`确定删除数据集「${dataset.name}」吗？对应的物理表也会被删除。`)
  if (!ok) return

  busyId.value = dataset.id
  actionError.value = ''
  try {
    await store.remove(dataset.id)
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busyId.value = ''
  }
}
</script>

<template>
  <div class="view-stack">
    <div class="view-toolbar">
      <p class="view-note">
        数据集对应数据库中的物理表。启用后，问数 Agent 会在这些表上生成只读 SQL。
      </p>
      <div class="toolbar-actions">
        <button class="btn btn-ghost btn-sm" type="button" :disabled="store.loading" @click="store.load">
          刷新
        </button>
        <RouterLink v-if="auth.isAdmin" to="/ingest" class="btn btn-primary btn-sm">
          上传新数据
        </RouterLink>
        <span v-else class="readonly-note">只读模式：上传与删除仅管理员可用</span>
      </div>
    </div>

    <p v-if="actionError" class="inline-error">{{ actionError }}</p>

    <div v-if="store.loading" class="card">
      <div class="empty-state">
        <span class="spinner"></span>
        <p class="empty-title">正在加载数据集…</p>
      </div>
    </div>

    <div v-else-if="store.error" class="card">
      <div class="empty-state">
        <p class="empty-title">加载失败</p>
        <p class="empty-desc">{{ store.error }}</p>
        <button class="btn btn-ghost btn-sm" type="button" @click="store.load">重试</button>
      </div>
    </div>

    <div v-else-if="store.datasets.length === 0" class="card">
      <div class="empty-state">
        <div class="empty-icon">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <ellipse cx="12" cy="6" rx="8" ry="3" />
            <path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
            <path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
          </svg>
        </div>
        <p class="empty-title">还没有数据集</p>
        <p class="empty-desc">上传一份采购账单 Excel，几秒钟后就能开始自然语言问数。</p>
        <RouterLink v-if="auth.isAdmin" to="/ingest" class="btn btn-primary btn-sm">
          上传第一份文件
        </RouterLink>
      </div>
    </div>

    <div v-else class="dataset-grid">
      <article
        v-for="dataset in store.datasets"
        :key="dataset.id"
        class="dataset-card"
        :class="{ selected: store.activeIds.includes(dataset.id) }"
      >
        <div class="dataset-top">
          <div>
            <h3 class="dataset-name">{{ dataset.name }}</h3>
            <p class="dataset-file">
              <span class="tag">{{ dataset.sheetName ?? 'Sheet1' }}</span>
              {{ dataset.sourceFile }}
            </p>
          </div>
          <span class="status-badge">{{ dataset.status === 'active' ? '已就绪' : '已归档' }}</span>
        </div>

        <div class="dataset-stats">
          <div class="stat">
            <div class="stat-value">{{ formatRows(dataset.rowCount) }}</div>
            <div class="stat-label">数据行</div>
          </div>
          <div class="stat">
            <div class="stat-value">{{ dataset.columns.length }}</div>
            <div class="stat-label">字段</div>
          </div>
          <div class="stat">
            <div class="stat-value">{{ dataset.createdAt.slice(0, 10) }}</div>
            <div class="stat-label">创建日期</div>
          </div>
        </div>

        <details class="column-details">
          <summary>查看字段结构</summary>
          <ul class="column-list">
            <li v-for="column in dataset.columns" :key="column.name">
              <span>{{ column.name }}</span>
              <em>{{ column.type }}</em>
            </li>
          </ul>
        </details>

        <div class="dataset-actions">
          <button class="btn btn-ghost btn-sm" type="button" @click="openPreview(dataset)">
            查看数据
          </button>
          <button
            class="chip"
            :class="{ active: store.activeIds.includes(dataset.id) }"
            type="button"
            @click="store.toggleActive(dataset.id)"
          >
            {{ store.activeIds.includes(dataset.id) ? '✓ 已启用问数' : '启用问数' }}
          </button>
          <button
            v-if="auth.isAdmin"
            class="btn btn-danger btn-sm"
            type="button"
            :disabled="busyId === dataset.id"
            @click="remove(dataset)"
          >
            {{ busyId === dataset.id ? '删除中…' : '删除' }}
          </button>
        </div>
      </article>
    </div>

    <DatasetPreviewDialog
      :open="previewOpen"
      :dataset="previewDataset"
      @close="previewOpen = false"
    />
  </div>
</template>
