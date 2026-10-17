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
    const messages: Record<number, string> = {
      401: path === '/auth/login' ? 'Invalid email or password.' : 'Your session has expired. Please sign in again.',
      404: 'This conversation is no longer available.',
      409: 'This conversation changed. Please retry your message.',
      429: 'Too many requests. Please wait a moment and retry.',
      503: 'The answer service is temporarily unavailable. Please retry.',
      504: 'The answer took too long. Please retry.',
    }
    throw new ApiError(response.status, messages[response.status] ?? `Request failed (${response.status}).`)
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
