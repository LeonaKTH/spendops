<script setup lang="ts">
import { ref, watch } from 'vue'

import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import PasswordInput from './PasswordInput.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const auth = useAuthStore()

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const error = ref('')
const loading = ref(false)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    error.value = ''
  },
)

async function submit() {
  error.value = ''
  if (!currentPassword.value || !newPassword.value) {
    error.value = '请填写当前密码和新密码。'
    return
  }
  if (newPassword.value.length < 8) {
    error.value = '新密码至少 8 个字符。'
    return
  }
  if (new TextEncoder().encode(newPassword.value).length > 72) {
    error.value = '新密码最多 72 字节（中文约 24 个字）。'
    return
  }
  if (newPassword.value === currentPassword.value) {
    error.value = '新密码不能与当前密码相同。'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的新密码不一致。'
    return
  }

  loading.value = true
  try {
    await api.changePassword(currentPassword.value, newPassword.value)
    auth.markPasswordChanged()
    emit('saved')
    emit('close')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="change-password-title">
        <div class="modal-head">
          <h2 id="change-password-title">修改密码</h2>
          <button class="modal-close" type="button" aria-label="关闭" @click="emit('close')">
            ×
          </button>
        </div>

        <form class="modal-body" @submit.prevent="submit">
          <label class="field">
            <span>当前密码</span>
            <PasswordInput v-model="currentPassword" autocomplete="current-password" />
          </label>
          <label class="field">
            <span>新密码</span>
            <PasswordInput
              v-model="newPassword"
              autocomplete="new-password"
              placeholder="至少 8 个字符"
            />
            <small class="field-hint">至少 8 个字符，最多 72 字节。</small>
          </label>
          <label class="field">
            <span>确认新密码</span>
            <PasswordInput v-model="confirmPassword" autocomplete="new-password" />
          </label>

          <p v-if="error" class="inline-error">{{ error }}</p>

          <div class="modal-actions">
            <button class="btn btn-ghost" type="button" @click="emit('close')">取消</button>
            <button class="btn btn-primary" type="submit" :disabled="loading">
              {{ loading ? '保存中…' : '保存' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
</template>
