<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AdminAuditTab from './admin/AdminAuditTab.vue'
import AdminDatasetsTab from './admin/AdminDatasetsTab.vue'
import AdminOverviewTab from './admin/AdminOverviewTab.vue'
import AdminUsersTab from './admin/AdminUsersTab.vue'

const route = useRoute()
const router = useRouter()

const tabs = [
  { key: 'overview', label: '概览' },
  { key: 'users', label: '用户管理' },
  { key: 'datasets', label: '合同文档' },
  { key: 'audit', label: '操作日志' },
]

const active = computed(() => {
  const value = typeof route.query.tab === 'string' ? route.query.tab : 'overview'
  return tabs.some((item) => item.key === value) ? value : 'overview'
})

function select(key: string) {
  void router.replace({ query: { ...route.query, tab: key } })
}
</script>

<template>
  <div class="view-stack">
    <div class="view-toolbar">
      <p class="view-note">
        管理员控制台：管理账号与权限、查看数据资产，并追溯关键写操作。
      </p>
    </div>

    <div class="tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab"
        :class="{ active: active === tab.key }"
        type="button"
        role="tab"
        :aria-selected="active === tab.key"
        @click="select(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <AdminOverviewTab v-if="active === 'overview'" />
    <AdminUsersTab v-else-if="active === 'users'" />
    <AdminDatasetsTab v-else-if="active === 'datasets'" />
    <AdminAuditTab v-else />
  </div>
</template>
