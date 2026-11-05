<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '../../api'
import type { Supplier } from '../../api/types'

const props = defineProps<{ isAdmin: boolean }>()

function statusLabel(s: string): string {
  return s === 'active' ? '在用' : s === 'inactive' ? '停用中' : '已冻结'
}

const items = ref<Supplier[]>([])
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const formError = ref('')

const form = ref({
  code: '',
  name: '',
  contactName: '',
  contactPhone: '',
  email: '',
  address: '',
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    items.value = await api.listSuppliers()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function submit() {
  formError.value = ''
  if (!form.value.code.trim() || !form.value.name.trim()) {
    formError.value = '供应商编码与名称必填。'
    return
  }
  saving.value = true
  try {
    await api.createSupplier({
      code: form.value.code.trim(),
      name: form.value.name.trim(),
      contactName: form.value.contactName.trim() || null,
      contactPhone: form.value.contactPhone.trim() || null,
      email: form.value.email.trim() || null,
      address: form.value.address.trim() || null,
    })
    form.value = { code: '', name: '', contactName: '', contactPhone: '', email: '', address: '' }
    await load()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '创建失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">供应商列表</h2>
        <p class="card-sub">采购订单与发票的供应商主数据</p>
      </div>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="empty-state">
      <p class="empty-title">正在加载供应商…</p>
    </div>
    <div v-else-if="error" class="empty-state">
      <p class="empty-title">加载失败</p>
      <p class="empty-desc">{{ error }}</p>
    </div>
    <div v-else-if="items.length === 0" class="empty-state">
      <p class="empty-title">还没有供应商</p>
      <p class="empty-desc">先在下方创建第一个供应商。</p>
    </div>
    <div v-else class="table-wrap">
      <table class="purch-table">
        <thead>
          <tr>
            <th>编码</th>
            <th>名称</th>
            <th>联系人</th>
            <th>电话</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in items" :key="s.id">
            <td class="mono">{{ s.code }}</td>
            <td>{{ s.name }}</td>
            <td>{{ s.contactName || '—' }}</td>
            <td>{{ s.contactPhone || '—' }}</td>
            <td><span class="status-badge" :class="s.status">{{ statusLabel(s.status) }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="props.isAdmin" class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">新增供应商</h2>
        <p class="card-sub">编码唯一，重复编码会被后端拒绝</p>
      </div>
    </div>
    <form class="purch-form" @submit.prevent="submit">
      <div class="purch-grid">
        <label class="field">
          <span class="field-label">供应商编码 *</span>
          <input v-model="form.code" class="input" placeholder="如 SUP-001" maxlength="32" />
        </label>
        <label class="field">
          <span class="field-label">供应商名称 *</span>
          <input v-model="form.name" class="input" placeholder="如 某某科技有限公司" maxlength="200" />
        </label>
        <label class="field">
          <span class="field-label">联系人</span>
          <input v-model="form.contactName" class="input" placeholder="可选" maxlength="100" />
        </label>
        <label class="field">
          <span class="field-label">联系电话</span>
          <input v-model="form.contactPhone" class="input" placeholder="可选" maxlength="64" />
        </label>
      </div>
      <p v-if="formError" class="inline-error">{{ formError }}</p>
      <div class="purch-actions">
        <button class="btn btn-primary" type="submit" :disabled="saving">
          {{ saving ? '创建中…' : '创建供应商' }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.purch-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.purch-table th,
.purch-table td {
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border, #e4e6eb);
}
.purch-table th {
  color: var(--muted, #7a7f8c);
  font-weight: 600;
  font-size: 12px;
}
.mono {
  font-family: var(--mono, ui-monospace, monospace);
}
.purch-form {
  padding: 16px 20px 20px;
}
.purch-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}
.field-label {
  display: block;
  font-size: 12px;
  color: var(--muted, #7a7f8c);
  margin-bottom: 6px;
}
.purch-actions {
  margin-top: 16px;
}
.card {
  margin-bottom: 20px;
}
</style>
