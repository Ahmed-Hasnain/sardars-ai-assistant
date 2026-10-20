import { useEffect, useState, type FormEvent } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { downloadSource, isFileSourceUrl } from './api'
import { useChatStore, type Message } from './store'
import KnowledgePanel from './KnowledgePanel'

function safeSourceUrl(url: string): string | null {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null
  } catch {
    return null
  }
}

function MessageCard({ message }: { message: Message }) {
  const token = useChatStore((state) => state.token)
  const [sourceError, setSourceError] = useState<string | null>(null)
  const approvedLinks = new Set(message.sources.map((source) => safeSourceUrl(source.url)))
  async function openFile(source: Message['sources'][number]) {
    if (!token) return
    try {
      setSourceError(null)
      await downloadSource(token, source)
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : 'Could not open this source.')
    }
  }
  return (
    <article className={`message ${message.role}`}>
      <div className="message-avatar" aria-hidden="true">{message.role === 'user' ? 'You' : 'S'}</div>
      <div className="message-body">
        <div className="message-author">{message.role === 'user' ? 'You' : 'Sardars Assistant'}</div>
        {message.role === 'assistant' ? (
          <div className="message-text markdown">
            <Markdown remarkPlugins={[remarkGfm]} skipHtml allowedElements={[
              'p', 'br', 'strong', 'em', 'del', 'a', 'h1', 'h2', 'h3', 'h4',
              'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'hr',
              'table', 'thead', 'tbody', 'tr', 'th', 'td',
            ]} components={{ a: ({ href, children }) => {
              const safe = href ? safeSourceUrl(href) : null
              return safe && approvedLinks.has(safe)
                ? <a href={safe} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>
            } }}>{message.text}</Markdown>
          </div>
        ) : <p className="message-text">{message.text}</p>}
        {message.sources.length > 0 && (
          <div className="sources" aria-label="Sources for this answer">
            <div className="sources-heading">Sources</div>
            <div className="source-list">
              {message.sources.map((source) => {
                const href = safeSourceUrl(source.url)
                return isFileSourceUrl(source.url) ? (
                  <button className="source-link" type="button" key={`${source.source_id}-${source.number}`} onClick={() => void openFile(source)}>
                    <span className="source-index">{source.number}</span><span>{source.title}</span><span aria-hidden="true">↓</span>
                  </button>
                ) : href ? (
                  <a className="source-link" key={`${source.source_id}-${source.number}`} href={href} target="_blank" rel="noopener noreferrer">
                    <span className="source-index">{source.number}</span>
                    <span>{source.title}</span>
                    <span aria-hidden="true">↗</span>
                  </a>
                ) : (
                  <span className="source-link" key={`${source.source_id}-${source.number}`}>
                    <span className="source-index">{source.number}</span>
                    <span>{source.title}</span>
                  </span>
                )
              })}
            </div>
            {sourceError && <div className="source-error" role="alert">{sourceError}</div>}
          </div>
        )}
      </div>
    </article>
  )
}

function Login() {
  const signIn = useChatStore((state) => state.signIn)
  const status = useChatStore((state) => state.status)
  const error = useChatStore((state) => state.error)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void signIn(email, password)
  }

  return (
    <main className="login-page">
      <div className="login-brand"><span className="brand-mark">S</span><span>Sardars <strong>AI</strong></span></div>
      <div className="login-card">
        <div className="eyebrow">INTERNAL ASSISTANT</div>
        <h1>Welcome back</h1>
        <p>Sign in with your staff account to ask questions about Sardars and its products.</p>
        <form onSubmit={submit}>
          <label htmlFor="email">Email address</label>
          <input id="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required />
          <label htmlFor="password">Password</label>
          <input id="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="primary-button" type="submit" disabled={status === 'signing-in'}>
            {status === 'signing-in' ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
      <p className="login-footnote">For authorized Sardars team members only.</p>
    </main>
  )
}

const suggestions = [
  'What brands does Sardars offer?',
  'Show me bathroom products',
  'What should I consider when choosing a basin mixer?',
]

