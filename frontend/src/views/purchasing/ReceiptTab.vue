<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '../../api'
import type { GoodsReceipt, PurchaseOrder } from '../../api/types'

const props = defineProps<{ isAdmin: boolean }>()

const receipts = ref<GoodsReceipt[]>([])
const orders = ref<PurchaseOrder[]>([])
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const formError = ref('')

const selectedOrderId = ref('')
const selectedOrder = ref<PurchaseOrder | null>(null)
const form = ref({ receiptNo: '', receiptDate: new Date().toISOString().slice(0, 10), lines: [] as { orderLineId: string; quantity: string }[] })

async function load() {
  loading.value = true
  error.value = ''
  try {
    receipts.value = await api.listReceipts()
    orders.value = (await api.listOrders()).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function pickOrder() {
  selectedOrder.value = null
  form.value.lines = []
  if (!selectedOrderId.value) return
  try {
    selectedOrder.value = await api.getOrder(selectedOrderId.value)
    // 只对未收满的明细行展示可收数量
    form.value.lines = selectedOrder.value.lines
      .filter((l) => Number(l.receivedQty) < Number(l.quantity))
      .map((l) => ({ orderLineId: l.id, quantity: '' }))
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '加载订单失败'
  }
}

async function submit() {
  formError.value = ''
  if (!form.value.receiptNo.trim()) return setError('收货单号必填。')
  if (!selectedOrderId.value) return setError('请选择采购订单。')
  const lines = form.value.lines.filter((l) => l.quantity !== '' && Number(l.quantity) > 0)
  if (lines.length === 0) return setError('请至少填写一条收货数量。')
  saving.value = true
  try {
    await api.createReceipt({
      receiptNo: form.value.receiptNo.trim(),
      orderId: selectedOrderId.value,
      receiptDate: form.value.receiptDate,
      lines,
    })
    form.value = { receiptNo: '', receiptDate: new Date().toISOString().slice(0, 10), lines: [] }
    selectedOrderId.value = ''
    selectedOrder.value = null
    await load()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '登记收货失败'
  } finally {
    saving.value = false
  }
}

function setError(msg: string) {
  formError.value = msg
}

function remainFor(orderLineId: string): string {
  if (!selectedOrder.value) return ''
  const line = selectedOrder.value.lines.find((x) => x.id === orderLineId)
  if (!line) return ''
  return (Number(line.quantity) - Number(line.receivedQty)).toString()
}

onMounted(load)
</script>

<template>
  <div class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">收货记录</h2>
        <p class="card-sub">一个订单可部分收货，超量收货会被后端拒绝</p>
      </div>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="empty-state"><p class="empty-title">正在加载…</p></div>
    <div v-else-if="error" class="empty-state">
      <p class="empty-title">加载失败</p>
      <p class="empty-desc">{{ error }}</p>
    </div>
    <div v-else-if="receipts.length === 0" class="empty-state">
      <p class="empty-title">还没有收货记录</p>
      <p class="empty-desc">选择一张订单登记到货。</p>
    </div>
    <div v-else class="table-wrap">
      <table class="purch-table">
        <thead>
          <tr>
            <th>收货单号</th>
            <th>订单号</th>
            <th>日期</th>
            <th>数量</th>
            <th>金额(元)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in receipts" :key="r.id">
            <td class="mono">{{ r.receiptNo }}</td>
            <td class="mono">{{ r.orderNo }}</td>
            <td>{{ r.receiptDate }}</td>
            <td>{{ r.totalQuantity }}</td>
            <td>{{ r.totalAmount }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="props.isAdmin" class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">登记收货</h2>
        <p class="card-sub">收货后订单状态自动联动为「部分收货 / 已收货」</p>
      </div>
    </div>
    <form class="purch-form" @submit.prevent="submit">
      <div class="purch-grid">
        <label class="field">
          <span class="field-label">收货单号 *</span>
          <input v-model="form.receiptNo" class="input" placeholder="如 GR-2026-001" maxlength="40" />
        </label>
        <label class="field">
          <span class="field-label">采购订单 *</span>
          <select v-model="selectedOrderId" class="select-input" @change="pickOrder">
            <option value="" disabled>请选择订单</option>
            <option v-for="o in orders" :key="o.id" :value="o.id" :disabled="o.status === 'cancelled' || o.status === 'received'">
              {{ o.orderNo }} · {{ o.supplierName }}（{{ o.status }}）
            </option>
          </select>
        </label>
        <label class="field">
          <span class="field-label">收货日期 *</span>
          <input v-model="form.receiptDate" type="date" class="input" />
        </label>
      </div>

      <div v-if="selectedOrder" class="line-head">
        <span>本次收货数量（订单数量 - 已收数量 = 可收数量）</span>
      </div>
      <div v-for="l in form.lines" :key="l.orderLineId" class="line-row">
        <span class="line-item">{{ selectedOrder?.lines.find((x) => x.id === l.orderLineId)?.itemName }}（可收 {{ remainFor(l.orderLineId) }}）</span>
        <input v-model="l.quantity" class="input" type="number" min="0" step="0.001" placeholder="本次数量" />
      </div>

      <p v-if="formError" class="inline-error">{{ formError }}</p>
      <div class="purch-actions">
        <button class="btn btn-primary" type="submit" :disabled="saving">{{ saving ? '提交中…' : '登记收货' }}</button>
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
  margin: 18px 0 10px;
  font-size: 13px;
  font-weight: 600;
}
.line-row {
  display: grid;
  grid-template-columns: 1fr 200px;
  gap: 12px;
  align-items: center;
  margin-bottom: 8px;
}
.line-item {
  font-size: 13px;
}
.purch-actions {
  margin-top: 16px;
}
.card {
  margin-bottom: 20px;
}
</style>
