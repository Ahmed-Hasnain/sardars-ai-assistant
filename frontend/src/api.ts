export type User = {
  id: number
  email: string
  role: 'admin' | 'staff'
  is_active: boolean
}

export type Source = {
  number: number
  source_id: string
  title: string
  url: string
  fetched_at: string | null
}

export type ChatReply = {
  answer: string
  route: 'general' | 'company' | 'product' | 'product_search' | 'out_of_scope'
  sources: Source[]
  conversation_id: string | null
  product_handles: string[]
}

export type ConversationSummary = {
  id: string
  created_at: string
  updated_at: string
  expires_at: string
  preview: string | null
}

export type HistoryMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
}

export type ConversationPage = {
  conversation: ConversationSummary
  messages: HistoryMessage[]
  next_before_message_id: number | null
  historical_notice: string
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
  }
}

function errorForStatus(status: number, path: string): ApiError {
  const messages: Record<number, string> = {
    401: path === '/auth/login' ? 'Invalid email or password.' : 'Your session has expired. Please sign in again.',
    404: 'This conversation is no longer available.',
    409: 'This conversation changed. Please retry your message.',
    429: 'Too many requests. Please wait a moment and retry.',
    503: 'The answer service is temporarily unavailable. Please retry.',
    504: 'The answer took too long. Please retry.',
  }
  return new ApiError(status, messages[status] ?? `Request failed (${status}).`)
}

async function request<T>(path: string, options: RequestInit, token?: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
  } catch {
    throw new ApiError(0, 'Could not reach the assistant. Check that the API is running.')
  }

  if (!response.ok) {
    throw errorForStatus(response.status, path)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function login(email: string, password: string): Promise<{ token: string; user: User }> {
  const session = await request<{ access_token: string }>('/auth/login', {
    method: 'POST', body: JSON.stringify({ email, password }),
  })
  const user = await request<User>('/auth/me', { method: 'GET' }, session.access_token)
  return { token: session.access_token, user }
}

export function logout(token: string): Promise<void> {
  return request<void>('/auth/logout', { method: 'POST' }, token)
}

export function currentUser(token: string): Promise<User> {
  return request<User>('/auth/me', { method: 'GET' }, token)
}

export function listConversations(token: string, offset = 0): Promise<ConversationSummary[]> {
  return request<ConversationSummary[]>(`/conversations?limit=20&offset=${offset}`, { method: 'GET' }, token)
}

export function getConversation(token: string, id: string, beforeMessageId?: number): Promise<ConversationPage> {
  const params = new URLSearchParams({ limit: '50' })
  if (beforeMessageId !== undefined) params.set('before_message_id', String(beforeMessageId))
  return request<ConversationPage>(`/conversations/${encodeURIComponent(id)}?${params}`, { method: 'GET' }, token)
}

export function sendMessage(token: string, message: string, conversationId: string | null): Promise<ChatReply> {
  return request<ChatReply>('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }),
  }, token)
}

export async function streamMessage(
  token: string, message: string, conversationId: string | null,
  onStart: (id: string | null) => void, onChunk: (text: string) => void,
): Promise<ChatReply> {
  let response: Response
  try {
    response = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }),
    })
  } catch {
    throw new ApiError(0, 'Could not reach the assistant. Check that the API is running.')
  }
  if (!response.ok) throw errorForStatus(response.status, '/chat/stream')
  if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
    throw new ApiError(0, 'The answer stream was unavailable. Please retry.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let complete: ChatReply | null = null
  let received = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n')
      if (buffer.length > 100_000) throw new ApiError(0, 'The answer stream exceeded its limit.')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const kind = frame.match(/^event: ([a-z]+)$/m)?.[1]
        const raw = frame.match(/^data: (.*)$/m)?.[1]
        if (kind && raw) {
          let data: unknown
          try { data = JSON.parse(raw) } catch { throw new ApiError(0, 'The answer stream was invalid.') }
          if (!data || typeof data !== 'object') throw new ApiError(0, 'The answer stream was invalid.')
          const item = data as Record<string, unknown>
          if (kind === 'start') onStart(typeof item.conversation_id === 'string' ? item.conversation_id : null)
          if (kind === 'chunk') {
            if (typeof item.text !== 'string') throw new ApiError(0, 'The answer stream was invalid.')
            received += item.text
            if (received.length > 50_000) throw new ApiError(0, 'The answer stream exceeded its limit.')
            onChunk(item.text)
          }
          if (kind === 'complete') {
            if (typeof item.answer !== 'string' || item.answer !== received || !Array.isArray(item.sources)) {
              throw new ApiError(0, 'The answer stream was invalid.')
            }
            complete = item as ChatReply
          }
        }
        boundary = buffer.indexOf('\n\n')
      }
    }
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(0, 'The connection ended before the answer completed. Open this conversation to check whether it was saved.')
  } finally {
    reader.releaseLock()
  }
  if (!complete) throw new ApiError(0, 'The connection ended before the answer completed. Open this conversation to check whether it was saved.')
  return complete
}