function Chat() {
  const user = useChatStore((state) => state.user)
  const token = useChatStore((state) => state.token)
  const messages = useChatStore((state) => state.messages)
  const status = useChatStore((state) => state.status)
  const error = useChatStore((state) => state.error)
  const conversationId = useChatStore((state) => state.conversationId)
  const conversations = useChatStore((state) => state.conversations)
  const historyLoading = useChatStore((state) => state.historyLoading)
  const historyHasMore = useChatStore((state) => state.historyHasMore)
  const historyError = useChatStore((state) => state.historyError)
  const conversationLoading = useChatStore((state) => state.conversationLoading)
  const olderLoading = useChatStore((state) => state.olderLoading)
  const olderCursor = useChatStore((state) => state.olderCursor)
  const historicalNotice = useChatStore((state) => state.historicalNotice)
  const ask = useChatStore((state) => state.ask)
  const loadConversations = useChatStore((state) => state.loadConversations)
  const openConversation = useChatStore((state) => state.openConversation)
  const loadOlderMessages = useChatStore((state) => state.loadOlderMessages)
  const newChat = useChatStore((state) => state.newChat)
  const signOut = useChatStore((state) => state.signOut)
  const [draft, setDraft] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [workspace, setWorkspace] = useState<'assistant' | 'knowledge'>('assistant')

  async function send(value: string) {
    const message = value.trim()
    if (!message) return
    await ask(message)
    if (!useChatStore.getState().error) setDraft('')
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void send(draft)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-top">
          <div className="brand"><span className="brand-mark">S</span><span>Sardars <strong>AI</strong></span></div>
          <button className="new-chat-button" aria-label="New conversation" onClick={() => { newChat(); setDraft(''); setWorkspace('assistant') }} disabled={status === 'sending'}>＋ <span>New conversation</span></button>
          <div className="sidebar-label">WORKSPACE</div>
          <button type="button" className={`sidebar-item ${workspace === 'assistant' ? 'active' : ''}`} onClick={() => setWorkspace('assistant')}><span aria-hidden="true">◇</span> Assistant</button>
          {user?.role === 'admin' && <button type="button" className={`sidebar-item ${workspace === 'knowledge' ? 'active' : ''}`} onClick={() => setWorkspace('knowledge')}><span aria-hidden="true">▣</span> Knowledge sources</button>}
          <section className={`history-section ${historyOpen ? 'open' : ''}`} aria-label="Recent conversations">
            <button className="history-toggle" type="button" onClick={() => setHistoryOpen((open) => !open)} aria-expanded={historyOpen}>Chats ▾</button>
            <div className="history-heading">RECENT CONVERSATIONS</div>
            <div className="history-list">
              {conversations.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  className={`history-item ${conversation.id === conversationId ? 'selected' : ''}`}
                  aria-current={conversation.id === conversationId ? 'page' : undefined}
                  disabled={status === 'sending'}
                  onClick={() => { setHistoryOpen(false); setDraft(''); void openConversation(conversation.id) }}
                >
                  <span className="history-preview">{conversation.preview || 'Conversation'}</span>
                  <span className="history-date">{new Date(conversation.updated_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span>
                </button>
              ))}
              {historyLoading && <div className="history-message" role="status">Loading conversations…</div>}
              {!historyLoading && conversations.length === 0 && !historyError && <div className="history-message">No conversations yet.</div>}
              {historyError && <div className="history-message" role="alert">{historyError} <button type="button" onClick={() => void loadConversations()}>Retry</button></div>}
              {historyHasMore && <button className="history-more" type="button" disabled={historyLoading} onClick={() => void loadConversations(conversations.length)}>Load more</button>}
            </div>
          </section>
        </div>
        <div className="sidebar-bottom">
          <div className="account"><span className="account-avatar">{user?.email.charAt(0).toUpperCase()}</span><span className="account-details"><strong>{user?.email}</strong><small>{user?.role}</small></span></div>
          <button className="signout-button" onClick={() => void signOut()} disabled={status === 'sending'}>Sign out</button>
        </div>
      </aside>

      <main className="chat-main">
        <header className="topbar">
          <div><span className="topbar-title">{workspace === 'knowledge' ? 'Knowledge sources' : 'Assistant'}</span><span className="topbar-subtitle">Internal knowledge &amp; product help</span></div>
          <div className="topbar-status"><span className="status-dot" /> {conversationId ? 'Conversation active' : 'Ready to help'}</div>
        </header>
        {workspace === 'knowledge' && user?.role === 'admin' && token ? <KnowledgePanel token={token} /> : <><div className="sr-only" role="status" aria-live="polite">
          {status === 'sending' ? 'Preparing answer' : messages.at(-1)?.role === 'assistant' ? 'Answer ready' : ''}
        </div>

        <div className="conversation">
          {conversationLoading ? (
            <div className="conversation-loading" role="status"><span className="spinner" /> Opening conversation…</div>
          ) : messages.length === 0 ? (
            <div className="welcome">
              <div className="welcome-icon">S</div>
              <div className="eyebrow">SARDARS AI ASSISTANT</div>
              <h1>How can I help you today?</h1>
              <p>Ask about Sardars, browse products, or explore bathroom ideas. Company answers use information your account is allowed to access.</p>
              <div className="suggestions">
                {suggestions.map((suggestion) => <button key={suggestion} onClick={() => { setDraft(suggestion); void send(suggestion) }}>{suggestion}<span aria-hidden="true">↗</span></button>)}
              </div>
            </div>
          ) : (
            <div className="messages">
              {historicalNotice && <div className="history-notice">{historicalNotice}</div>}
              {olderCursor && <button className="older-button" type="button" onClick={() => void loadOlderMessages()} disabled={olderLoading}>{olderLoading ? 'Loading…' : 'Load older messages'}</button>}
              {messages.map((message) => <MessageCard key={message.id} message={message} />)}
              {status === 'sending' && <div className="thinking" role="status"><span className="spinner" /> Preparing and delivering answer…</div>}
            </div>
          )}
        </div>

        <div className="composer-area">
          {error && <div className="chat-error" role="alert">{error}</div>}
          <form className="composer" onSubmit={submit}>
            <label className="sr-only" htmlFor="message">Message</label>
            <textarea id="message" rows={2} maxLength={2000} placeholder="Ask a question…" value={draft} disabled={status === 'sending' || conversationLoading} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(draft) }
            }} />
            <button className="send-button" type="submit" disabled={!draft.trim() || status === 'sending' || conversationLoading} aria-label="Send message">↑</button>
          </form>
          <p className="composer-note">Company details are shown only when verified against authorized sources. Double-check important decisions.</p>
        </div>
        </>}
      </main>
    </div>
  )
}

export default function App() {
  const token = useChatStore((state) => state.token)
  const status = useChatStore((state) => state.status)
  useEffect(() => { void useChatStore.getState().restoreSession() }, [])
  if (status === 'restoring' || status === 'checking-session') {
    return <main className="login-page" role="status">Restoring your session…</main>
  }
  return token ? <Chat /> : <Login />
}
