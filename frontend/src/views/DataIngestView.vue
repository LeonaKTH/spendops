<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api'
import { ApiError } from '../api/errors'
import type { Dataset, DocumentItem, PreviewResult, TableResult } from '../api/types'
import DataTable from '../components/DataTable.vue'
import FileDropzone from '../components/FileDropzone.vue'
import { useDatasetStore } from '../stores/datasets'
import { useDocumentStore } from '../stores/documents'

const store = useDatasetStore()
const docStore = useDocumentStore()
const router = useRouter()

type Mode = 'table' | 'document'

const TABLE_STEPS = ['读取文件', '识别表头', '推断字段类型', '注册数据集']
const DOC_STEPS = ['读取文档', '提取文本', '切分条款', '建立索引']
const TABLE_EXTENSIONS = ['xlsx', 'xls', 'csv']
const DOC_EXTENSIONS = ['pdf', 'docx', 'txt']
const MAX_SIZE = 20 * 1024 * 1024

const mode = ref<Mode>('table')
const steps = computed(() => (mode.value === 'document' ? DOC_STEPS : TABLE_STEPS))

const file = ref<File | null>(null)
const step = ref(0)
const parsing = ref(false)
const importing = ref(false)
const preview = ref<PreviewResult | null>(null)
const imported = ref<Dataset | null>(null)
const importedDoc = ref<DocumentItem | null>(null)
const error = ref('')
const duplicate = ref(false)

let parseToken = 0

