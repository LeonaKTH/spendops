<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { USING_MOCK } from './api'
import { UNAUTHORIZED_EVENT } from './api/events'
import AppSidebar from './components/AppSidebar.vue'
import ChangePasswordDialog from './components/ChangePasswordDialog.vue'
import { useAuthStore } from './stores/auth'
import { useDatasetStore } from './stores/datasets'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const store = useDatasetStore()

const passwordOpen = ref(false)
const passwordSaved = ref(false)
let passwordSavedTimer: ReturnType<typeof setTimeout> | undefined

function flashPasswordSaved() {
  passwordSaved.value = true
  if (passwordSavedTimer) clearTimeout(passwordSavedTimer)
  passwordSavedTimer = setTimeout(() => {
    passwordSaved.value = false
  }, 6000)
}

const isPublic = computed(() => route.meta.public === true)
const title = computed(() => route.meta.title ?? 'ProcureBI')
const initial = computed(() => auth.displayName.slice(0, 1).toUpperCase() || 'U')

function loadWorkspace() {
  void store.load()
}

onMounted(() => {
  if (auth.isAuthenticated) loadWorkspace()
})

watch(
  () => auth.isAuthenticated,
  (authenticated) => {
    if (authenticated) {
      loadWorkspace()
    } else {
      passwordSaved.value = false
      if (passwordSavedTimer) clearTimeout(passwordSavedTimer)
    }
  },
)

async function handleUnauthorized() {
  auth.clear()
  if (!route.meta.public) {
    await router.replace({ path: '/login', query: { redirect: route.fullPath } })
  }
}

async function logout() {
  await auth.logout()
  await router.replace('/login')
}

onMounted(() => window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized))
onBeforeUnmount(() => {
  window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized)
  if (passwordSavedTimer) clearTimeout(passwordSavedTimer)
})
</script>

<template>
  <RouterView v-if="isPublic" />

  <div v-else class="app-shell">
    <AppSidebar />
    <div class="app-main">
      <header class="topbar">
        <div>
          <p class="eyebrow">LLM PROCUREMENT INTELLIGENCE</p>
          <h1>{{ title }}</h1>
        </div>
        <div class="topbar-side">
          <span v-if="USING_MOCK" class="pill pill-mock">Mock 数据</span>
          <span class="dataset-count">
            <span class="dot"></span>
            {{ store.datasets.length }} 个数据集
          </span>

          <div class="user-chip">
            <span class="user-avatar">{{ initial }}</span>
            <span class="user-meta">
              <span class="user-name">{{ auth.displayName }}</span>
              <span class="role-badge" :class="auth.isAdmin ? 'role-admin' : 'role-viewer'">
                {{ auth.isAdmin ? '管理员' : '普通用户' }}
              </span>
            </span>
            <button class="topbar-link" type="button" @click="passwordOpen = true">
              修改密码
            </button>
            <button class="topbar-link danger" type="button" :disabled="auth.loading" @click="logout">
              退出
            </button>
          </div>
        </div>
      </header>

      <div v-if="auth.user?.mustChangePassword" class="password-banner">
        <span>当前使用的是初始密码或管理员重置的密码，建议立即修改。</span>
        <button class="btn btn-ghost btn-sm" type="button" @click="passwordOpen = true">
          去修改
        </button>
      </div>

      <p v-if="passwordSaved" class="inline-success app-flash">密码已更新。</p>

      <main class="page">
        <RouterView />
      </main>
    </div>

    <ChangePasswordDialog
      :open="passwordOpen"
      @close="passwordOpen = false"
      @saved="flashPasswordSaved"
    />
  </div>
</template>
