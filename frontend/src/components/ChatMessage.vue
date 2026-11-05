<script setup lang="ts">
import { ref } from 'vue'

import type { ChatMessage, ChatSource } from '../api/types'
import { copyText } from '../utils/clipboard'
import ChartRenderer from './ChartRenderer.vue'
import DataTable from './DataTable.vue'
import SqlBlock from './SqlBlock.vue'

const props = defineProps<{ message: ChatMessage }>()

const emit = defineEmits<{ 'open-source': [source: ChatSource] }>()

const copied = ref(false)

async function copyAnswer() {
  if (!props.message.content) return
  await copyText(props.message.content)
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1600)
}
</script>

<template>
  <div class="message" :class="message.role">
    <div class="avatar">{{ message.role === 'assistant' ? 'AI' : '我' }}</div>

    <div class="message-body">
      <template v-if="message.role === 'user'">
        <div class="message-content">{{ message.content }}</div>
      </template>

      <template v-else>
        <div v-if="message.loading && message.status" class="message-status">
          <span class="spinner"></span>
          {{ message.status }}
        </div>

        <div v-if="message.error" class="message-error">{{ message.error }}</div>

        <SqlBlock
          v-if="message.sql"
          :sql="message.sql"
          :datasets="message.datasets"
          :row-count="message.table?.rows.length"
          :truncated="message.table?.truncated"
        />

        <div v-if="message.chart" class="message-chart">
          <p class="chart-title">{{ message.chart.title }}</p>
          <ChartRenderer :spec="message.chart" />
        </div>

        <div v-if="message.table" class="message-table">
          <DataTable :result="message.table" />
        </div>

        <div v-if="message.content" class="message-content">{{ message.content }}</div>

        <div v-if="message.content && !message.loading" class="message-actions">
          <button class="answer-copy" type="button" @click="copyAnswer">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <rect x="9" y="9" width="12" height="12" rx="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            {{ copied ? '已复制' : '复制' }}
          </button>
        </div>

        <div v-if="message.sources?.length" class="message-sources">
          <span class="context-label">引用条款</span>
          <button
            v-for="(source, index) in message.sources"
            :key="`${source.documentId}-${source.page}-${index}`"
            class="source-chip"
            type="button"
            @click="emit('open-source', source)"
          >
            {{ source.document }}<template v-if="source.page"> · 第 {{ source.page }} 页</template>
          </button>
        </div>

        <div v-else-if="message.loading" class="typing">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </template>
    </div>
  </div>
</template>
