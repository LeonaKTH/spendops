<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { USING_MOCK } from '../api'
import PasswordInput from '../components/PasswordInput.vue'
import { safeRedirect } from '../router'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const error = ref('')

async function submit() {
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码。'
    return
  }

  try {
    await auth.login(username.value, password.value)
    await router.replace(safeRedirect(route.query.redirect) ?? '/chat')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-shell">
      <section class="login-brand">
        <div class="brand-mark login-mark">
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
        <p class="eyebrow login-eyebrow">LLM PROCUREMENT INTELLIGENCE</p>
        <h1>把采购账单变成<br />可以对话的 BI</h1>
        <p class="login-lead">
          上传多供应商账单与合同，用自然语言查询成本、用量与配额，自动生成 SQL、图表和风险洞察。
        </p>
        <ul class="login-points">
          <li>多供应商账单自动建表，不锁定字段结构</li>
          <li>LangGraph 问数链路，SQL 只读校验与重试</li>
          <li>合同条款检索与配额风险提示</li>
        </ul>
      </section>

      <section class="login-panel">
        <div class="login-panel-head">
          <h2>登录</h2>
          <p>使用管理员分配的账号进入工作台</p>
        </div>

        <form class="login-form" @submit.prevent="submit">
          <label class="field">
            <span>用户名</span>
            <input
              v-model="username"
              class="input"
              type="text"
              autocomplete="username"
              placeholder="例如 admin"
            />
          </label>
          <label class="field">
            <span>密码</span>
            <PasswordInput
              v-model="password"
              autocomplete="current-password"
              placeholder="请输入密码"
            />
          </label>

          <p v-if="error || auth.error" class="inline-error">{{ error || auth.error }}</p>

          <button class="btn btn-primary login-submit" type="submit" :disabled="auth.loading">
            {{ auth.loading ? '登录中…' : '登录' }}
          </button>
        </form>

        <div v-if="USING_MOCK" class="login-demo">
          <span class="tag">Mock 演示</span>
          <p>管理员：admin / admin123456</p>
          <p>普通用户：viewer / viewer123456</p>
        </div>
        <p v-else class="login-foot">账号由管理员在「后台管理 → 用户管理」中创建。</p>
      </section>
    </div>
  </div>
</template>
