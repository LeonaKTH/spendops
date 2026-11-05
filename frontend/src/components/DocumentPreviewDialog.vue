<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api } from '../api'
import type { ChatSource, DocumentPages } from '../api/types'

const props = defineProps<{
  open: boolean
  source: ChatSource | null
}>()

const emit = defineEmits<{ close: [] }>()

const pages = ref<DocumentPages | null>(null)
const activePage = ref<number | null>(null)
const loading = ref(false)
const error = ref('')

const current = computed(
  () => pages.value?.pages.find((item) => item.page === activePage.value) ?? null,
)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    pages.value = null
    error.value = ''
    activePage.value = props.source?.page ?? null
    if (!props.source) return

    loading.value = true
    try {
      const result = await api.getDocumentPages(props.source.documentId)
      pages.value = result
      if (activePage.value === null && result.pages.length) {
        activePage.value = result.pages[0].page
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      loading.value = false
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
      <div class="modal doc-preview-modal" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div>
            <h2>{{ source?.document || pages?.name || '合同原文' }}</h2>
            <p v-if="source?.page" class="modal-context">定位到第 {{ source.page }} 页</p>
          </div>
          <button class="modal-close" type="button" aria-label="关闭" @click="emit('close')">
            ×
          </button>
        </div>

        <div class="modal-body">
          <p v-if="source?.snippet" class="source-snippet">「{{ source.snippet }}」</p>

          <div v-if="loading" class="empty-state compact">
            <span class="spinner"></span>
            <p class="empty-desc">正在加载文档内容…</p>
          </div>
          <p v-else-if="error" class="form-error">{{ error }}</p>
          <template v-else-if="pages">
            <div class="doc-pages">
              <button
                v-for="item in pages.pages"
                :key="item.page"
                class="chip"
                :class="{ active: item.page === activePage }"
                type="button"
                @click="activePage = item.page"
              >
                第 {{ item.page }} 页
              </button>
            </div>
            <pre v-if="current" class="doc-page-text">{{ current.content }}</pre>
            <p v-else class="empty-desc">该页没有可展示的文本内容。</p>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
