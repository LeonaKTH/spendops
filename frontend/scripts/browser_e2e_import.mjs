// SpendOps G2 数据导入浏览器端到端验收（复用系统 Chrome）。
// 流程：登录 → 数据导入页 → 上传供应商 CSV（含错误行）→ 预览 → 确认 → Worker 入库 → 错误报告 → 结果。
// 运行：node scripts/browser_e2e_import.mjs

import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const SUFFIX = Date.now().toString().slice(-6)

const results = []
function check(name, cond, detail = '') {
  results.push(cond)
  console.log(`  ${cond ? '✓' : '✗'} ${name}` + (cond ? '' : ` -> ${detail}`))
}

const SUPPLIER_CSV = [
  '供应商编码,供应商名称,联系人',
  `SUP-B-${SUFFIX},浏览器供应商甲,张三`,
  `SUP-B-${SUFFIX}-BAD,,李四`, // 缺名称 -> 字段级错误
].join('\n')

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage()

try {
  console.log('\n[1] 登录（真实 UI 交互）')
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  const userInput = page.locator('input[autocomplete=username]')
  const passInput = page.locator('input[autocomplete=current-password]')
  await userInput.fill('admin')
  await passInput.fill('admin123456')
  // 关键：fill 后读一次 inputValue，让 Vue 完成 v-model 响应式更新，再点击。
  await userInput.inputValue()
  await passInput.inputValue()
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/chat/, { timeout: 10000 })
  check('UI 登录成功并跳转', page.url().includes('/chat'), page.url())

  await page.goto(`${BASE}/imports`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const entered = (await page.locator('.page-title').textContent().catch(() => '')) === '数据导入'
  check('进入数据导入页', entered, page.url())

  console.log('\n[2] 上传供应商 CSV')
  await page.locator('.select-input').selectOption('supplier')
  await page.locator('input[type=file]').setInputFiles({
    name: 'suppliers.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(SUPPLIER_CSV, 'utf-8'),
  })
  await page.waitForTimeout(2500)
  const hasPreview = (await page.locator('.preview-block').count()) > 0
  check('上传后展示解析预览', hasPreview)

  const previewText = await page.locator('.preview-block').textContent().catch(() => '')
  check('预览含校验通过行', previewText.includes('通过'), previewText.slice(0, 80))

  console.log('\n[3] 确认导入')
  await page.locator('button').filter({ hasText: '确认导入' }).first().click()
  await page.waitForTimeout(3000)

  console.log('\n[4] 等待 Worker 处理并查看结果')
  let statusText = ''
  for (let i = 0; i < 15; i++) {
    await page.waitForTimeout(1000)
    statusText = await page.locator('.table').first().textContent().catch(() => '')
    if (statusText.includes('部分失败') || statusText.includes('已完成') || statusText.includes('失败')) break
  }
  check('任务进入终态（部分失败）', statusText.includes('部分失败'), statusText.slice(0, 80))

  console.log('\n[5] 查看错误报告')
  await page.locator('tr').filter({ hasText: '确认导入' }).first().click().catch(() => {})
  const errorText = await page.locator('.error-block').textContent().catch(() => '')
  check('错误报告展示缺失字段错误', errorText.includes('必填字段缺失') || errorText.includes('供应商名称'), errorText.slice(0, 80))

  await page.screenshot({ path: 'browser_e2e_import.png', fullPage: true })
  check('截图保存', true)
} catch (e) {
  console.error('脚本异常：', e.message)
  await page.screenshot({ path: 'browser_e2e_import_error.png', fullPage: true }).catch(() => {})
} finally {
  await browser.close()
}

const passed = results.filter(Boolean).length
console.log(`\n结果：${passed}/${results.length} 通过`)
process.exit(passed === results.length ? 0 : 1)