const fileSize = computed(() => {
  if (!file.value) return ''
  const size = file.value.size
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(size / 1024))} KB`
})

const fileBadge = computed(() => {
  if (!file.value) return ''
  const extension = file.value.name.split('.').pop()?.toLowerCase() ?? ''
  return ['pdf', 'docx', 'txt'].includes(extension) ? 'DOC' : 'XLS'
})

const canPreview = computed(() => mode.value === 'table' && !!preview.value && !parsing.value)
const canImportDoc = computed(
  () =>
    mode.value === 'document' &&
    !!file.value &&
    !parsing.value &&
    !importing.value &&
    !importedDoc.value,
)

const previewTable = computed<TableResult>(() => ({
  columns: preview.value?.columns.map((column) => column.name) ?? [],
  rows: preview.value?.rows ?? [],
}))

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN')
}

function reset() {
  parseToken += 1
  file.value = null
  step.value = 0
  parsing.value = false
  importing.value = false
  preview.value = null
  imported.value = null
  importedDoc.value = null
  error.value = ''
  duplicate.value = false
}

async function selectFile(next: File) {
  const extension = next.name.split('.').pop()?.toLowerCase() ?? ''
  const supported = [...TABLE_EXTENSIONS, ...DOC_EXTENSIONS]
  if (!supported.includes(extension)) {
    error.value = '仅支持 .xlsx / .xls / .csv 表格，以及 .pdf / .docx / .txt 合同文档。'
    return
  }
  if (next.size > MAX_SIZE) {
    error.value = '文件超过 20 MB，请拆分后再上传。'
    return
  }

  mode.value = DOC_EXTENSIONS.includes(extension) ? 'document' : 'table'
  file.value = next
  preview.value = null
  imported.value = null
  importedDoc.value = null
  error.value = ''
  duplicate.value = false
  parsing.value = true
  step.value = 0

  const token = ++parseToken
  const previewPromise =
    mode.value === 'table'
      ? api
          .previewDataset(next)
          .then((result) => {
            if (token === parseToken) preview.value = result
          })
          .catch((cause) => {
            if (token !== parseToken) return
            error.value = cause instanceof Error ? cause.message : String(cause)
          })
      : Promise.resolve()

  for (let index = 0; index < steps.value.length; index += 1) {
    await sleep(280 + index * 160)
    if (token !== parseToken) return
    step.value = index + 1
  }

  await previewPromise
  if (token === parseToken) parsing.value = false
}

function isDuplicate(cause: unknown): boolean {
  if (cause instanceof ApiError) return cause.status === 409
  return cause instanceof Error && cause.message.includes('已导入为数据集')
}

async function confirmImport(force = false) {
  if (!file.value || importing.value) return

  if (mode.value === 'document') {
    importing.value = true
    error.value = ''
    try {
      importedDoc.value = await docStore.upload(file.value)
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      importing.value = false
    }
    return
  }

  importing.value = true
  error.value = ''
  duplicate.value = false
  try {
    imported.value = await store.upload(file.value, force)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    duplicate.value = !force && isDuplicate(cause)
  } finally {
    importing.value = false
  }
}

function forceImport() {
  void confirmImport(true)
}

async function removeDocument(document: DocumentItem) {
  if (!window.confirm(`确定删除《${document.name}》吗？`)) return
  try {
    await docStore.remove(document.id)
    if (importedDoc.value?.id === document.id) importedDoc.value = null
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

onMounted(() => {
  void docStore.load()
})
</script>

<template>
  <div class="view-stack">
    <div class="view-toolbar">
      <p class="view-note">
        上传采购账单 Excel 自动建表；上传 PDF / Word 合同，系统会抽取条款并建立检索索引，提问时自动引用原文。
      </p>
      <RouterLink to="/datasets" class="btn btn-ghost btn-sm">查看已有数据集</RouterLink>
    </div>

    <div class="ingest-grid">
      <section class="card panel">
        <div class="card-head" style="padding: 0 0 16px">
          <div>
            <h2 class="card-title">上传采购文件</h2>
            <p class="card-sub">
              Excel 自动识别表头并建表；合同文档会切分条款，供 Agent 引用原文。
            </p>
          </div>
        </div>

        <FileDropzone
          accept=".xlsx,.xls,.csv,.pdf,.docx,.txt"
          :disabled="parsing || importing"
          @select="selectFile"
        />

        <div v-if="file" class="file-card">
          <div class="file-icon">{{ fileBadge }}</div>
          <div class="file-meta">
            <p class="file-name">{{ file.name }}</p>
            <p class="file-size">
              {{ fileSize }} ·
              {{
                importing
                  ? mode === 'document'
                    ? '正在建立索引'
                    : '正在写入数据库'
                  : imported || importedDoc
                    ? '已导入'
                    : parsing
                      ? '正在解析'
                      : '等待确认'
              }}
            </p>
          </div>
          <button class="btn btn-ghost btn-sm" type="button" @click="reset">移除</button>
        </div>

        <div v-if="file" class="parse-steps">
          <div
            v-for="(label, index) in steps"
            :key="label"
            class="step"
            :class="{
              active: parsing && index === step,
              done: index < step,
            }"
          >
            <span class="step-index">{{ index + 1 }}</span>
            {{ label }}
          </div>
        </div>

        <p v-if="error" class="inline-error">{{ error }}</p>
      </section>

      <section class="card panel">
        <div v-if="!file" class="empty-state">
          <div class="empty-icon">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M4 5a2 2 0 0 1 2-2h8l6 6v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5Z" />
              <path d="M14 3v6h6" />
              <path d="M8 13h8" />
              <path d="M8 17h5" />
            </svg>
          </div>
          <p class="empty-title">上传后在这里预览</p>
          <p class="empty-desc">
            Excel 会展示识别出的字段、类型和样例行；合同会展示解析与索引状态。
          </p>
        </div>

        <div v-else-if="parsing" class="empty-state">
          <span class="spinner"></span>
          <p class="empty-title">正在解析 {{ file.name }}</p>
          <p class="empty-desc">
            当前步骤：{{ steps[Math.min(step, steps.length - 1)] }}
          </p>
        </div>

        <template v-else-if="mode === 'document'">
          <div class="preview-head">
            <div>
              <h2 class="card-title">合同文档</h2>
              <p class="card-sub">
                抽取文本 → 切分条款 → 中文条款检索索引，提问时会自动召回相关段落。
              </p>
            </div>
            <span class="status-badge">{{ importedDoc ? '已入库' : '解析完成' }}</span>
          </div>

          <div class="doc-summary">
            <div class="file-icon">{{ fileBadge }}</div>
            <div>
              <p class="file-name">{{ file.name }}</p>
              <p class="file-size">
                {{
                  importedDoc
                    ? `已切分为 ${importedDoc.chunkCount} 个片段${
                        importedDoc.pageCount ? ` · ${importedDoc.pageCount} 页` : ''
                      }`
                    : '等待确认后写入文档库'
                }}
              </p>
            </div>
          </div>

          <div v-if="importedDoc" class="success-banner">
            <div>
              <strong>文档已入库</strong>
              <p>《{{ importedDoc.name }}》已建立检索索引，可以直接用自然语言提问合同条款。</p>
            </div>
            <div class="success-actions">
              <button class="btn btn-ghost btn-sm" type="button" @click="reset">继续上传</button>
              <button class="btn btn-primary btn-sm" type="button" @click="router.push('/chat')">
                去问数
              </button>
            </div>
          </div>

          <div v-else-if="canImportDoc" class="preview-actions">
            <button class="btn btn-ghost" type="button" @click="reset">取消</button>
            <button class="btn btn-primary" type="button" @click="confirmImport()">
              开始入库
            </button>
          </div>
        </template>

        <template v-else-if="canPreview">
          <div class="preview-head">
            <div>
              <h2 class="card-title">字段预览</h2>
              <p class="card-sub">
                识别到 {{ preview?.columns.length ?? 0 }} 个字段 · 共
                {{ (preview?.rowCount ?? 0).toLocaleString('zh-CN') }} 行 · Sheet「{{
                  preview?.sheetName ?? '-'
                }}」
              </p>
            </div>
            <span class="status-badge">解析完成</span>
          </div>

          <div v-if="preview?.quality" class="quality-strip">
            <span class="tag">源数据 {{ preview.quality.sourceRows.toLocaleString('zh-CN') }} 行</span>
            <span class="tag">可导入 {{ preview.quality.importedRows.toLocaleString('zh-CN') }} 行</span>
            <span v-if="preview.quality.blankRows" class="tag tag-warn">
              跳过空行 {{ preview.quality.blankRows }}
            </span>
            <span v-if="preview.quality.duplicateRows" class="tag tag-warn">
              重复行 {{ preview.quality.duplicateRows }}
            </span>
            <span v-if="preview.quality.invalidCells" class="tag tag-warn">
              异常单元格 {{ preview.quality.invalidCells }}
            </span>
          </div>

          <ul v-if="preview?.quality?.issues?.length" class="quality-issues">
            <li v-for="issue in preview.quality.issues" :key="issue">{{ issue }}</li>
          </ul>

          <DataTable :result="previewTable" :max-rows="5" max-height="236px" />

          <div v-if="imported" class="success-banner">
            <div>
              <strong>导入成功</strong>
              <p>{{ imported.name }} 已注册，可以直接用自然语言提问。</p>
            </div>
            <div class="success-actions">
              <button class="btn btn-ghost btn-sm" type="button" @click="reset">继续上传</button>
              <button class="btn btn-primary btn-sm" type="button" @click="router.push('/chat')">
                去问数
              </button>
            </div>
          </div>

          <div v-else class="preview-actions">
            <button class="btn btn-ghost" type="button" @click="reset">取消</button>
            <button
              v-if="duplicate"
              class="btn btn-primary"
              type="button"
              :disabled="importing"
              @click="forceImport"
            >
              <span v-if="importing" class="spinner spinner-light"></span>
              {{ importing ? '正在写入数据库…' : '仍然导入副本' }}
            </button>
            <button
              v-else
              class="btn btn-primary"
              type="button"
              :disabled="importing"
              @click="confirmImport()"
            >
              <span v-if="importing" class="spinner spinner-light"></span>
              {{ importing ? '正在写入数据库…' : '确认导入' }}
            </button>
          </div>
        </template>

        <div v-else class="empty-state">
          <p class="empty-title">解析失败</p>
          <p class="empty-desc">{{ error || '请重新选择文件。' }}</p>
        </div>
      </section>
    </div>

    <section class="card panel">
      <div class="card-head" style="padding: 0 0 14px">
        <div>
          <h2 class="card-title">合同文档库</h2>
          <p class="card-sub">
            共 {{ docStore.documents.length }} 份 · {{ docStore.totalChunks }} 个检索片段
          </p>
        </div>
        <button class="btn btn-ghost btn-sm" type="button" @click="docStore.load()">刷新</button>
      </div>

      <div v-if="docStore.loading" class="empty-state compact">
        <span class="spinner"></span>
        <p class="empty-desc">正在加载文档…</p>
      </div>
      <p v-else-if="docStore.error" class="inline-error">{{ docStore.error }}</p>
      <div v-else-if="docStore.documents.length === 0" class="empty-state compact">
        <p class="empty-desc">还没有合同文档，上传 PDF / Word 后会自动出现在这里。</p>
      </div>
      <div v-else class="doc-list">
        <div v-for="document in docStore.documents" :key="document.id" class="doc-item">
          <div class="file-icon">{{ document.docType.toUpperCase() }}</div>
          <div class="doc-meta">
            <p class="file-name">{{ document.name }}</p>
            <p class="file-size">
              {{ document.pageCount ? `${document.pageCount} 页 · ` : ''
              }}{{ document.chunkCount }} 个片段 · {{ formatDate(document.createdAt) }}
            </p>
          </div>
          <button class="btn btn-ghost btn-sm" type="button" @click="removeDocument(document)">
            删除
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
