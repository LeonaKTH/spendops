<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'

import { api } from '../api'
import type { ChatMessage, ChatSource } from '../api/types'
import ChatMessageItem from '../components/ChatMessage.vue'
import DocumentPreviewDialog from '../components/DocumentPreviewDialog.vue'
import { useDatasetStore } from '../stores/datasets'

const store = useDatasetStore()

const suggestions = [
  '2025 年各供应商采购金额是多少？',
  '6 月成本为什么突然上升？',
  '哪些模型比 deepseek-chat 更便宜？',
  '哪些供应商的合同配额快用完了？',
]

const messages = ref<ChatMessage[]>([])
const input = ref('')
const sending = ref(false)
const inputEl = ref<HTMLTextAreaElement | null>(null)
const scrollEl = ref<HTMLDivElement | null>(null)
const previewOpen = ref(false)
const previewSource = ref<ChatSource | null>(null)

function openSource(source: ChatSource) {
  previewSource.value = source
  previewOpen.value = true
}

function mergeSources(existing: ChatSource[] | undefined, incoming: ChatSource[]): ChatSource[] {
  const merged = [...(existing ?? [])]
  const seen = new Set(merged.map((item) => `${item.documentId}:${item.page}`))
  for (const item of incoming) {
    const key = `${item.documentId}:${item.page}`
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
    if (merged.length >= 6) break
  }
  return merged
}

let controller: AbortController | null = null
let messageSeq = 0

const nextId = () => {
  messageSeq += 1
  return `m-${Date.now()}-${messageSeq}`
}

const progress = computed(() =>
  messages.value
    .map(
      (message) =>
        `${message.content.length}:${message.loading ? 1 : 0}:${message.status ?? ''}:${
          message.sql ? 1 : 0
        }:${message.table ? 1 : 0}:${message.chart ? 1 : 0}:${message.sources?.length ?? 0}:${
          message.error ?? ''
        }`,
    )
    .join('|'),
)

function scrollToBottom() {
  const el = scrollEl.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(progress, () => {
  nextTick(scrollToBottom)
})

function autoSize() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}

async function send(preset?: string) {
  const question = (preset ?? input.value).trim()
  if (!question || sending.value) return

  input.value = ''
  await nextTick()
  autoSize()

  messages.value.push({ id: nextId(), role: 'user', content: question })
  const assistant = reactive<ChatMessage>({
    id: nextId(),
    role: 'assistant',
    content: '',
    status: '正在理解问题…',
    loading: true,
  })
  messages.value.push(assistant)

  sending.value = true
  controller = new AbortController()

  try {
    await api.askQuestion(
      question,
      (event) => {
        switch (event.type) {
          case 'status':
            assistant.status = event.data.stage
            break
          case 'sql':
            assistant.sql = event.data.sql
            assistant.datasets = event.data.datasets
            break
          case 'table':
            assistant.table = event.data
            break
          case 'chart':
            assistant.chart = event.data
            break
          case 'text':
            assistant.content += event.data.delta
            break
          case 'sources':
            assistant.sources = mergeSources(assistant.sources, event.data.items)
            break
          case 'error':
            assistant.error = event.data.message
            break
          case 'done':
            assistant.loading = false
            break
        }
      },
      controller.signal,
      [...store.activeIds],
    )
  } catch (cause) {
    if ((cause as Error)?.name !== 'AbortError') {
      assistant.error = cause instanceof Error ? cause.message : String(cause)
    }
  } finally {
    assistant.loading = false
    sending.value = false
    controller = null
  }
}

function stop() {
  controller?.abort()
}

onBeforeUnmount(() => {
  controller?.abort()
})
</script>

<template>
  <div class="chat-layout">
    <div class="chat-context">
      <span class="context-label">可用数据集</span>
      <button
        v-for="dataset in store.datasets"
        :key="dataset.id"
        class="chip"
        :class="{ active: store.activeIds.includes(dataset.id) }"
        type="button"
        @click="store.toggleActive(dataset.id)"
      >
        {{ dataset.name }}
      </button>
      <span v-if="store.activeIds.length === 0" class="context-warning">
        未启用数据集时默认查询全部
      </span>
    </div>

    <div ref="scrollEl" class="chat-scroll">
      <div v-if="messages.length === 0" class="chat-empty">
        <div class="chat-empty-mark">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M12 3v3" />
            <path d="M12 18v3" />
            <path d="M4.2 4.2 6.3 6.3" />
            <path d="m17.7 17.7 2.1 2.1" />
            <path d="M3 12h3" />
            <path d="M18 12h3" />
            <path d="m4.2 19.8 2.1-2.1" />
            <path d="m17.7 6.3 2.1-2.1" />
            <circle cx="12" cy="12" r="3.2" />
          </svg>
        </div>
        <h2>用一句话，问清采购成本</h2>
        <p>
          我会自动检索数据集、生成只读 SQL、执行查询，并把结果整理成图表和可执行的结论。
        </p>
        <div class="suggestions">
          <button
            v-for="item in suggestions"
            :key="item"
            class="suggestion"
            type="button"
            @click="send(item)"
          >
            {{ item }}
          </button>
        </div>
      </div>

      <div v-else class="chat-thread">
        <ChatMessageItem
          v-for="message in messages"
          :key="message.id"
          :message="message"
          @open-source="openSource"
        />
      </div>
    </div>

    <div class="composer-wrap">
      <div class="composer">
        <div class="composer-row">
          <textarea
            ref="inputEl"
            v-model="input"
            rows="1"
            placeholder="问一个关于采购成本、调用量、单价或配额的问题…"
            :disabled="sending"
            @input="autoSize"
            @keydown="onKeydown"
          ></textarea>
          <button
            v-if="!sending"
            class="send-btn"
            type="button"
            :disabled="!input.trim()"
            aria-label="发送"
            @click="send()"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M12 19V5" />
              <path d="m5 12 7-7 7 7" />
            </svg>
          </button>
          <button v-else class="send-btn stop" type="button" aria-label="停止生成" @click="stop">
            <svg viewBox="0 0 24 24" fill="currentColor">
              <rect x="7" y="7" width="10" height="10" rx="2" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <DocumentPreviewDialog
      :open="previewOpen"
      :source="previewSource"
      @close="previewOpen = false"
    />
  </div>
</template>
