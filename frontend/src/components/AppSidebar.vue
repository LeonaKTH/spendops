<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const route = useRoute()
const auth = useAuthStore()

const workspaceItems = [
  {
    to: '/chat',
    label: '智能问数',
    desc: '自然语言分析',
    icon: ['M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H9l-5 4V5.5Z'],
  },
  {
    to: '/datasets',
    label: '数据集',
    desc: '已接入数据',
    icon: [
      'M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3Z',
      'M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6',
      'M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
    ],
  },
  {
    to: '/reports',
    label: 'BI 报表',
    desc: '可视化看板',
    icon: ['M4 20V10', 'M10 20V4', 'M16 20v-7', 'M22 20H2'],
  },
  {
    to: '/purchasing',
    label: '采购管理',
    desc: '供应商与订单',
    icon: ['M6 6h12v12H6z', 'M9 6V4', 'M15 6V4', 'M9 18v-2', 'M15 18v-2'],
  },
  {
    to: '/analytics',
    label: '经营分析',
    desc: '采购指标看板',
    icon: ['M4 20V10', 'M10 20V4', 'M16 20v-7', 'M22 20H2'],
  },
]

const adminItems = [
  {
    to: '/imports',
    label: '数据导入',
    desc: '采购业务批量导入',
    icon: ['M12 3v12', 'm7 8 5-5 5 5', 'M5 21h14'],
  },
  {
    to: '/ingest',
    label: '数据接入',
    desc: '上传采购单据',
    icon: ['M12 16V4', 'm7 9 5-5 5 5', 'M5 20h14'],
  },
  {
    to: '/admin',
    label: '后台管理',
    desc: '用户与日志',
    icon: ['M12 3l7 4v5c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V7l7-4Z', 'm9 12 2 2 4-4'],
  },
]

const items = computed(() => (auth.isAdmin ? [...workspaceItems, ...adminItems] : workspaceItems))
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M4 19V9" />
          <path d="M10 19V5" />
          <path d="M16 19v-6" />
          <path d="M22 19H2" />
        </svg>
      </div>
      <div class="brand-text">
        <div class="brand-name">ProcureBI</div>
        <div class="brand-sub">LLM 采购数据智能体</div>
      </div>
    </div>

    <p class="nav-section">工作台</p>
    <nav class="nav">
      <RouterLink
        v-for="item in items"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ active: route.path === item.to }"
      >
        <span class="nav-icon">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.7"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path v-for="(d, index) in item.icon" :key="index" :d="d" />
          </svg>
        </span>
        <span>
          <span class="nav-label">{{ item.label }}</span>
          <span class="nav-desc">{{ item.desc }}</span>
        </span>
      </RouterLink>
    </nav>

    <div class="sidebar-footer">
      <span class="env-badge">
        <span class="pulse"></span>
        <span>{{ auth.isAdmin ? '管理员工作区' : '只读工作区' }}</span>
      </span>
    </div>
  </aside>
</template>
