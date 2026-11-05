<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api, USING_MOCK } from '../api'
import type { ReportShare } from '../api/types'

const props = defineProps<{
  open: boolean
  datasetId: string
  datasetName: string
  startDate?: string
  endDate?: string
  provider?: string
  rangeLabel: string
}>()

const emit = defineEmits<{ close: [] }>()

const expires = ref(30)
const creating = ref(false)
const loading = ref(false)
const revokingId = ref('')
const error = ref('')
const createdLink = ref('')
const copied = ref(false)
const shares = ref<ReportShare[]>([])

const canCreate = computed(() => Boolean(props.datasetId) && !creating.value)

async function loadShares() {
  if (!props.datasetId) {
    shares.value = []
    return
  }
  loading.value = true
  try {
    shares.value = await api.listReportShares(props.datasetId)
  } catch {
    shares.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    error.value = ''
    createdLink.value = ''
    copied.value = false
    expires.value = 30
    await loadShares()
  },
)

async function create() {
  if (!canCreate.value) return
  creating.value = true
  error.value = ''
  createdLink.value = ''
  try {
    const share = await api.createReportShare({
      datasetId: props.datasetId,
      startDate: props.startDate,
      endDate: props.endDate,
      provider: props.provider || undefined,
      expiresInDays: expires.value,
    })
    createdLink.value = `${window.location.origin}${share.path}`
    await loadShares()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    creating.value = false
  }
}

async function copyLink() {
  if (!createdLink.value) return
  try {
    await navigator.clipboard.writeText(createdLink.value)
    copied.value = true
  } catch {
    const input = document.createElement('textarea')
    input.value = createdLink.value
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    input.remove()
    copied.value = true
  }
  setTimeout(() => {
    copied.value = false
  }, 2500)
}

async function revoke(share: ReportShare) {
  if (!window.confirm(`确定撤销该分享链接？撤销后访客将立即无法打开。`)) return
  revokingId.value = share.id
  try {
    await api.revokeReportShare(share.id)
    await loadShares()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    revokingId.value = ''
  }
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
      <div class="modal share-modal" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h2>分享只读报表</h2>
          <button class="modal-close" type="button" aria-label="关闭" @click="emit('close')">
            ×
          </button>
        </div>

        <div class="modal-body">
          <p class="modal-context">
            {{ datasetName }} · {{ rangeLabel }}
            <template v-if="provider"> · 供应商 {{ provider }}</template>
          </p>
          <p class="field-hint">
            <template v-if="USING_MOCK">
              演示模式下分享链接仅在当前浏览器有效，导出格式为 CSV。
            </template>
            <template v-else>
              获得链接的人无需登录即可查看这份报表，并可导出 Excel / PDF。
            </template>
          </p>

          <label class="field">
            <span>链接有效期</span>
            <select v-model.number="expires" class="input">
              <option :value="7">7 天</option>
              <option :value="30">30 天</option>
              <option :value="90">90 天</option>
            </select>
          </label>

          <p v-if="error" class="form-error">{{ error }}</p>

          <div v-if="createdLink" class="share-link-box">
            <p class="share-link-label">链接已生成（只显示这一次，请复制保存）</p>
            <div class="share-link-row">
              <input class="input" :value="createdLink" readonly @click="copyLink" />
              <button class="btn btn-primary btn-sm" type="button" @click="copyLink">
                {{ copied ? '已复制' : '复制链接' }}
              </button>
            </div>
          </div>

          <button class="btn btn-primary" type="button" :disabled="!canCreate" @click="create">
            {{ creating ? '正在创建…' : '生成分享链接' }}
          </button>

          <div class="share-list">
            <div class="share-list-head">
              <span>已有有效链接</span>
              <span class="tag">{{ shares.length }}</span>
            </div>
            <p v-if="loading" class="field-hint">正在加载…</p>
            <p v-else-if="!shares.length" class="field-hint">还没有有效链接。</p>
            <div v-for="share in shares" :key="share.id" class="share-item">
              <div>
                <p class="share-item-title">
                  {{ share.periodStart || '全部账期' }}
                  <template v-if="share.periodEnd && share.periodEnd !== share.periodStart">
                    至 {{ share.periodEnd }}
                  </template>
                  <template v-if="share.provider"> · {{ share.provider }}</template>
                </p>
                <p class="share-item-meta">
                  {{ share.createdByUsername }} 创建 · 到期 {{ formatTime(share.expiresAt) }} ·
                  访问 {{ share.viewCount }} 次
                </p>
              </div>
              <button
                class="btn btn-ghost btn-sm"
                type="button"
                :disabled="revokingId === share.id"
                @click="revoke(share)"
              >
                {{ revokingId === share.id ? '撤销中…' : '撤销' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
