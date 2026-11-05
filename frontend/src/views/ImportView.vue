<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api, USING_MOCK } from '../api'
import { ApiError } from '../api/errors'
import type { ImportTask, ImportTaskType, ImportErrorItem } from '../api/types'

const TYPE_OPTIONS: { value: ImportTaskType; label: string }[] = [
  { value: 'supplier', label: '供应商基础信息' },
  { value: 'purchase_order', label: '采购订单及明细' },
  { value: 'goods_receipt', label: '收货记录及明细' },
  { value: 'purchase_invoice', label: '采购发票及明细' },
]

const STATUS_LABEL: Record<string, string> = {
  uploaded: '已上传',
  awaiting_confirm: '待确认',
  importing: '导入中',
  completed: '已完成',
  partial_failed: '部分失败',
  failed: '失败',
  cancelled: '已取消',
}

const ERROR_LABEL: Record<string, string> = {
  file_format: '文件格式错误',
  missing_required: '必填字段缺失',
  invalid_format: '格式错误',
  supplier_not_found: '供应商不存在',
  order_not_found: '订单不存在',
  order_line_not_found: '订单明细缺失',
  duplicate_business_key: '重复业务单号',
  invalid_quantity: '非法收货数量',
  invalid_invoice_quantity: '非法开票数量',
  business_conflict: '业务状态冲突',
}

const tasks = ref<ImportTask[]>([])
const selectedId = ref<string | null>(null)
const loading = ref(false)
const uploading = ref(false)
const uploadError = ref('')
const uploadType = ref<ImportTaskType>('supplier')
const errors = ref<ImportErrorItem[]>([])
const errorsTotal = ref(0)
const errorsLoading = ref(false)
const errorsTaskId = ref<string | null>(null)

let pollTimer: ReturnType<typeof setInterval> | null = null

const selected = computed(() => tasks.value.find((t) => t.id === selectedId.value) ?? null)

async function loadTasks() {
  loading.value = true
  try {
    tasks.value = await api.listImports()
  } catch (e) {
    if (e instanceof ApiError) uploadError.value = e.message
  } finally {
    loading.value = false
  }
}

async function handleUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploadError.value = ''
  uploading.value = true
  try {
    const task = await api.uploadImport(file, uploadType.value)
    // 直接写入列表（保留 upload 返回的 preview），避免重新拉取丢失预览。
    tasks.value = [task, ...tasks.value.filter((t) => t.id !== task.id)]
    selectedId.value = task.id
    await loadErrors(task.id)
  } catch (e) {
    uploadError.value = e instanceof ApiError ? e.message : '上传失败'
  } finally {
    uploading.value = false
    input.value = ''
  }
}

async function loadErrors(taskId: string) {
  errorsLoading.value = true
  errorsTaskId.value = taskId
  try {
    const result = await api.getImportErrors(taskId, 200, 0)
    errors.value = result.errors
    errorsTotal.value = result.total
  } catch {
    errors.value = []
    errorsTotal.value = 0
  } finally {
    errorsLoading.value = false
  }
}

async function handleConfirm(task: ImportTask) {
  uploadError.value = ''
  try {
    await api.confirmImport(task.id)
    await loadTasks()
    startPolling()
  } catch (e) {
    uploadError.value = e instanceof ApiError ? e.message : '确认失败'
  }
}

async function handleCancel(task: ImportTask) {
  uploadError.value = ''
  try {
    await api.cancelImport(task.id)
    await loadTasks()
  } catch (e) {
    uploadError.value = e instanceof ApiError ? e.message : '取消失败'
  }
}

