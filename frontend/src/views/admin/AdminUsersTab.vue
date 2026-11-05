<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '../../api'
import { formatTime } from '../../api/auditLabels'
import type { AuthUser, Role } from '../../api/types'
import PasswordInput from '../../components/PasswordInput.vue'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()

const users = ref<AuthUser[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const error = ref('')
const actionError = ref('')

const keyword = ref('')
const roleFilter = ref<'' | Role>('')
const statusFilter = ref<'' | 'active' | 'inactive'>('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

type DialogMode = 'create' | 'edit' | 'reset' | null
const dialog = ref<DialogMode>(null)
const selected = ref<AuthUser | null>(null)
const form = ref({
  username: '',
  displayName: '',
  password: '',
  role: 'viewer' as Role,
  isActive: true,
})
const newPassword = ref('')
const dialogError = ref('')
const saving = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await api.listUsers({
      page: page.value,
      pageSize,
      q: keyword.value.trim() || undefined,
      role: roleFilter.value || undefined,
      isActive:
        statusFilter.value === '' ? undefined : statusFilter.value === 'active',
    })
    users.value = result.items
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
  keyword.value = ''
  roleFilter.value = ''
  statusFilter.value = ''
  page.value = 1
  void load()
}

function goPage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return
  page.value = next
  void load()
}

function openCreate() {
  selected.value = null
  form.value = {
    username: '',
    displayName: '',
    password: '',
    role: 'viewer',
    isActive: true,
  }
  dialogError.value = ''
  dialog.value = 'create'
}

function openEdit(user: AuthUser) {
  selected.value = user
  form.value = {
    username: user.username,
    displayName: user.displayName,
    password: '',
    role: user.role,
    isActive: user.isActive,
  }
  dialogError.value = ''
  dialog.value = 'edit'
}

function openReset(user: AuthUser) {
  selected.value = user
  newPassword.value = ''
  dialogError.value = ''
  dialog.value = 'reset'
}

function closeDialog() {
  if (saving.value) return
  dialog.value = null
  selected.value = null
}

/** 与后端 validate_password 保持一致，提前给出中文提示。 */
function passwordIssue(value: string): string {
  if (value.length < 8) return '密码至少 8 个字符。'
  if (new TextEncoder().encode(value).length > 72) {
    return '密码最多 72 字节（中文约 24 个字）。'
  }
  return ''
}

