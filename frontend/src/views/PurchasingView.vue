<script setup lang="ts">
import { ref } from 'vue'

import { useAuthStore } from '../stores/auth'
import SupplierTab from './purchasing/SupplierTab.vue'
import OrderTab from './purchasing/OrderTab.vue'
import ReceiptTab from './purchasing/ReceiptTab.vue'
import InvoiceTab from './purchasing/InvoiceTab.vue'

const auth = useAuthStore()

type TabKey = 'suppliers' | 'orders' | 'receipts' | 'invoices'

const active = ref<TabKey>('suppliers')

const tabs: { key: TabKey; label: string; desc: string }[] = [
  { key: 'suppliers', label: '供应商', desc: '供应商主数据' },
  { key: 'orders', label: '采购订单', desc: '订单与明细' },
  { key: 'receipts', label: '收货', desc: '到货登记' },
  { key: 'invoices', label: '发票', desc: '发票录入' },
]
</script>

<template>
  <main class="app-main">
    <header class="page-head">
      <div>
        <h1 class="page-title">采购管理</h1>
        <p class="page-sub">供应商、采购订单、收货与发票的真实业务闭环</p>
      </div>
    </header>

    <div class="purch-tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="purch-tab"
        :class="{ active: active === tab.key }"
        :aria-selected="active === tab.key"
        role="tab"
        @click="active = tab.key"
      >
        <span class="purch-tab-label">{{ tab.label }}</span>
        <span class="purch-tab-desc">{{ tab.desc }}</span>
      </button>
    </div>

    <SupplierTab v-if="active === 'suppliers'" :is-admin="auth.isAdmin" />
    <OrderTab v-else-if="active === 'orders'" :is-admin="auth.isAdmin" />
    <ReceiptTab v-else-if="active === 'receipts'" :is-admin="auth.isAdmin" />
    <InvoiceTab v-else :is-admin="auth.isAdmin" />
  </main>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 20px;
}
.page-title {
  font-size: 20px;
  font-weight: 650;
  margin: 0 0 4px;
  letter-spacing: -0.01em;
}
.page-sub {
  margin: 0;
  color: var(--muted, #7a7f8c);
  font-size: 13px;
}
.purch-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.purch-tab {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 10px 16px;
  border: 1px solid var(--border, #e4e6eb);
  border-radius: 10px;
  background: var(--surface, #fff);
  cursor: pointer;
  font: inherit;
  color: var(--text, #1c1f26);
  transition: border-color 0.15s, background 0.15s;
}
.purch-tab:hover {
  border-color: var(--accent, #2f6bff);
}
.purch-tab.active {
  border-color: var(--accent, #2f6bff);
  background: var(--accent-soft, #eef3ff);
}
.purch-tab-label {
  font-weight: 600;
  font-size: 14px;
}
.purch-tab-desc {
  font-size: 12px;
  color: var(--muted, #7a7f8c);
}
</style>
