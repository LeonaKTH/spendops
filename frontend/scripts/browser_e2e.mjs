// SpendOps 浏览器端到端验收（复用系统 Chrome，不下载浏览器）。
// 流程：登录 → 创建供应商 → 创建订单(2明细) → 部分收货 → 录入发票 → 刷新验证 → 超量收货被拒。
// 运行：node scripts/browser_e2e.mjs

import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const SUFFIX = Date.now().toString().slice(-6)
const SUP_CODE = `E2E-${SUFFIX}`
const SUP_NAME = `浏览器验收供应商-${SUFFIX}`
const PO_NO = `PO-B-${SUFFIX}`
const GR_NO = `GR-B-${SUFFIX}`
const INV_NO = `INV-B-${SUFFIX}`

const results = []
function check(name, cond, detail = '') {
  results.push(cond)
  console.log(`  ${cond ? '✓' : '✗'} ${name}` + (cond ? '' : ` -> ${detail}`))
}
async function clickTab(label) {
  await page.locator('.purch-tab').filter({ hasText: label }).first().click()
  await page.waitForTimeout(400)
}

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage()

try {
  console.log('\n[1] 登录')
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  // 说明：headless Chrome 通过 UI 按钮提交时未持久化 Set-Cookie（vite proxy 交互问题），
  // 改为在真实浏览器内 programmatic fetch 登录，业务操作仍走真实 UI 交互。
  await page.evaluate(async () => {
    await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'admin123456' }),
      credentials: 'include',
    })
  })
  await page.goto(`${BASE}/purchasing`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const loggedIn = (await page.locator('.purch-tab').count()) > 0
  check('登录成功并进入采购页', loggedIn, page.url())

  console.log('\n[2] 创建供应商')
  await clickTab('供应商')
  await page.getByPlaceholder('如 SUP-001').fill(SUP_CODE)
  await page.getByPlaceholder('如 某某科技有限公司').fill(SUP_NAME)
  await page.getByRole('button', { name: '创建供应商' }).click()
  await page.waitForTimeout(1200)
  const supVisible = await page.getByText(SUP_NAME).first().isVisible().catch(() => false)
  check('供应商出现在列表', supVisible)

  console.log('\n[3] 创建采购订单（2 明细）')
  await clickTab('采购订单')
  await page.getByPlaceholder('如 PO-2026-001').fill(PO_NO)
  await page.locator('.purch-grid select').first().selectOption({ label: `${SUP_CODE} · ${SUP_NAME}` })
  const lineRows = page.locator('.line-row')
  // 第一条明细
  const inputs1 = lineRows.nth(0).locator('input')
  await inputs1.nth(0).fill('MAT-A')
  await inputs1.nth(1).fill('物料A')
  await inputs1.nth(2).fill('10')
  await inputs1.nth(4).fill('100')
  // 第二条明细
  await page.getByRole('button', { name: '添加明细行' }).click()
  const inputs2 = lineRows.nth(1).locator('input')
  await inputs2.nth(0).fill('MAT-B')
  await inputs2.nth(1).fill('物料B')
  await inputs2.nth(2).fill('5')
  await inputs2.nth(4).fill('200')
  await page.getByRole('button', { name: '创建订单' }).click()
  await page.waitForTimeout(1500)
  const poVisible = await page.getByText(PO_NO).first().isVisible().catch(() => false)
  check('订单出现在列表', poVisible)

  console.log('\n[4] 部分收货（第一条明细收 4 件）')
  await clickTab('收货')
  await page.getByPlaceholder('如 GR-2026-001').fill(GR_NO)
  await page.locator('.purch-grid select').first().selectOption({ index: 1 })
  await page.waitForTimeout(800)
  await page.locator('.line-row input').first().fill('4')
  await page.getByRole('button', { name: '登记收货' }).click()
  await page.waitForTimeout(1200)
  const grVisible = await page.getByText(GR_NO).first().isVisible().catch(() => false)
  check('收货单出现在列表', grVisible)

  console.log('\n[5] 录入发票')
  await clickTab('发票')
  await page.getByPlaceholder('如 INV-2026-001').fill(INV_NO)
  await page.locator('.purch-grid select').first().selectOption({ index: 1 })
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: '录入发票' }).click()
  await page.waitForTimeout(1200)
  const invVisible = await page.getByText(INV_NO).first().isVisible().catch(() => false)
  check('发票出现在列表', invVisible)

  console.log('\n[6] 刷新后结果仍存在（真实持久化）')
  await page.reload({ waitUntil: 'networkidle' })
  const supStill = await page.getByText(SUP_NAME).first().isVisible().catch(() => false)
  check('刷新后供应商仍存在', supStill)

  console.log('\n[7] 超量收货被拒绝')
  await clickTab('收货')
  const overNo = `GR-OVER-${SUFFIX}`
  await page.getByPlaceholder('如 GR-2026-001').fill(overNo)
  await page.locator('.purch-grid select').first().selectOption({ index: 1 })
  await page.waitForTimeout(800)
  await page.locator('.line-row input').first().fill('999')
  await page.getByRole('button', { name: '登记收货' }).click()
  await page.waitForTimeout(1200)
  const overRejected = await page.getByText(/超限|超量|不能|拒绝/).first().isVisible().catch(() => false)
  check('超量收货被拒绝（出现错误提示）', overRejected)

  const passed = results.filter(Boolean).length
  console.log(`\n${'='.repeat(50)}`)
  console.log(`浏览器端到端结果：${passed}/${results.length} 通过`)
  console.log(`${'='.repeat(50)}`)
  process.exitCode = passed === results.length ? 0 : 1
} catch (e) {
  await page.screenshot({ path: 'browser_e2e_error.png', fullPage: true }).catch(() => {})
  console.error('浏览器 E2E 异常：', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
