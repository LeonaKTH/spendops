<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '../../api'
import { ACTION_OPTIONS, actionLabel, formatTime } from '../../api/auditLabels'
import type { AuditLogItem } from '../../api/types'

const items = ref<AuditLogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const error = ref('')

const actionFilter = ref('')
const statusFilter = ref<'' | 'success' | 'failure'>('')
const actorFilter = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await api.listAuditLogs({
      page: page.value,
      pageSize,
      action: actionFilter.value || undefined,
      status: statusFilter.value || undefined,
      actor: actorFilter.value.trim() || undefined,
    })
    items.value = result.items
    total.value = result.total
    if (page.value > totalPages.value) {
      page.value = totalPages.value
      await load()
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}

function resetFilters() {
  actionFilter.value = ''
  statusFilter.value = ''
  actorFilter.value = ''
  page.value = 1
  void load()
}

function goPage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return
  page.value = next
  void load()
}

function detailText(detail: Record<string, unknown> | null): string {
  if (!detail || Object.keys(detail).length === 0) return ''
  return JSON.stringify(detail, null, 2)
}

onMounted(load)
</script>

<template>
  <div class="view-stack">
    <div class="view-toolbar">
      <p class="view-note">记录登录、用户管理与数据写操作；不包含密码、令牌或文件内容。</p>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="loading" @click="load">
        刷新
      </button>
    </div>

    <div class="filter-bar">
      <select v-model="actionFilter" class="input select">
        <option value="">全部动作</option>
        <option v-for="option in ACTION_OPTIONS" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
      <select v-model="statusFilter" class="input select">
        <option value="">全部结果</option>
        <option value="success">成功</option>
        <option value="failure">失败</option>
      </select>
      <input
        v-model="actorFilter"
        class="input"
        type="search"
        placeholder="操作人用户名"
        @keyup.enter="search"
      />
      <button class="btn btn-ghost btn-sm" type="button" @click="search">查询</button>
      <button class="btn btn-ghost btn-sm" type="button" @click="resetFilters">重置</button>
    </div>

    <div class="card">
      <div v-if="loading" class="empty-state">
        <span class="spinner"></span>
        <p class="empty-title">正在加载操作日志…</p>
      </div>
      <div v-else-if="error" class="empty-state">
        <p class="empty-title">加载失败</p>
        <p class="empty-desc">{{ error }}</p>
        <button class="btn btn-ghost btn-sm" type="button" @click="load">重试</button>
      </div>
      <div v-else-if="items.length === 0" class="empty-state">
        <p class="empty-title">没有匹配的日志</p>
        <p class="empty-desc">调整筛选条件后再试。</p>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>操作人</th>
              <th>动作</th>
              <th>对象</th>
              <th>结果</th>
              <th>IP</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td class="nowrap">{{ formatTime(item.createdAt) }}</td>
              <td>{{ item.actorUsername || '匿名' }}</td>
              <td>
                <span class="tag">{{ actionLabel(item.action) }}</span>
                <span class="table-sub">{{ item.action }}</span>
              </td>
              <td>
                <template v-if="item.targetType">
                  {{ item.targetType }}
                  <span class="table-sub mono">{{ item.targetId?.slice(0, 8) }}</span>
                </template>
                <span v-else class="muted">—</span>
              </td>
              <td>
                <span class="status-dot" :class="item.status === 'success' ? 'on' : 'off'">
                  {{ item.status === 'success' ? '成功' : '失败' }}
                </span>
              </td>
              <td class="nowrap">{{ item.ip || '—' }}</td>
              <td>
                <details v-if="detailText(item.detail)" class="detail-toggle">
                  <summary>查看</summary>
                  <pre class="detail-pre">{{ detailText(item.detail) }}</pre>
                </details>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!loading && !error && total > pageSize" class="pagination">
        <span>共 {{ total }} 条记录</span>
        <div class="pagination-actions">
          <button class="btn btn-ghost btn-sm" type="button" :disabled="page <= 1" @click="goPage(page - 1)">
            上一页
          </button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button
            class="btn btn-ghost btn-sm"
            type="button"
            :disabled="page >= totalPages"
            @click="goPage(page + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
