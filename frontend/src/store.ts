import { create } from 'zustand'
import {
  ApiError, currentUser, getConversation, listConversations, login, logout, streamMessage,
  type ConversationSummary, type HistoryMessage, type Source, type User,
} from './api'
import {
  clearStoredSession, readActiveConversation, readSessionToken,
  saveActiveConversation, saveSessionToken,
} from './session'

export type Message = {
  id: string
  role: 'user' | 'assistant'
  text: string
  sources: Source[]
}

type Status = 'restoring' | 'checking-session' | 'idle' | 'signing-in' | 'sending'

type ChatStore = {
  token: string | null
  user: User | null
  conversationId: string | null
  messages: Message[]
  status: Status
  error: string | null
  conversations: ConversationSummary[]
  historyLoading: boolean
  historyHasMore: boolean
  historyError: string | null
  conversationLoading: boolean
  olderLoading: boolean
  olderCursor: number | null
  historicalNotice: string | null
  restoreSession: () => Promise<void>
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  loadConversations: (offset?: number) => Promise<void>
  openConversation: (id: string) => Promise<void>
  loadOlderMessages: () => Promise<void>
  newChat: () => void
  ask: (message: string) => Promise<void>
}

let selectionEpoch = 0

function historyMessages(rows: HistoryMessage[]): Message[] {
  return rows.map((row) => ({ id: String(row.id), role: row.role, text: row.content, sources: row.sources ?? [] }))
}

function clearAuth(set: (values: Partial<ChatStore>) => void, message: string | null): void {
  selectionEpoch += 1
  clearStoredSession()
  set({
    token: null, user: null, conversationId: null, messages: [], status: 'idle', error: message,
    conversations: [], historyLoading: false, historyHasMore: false, historyError: null,
    conversationLoading: false, olderLoading: false, olderCursor: null, historicalNotice: null,
  })
}