async function submitDialog() {
  if (!dialog.value) return
  dialogError.value = ''

  if (dialog.value === 'create') {
    const username = form.value.username.trim()
    if (!/^[a-z0-9_.-]{3,32}$/.test(username)) {
      dialogError.value = '用户名需为 3-32 位小写字母、数字、下划线、点或短横线。'
      return
    }
    const issue = passwordIssue(form.value.password)
    if (issue) {
      dialogError.value = issue
      return
    }
  }

  if (dialog.value === 'reset') {
    const issue = passwordIssue(newPassword.value)
    if (issue) {
      dialogError.value = issue
      return
    }
  }

  saving.value = true

  try {
    if (dialog.value === 'create') {
      await api.createUser({
        username: form.value.username.trim(),
        password: form.value.password,
        role: form.value.role,
        displayName: form.value.displayName.trim(),
      })
    } else if (dialog.value === 'edit' && selected.value) {
      const updated = await api.updateUser(selected.value.id, {
        displayName: form.value.displayName.trim(),
        role: form.value.role,
        isActive: form.value.isActive,
      })
      if (updated.id === auth.user?.id) await auth.restore(true)
    } else if (dialog.value === 'reset' && selected.value) {
      await api.resetUserPassword(selected.value.id, newPassword.value)
    }

    dialog.value = null
    selected.value = null
    await load()
  } catch (cause) {
    dialogError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

async function toggleActive(user: AuthUser) {
  actionError.value = ''
  try {
    await api.updateUser(user.id, { isActive: !user.isActive })
    await load()
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function remove(user: AuthUser) {
  const ok = window.confirm(`确定删除用户「${user.username}」吗？删除后无法恢复。`)
  if (!ok) return

  actionError.value = ''
  try {
    await api.deleteUser(user.id)
    await load()
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

onMounted(load)
</script>

<template>
  <div class="view-stack">
    <div class="view-toolbar">
      <p class="view-note">账号不开放注册，由管理员创建；停用或改角色会立即生效。</p>
      <button class="btn btn-primary btn-sm" type="button" @click="openCreate">新建用户</button>
    </div>

    <div class="filter-bar">
      <input
        v-model="keyword"
        class="input"
        type="search"
        placeholder="搜索用户名或显示名"
        @keyup.enter="search"
      />
      <select v-model="roleFilter" class="input select">
        <option value="">全部角色</option>
        <option value="admin">管理员</option>
        <option value="viewer">普通用户</option>
      </select>
      <select v-model="statusFilter" class="input select">
        <option value="">全部状态</option>
        <option value="active">启用</option>
        <option value="inactive">已停用</option>
      </select>
      <button class="btn btn-ghost btn-sm" type="button" @click="search">查询</button>
      <button class="btn btn-ghost btn-sm" type="button" @click="resetFilters">重置</button>
    </div>

    <p v-if="actionError" class="inline-error">{{ actionError }}</p>

    <div class="card">
      <div v-if="loading" class="empty-state">
        <span class="spinner"></span>
        <p class="empty-title">正在加载用户…</p>
      </div>
      <div v-else-if="error" class="empty-state">
        <p class="empty-title">加载失败</p>
        <p class="empty-desc">{{ error }}</p>
        <button class="btn btn-ghost btn-sm" type="button" @click="load">重试</button>
      </div>
      <div v-else-if="users.length === 0" class="empty-state">
        <p class="empty-title">没有匹配的用户</p>
        <p class="empty-desc">调整筛选条件，或新建一个账号。</p>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用户</th>
              <th>角色</th>
              <th>状态</th>
              <th>最后登录</th>
              <th>创建时间</th>
              <th class="align-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>
                <div class="table-user">
                  <span class="user-avatar small">{{ user.displayName.slice(0, 1) }}</span>
                  <span>
                    <strong>{{ user.displayName }}</strong>
                    <span class="table-sub">@{{ user.username }}</span>
                  </span>
                </div>
              </td>
              <td>
                <span class="role-badge" :class="user.role === 'admin' ? 'role-admin' : 'role-viewer'">
                  {{ user.role === 'admin' ? '管理员' : '普通用户' }}
                </span>
              </td>
              <td>
                <span class="status-dot" :class="user.isActive ? 'on' : 'off'">
                  {{ user.isActive ? '启用' : '已停用' }}
                </span>
                <span v-if="user.mustChangePassword" class="tag tag-warn">待改密</span>
              </td>
              <td>{{ formatTime(user.lastLoginAt) }}</td>
              <td>{{ formatTime(user.createdAt) }}</td>
              <td class="align-right">
                <div class="row-actions">
                  <button class="btn btn-ghost btn-sm" type="button" @click="openEdit(user)">
                    编辑
                  </button>
                  <button
                    class="btn btn-ghost btn-sm"
                    type="button"
                    :disabled="user.id === auth.user?.id"
                    @click="openReset(user)"
                  >
                    重置密码
                  </button>
                  <button
                    class="btn btn-ghost btn-sm"
                    type="button"
                    :disabled="user.id === auth.user?.id"
                    @click="toggleActive(user)"
                  >
                    {{ user.isActive ? '停用' : '启用' }}
                  </button>
                  <button
                    class="btn btn-danger btn-sm"
                    type="button"
                    :disabled="user.id === auth.user?.id"
                    @click="remove(user)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!loading && !error && total > pageSize" class="pagination">
        <span>共 {{ total }} 个用户</span>
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

    <Teleport to="body">
      <div v-if="dialog" class="modal-backdrop" @click.self="closeDialog">
        <div class="modal" role="dialog" aria-modal="true">
          <div class="modal-head">
            <h2>
              {{
                dialog === 'create' ? '新建用户' : dialog === 'edit' ? '编辑用户' : '重置密码'
              }}
            </h2>
            <button class="modal-close" type="button" aria-label="关闭" @click="closeDialog">
              ×
            </button>
          </div>

          <form class="modal-body" @submit.prevent="submitDialog">
            <template v-if="dialog === 'create'">
              <label class="field">
                <span>用户名</span>
                <input v-model="form.username" class="input" type="text" autocomplete="off" />
                <small class="field-hint">3-32 位小写字母、数字、下划线、点或短横线。</small>
              </label>
              <label class="field">
                <span>显示名</span>
                <input v-model="form.displayName" class="input" type="text" autocomplete="off" />
              </label>
              <label class="field">
                <span>初始密码</span>
                <PasswordInput
                  v-model="form.password"
                  autocomplete="new-password"
                  placeholder="至少 8 个字符"
                />
                <small class="field-hint">至少 8 个字符；用户首次登录后会看到改密提示。</small>
              </label>
              <label class="field">
                <span>角色</span>
                <select v-model="form.role" class="input select">
                  <option value="viewer">普通用户</option>
                  <option value="admin">管理员</option>
                </select>
              </label>
            </template>

            <template v-else-if="dialog === 'edit' && selected">
              <p class="modal-context">@{{ selected.username }}</p>
              <label class="field">
                <span>显示名</span>
                <input v-model="form.displayName" class="input" type="text" />
              </label>
              <label class="field">
                <span>角色</span>
                <select v-model="form.role" class="input select">
                  <option value="viewer">普通用户</option>
                  <option value="admin">管理员</option>
                </select>
              </label>
              <label class="field inline-check">
                <input v-model="form.isActive" type="checkbox" />
                <span>账号启用</span>
              </label>
            </template>

            <template v-else-if="dialog === 'reset' && selected">
              <p class="modal-context">@{{ selected.username }}</p>
              <label class="field">
                <span>新密码</span>
                <PasswordInput
                  v-model="newPassword"
                  autocomplete="new-password"
                  placeholder="至少 8 个字符"
                />
                <small class="field-hint">
                  重置后该用户已登录的会话立即失效，并需要在下次登录后改密。
                </small>
              </label>
            </template>

            <p v-if="dialogError" class="inline-error">{{ dialogError }}</p>

            <div class="modal-actions">
              <button class="btn btn-ghost" type="button" :disabled="saving" @click="closeDialog">
                取消
              </button>
              <button class="btn btn-primary" type="submit" :disabled="saving">
                {{ saving ? '保存中…' : '保存' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>
  </div>
</template>
