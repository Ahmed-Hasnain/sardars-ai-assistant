import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConversationSummary, User } from './api'
import { useChatStore } from './store'

const user: User = { id: 7, email: 'staff@example.com', role: 'staff', is_active: true }

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function memoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() { return values.size },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key) },
    setItem: (key, value) => { values.set(key, value) },
  }
}

function summary(id: string): ConversationSummary {
  return {
    id, preview: `Question for ${id}`,
    created_at: '2026-10-17T10:00:00Z', updated_at: '2026-10-17T10:01:00Z',
    expires_at: '2026-11-16T10:01:00Z',
  }
}

beforeEach(() => {
  vi.unstubAllGlobals()
  vi.stubGlobal('window', { sessionStorage: memoryStorage() })
  useChatStore.setState({
    token: null, user: null, conversationId: null, messages: [], status: 'idle', error: null,
    conversations: [], historyLoading: false, historyHasMore: false, historyError: null,
    conversationLoading: false, olderLoading: false, olderCursor: null, historicalNotice: null,
  })
})

describe('chat session', () => {
  it('shows an invalid-credentials error for a rejected login', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Invalid credentials' }, 401)))

    await useChatStore.getState().signIn('staff@example.com', 'incorrect-password')

    expect(useChatStore.getState().token).toBeNull()
    expect(useChatStore.getState().error).toBe('Invalid email or password.')
    expect(window.sessionStorage.length).toBe(0)
  })

  it('signs in, loads owned conversations and continues with the returned ID', async () => {
    let chatCount = 0
    const fetchMock = vi.fn((path: string, _options: RequestInit) => {
      if (path.endsWith('/auth/login')) return Promise.resolve(json({ access_token: 'test-token' }))
      if (path.endsWith('/auth/me')) return Promise.resolve(json(user))
      if (path.includes('/conversations?')) return Promise.resolve(json([summary('first-id')]))
      if (path.endsWith('/chat')) {
        chatCount += 1
        return Promise.resolve(json({
          answer: chatCount === 1 ? 'First answer' : 'Second answer', route: 'company',
          sources: [], conversation_id: 'first-id', product_handles: [],
        }))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    await useChatStore.getState().signIn('staff@example.com', 'password')
    expect(useChatStore.getState().conversations[0].preview).toBe('Question for first-id')
    expect(window.sessionStorage.getItem('sardars.session.token')).toBe('test-token')

    await useChatStore.getState().ask('What brands?')
    await useChatStore.getState().ask('Tell me more')

    const chatCalls = fetchMock.mock.calls.filter(([path]) => path.endsWith('/chat'))
    expect(JSON.parse(String(chatCalls[0][1].body))).toEqual({ message: 'What brands?' })
    expect(JSON.parse(String(chatCalls[1][1].body))).toEqual({ message: 'Tell me more', conversation_id: 'first-id' })
    expect(useChatStore.getState().messages.map((message) => message.text)).toEqual([
      'What brands?', 'First answer', 'Tell me more', 'Second answer',
    ])
    expect(window.sessionStorage.getItem('sardars.session.conversation')).toBe('first-id')
  })

  it('restores a saved token only after /auth/me and reloads the active conversation', async () => {
    window.sessionStorage.setItem('sardars.session.token', 'saved-token')
    window.sessionStorage.setItem('sardars.session.conversation', 'owned-id')
    useChatStore.setState({ status: 'restoring' })
    const fetchMock = vi.fn((path: string, _options: RequestInit) => {
      if (path.endsWith('/auth/me')) return Promise.resolve(json(user))
      if (path.includes('/conversations?')) return Promise.resolve(json([summary('owned-id')]))
      if (path.includes('/conversations/owned-id?')) return Promise.resolve(json({
        conversation: summary('owned-id'), historical_notice: 'Earlier answers may be stale.',
        next_before_message_id: null,
        messages: [{ id: 1, role: 'user', content: 'Old question' }, { id: 2, role: 'assistant', content: 'Old answer' }],
      }))
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const restoring = useChatStore.getState().restoreSession()
    expect(useChatStore.getState().token).toBeNull()
    expect(useChatStore.getState().status).toBe('checking-session')
    await restoring

    expect(useChatStore.getState().user).toEqual(user)
    expect(useChatStore.getState().conversationId).toBe('owned-id')
    expect(useChatStore.getState().messages.map((message) => message.text)).toEqual(['Old question', 'Old answer'])
    expect(useChatStore.getState().historicalNotice).toBe('Earlier answers may be stale.')
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('Authorization')).toBe('Bearer saved-token')
  })

  it('clears a revoked token and active ID instead of displaying stored chat', async () => {
    window.sessionStorage.setItem('sardars.session.token', 'revoked-token')
    window.sessionStorage.setItem('sardars.session.conversation', 'old-id')
    useChatStore.setState({ status: 'restoring' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Unauthorized' }, 401)))

    await useChatStore.getState().restoreSession()

    expect(useChatStore.getState().token).toBeNull()
    expect(useChatStore.getState().status).toBe('idle')
    expect(useChatStore.getState().conversations).toEqual([])
    expect(window.sessionStorage.length).toBe(0)
  })

  it('loads older messages and more conversation summaries in bounded pages', async () => {
    useChatStore.setState({ token: 'test-token', user })
    const firstPage = Array.from({ length: 20 }, (_, index) => summary(`id-${index}`))
    const fetchMock = vi.fn((path: string) => {
      if (path.includes('offset=0')) return Promise.resolve(json(firstPage))
      if (path.includes('offset=20')) return Promise.resolve(json([summary('id-20')]))
      if (path.includes('before_message_id=5')) return Promise.resolve(json({
        conversation: summary('id-0'), historical_notice: 'Historical answer',
        next_before_message_id: null, messages: [{ id: 3, role: 'user', content: 'Earlier question' }],
      }))
      if (path.includes('/conversations/id-0?')) return Promise.resolve(json({
        conversation: summary('id-0'), historical_notice: 'Historical answer',
        next_before_message_id: 5, messages: [{ id: 5, role: 'assistant', content: 'Latest answer' }],
      }))
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    await useChatStore.getState().loadConversations()
    expect(useChatStore.getState().historyHasMore).toBe(true)
    await useChatStore.getState().loadConversations(20)
    expect(useChatStore.getState().conversations).toHaveLength(21)
    await useChatStore.getState().openConversation('id-0')
    await useChatStore.getState().loadOlderMessages()

    expect(useChatStore.getState().messages.map((message) => message.text)).toEqual(['Earlier question', 'Latest answer'])
    expect(useChatStore.getState().olderCursor).toBeNull()
  })

  it('keeps the current conversation and removes a failed pending turn for retry', async () => {
    useChatStore.setState({ token: 'test-token', user, conversationId: 'existing-id' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Answer timed out' }, 504)))

    await useChatStore.getState().ask('Try this')

    expect(useChatStore.getState().conversationId).toBe('existing-id')
    expect(useChatStore.getState().messages).toEqual([])
    expect(useChatStore.getState().error).toMatch(/too long/i)
    expect(useChatStore.getState().status).toBe('idle')
  })

  it('clears an expired session and its conversation on a chat 401', async () => {
    window.sessionStorage.setItem('sardars.session.token', 'expired-token')
    window.sessionStorage.setItem('sardars.session.conversation', 'existing-id')
    useChatStore.setState({ token: 'expired-token', user, conversationId: 'existing-id' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Unauthorized' }, 401)))

    await useChatStore.getState().ask('Hello')

    expect(useChatStore.getState().token).toBeNull()
    expect(useChatStore.getState().conversationId).toBeNull()
    expect(window.sessionStorage.length).toBe(0)
  })

  it('removes the tab token on sign-out', async () => {
    window.sessionStorage.setItem('sardars.session.token', 'test-token')
    window.sessionStorage.setItem('sardars.session.conversation', 'existing-id')
    useChatStore.setState({ token: 'test-token', user, conversationId: 'existing-id' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))

    await useChatStore.getState().signOut()

    expect(useChatStore.getState().token).toBeNull()
    expect(window.sessionStorage.length).toBe(0)
  })

  it('starts in restoration mode when this tab already has a token', async () => {
    window.sessionStorage.setItem('sardars.session.token', 'saved-token')
    vi.resetModules()

    const freshStore = (await import('./store')).useChatStore

    expect(freshStore.getState().token).toBeNull()
    expect(freshStore.getState().status).toBe('restoring')
  })
})
