const TOKEN_KEY = 'sardars.session.token'
const CONVERSATION_KEY = 'sardars.session.conversation'

function tabStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage
  } catch {
    return null
  }
}

export function readSessionToken(): string | null {
  try {
    return tabStorage()?.getItem(TOKEN_KEY) ?? null
  } catch {
    return null
  }
}

export function saveSessionToken(token: string): void {
  try {
    tabStorage()?.setItem(TOKEN_KEY, token)
  } catch {
    // The current tab can still use its in-memory session.
  }
}

export function readActiveConversation(): string | null {
  try {
    return tabStorage()?.getItem(CONVERSATION_KEY) ?? null
  } catch {
    return null
  }
}

export function saveActiveConversation(id: string | null): void {
  try {
    const storage = tabStorage()
    if (id) storage?.setItem(CONVERSATION_KEY, id)
    else storage?.removeItem(CONVERSATION_KEY)
  } catch {
    // The current tab can still use the selected in-memory conversation.
  }
}

export function clearStoredSession(): void {
  try {
    const storage = tabStorage()
    storage?.removeItem(TOKEN_KEY)
    storage?.removeItem(CONVERSATION_KEY)
  } catch {
    // A blocked storage area cannot retain a session written by this tab.
  }
}
