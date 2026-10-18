import { afterEach, expect, it, vi } from 'vitest'
import { ApiError, isFileSourceUrl, streamMessage } from './api'

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
