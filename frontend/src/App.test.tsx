import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({ state: {} as Record<string, unknown> }))
vi.mock('./store', () => ({
  useChatStore: (selector: (state: Record<string, unknown>) => unknown) => selector(mocked.state),
}))

import App from './App'

it('shows conversation previews and a warning on reopened history', () => {
  mocked.state = {
    token: 'test-token', status: 'idle',
    user: { id: 1, email: 'staff@example.com', role: 'staff', is_active: true },
    conversationId: 'owned-id', historyLoading: false, historyHasMore: false,
    historyError: null, conversationLoading: false, olderLoading: false, olderCursor: null,
    conversations: [{
      id: 'owned-id', preview: 'Which brands does Sardars offer?',
      created_at: '2026-10-17T10:00:00Z', updated_at: '2026-10-17T10:01:00Z',
      expires_at: '2026-11-16T10:01:00Z',
    }],
    messages: [{ id: '1', role: 'user', text: 'Which brands?', sources: [] }, {
      id: '2', role: 'assistant', text: 'Earlier answer', sources: [],
    }],
    historicalNotice: 'Earlier answers may be stale.',
  }

  const html = renderToStaticMarkup(<App />)

  expect(html).toContain('Which brands does Sardars offer?')
  expect(html).toContain('Earlier answer')
  expect(html).toContain('Earlier answers may be stale.')
  expect(html).not.toContain('Knowledge sources</button>')
})

it('shows the knowledge workspace navigation only to admins', () => {
  mocked.state = {
    token: 'test-token', status: 'idle',
    user: { id: 2, email: 'admin@example.com', role: 'admin', is_active: true },
    conversationId: null, historyLoading: false, historyHasMore: false,
    historyError: null, conversationLoading: false, olderLoading: false, olderCursor: null,
    conversations: [], messages: [], historicalNotice: null,
  }
  expect(renderToStaticMarkup(<App />)).toContain('Knowledge sources</button>')
})

it('renders cited Markdown while blocking raw HTML and unsafe links', () => {
  mocked.state = {
    token: 'test-token', status: 'idle',
    user: { id: 1, email: 'staff@example.com', role: 'staff', is_active: true },
    conversationId: 'owned-id', historyLoading: false, historyHasMore: false,
    historyError: null, conversationLoading: false, olderLoading: false, olderCursor: null,
    conversations: [], historicalNotice: null,
    messages: [{ id: '1', role: 'assistant',
      text: '**Supported** answer.\n\n| Item | Value |\n| --- | --- |\n| Mixer | Brass |\n\n<script>alert(1)</script> [bad](javascript:alert(2)) [unapproved](https://evil.example)',
      sources: [{ number: 1, source_id: 'a', title: 'About', url: 'https://example.com/about', fetched_at: null },
        { number: 2, source_id: 'b', title: 'Profile.pdf', url: '/api/v1/ingestion/files/11111111-1111-1111-1111-111111111111', fetched_at: null },
        { number: 3, source_id: 'web:c', title: 'Web: Python releases', url: 'https://www.python.org/downloads/',
          fetched_at: '2026-10-29T00:00:00Z', origin: 'web' }],
    }],
  }
  const html = renderToStaticMarkup(<App />)
  expect(html).toContain('<strong>Supported</strong>')
  expect(html).toContain('<table>')
  expect(html).not.toContain('<script>')
  expect(html).not.toContain('href="javascript:')
  expect(html).not.toContain('href="https://evil.example')
  expect(html).toContain('href="https://example.com/about"')
  expect(html).toContain('Profile.pdf')
  expect(html).toContain('Web · Python releases')
  expect(html).toContain('searched')
  expect(html).toContain('type="button"')
})