function selectTask(task: ImportTask) {
  selectedId.value = task.id
  if (task.status !== 'awaiting_confirm' || task.failedRows > 0) {
    loadErrors(task.id)
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    const hasImporting = tasks.value.some((t) => t.status === 'importing')
    if (hasImporting) {
      await loadTasks()
      if (selected.value && selected.value.status !== 'importing') {
        await loadErrors(selected.value.id)
      }
    } else {
      stopPolling()
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function statusClass(status: string): string {
  if (status === 'completed') return 'status-ok'
  if (status === 'partial_failed' || status === 'failed') return 'status-err'
  if (status === 'importing') return 'status-run'
  return ''
}

onMounted(() => {
  loadTasks()
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <main class="app-main">
    <header class="page-head">
      <div>
        <h1 class="page-title">数据导入</h1>
        <p class="page-sub">CSV / Excel 批量接入供应商、订单、收货与发票，异步校验入库</p>
      </div>
      <span v-if="USING_MOCK" class="mock-badge">Mock 模式</span>
    </header>

    <!-- 上传区 -->
    <section class="card">
      <h2 class="card-title">上传采购数据文件</h2>
      <div class="upload-row">
        <select v-model="uploadType" class="select-input">
          <option v-for="opt in TYPE_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
        <label class="btn btn-primary" :class="{ disabled: uploading }">
          {{ uploading ? '上传中…' : '选择文件并上传' }}
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            :disabled="uploading"
            @change="handleUpload"
          />
        </label>
        <span class="hint">支持 .csv / .xlsx / .xls，中文列名自动映射</span>
      </div>
      <p v-if="uploadError" class="inline-error">{{ uploadError }}</p>
    </section>

    <!-- 任务列表 -->
    <section class="card">
      <h2 class="card-title">导入任务</h2>
      <div v-if="loading" class="empty-state">加载中…</div>
      <div v-else-if="tasks.length === 0" class="empty-state">
        <p class="empty-title">暂无导入任务</p>
        <p class="empty-desc">上传一个采购数据文件开始</p>
      </div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>类型</th>
              <th>文件</th>
              <th>状态</th>
              <th>进度</th>
              <th>成功 / 失败</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="task in tasks"
              :key="task.id"
              :class="{ selected: task.id === selectedId }"
              @click="selectTask(task)"
            >
              <td>{{ TYPE_OPTIONS.find((o) => o.value === task.taskType)?.label ?? task.taskType }}</td>
              <td class="mono">{{ task.originalName }}</td>
              <td><span class="chip" :class="statusClass(task.status)">{{ STATUS_LABEL[task.status] ?? task.status }}</span></td>
              <td>{{ task.processedRows }} / {{ task.totalRows }}</td>
              <td>{{ task.successRows }} / {{ task.failedRows }}</td>
              <td>{{ fmtTime(task.createdAt) }}</td>
              <td>
                <div class="actions">
                  <button
                    v-if="task.status === 'awaiting_confirm'"
                    class="btn btn-small btn-primary"
                    type="button"
                    @click.stop="handleConfirm(task)"
                  >
                    确认导入
                  </button>
                  <button
                    v-if="['uploaded', 'awaiting_confirm', 'importing'].includes(task.status)"
                    class="btn btn-small"
                    type="button"
                    @click.stop="handleCancel(task)"
                  >
                    取消
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 任务详情 + 预览 + 错误报告 -->
    <section v-if="selected" class="card">
      <h2 class="card-title">任务详情</h2>
      <div class="detail-grid">
        <div><span class="label">文件</span><span>{{ selected.originalName }}</span></div>
        <div><span class="label">状态</span><span>{{ STATUS_LABEL[selected.status] ?? selected.status }}</span></div>
        <div><span class="label">总行数</span><span>{{ selected.totalRows }}</span></div>
        <div><span class="label">成功</span><span>{{ selected.successRows }}</span></div>
        <div><span class="label">失败</span><span>{{ selected.failedRows }}</span></div>
        <div><span class="label">文件指纹</span><span class="mono">{{ selected.fileHash?.slice(0, 16) }}…</span></div>
      </div>

      <!-- 预览 -->
      <div v-if="selected.preview?.length" class="preview-block">
        <h3 class="sub-title">解析预览（前 {{ selected.preview.length }} 行）</h3>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>行号</th>
                <th>原始数据</th>
                <th>校验</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in selected.preview" :key="row.rowNumber">
                <td>{{ row.rowNumber }}</td>
                <td class="mono small">{{ JSON.stringify(row.raw) }}</td>
                <td>
                  <span v-if="row.status === 'valid'" class="chip status-ok">通过</span>
                  <span v-else class="chip status-err">{{ ERROR_LABEL[row.errorType ?? ''] ?? row.errorType }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 错误报告 -->
      <div v-if="errorsTotal > 0" class="error-block">
        <h3 class="sub-title">错误报告（共 {{ errorsTotal }} 条）</h3>
        <div v-if="errorsLoading" class="empty-state">加载中…</div>
        <div v-else class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>行号</th>
                <th>字段</th>
                <th>错误类型</th>
                <th>说明</th>
                <th>修复建议</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(err, i) in errors" :key="i">
                <td>{{ err.rowNumber }}</td>
                <td class="mono">{{ err.field ?? '—' }}</td>
                <td><span class="chip status-err">{{ ERROR_LABEL[err.errorType] ?? err.errorType }}</span></td>
                <td>{{ err.message ?? '—' }}</td>
                <td class="small">{{ err.suggestion }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.upload-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.upload-row input[type='file'] {
  display: none;
}
.hint {
  font-size: 13px;
  color: var(--muted, #888);
}
.card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  padding: 16px 18px;
  margin-bottom: 16px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 12px;
}
.sub-title {
  font-size: 13px;
  font-weight: 600;
  margin: 16px 0 8px;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px;
}
.detail-grid .label {
  display: block;
  font-size: 12px;
  color: var(--muted, #888);
  margin-bottom: 2px;
}
.table-wrap {
  overflow-x: auto;
}
.selected {
  background: var(--bg-hover, #f3f4f6);
}
.actions {
  display: flex;
  gap: 6px;
}
.chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  background: var(--bg-hover, #f3f4f6);
}
.status-ok {
  background: #e8f5e9;
  color: #1b7f3b;
}
.status-err {
  background: #fdecea;
  color: #c0392b;
}
.status-run {
  background: #e3f2fd;
  color: #1565c0;
}
.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.small {
  font-size: 12px;
  color: var(--muted, #888);
}
.inline-error {
  color: #c0392b;
  font-size: 13px;
  margin: 10px 0 0;
}
.mock-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #fff3cd;
  color: #856404;
}
.empty-state {
  padding: 24px;
  text-align: center;
  color: var(--muted, #888);
}
.empty-title {
  margin: 0;
  font-weight: 600;
}
.empty-desc {
  margin: 4px 0 0;
  font-size: 13px;
}
</style>
