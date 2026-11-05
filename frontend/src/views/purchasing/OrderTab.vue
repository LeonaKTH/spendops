<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '../../api'
import type { PurchaseOrder, Supplier } from '../../api/types'

const props = defineProps<{ isAdmin: boolean }>()

const items = ref<PurchaseOrder[]>([])
const suppliers = ref<Supplier[]>([])
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const formError = ref('')
const detail = ref<PurchaseOrder | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const cancelling = ref(false)

const form = ref({
  orderNo: '',
  supplierId: '',
  orderDate: new Date().toISOString().slice(0, 10),
  lines: [{ itemCode: '', itemName: '', quantity: '1', unit: '件', unitPrice: '0', taxRate: '0' }],
})

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    draft: '草稿',
    submitted: '已提交',
    partially_received: '部分收货',
    received: '已收货',
    cancelled: '已取消',
  }
  return map[s] ?? s
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await api.listOrders()
    items.value = result.items
    suppliers.value = await api.listSuppliers()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function addLine() {
  form.value.lines.push({ itemCode: '', itemName: '', quantity: '1', unit: '件', unitPrice: '0', taxRate: '0' })
}

function removeLine(index: number) {
  if (form.value.lines.length > 1) form.value.lines.splice(index, 1)
}

async function submit() {
  formError.value = ''
  if (!form.value.orderNo.trim()) return setError('订单号必填。')
  if (!form.value.supplierId) return setError('请选择供应商。')
  for (const line of form.value.lines) {
    if (!line.itemCode.trim() || !line.itemName.trim()) return setError('明细的物料编码与名称必填。')
    if (Number(line.quantity) <= 0) return setError('明细数量必须大于 0。')
    if (Number(line.unitPrice) < 0) return setError('明细单价不能为负。')
  }
  saving.value = true
  try {
    const order = await api.createOrder({
      orderNo: form.value.orderNo.trim(),
      supplierId: form.value.supplierId,
      orderDate: form.value.orderDate,
      lines: form.value.lines,
    })
    form.value = {
      orderNo: '',
      supplierId: '',
      orderDate: new Date().toISOString().slice(0, 10),
      lines: [{ itemCode: '', itemName: '', quantity: '1', unit: '件', unitPrice: '0', taxRate: '0' }],
    }
    await load()
    await openDetail(order.id)
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '创建失败'
  } finally {
    saving.value = false
  }
}

function setError(msg: string) {
  formError.value = msg
}

async function openDetail(id: string) {
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  try {
    detail.value = await api.getOrder(id)
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : '加载详情失败'
  } finally {
    detailLoading.value = false
  }
}

async function cancelOrder() {
  if (!detail.value) return
  cancelling.value = true
  try {
    detail.value = await api.cancelOrder(detail.value.id)
    await load()
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : '取消失败'
  } finally {
    cancelling.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">采购订单</h2>
        <p class="card-sub">一个供应商对应多个订单，一个订单含多条明细</p>
      </div>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="empty-state"><p class="empty-title">正在加载订单…</p></div>
    <div v-else-if="error" class="empty-state">
      <p class="empty-title">加载失败</p>
      <p class="empty-desc">{{ error }}</p>
    </div>
    <div v-else-if="items.length === 0" class="empty-state">
      <p class="empty-title">还没有采购订单</p>
      <p class="empty-desc">先在下方创建第一张订单。</p>
    </div>
    <div v-else class="table-wrap">
      <table class="purch-table">
        <thead>
          <tr>
            <th>订单号</th>
            <th>供应商</th>
            <th>日期</th>
            <th>金额(元)</th>
            <th>状态</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in items" :key="o.id">
            <td class="mono">{{ o.orderNo }}</td>
            <td>{{ o.supplierName || o.supplierId }}</td>
            <td>{{ o.orderDate }}</td>
            <td>{{ o.totalAmount }}</td>
            <td><span class="status-badge" :class="o.status">{{ statusLabel(o.status) }}</span></td>
            <td><button class="btn btn-ghost btn-sm" type="button" @click="openDetail(o.id)">详情</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="props.isAdmin" class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">创建采购订单</h2>
        <p class="card-sub">金额由后端按「数量 × 单价」确定性计算</p>
      </div>
    </div>
    <form class="purch-form" @submit.prevent="submit">
      <div class="purch-grid">
        <label class="field">
          <span class="field-label">订单号 *</span>
          <input v-model="form.orderNo" class="input" placeholder="如 PO-2026-001" maxlength="40" />
        </label>
        <label class="field">
          <span class="field-label">供应商 *</span>
          <select v-model="form.supplierId" class="select-input">
            <option value="" disabled>请选择供应商</option>
            <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.code }} · {{ s.name }}</option>
          </select>
        </label>
        <label class="field">
          <span class="field-label">订单日期 *</span>
          <input v-model="form.orderDate" type="date" class="input" />
        </label>
      </div>

      <div class="line-head">
        <span>订单明细</span>
        <button class="btn btn-ghost btn-sm" type="button" @click="addLine">添加明细行</button>
      </div>
      <div v-for="(line, i) in form.lines" :key="i" class="line-row">
        <input v-model="line.itemCode" class="input" placeholder="物料编码" />
        <input v-model="line.itemName" class="input" placeholder="物料名称" />
        <input v-model="line.quantity" class="input" type="number" min="0" step="0.001" placeholder="数量" />
        <input v-model="line.unit" class="input" placeholder="单位" />
        <input v-model="line.unitPrice" class="input" type="number" min="0" step="0.0001" placeholder="单价" />
        <button class="btn btn-ghost btn-sm" type="button" @click="removeLine(i)">删</button>
      </div>

      <p v-if="formError" class="inline-error">{{ formError }}</p>
      <div class="purch-actions">
        <button class="btn btn-primary" type="submit" :disabled="saving">{{ saving ? '创建中…' : '创建订单' }}</button>
      </div>
    </form>
  </div>

  <div v-if="detail || detailLoading || detailError" class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">订单详情</h2>
        <p v-if="detail" class="card-sub">{{ detail.orderNo }} · 状态 {{ statusLabel(detail.status) }}</p>
      </div>
      <div v-if="detail && props.isAdmin && detail.status !== 'cancelled' && detail.status !== 'received'">
        <button class="btn btn-danger btn-sm" type="button" :disabled="cancelling" @click="cancelOrder">
          {{ cancelling ? '取消中…' : '取消订单' }}
        </button>
      </div>
    </div>
    <div v-if="detailLoading" class="empty-state"><p class="empty-title">加载详情…</p></div>
    <div v-else-if="detailError" class="empty-state"><p class="empty-desc">{{ detailError }}</p></div>
    <div v-else-if="detail" class="purch-form">
      <p v-if="detail.remark" class="card-sub">备注：{{ detail.remark }}</p>
      <div class="table-wrap">
        <table class="purch-table">
          <thead>
            <tr>
              <th>物料</th>
              <th>数量</th>
              <th>单价</th>
              <th>金额</th>
              <th>已收</th>
              <th>已开票</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="l in detail.lines" :key="l.id">
              <td>{{ l.itemCode }} · {{ l.itemName }}</td>
              <td>{{ l.quantity }}</td>
              <td>{{ l.unitPrice }}</td>
              <td>{{ l.amount }}</td>
              <td>{{ l.receivedQty }}</td>
              <td>{{ l.invoicedQty }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="card-sub">订单总额：<strong>{{ detail.totalAmount }}</strong> 元（{{ detail.currency }}）</p>
    </div>
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
  grid-template-columns: 1fr 1.4fr 0.8fr 0.6fr 0.8fr auto;
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
