// SpendOps G5 受控经营问数浏览器端到端验收（复用系统 Chrome）。
// 流程：登录 → 经营分析页 → AI 面板 → 示例问题 → 结果 → 离线标注。
// 运行：node scripts/browser_e2e_analysis.mjs

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
  await page.waitForTimeout(1200)
  const panelTitle = await page.locator('.ai-title').textContent().catch(() => '')
  check('AI 分析面板渲染', panelTitle.includes('AI 经营分析'), panelTitle)

  console.log('\n[3] 点击示例问题')
  const exampleBtn = page.locator('.ai-example').first()
  const exampleText = await exampleBtn.textContent().catch(() => '')
  await exampleBtn.click()
  await page.waitForTimeout(1500)
  const hasResult = (await page.locator('.ai-result').count()) > 0
  check('返回分析结果', hasResult)

  console.log('\n[4] 结果内容')
  const badges = await page.locator('.ai-badges').textContent().catch(() => '')
  check('包含意图徽章', badges.includes('意图'), badges.slice(0, 40))
  check('包含离线确定性标注', badges.includes('离线确定性'), badges)
  const explanation = await page.locator('.ai-explanation').textContent().catch(() => '')
  check('解释文本非空', explanation.length > 0, explanation.slice(0, 50))
  check('解释含金额/比例/数字', /¥|%|\d/.test(explanation), explanation.slice(0, 60))

  console.log('\n[5] 数据依据可展开')
  await page.locator('.ai-details summary').click()
  await page.waitForTimeout(300)
  const factsVisible = (await page.locator('.ai-facts').count()) > 0
  check('数据依据（原始计算值）可见', factsVisible)

  console.log('\n[6] 手动输入问题')
  const q = '哪些订单存在交付延期？'
  await page.locator('.ai-input').fill(q)
  await page.locator('.ai-input').inputValue()
  await page.locator('.ai-input-row .btn').click()
  await page.waitForTimeout(1500)
  const explanation2 = await page.locator('.ai-explanation').textContent().catch(() => '')
  check('交付延期问题返回结果', explanation2.length > 0 && explanation2.includes('及时'), explanation2.slice(0, 50))

  console.log('\n[7] LLM 模式降级（无 key）')
  await page.locator('input[value=llm]').check()
  await page.locator('.ai-input-row .btn').click()
  await page.waitForTimeout(1500)
  const badges2 = await page.locator('.ai-badges').textContent().catch(() => '')
  check('LLM 模式无 key 降级为离线', badges2.includes('离线确定性'), badges2.slice(0, 60))

  console.log(`\n结果：${results.filter(Boolean).length}/${results.length} 通过`)
  process.exitCode = results.every(Boolean) ? 0 : 1
} catch (e) {
  console.error('E2E 异常:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
