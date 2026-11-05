<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '../../api'
import type { PurchaseInvoice, PurchaseOrder, Supplier } from '../../api/types'

const props = defineProps<{ isAdmin: boolean }>()

const invoices = ref<PurchaseInvoice[]>([])
const orders = ref<PurchaseOrder[]>([])
const suppliers = ref<Supplier[]>([])
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const formError = ref('')

const selectedOrderId = ref('')
const form = ref({
  invoiceNo: '',
  supplierId: '',
  invoiceDate: new Date().toISOString().slice(0, 10),
  lines: [] as { orderLineId: string | null; itemName: string; quantity: string; unitPrice: string; taxRate: string }[],
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    invoices.value = await api.listInvoices()
    orders.value = (await api.listOrders()).items
    suppliers.value = await api.listSuppliers()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function pickOrder() {
  form.value.lines = []
  form.value.supplierId = ''
  if (!selectedOrderId.value) return
  const order = orders.value.find((o) => o.id === selectedOrderId.value)
  if (!order) return
  form.value.supplierId = order.supplierId
  form.value.lines = order.lines.map((l) => ({
    orderLineId: l.id,
    itemName: l.itemName,
    quantity: l.quantity,
    unitPrice: l.unitPrice,
    taxRate: l.taxRate,
  }))
}

async function submit() {
  formError.value = ''
  if (!form.value.invoiceNo.trim()) return setError('发票号必填。')
  if (!form.value.supplierId) return setError('请选择供应商（选择订单可自动带出）。')
  if (form.value.lines.length === 0) return setError('请至少填写一条发票明细。')
  for (const l of form.value.lines) {
    if (!l.itemName.trim()) return setError('发票明细的物料名称必填。')
    if (Number(l.quantity) < 0) return setError('发票数量不能为负。')
  }
  saving.value = true
  try {
    await api.createInvoice({
      invoiceNo: form.value.invoiceNo.trim(),
      orderId: selectedOrderId.value || null,
      supplierId: form.value.supplierId,
      invoiceDate: form.value.invoiceDate,
      lines: form.value.lines,
    })
    form.value = { invoiceNo: '', supplierId: '', invoiceDate: new Date().toISOString().slice(0, 10), lines: [] }
    selectedOrderId.value = ''
    await load()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '录入发票失败'
  } finally {
    saving.value = false
  }
}

function setError(msg: string) {
  formError.value = msg
}

onMounted(load)
</script>

<template>
  <div class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">采购发票</h2>
        <p class="card-sub">发票可追溯到订单明细，开票数量受订单数量约束</p>
      </div>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="empty-state"><p class="empty-title">正在加载…</p></div>
    <div v-else-if="error" class="empty-state">
      <p class="empty-title">加载失败</p>
      <p class="empty-desc">{{ error }}</p>
    </div>
    <div v-else-if="invoices.length === 0" class="empty-state">
      <p class="empty-title">还没有发票</p>
      <p class="empty-desc">在下方录入第一张采购发票。</p>
    </div>
    <div v-else class="table-wrap">
      <table class="purch-table">
        <thead>
          <tr>
            <th>发票号</th>
            <th>订单号</th>
            <th>供应商</th>
            <th>日期</th>
            <th>金额(元)</th>
            <th>税额(元)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="i in invoices" :key="i.id">
            <td class="mono">{{ i.invoiceNo }}</td>
            <td class="mono">{{ i.orderNo || '—' }}</td>
            <td>{{ i.supplierName }}</td>
            <td>{{ i.invoiceDate }}</td>
            <td>{{ i.totalAmount }}</td>
            <td>{{ i.taxAmount }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="props.isAdmin" class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">录入发票</h2>
        <p class="card-sub">选择订单后自动带出明细与供应商</p>
      </div>
    </div>
    <form class="purch-form" @submit.prevent="submit">
      <div class="purch-grid">
        <label class="field">
          <span class="field-label">发票号 *</span>
          <input v-model="form.invoiceNo" class="input" placeholder="如 INV-2026-001" maxlength="40" />
        </label>
        <label class="field">
          <span class="field-label">关联订单</span>
          <select v-model="selectedOrderId" class="select-input" @change="pickOrder">
            <option value="">不关联订单</option>
            <option v-for="o in orders" :key="o.id" :value="o.id">{{ o.orderNo }} · {{ o.supplierName }}</option>
          </select>
        </label>
        <label class="field">
          <span class="field-label">供应商 *</span>
          <select v-model="form.supplierId" class="select-input">
            <option value="" disabled>请选择供应商</option>
            <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.code }} · {{ s.name }}</option>
          </select>
        </label>
        <label class="field">
          <span class="field-label">发票日期 *</span>
          <input v-model="form.invoiceDate" type="date" class="input" />
        </label>
      </div>

      <div class="line-head">
        <span>发票明细</span>
        <button class="btn btn-ghost btn-sm" type="button" @click="form.lines.push({ orderLineId: null, itemName: '', quantity: '0', unitPrice: '0', taxRate: '0' })">
          添加明细行
        </button>
      </div>
      <div v-for="(l, i) in form.lines" :key="i" class="line-row">
        <input v-model="l.itemName" class="input" placeholder="物料名称" />
        <input v-model="l.quantity" class="input" type="number" min="0" step="0.001" placeholder="数量" />
        <input v-model="l.unitPrice" class="input" type="number" min="0" step="0.0001" placeholder="单价" />
        <input v-model="l.taxRate" class="input" type="number" min="0" max="1" step="0.01" placeholder="税率" />
        <button class="btn btn-ghost btn-sm" type="button" @click="form.lines.splice(i, 1)">删</button>
      </div>

      <p v-if="formError" class="inline-error">{{ formError }}</p>
      <div class="purch-actions">
        <button class="btn btn-primary" type="submit" :disabled="saving">{{ saving ? '提交中…' : '录入发票' }}</button>
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
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}
.field-label {
  display: block;
  font-size: 12px;
  color: var(--muted, #7a7f8c);
  margin-bottom: 6px;
}
.line-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 18px 0 10px;
  font-size: 13px;
  font-weight: 600;
}
.line-row {
  display: grid;
  grid-template-columns: 1.4fr 0.8fr 0.8fr 0.7fr auto;
  gap: 8px;
  margin-bottom: 8px;
}
.purch-actions {
  margin-top: 16px;
}
.card {
  margin-bottom: 20px;
}
</style>
