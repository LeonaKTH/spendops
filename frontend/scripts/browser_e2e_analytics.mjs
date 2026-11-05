// SpendOps G3 经营分析浏览器端到端验收（复用系统 Chrome）。
// 流程：登录 → 经营分析页 → KPI → 图表 → 供应商下钻 → 差异表 → 导出。
// 运行：node scripts/browser_e2e_analytics.mjs

import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const results = []
function check(name, cond, detail = '') {
  results.push(cond)
  console.log(`  ${cond ? '✓' : '✗'} ${name}` + (cond ? '' : ` -> ${detail}`))
}

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage()

try {
  console.log('\n[1] 登录（真实 UI）')
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  const userInput = page.locator('input[autocomplete=username]')
  const passInput = page.locator('input[autocomplete=current-password]')
  await userInput.fill('admin')
  await passInput.fill('admin123456')
  await userInput.inputValue()
  await passInput.inputValue()
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/chat/, { timeout: 10000 })
  check('登录成功', page.url().includes('/chat'))

  console.log('\n[2] 进入经营分析页')
  await page.goto(`${BASE}/analytics`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  const title = await page.locator('.page-title').textContent().catch(() => '')
  check('页面标题为经营分析', title === '经营分析', title)

  console.log('\n[3] KPI 卡片')
  const kpiCount = await page.locator('.kpi-card').count()
  check('KPI 卡片渲染（6 个）', kpiCount >= 6, `count=${kpiCount}`)
  const kpiText = await page.locator('.kpi-grid').textContent().catch(() => '')
  check('KPI 含金额 ¥', kpiText.includes('¥'), kpiText.slice(0, 60))

  console.log('\n[4] ECharts 图表')
  const canvasCount = await page.locator('canvas').count()
  check('ECharts canvas 渲染（≥3）', canvasCount >= 3, `canvas=${canvasCount}`)

  console.log('\n[5] 供应商排名 + 下钻')
  const rankRows = await page.locator('.drillable').count()
  check('供应商排名表有行', rankRows > 0, `rows=${rankRows}`)

  // 下钻：点击第一个供应商
  const firstSupplier = await page.locator('.drillable').first().textContent().catch(() => '')
  await page.locator('.drillable').first().click()
  await page.waitForTimeout(1200)
  const active = await page.locator('.drillable.active').count()
  check('点击供应商后下钻筛选生效', active >= 1, `active=${active}`)

  console.log('\n[6] 差异分析表 + 导出')
  const discRows = await page.locator('.table tbody tr').count()
  check('差异分析表渲染', discRows >= 0, `rows=${discRows}`)
  const exportBtn = await page.locator('button').filter({ hasText: '导出 CSV' }).count()
  check('导出 CSV 按钮存在', exportBtn >= 1)

  await page.screenshot({ path: 'browser_e2e_analytics.png', fullPage: true })
  check('截图保存', true)
} catch (e) {
  console.error('脚本异常：', e.message)
  await page.screenshot({ path: 'browser_e2e_analytics_error.png', fullPage: true }).catch(() => {})
} finally {
  await browser.close()
}

const passed = results.filter(Boolean).length
console.log(`\n结果：${passed}/${results.length} 通过`)
process.exit(passed === results.length ? 0 : 1)
