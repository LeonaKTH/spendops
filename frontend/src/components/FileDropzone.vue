<script setup lang="ts">
import { ref } from 'vue'

withDefaults(
  defineProps<{
    accept?: string
    disabled?: boolean
  }>(),
  {
    accept: '.xlsx,.xls,.csv,.pdf,.docx,.txt',
    disabled: false,
  },
)

const emit = defineEmits<{ select: [file: File] }>()

const dragging = ref(false)
const input = ref<HTMLInputElement | null>(null)

function openPicker() {
  input.value?.click()
}

function onDrop(event: DragEvent) {
  dragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) emit('select', file)
}

function onChange(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (file) emit('select', file)
  target.value = ''
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ dragging }"
    role="button"
    tabindex="0"
    @click="openPicker"
    @keydown.enter="openPicker"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <input
      ref="input"
      type="file"
      :accept="accept"
      :disabled="disabled"
      hidden
      @change="onChange"
    />
    <div class="dropzone-icon">
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.7"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M12 16V4" />
        <path d="m7 9 5-5 5 5" />
        <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
      </svg>
    </div>
    <p class="dropzone-title">拖拽文件到这里，或点击选择</p>
    <p class="dropzone-hint">
      Excel 账单 / 报价 / 配额表，或 PDF / Word 合同<br />
      Excel 自动建表；合同切分条款并建立检索索引 · 单文件 ≤ 20 MB
    </p>
  </div>
</template>