export function isFileSourceUrl(url: string): boolean {
  return /^\/api\/v1\/ingestion\/files\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(url)
}

export async function downloadSource(token: string, source: Source): Promise<void> {
  if (!isFileSourceUrl(source.url)) throw new ApiError(0, 'This source link is invalid.')
  let response: Response
  try {
    response = await fetch(source.url, { headers: { Authorization: `Bearer ${token}` } })
  } catch {
    throw new ApiError(0, 'Could not reach the source file.')
  }
  if (!response.ok) throw errorForStatus(response.status, '/source')
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = source.title.replace(/[\\/]/g, '_').slice(0, 120) || 'source'
    link.click()
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
}

export type IngestionJob = {
  job_id: string
  operation: 'import' | 'remove' | 'crawl'
  status: 'pending' | 'processing' | 'completed' | 'failed'
  parent_job_id: string | null
  attempts: number
  max_attempts: number
  error: string | null
  result: Record<string, unknown> | null
  crawl_progress?: { discovered_pages: number | null; queued_pages: number; pending: number; processing: number; completed: number; failed: number }
  url?: string
}

export type IngestedSource = {
  source_id: string
  title: string | null
  url: string
  source_type: string
  visibility: 'public' | 'staff' | 'admin'
  active: boolean
  index_status: string
  job_id: string | null
}

async function ingestionRequest<T>(token: string, path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/v1/ingestion${path}`, {
      ...options,
      headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        Authorization: `Bearer ${token}`, ...(options.headers ?? {}) },
    })
  } catch {
    throw new ApiError(0, 'Could not reach the ingestion service.')
  }
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail.slice(0, 250)
    } catch { /* Return a safe generic error for invalid server responses. */ }
    throw new ApiError(response.status, detail || `Ingestion request failed (${response.status}).`)
  }
  return response.json() as Promise<T>
}

export function listIngestionJobs(token: string): Promise<IngestionJob[]> {
  return ingestionRequest(token, '/jobs?limit=50')
}

export function getIngestionJob(token: string, id: string): Promise<IngestionJob> {
  return ingestionRequest(token, `/jobs/${encodeURIComponent(id)}`)
}

export function listCrawlPages(token: string, id: string, offset = 0): Promise<IngestionJob[]> {
  return ingestionRequest(token, `/jobs/${encodeURIComponent(id)}/pages?limit=50&offset=${offset}`)
}

export function listIngestedSources(token: string, offset = 0): Promise<IngestedSource[]> {
  return ingestionRequest(token, `/sources?limit=100&offset=${offset}`)
}

export function submitIngestionFile(token: string, file: File, visibility: 'staff' | 'admin', title: string, sourceId?: string): Promise<IngestionJob> {
  const data = new FormData()
  data.set('file', file)
  data.set('visibility', visibility)
  if (title.trim()) data.set('title', title.trim())
  if (sourceId) data.set('source_id', sourceId)
  return ingestionRequest(token, '/files', { method: 'POST', body: data })
}

export function submitIngestionUrl(token: string, url: string, visibility: 'staff' | 'admin'): Promise<IngestionJob> {
  return ingestionRequest(token, '/urls', { method: 'POST', body: JSON.stringify({ url: url.trim(), visibility }) })
}

export function submitSitemap(token: string, url: string, visibility: 'staff' | 'admin', maxPages: number): Promise<IngestionJob> {
  return ingestionRequest(token, '/sitemaps', { method: 'POST', body: JSON.stringify({ url: url.trim(), visibility, max_pages: maxPages }) })
}

export function retryIngestionJob(token: string, id: string): Promise<IngestionJob> {
  return ingestionRequest(token, `/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' })
}

export function removeIngestedSource(token: string, id: string): Promise<IngestionJob> {
  return ingestionRequest(token, `/sources/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function restoreIngestedSource(token: string, id: string): Promise<IngestionJob> {
  return ingestionRequest(token, `/sources/${encodeURIComponent(id)}/restore`, { method: 'POST' })
}
