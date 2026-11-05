<script setup lang="ts">
import { ref } from 'vue'

const model = defineModel<string>({ default: '' })

defineProps<{
  autocomplete?: string
  placeholder?: string
}>()

const visible = ref(false)
</script>

<template>
  <span class="password-field">
    <input
      v-model="model"
      class="input"
      :type="visible ? 'text' : 'password'"
      :autocomplete="autocomplete"
      :placeholder="placeholder"
    />
    <button
      class="password-toggle"
      type="button"
      :aria-label="visible ? '隐藏密码' : '显示密码'"
      :aria-pressed="visible"
      @click.prevent.stop="visible = !visible"
    >
      {{ visible ? '隐藏' : '显示' }}
    </button>
  </span>
</template>
