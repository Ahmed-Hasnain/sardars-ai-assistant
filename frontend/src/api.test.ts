import { afterEach, expect, it, vi } from 'vitest'
import { ApiError, isFileSourceUrl, streamMessage, submitIngestionFile, submitSitemap } from './api'

afterEach(() => vi.unstubAllGlobals())

function chunks(parts: string[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part))
      controller.close()
    },
  })
  return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
}

it('parses SSE frames split across network chunks and returns the checked result', async () => {
  const result = { answer: 'Verified answer.', route: 'company', sources: [], conversation_id: 'owned', product_handles: [] }
  const frames = `event: start\r\ndata: {"conversation_id":"owned"}\r\n\r\n` +
    `event: chunk\r\ndata: {"text":"Verified "}\r\n\r\n` +
    `event: chunk\r\ndata: {"text":"answer."}\r\n\r\n` +
    `event: complete\r\ndata: ${JSON.stringify(result)}\r\n\r\n`
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(chunks([frames.slice(0, 15), frames.slice(15, 42), frames.slice(42)])))
  const starts: Array<string | null> = []
  const pieces: string[] = []
  const reply = await streamMessage('token', 'Question', null, (id) => starts.push(id), (text) => pieces.push(text))
  expect(starts).toEqual(['owned'])
  expect(pieces).toEqual(['Verified ', 'answer.'])
  expect(reply).toEqual(result)
})

it('rejects an interrupted or inconsistent answer stream', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(chunks([
    'event: start\ndata: {"conversation_id":"owned"}\n\n',
    'event: chunk\ndata: {"text":"Partial"}\n\n',
  ])))
  await expect(streamMessage('token', 'Question', null, () => {}, () => {})).rejects.toThrow(/connection ended/i)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(chunks([
    'event: chunk\ndata: {"text":"safe"}\n\n',
    'event: complete\ndata: {"answer":"different","sources":[]}\n\n',
  ])))
  await expect(streamMessage('token', 'Question', null, () => {}, () => {})).rejects.toBeInstanceOf(ApiError)
})

it('accepts only the authenticated local file route for file sources', () => {
  expect(isFileSourceUrl('/api/v1/ingestion/files/11111111-1111-1111-1111-111111111111')).toBe(true)
  expect(isFileSourceUrl('https://evil.example/api/v1/ingestion/files/11111111-1111-1111-1111-111111111111')).toBe(false)
  expect(isFileSourceUrl('/api/v1/ingestion/files/../../secrets')).toBe(false)
})

it('submits a sitemap with the admin token and bounded page count', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ job_id: 'job-1', status: 'pending' }), { status: 202 }))
  vi.stubGlobal('fetch', fetchMock)
  await submitSitemap('admin-token', 'https://sardarandco.com/sitemap.xml', 'staff', 1500)
  const [path, options] = fetchMock.mock.calls[0]
  expect(path).toBe('/api/v1/ingestion/sitemaps')
  expect(options.headers.Authorization).toBe('Bearer admin-token')
  expect(JSON.parse(options.body)).toEqual({ url: 'https://sardarandco.com/sitemap.xml', visibility: 'staff', max_pages: 1500 })
})

it('uploads multipart file without overriding the browser boundary', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ job_id: 'job-2', status: 'pending' }), { status: 202 }))
  vi.stubGlobal('fetch', fetchMock)
  await submitIngestionFile('admin-token', new File(['descriptive facts'], 'profile.txt'), 'admin', 'Profile')
  const [, options] = fetchMock.mock.calls[0]
  expect(options.headers['Content-Type']).toBeUndefined()
  expect(options.body.get('file').name).toBe('profile.txt')
  expect(options.body.get('visibility')).toBe('admin')
})