export const useChatStore = create<ChatStore>((set, get) => ({
  token: null,
  user: null,
  conversationId: null,
  messages: [],
  status: readSessionToken() ? 'restoring' : 'idle',
  error: null,
  conversations: [],
  historyLoading: false,
  historyHasMore: false,
  historyError: null,
  conversationLoading: false,
  olderLoading: false,
  olderCursor: null,
  historicalNotice: null,

  async restoreSession() {
    if (get().status !== 'restoring') return
    const token = readSessionToken()
    if (!token) {
      set({ status: 'idle' })
      return
    }
    set({ status: 'checking-session' })
    try {
      const user = await currentUser(token)
      if (get().status !== 'checking-session') return
      set({ token, user, error: null })
      await get().loadConversations()
      const activeId = readActiveConversation()
      if (activeId && get().token === token) await get().openConversation(activeId)
      if (get().token === token && get().status === 'checking-session') set({ status: 'idle' })
    } catch (error) {
      if (get().status === 'checking-session') {
        if (error instanceof ApiError && error.status === 401) {
          clearAuth(set, error.message)
        } else {
          set({ status: 'idle', error: error instanceof Error ? error.message : 'Could not restore your session.' })
        }
      }
    }
  },

  async signIn(email, password) {
    set({ status: 'signing-in', error: null })
    try {
      const session = await login(email, password)
      selectionEpoch += 1
      saveSessionToken(session.token)
      saveActiveConversation(null)
      set({
        token: session.token, user: session.user, status: 'idle', error: null,
        conversationId: null, messages: [], olderCursor: null, historicalNotice: null,
      })
      await get().loadConversations()
    } catch (error) {
      if (get().status === 'signing-in') {
        set({ status: 'idle', error: error instanceof Error ? error.message : 'Sign-in failed.' })
      }
    }
  },

  async signOut() {
    const token = get().token
    clearAuth(set, null)
    if (token) {
      try {
        await logout(token)
      } catch {
        // The tab state is cleared even when the API cannot revoke the session.
      }
    }
  },

  async loadConversations(offset = 0) {
    const { token, historyLoading } = get()
    if (!token || historyLoading) return
    set({ historyLoading: true, historyError: null })
    try {
      const page = await listConversations(token, offset)
      if (get().token !== token) return
      set((state) => ({
        conversations: offset === 0 ? page : [...state.conversations, ...page],
        historyHasMore: page.length === 20,
        historyLoading: false,
      }))
    } catch (error) {
      if (get().token !== token) return
      if (error instanceof ApiError && error.status === 401) clearAuth(set, error.message)
      else set({ historyLoading: false, historyError: error instanceof Error ? error.message : 'Could not load conversations.' })
    }
  },

  async openConversation(id) {
    const { token, status } = get()
    if (!token || status === 'sending') return
    const epoch = ++selectionEpoch
    set({ conversationLoading: true, error: null })
    try {
      const page = await getConversation(token, id)
      if (get().token !== token || epoch !== selectionEpoch) return
      saveActiveConversation(id)
      set({
        conversationId: id, messages: historyMessages(page.messages),
        olderCursor: page.next_before_message_id, historicalNotice: page.historical_notice,
        conversationLoading: false,
      })
    } catch (error) {
      if (get().token !== token || epoch !== selectionEpoch) return
      if (error instanceof ApiError && error.status === 401) clearAuth(set, error.message)
      else {
        if (error instanceof ApiError && error.status === 404 && readActiveConversation() === id) {
          saveActiveConversation(null)
        }
        set({ conversationLoading: false, error: error instanceof Error ? error.message : 'Could not open conversation.' })
      }
    }
  },

  async loadOlderMessages() {
    const { token, conversationId, olderCursor, olderLoading } = get()
    if (!token || !conversationId || !olderCursor || olderLoading) return
    set({ olderLoading: true, error: null })
    try {
      const page = await getConversation(token, conversationId, olderCursor)
      if (get().token !== token || get().conversationId !== conversationId) return
      set((state) => ({
        messages: [...historyMessages(page.messages), ...state.messages],
        olderCursor: page.next_before_message_id, olderLoading: false,
      }))
    } catch (error) {
      if (get().token !== token || get().conversationId !== conversationId) return
      if (error instanceof ApiError && error.status === 401) clearAuth(set, error.message)
      else set({ olderLoading: false, error: error instanceof Error ? error.message : 'Could not load older messages.' })
    }
  },

  newChat() {
    if (get().status === 'sending') return
    selectionEpoch += 1
    saveActiveConversation(null)
    set({
      conversationId: null, messages: [], error: null, conversationLoading: false,
      olderLoading: false, olderCursor: null, historicalNotice: null,
    })
  },

  async ask(rawMessage) {
    const { token, conversationId, status, conversationLoading } = get()
    const message = rawMessage.trim()
    if (!token || !message || status !== 'idle' || conversationLoading) return

    const userMessage: Message = { id: crypto.randomUUID(), role: 'user', text: message, sources: [] }
    const assistantMessage: Message = { id: crypto.randomUUID(), role: 'assistant', text: '', sources: [] }
    let startedId: string | null = null
    set((state) => ({ status: 'sending', error: null, messages: [...state.messages, userMessage, assistantMessage] }))
    try {
      const reply = await streamMessage(token, message, conversationId, (id) => {
        startedId = id
        if (id && get().token === token) {
          saveActiveConversation(id)
          set({ conversationId: id })
        }
      }, (chunk) => {
        if (get().token !== token) return
        set((state) => ({ messages: state.messages.map((item) => item.id === assistantMessage.id
          ? { ...item, text: item.text + chunk } : item) }))
      })
      if (get().token !== token) return
      const nextId = reply.conversation_id ?? conversationId
      if (nextId) saveActiveConversation(nextId)
      set((state) => ({
        status: 'idle', conversationId: nextId,
        messages: state.messages.map((item) => item.id === assistantMessage.id
          ? { ...item, text: reply.answer, sources: reply.sources } : item),
      }))
      void get().loadConversations()
    } catch (error) {
      if (get().token !== token) return
      if (error instanceof ApiError && error.status === 401) clearAuth(set, error.message)
      else {
        set((state) => ({
          status: 'idle',
          messages: state.messages.filter((item) => item.id !== userMessage.id && item.id !== assistantMessage.id),
          error: error instanceof Error ? error.message : 'Could not send your message.',
        }))
        const recoverId = startedId ?? (error instanceof ApiError && error.status > 0 ? null : conversationId)
        if (recoverId) {
          await get().openConversation(recoverId)
          if (get().token === token && get().conversationId === recoverId && !get().conversationLoading) {
            set({ error: 'The connection was interrupted. This conversation was reloaded; check the latest message before retrying.' })
          }
          void get().loadConversations()
        }
      }
    }
  },
}))
