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
})
