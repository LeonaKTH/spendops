import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api } from '../api'
import type { AuthUser } from '../api/types'

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause)
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const ready = ref(false)
  const loading = ref(false)
  const error = ref('')

  const isAuthenticated = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const displayName = computed(() => user.value?.displayName || user.value?.username || '')

  let restorePromise: Promise<void> | null = null

  /** 页面刷新后恢复登录态；多个路由守卫并发调用时只请求一次。 */
  async function restore(force = false): Promise<void> {
    if (ready.value && !force) return
    if (restorePromise) return restorePromise

    restorePromise = (async () => {
      loading.value = true
      try {
        user.value = await api.me()
        error.value = ''
      } catch {
        user.value = null
      } finally {
        ready.value = true
        loading.value = false
        restorePromise = null
      }
    })()
    return restorePromise
  }

  async function login(username: string, password: string): Promise<AuthUser> {
    loading.value = true
    error.value = ''
    try {
      const current = await api.login(username, password)
      user.value = current
      ready.value = true
      return current
    } catch (cause) {
      error.value = messageOf(cause)
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    loading.value = true
    try {
      await api.logout()
    } finally {
      user.value = null
      ready.value = true
      loading.value = false
    }
  }

  function clear() {
    user.value = null
    ready.value = true
    loading.value = false
  }

  function markPasswordChanged() {
    if (user.value) user.value = { ...user.value, mustChangePassword: false }
  }

  return {
    user,
    ready,
    loading,
    error,
    isAuthenticated,
    isAdmin,
    displayName,
    restore,
    login,
    logout,
    clear,
    markPasswordChanged,
  }
})
