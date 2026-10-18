import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { chromium } from 'playwright-core'

const origin = 'http://127.0.0.1:5174'
const vite = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', '5174', '--strictPort'], { stdio: 'ignore' })

async function ready() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (vite.exitCode !== null) throw new Error('Vite exited before the browser smoke started')
    try { if ((await fetch(origin)).ok) return } catch { /* starting */ }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error('Vite did not start')
}

function json(value, status = 200) {
  return { status, contentType: 'application/json', body: JSON.stringify(value) }
}

async function scenario(browser, viewport) {
  const context = await browser.newContext({ viewport, acceptDownloads: true })
  const page = await context.newPage()
  const id = '11111111-1111-1111-1111-111111111111'
  const source = { number: 1, source_id: 'a'.repeat(64), title: 'Sardars overview', url: 'https://example.com/about', fetched_at: null }
  const file = { number: 2, source_id: 'b'.repeat(64), title: 'source.txt', url: '/api/v1/ingestion/files/22222222-2222-2222-2222-222222222222', fetched_at: null }
  const summary = { id, preview: 'What brands does Sardars offer?', created_at: '2026-10-18T10:00:00Z', updated_at: '2026-10-18T10:01:00Z', expires_at: '2026-11-17T10:01:00Z' }
  let saved = false
  let failNext = true
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/auth/login') return route.fulfill(json({ access_token: 'browser-test-token' }))
    if (path === '/api/v1/auth/me') return route.fulfill(json({ id: 1, email: 'staff@example.com', role: 'staff', is_active: true }))
    if (path === file.url) {
      assert.equal(route.request().headers().authorization, 'Bearer browser-test-token')
      return route.fulfill({ status: 200, contentType: 'text/plain', body: 'Authorized source content' })
    }
    if (path === '/api/v1/conversations') return route.fulfill(json(saved ? [summary] : []))
    if (path === `/api/v1/conversations/${id}`) return route.fulfill(json({
      conversation: summary, historical_notice: 'Earlier answers may be stale.', next_before_message_id: null,
      messages: [{ id: 1, role: 'user', content: summary.preview, sources: [] },
        { id: 2, role: 'assistant', content: '**Sardars** offers listed brands. [1]', sources: [source, file] }],
    }))
    if (path === '/api/v1/chat/stream') {
      if (failNext) { failNext = false; return route.fulfill(json({ detail: 'Unavailable' }, 503)) }
      saved = true
      const answer = '**Sardars** offers listed brands. [1]'
      const reply = { answer, route: 'company', sources: [source, file], conversation_id: id, product_handles: [] }
      const body = `event: start\ndata: ${JSON.stringify({ conversation_id: id })}\n\n` +
        `event: chunk\ndata: ${JSON.stringify({ text: answer })}\n\n` +
        `event: complete\ndata: ${JSON.stringify(reply)}\n\n`
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body })
    }
    throw new Error(`Unexpected API route: ${path}`)
  })

  await page.goto(origin)
  await page.getByLabel('Email address').fill('staff@example.com')
  await page.getByLabel('Password').fill('test-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('heading', { name: 'How can I help you today?' }).waitFor()
  await page.getByRole('textbox', { name: 'Message' }).fill(summary.preview)
  await page.getByRole('button', { name: 'Send message' }).click()
  await page.getByRole('alert').getByText(/temporarily unavailable/i).waitFor()
  assert.equal(await page.getByRole('textbox', { name: 'Message' }).inputValue(), summary.preview)
  await page.getByRole('button', { name: 'Send message' }).click()
  await page.getByRole('link', { name: /Sardars overview/ }).waitFor()
  assert.equal(await page.locator('.markdown strong').textContent(), 'Sardars')
  assert.equal(await page.getByRole('link', { name: /Sardars overview/ }).getAttribute('href'), 'https://example.com/about')
  const downloadWait = page.waitForEvent('download')
  await page.getByRole('button', { name: /source.txt/ }).click()
  assert.equal((await downloadWait).suggestedFilename(), 'source.txt')
  await page.reload()
  await page.getByRole('link', { name: /Sardars overview/ }).waitFor()
  await page.getByRole('button', { name: /New conversation/ }).click()
  if (viewport.width < 600) await page.getByRole('button', { name: /Chats/ }).click()
  await page.locator('.history-list .history-item').filter({ hasText: summary.preview }).click()
  await page.getByText('Earlier answers may be stale.').waitFor()
  await page.getByRole('link', { name: /Sardars overview/ }).waitFor()
  const width = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  assert.ok(width <= 1, `Horizontal overflow at ${viewport.width}px: ${width}px`)
  await page.keyboard.press('Tab')
  const focused = await page.evaluate(() => document.activeElement?.tagName)
  assert.ok(focused && focused !== 'BODY', 'Keyboard focus was lost')
  await context.close()
}

let browser
try {
  await ready()
  browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] })
  await scenario(browser, { width: 1440, height: 900 })
  await scenario(browser, { width: 390, height: 844 })
  console.log('Desktop and mobile browser smoke passed: login, retry, streamed answer, citations, authenticated file download, refresh, history, keyboard focus, layout.')
} finally {
  await browser?.close()
  vite.kill('SIGTERM')
}
