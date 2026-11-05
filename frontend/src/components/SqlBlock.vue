<script setup lang="ts">
import { computed, ref } from 'vue'

import { copyText } from '../utils/clipboard'

const props = defineProps<{
  sql: string
  datasets?: string[]
  rowCount?: number
  truncated?: boolean
}>()

const copied = ref(false)

const hasMeta = computed(
  () => !!props.datasets?.length || props.rowCount !== undefined || !!props.truncated,
)

async function copy(event: MouseEvent) {
  event.preventDefault()
  event.stopPropagation()

  await copyText(props.sql)
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1600)
}
</script>

<template>
  <details class="sql-block">
    <summary>
      <span>查看生成的 SQL</span>
      <button class="copy-btn" type="button" @click="copy">
        {{ copied ? '已复制' : '复制' }}
      </button>
    </summary>
    <div v-if="hasMeta" class="sql-meta">
      <span v-if="datasets?.length">数据集 {{ datasets.join('、') }}</span>
      <span v-if="rowCount !== undefined">返回 {{ rowCount }} 行</span>
      <span v-if="truncated" class="sql-meta-warn">已按安全上限截断</span>
    </div>
    <pre><code>{{ sql }}</code></pre>
  </details>
</template>
