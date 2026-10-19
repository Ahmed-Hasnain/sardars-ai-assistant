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

async function adminKnowledgeScenario(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  const id = '33333333-3333-3333-3333-333333333333'
  let job = null
  let submittedFile = false
  let submittedSitemap = false
  let submittedRestore = false
  const removedSource = { source_id: 'c'.repeat(64), title: 'About us', url: 'https://sardarandco.com/pages/about-us',
    source_type: 'pages', visibility: 'staff', active: false, index_status: 'removed', job_id: null }
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/auth/login') return route.fulfill(json({ access_token: 'admin-test-token' }))
    if (path === '/api/v1/auth/me') return route.fulfill(json({ id: 2, email: 'admin@example.com', role: 'admin', is_active: true }))
    if (path === '/api/v1/conversations') return route.fulfill(json([]))
    if (path === '/api/v1/ingestion/jobs' && request.method() === 'GET') return route.fulfill(json(job ? [job] : []))
    if (path === '/api/v1/ingestion/sources') return route.fulfill(json([removedSource]))
    if (path === `/api/v1/ingestion/sources/${removedSource.source_id}/restore` && request.method() === 'POST') {
      assert.equal(request.headers().authorization, 'Bearer admin-test-token')
      submittedRestore = true
      job = { job_id: id, operation: 'import', status: 'pending', attempts: 0, max_attempts: 3, error: null }
      return route.fulfill(json(job, 202))
    }
    if (path === '/api/v1/ingestion/files' && request.method() === 'POST') {
      assert.equal(request.headers().authorization, 'Bearer admin-test-token')
      assert.match(request.headers()['content-type'], /^multipart\/form-data;/)
      submittedFile = true
      job = { job_id: id, operation: 'import', status: 'pending', attempts: 0, max_attempts: 3, error: null }
      return route.fulfill(json(job, 202))
    }
    if (path === '/api/v1/ingestion/sitemaps' && request.method() === 'POST') {
      assert.equal(request.headers().authorization, 'Bearer admin-test-token')
      assert.equal(JSON.parse(request.postData()).max_pages, 2)
      submittedSitemap = true
      job = { job_id: id, operation: 'crawl', status: 'completed', attempts: 1, max_attempts: 3, error: null,
        crawl_progress: { discovered_pages: 2, queued_pages: 2, pending: 1, processing: 0, completed: 1, failed: 0 } }
      return route.fulfill(json(job, 202))
    }
    if (path === `/api/v1/ingestion/jobs/${id}/pages`) return route.fulfill(json([{
      job_id: '44444444-4444-4444-4444-444444444444', operation: 'import', status: 'completed',
      url: 'https://sardarandco.com/pages/about-us', attempts: 1, max_attempts: 3, error: null,
    }]))
    if (path === `/api/v1/ingestion/jobs/${id}`) return route.fulfill(json(job))
    throw new Error(`Unexpected admin API route: ${path}`)
  })

  await page.goto(origin)
  await page.getByLabel('Email address').fill('admin@example.com')
  await page.getByLabel('Password').fill('test-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('button', { name: 'Knowledge sources' }).click()
  await page.getByRole('heading', { name: 'Upload a document' }).waitFor()
  await page.locator('#knowledge-file').setInputFiles({ name: 'profile.txt', mimeType: 'text/plain', buffer: Buffer.from('Approved company description.') })
  await page.getByRole('button', { name: 'Upload file' }).click()
  await page.getByText('File submitted.').waitFor()
  assert.equal(submittedFile, true)
  assert.equal(await page.locator('#knowledge-file').inputValue(), '')

  await page.locator('#knowledge-sitemap-limit').fill('2')
  await page.getByRole('button', { name: 'Import sitemap' }).click()
  await page.getByText('Sitemap submitted.').waitFor()
  await page.getByText('Pages: 1 completed, 0 failed, 1 pending').waitFor()
  await page.getByText('https://sardarandco.com/pages/about-us').waitFor()
  assert.equal(submittedSitemap, true)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Restore' }).click()
  await page.getByText('Source restoration submitted.').waitFor()
  assert.equal(submittedRestore, true)
  await context.close()
}

let browser
try {
  await ready()
  browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] })
  await scenario(browser, { width: 1440, height: 900 })
  await scenario(browser, { width: 390, height: 844 })
  await adminKnowledgeScenario(browser)
  console.log('Desktop/mobile chat and admin knowledge smoke passed: login, retry, streamed answer, citations, authenticated file download, refresh, history, file upload, sitemap progress, source restore, keyboard focus and layout.')
} finally {
  await browser?.close()
  vite.kill('SIGTERM')
}
