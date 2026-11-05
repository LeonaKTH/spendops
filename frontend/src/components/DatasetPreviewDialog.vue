<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api } from '../api'
import type { Dataset, DatasetRows } from '../api/types'
import DataTable from './DataTable.vue'

const PAGE_SIZE = 20

const props = defineProps<{
  open: boolean
  dataset: Dataset | null
}>()

const emit = defineEmits<{ close: [] }>()

const page = ref<DatasetRows | null>(null)
const offset = ref(0)
const loading = ref(false)
const error = ref('')
const jumpPage = ref(1)

const total = computed(() => page.value?.total ?? props.dataset?.rowCount ?? 0)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const pageNo = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
const canPrev = computed(() => offset.value > 0 && !loading.value)
const canNext = computed(() => offset.value + PAGE_SIZE < total.value && !loading.value)

async function load() {
  if (!props.dataset) return
  loading.value = true
  error.value = ''
  try {
    page.value = await api.getDatasetRows(props.dataset.id, PAGE_SIZE, offset.value)
  } catch (cause) {
    page.value = null
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

function go(delta: number) {
  const next = offset.value + delta * PAGE_SIZE
  if (next < 0 || next >= total.value) return
  offset.value = next
  void load()
}

function jump() {
  const target = Math.min(pageCount.value, Math.max(1, Math.floor(Number(jumpPage.value) || 1)))
  const next = (target - 1) * PAGE_SIZE
  jumpPage.value = target
  if (next === offset.value) return
  offset.value = next
  void load()
}

watch(pageNo, (value) => {
  jumpPage.value = value
})

watch(
  () => props.open,
  (open) => {
    if (!open) return
    offset.value = 0
    jumpPage.value = 1
    page.value = null
    void load()
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
      <div class="modal dataset-preview-modal" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div>
            <h2>{{ dataset?.name ?? '数据集' }}</h2>
            <p class="modal-context">
              {{ dataset?.sourceFile }}
              <template v-if="dataset">
                · {{ total.toLocaleString('zh-CN') }} 行 · {{ dataset.columns.length }} 个字段
              </template>
            </p>
          </div>
          <button class="modal-close" type="button" aria-label="关闭" @click="emit('close')">
            ×
          </button>
        </div>

        <div class="modal-body">
          <div v-if="loading" class="empty-state compact">
            <span class="spinner"></span>
            <p class="empty-desc">正在读取数据…</p>
          </div>
          <p v-else-if="error" class="form-error">{{ error }}</p>
          <template v-else-if="page">
            <DataTable :result="page" :max-rows="PAGE_SIZE" max-height="52vh" />
            <div class="pagination">
              <span>
                第 {{ pageNo }} / {{ pageCount }} 页 · 共
                {{ total.toLocaleString('zh-CN') }} 行
              </span>
              <div class="pagination-actions">
                <input
                  v-model.number="jumpPage"
                  class="page-input"
                  type="number"
                  min="1"
                  :max="pageCount"
                  aria-label="跳转到页码"
                  @keydown.enter="jump"
                />
                <button class="btn btn-ghost btn-sm" type="button" @click="jump">跳转</button>
                <button
                  class="btn btn-ghost btn-sm"
                  type="button"
                  :disabled="!canPrev"
                  @click="go(-1)"
                >
                  上一页
                </button>
                <button
                  class="btn btn-ghost btn-sm"
                  type="button"
                  :disabled="!canNext"
                  @click="go(1)"
                >
                  下一页
                </button>
              </div>
            </div>
          </template>
          <p v-else class="empty-desc">该数据集没有可展示的数据。</p>
        </div>
      </div>
    </div>
  </Teleport>
</template>
