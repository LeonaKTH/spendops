<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '../api'
import { ApiError } from '../api/errors'
import type { AnalysisMode, AnalysisResult } from '../api/types'

const question = ref('')
const mode = ref<AnalysisMode>('offline')
const examples = ref<string[]>([])
const result = ref<AnalysisResult | null>(null)
const loading = ref(false)
const error = ref('')

const prettyFacts = computed(() => JSON.stringify(result.value?.facts ?? {}, null, 2))

const modeLabel = computed(() => {
  const m = result.value?.mode ?? mode.value
  return m === 'llm' ? 'LLM 解释' : '离线确定性分析'
})

async function loadExamples() {
  try {
    examples.value = await api.getAnalysisExamples()
  } catch {
    examples.value = []
  }
}

function useExample(q: string) {
  question.value = q
  ask()
}

async function ask() {
  const q = question.value.trim()
  if (!q) return
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await api.askAnalysis(q, mode.value)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '分析失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(loadExamples)
</script>

<template>
  <section class="ai-panel">
    <div class="ai-head">
      <h3 class="ai-title">AI 经营分析（受控问数）</h3>
      <span class="ai-mode-hint">金额与比例均为数据库确定性计算，AI 不生成数字</span>
    </div>

    <div class="ai-input-row">
      <input
        v-model="question"
        type="text"
        class="input ai-input"
        placeholder="例如：哪些供应商采购金额最高？"
        :disabled="loading"
        @keyup.enter="ask"
      />
      <button class="btn" type="button" :disabled="loading || !question.trim()" @click="ask">
        {{ loading ? '分析中…' : '分析' }}
      </button>
    </div>

    <div class="ai-mode-row">
      <label class="ai-radio">
        <input v-model="mode" type="radio" value="offline" name="ai-mode" />
        离线确定性分析
      </label>
      <label class="ai-radio">
        <input v-model="mode" type="radio" value="llm" name="ai-mode" />
        LLM 解释（需配置 Key）
      </label>
    </div>

    <div v-if="examples.length" class="ai-examples">
      <button
        v-for="ex in examples"
        :key="ex"
        type="button"
        class="ai-example"
        :disabled="loading"
        @click="useExample(ex)"
      >
        {{ ex }}
      </button>
    </div>

    <div v-if="loading" class="empty-state">正在分析…</div>
    <p v-else-if="error" class="inline-error">{{ error }}</p>

    <div v-else-if="result" class="ai-result">
      <div class="ai-badges">
        <span class="chip">意图：{{ result.intentLabel }}</span>
        <span class="chip">时间：{{ result.timeRange.start }} ~ {{ result.timeRange.end }}</span>
        <span v-if="result.supplier" class="chip">供应商：{{ result.supplier.name }}</span>
        <span class="chip" :class="result.mode === 'llm' ? 'ai-chip-llm' : 'ai-chip-off'">
          来源：{{ modeLabel }}
        </span>
      </div>

      <p class="ai-explanation">{{ result.explanation }}</p>

      <div v-if="result.observations.length" class="ai-observations">
        <div v-for="(o, i) in result.observations" :key="i" class="ai-obs">• {{ o }}</div>
      </div>

      <details class="ai-details">
        <summary>数据依据（指标口径与原始计算值）</summary>
        <p class="hint">{{ result.metricDefinition }}</p>
        <pre class="ai-facts">{{ prettyFacts }}</pre>
      </details>

      <div v-if="result.limitations.length" class="ai-limitations">
        <span v-for="(l, i) in result.limitations" :key="i" class="ai-limit">说明：{{ l }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ai-panel {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 16px;
}
.ai-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.ai-title {
  font-size: 15px;
  font-weight: 650;
  margin: 0;
}
.ai-mode-hint {
  font-size: 12px;
  color: var(--muted, #888);
}
.ai-input-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.ai-input {
  flex: 1;
}
.ai-mode-row {
  display: flex;
  gap: 14px;
  margin-bottom: 8px;
}
.ai-radio {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  cursor: pointer;
}
.ai-examples {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.ai-example {
  font-size: 12px;
  color: var(--fg, #333);
  background: var(--bg-hover, #f3f4f6);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 999px;
  padding: 4px 10px;
  cursor: pointer;
}
.ai-example:hover {
  background: #e0f2fe;
}
.ai-result {
  border-top: 1px dashed var(--border, #e5e7eb);
  padding-top: 10px;
}
.ai-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.ai-chip-off {
  background: #f0f4ff;
  color: #3b5bdb;
}
.ai-chip-llm {
  background: #e8f5e9;
  color: #1b7f3b;
}
.ai-explanation {
  font-size: 14px;
  line-height: 1.6;
  margin: 0 0 8px;
}
.ai-observations {
  margin-bottom: 8px;
}
.ai-obs {
  font-size: 13px;
  color: #6b7280;
  margin: 2px 0;
}
.ai-details {
  font-size: 13px;
  margin-bottom: 8px;
}
.ai-details summary {
  cursor: pointer;
  color: var(--fg, #333);
  font-weight: 600;
}
.ai-facts {
  background: #f8fafc;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  padding: 10px;
  overflow-x: auto;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}
.ai-limitations {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ai-limit {
  font-size: 12px;
  color: var(--muted, #888);
}
.inline-error {
  color: #c0392b;
  font-size: 13px;
  margin: 8px 0;
}
.empty-state {
  padding: 16px;
  text-align: center;
  color: var(--muted, #888);
  font-size: 13px;
}
.hint {
  font-size: 12px;
  color: var(--muted, #888);
  margin: 6px 0;
}
</style>
