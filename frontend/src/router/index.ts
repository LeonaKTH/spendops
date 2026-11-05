import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'

export function safeRedirect(value: unknown): string | null {
  if (typeof value !== 'string') return null
  // 只允许站内绝对路径，避免 //evil.com 这类开放重定向。
  if (!value.startsWith('/') || value.startsWith('//')) return null
  return value
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    {
      path: '/login',
      component: () => import('../views/LoginView.vue'),
      meta: { title: '登录', public: true },
    },
    {
      path: '/share/:token',
      component: () => import('../views/SharedReportView.vue'),
      meta: { title: '分享报表', public: true, allowAuthenticated: true },
    },
    {
      path: '/chat',
      component: () => import('../views/ChatView.vue'),
      meta: { title: '智能问数' },
    },
    {
      path: '/datasets',
      component: () => import('../views/DatasetsView.vue'),
      meta: { title: '数据集' },
    },
    {
      path: '/ingest',
      component: () => import('../views/DataIngestView.vue'),
      meta: { title: '数据接入', requiresAdmin: true },
    },
    {
      path: '/reports',
      component: () => import('../views/ReportsView.vue'),
      meta: { title: 'BI 报表' },
    },
    {
      path: '/purchasing',
      component: () => import('../views/PurchasingView.vue'),
      meta: { title: '采购管理' },
    },
    {
      path: '/analytics',
      component: () => import('../views/AnalyticsView.vue'),
      meta: { title: '经营分析' },
    },
    {
      path: '/imports',
      component: () => import('../views/ImportView.vue'),
      meta: { title: '数据导入', requiresAdmin: true },
    },
    {
      path: '/admin',
      component: () => import('../views/AdminView.vue'),
      meta: { title: '后台管理', requiresAdmin: true },
    },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.restore()

  if (to.meta.public) {
    if (auth.isAuthenticated && !to.meta.allowAuthenticated) {
      return safeRedirect(to.query.redirect) ?? '/chat'
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return {
      path: '/login',
      query: to.fullPath === '/' ? {} : { redirect: to.fullPath },
    }
  }

  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return '/chat'
  }

  return true
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · ProcureBI` : 'ProcureBI'
})

export default router
