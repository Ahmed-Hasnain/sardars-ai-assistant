import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  getIngestionJob, listCrawlPages, listIngestedSources, listIngestionJobs,
  removeIngestedSource, restoreIngestedSource, retryIngestionJob, submitIngestionFile, submitIngestionUrl, submitSitemap,
  type IngestedSource, type IngestionJob,
} from './api'

type Visibility = 'staff' | 'admin'

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'The request failed.'
}

export default function KnowledgePanel({ token }: { token: string }) {
  const panelRef = useRef<HTMLElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [fileVisibility, setFileVisibility] = useState<Visibility>('staff')
  const [replaceSource, setReplaceSource] = useState<IngestedSource | null>(null)
  const [pageUrl, setPageUrl] = useState('')
  const [pageVisibility, setPageVisibility] = useState<Visibility>('staff')
  const [sitemapUrl, setSitemapUrl] = useState('https://sardarandco.com/sitemap.xml')
  const [sitemapVisibility, setSitemapVisibility] = useState<Visibility>('staff')
  const [maxPages, setMaxPages] = useState(1500)
  const [jobs, setJobs] = useState<IngestionJob[]>([])
  const [sources, setSources] = useState<IngestedSource[]>([])
  const [sourceOffset, setSourceOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<IngestionJob | null>(null)
  const [pages, setPages] = useState<IngestionJob[]>([])
  const [pageOffset, setPageOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async (offset = sourceOffset, currentId = selectedId, crawlOffset = pageOffset) => {
    const [latestJobs, latestSources] = await Promise.all([
      listIngestionJobs(token), listIngestedSources(token, offset),
    ])
    setJobs(latestJobs)
    setSources(latestSources)
    if (currentId) {
      const detail = await getIngestionJob(token, currentId)
      setSelected(detail)
      setPages(detail.operation === 'crawl' ? await listCrawlPages(token, currentId, crawlOffset) : [])
    }
  }, [token, sourceOffset, selectedId, pageOffset])

  useEffect(() => {
    let active = true
    void refresh().catch((reason) => { if (active) setError(message(reason)) })
    const timer = window.setInterval(() => {
      void refresh().catch((reason) => { if (active) setError(message(reason)) })
    }, 4000)
    return () => { active = false; window.clearInterval(timer) }
  }, [refresh])

  async function run(action: () => Promise<IngestionJob>, success: string, afterSuccess?: () => void) {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await action()
      setNotice(`${success} Job ${result.job_id} was accepted.`)
      afterSuccess?.()
      setSelectedId(result.job_id)
      setPageOffset(0)
      setSourceOffset(0)
      await refresh(0, result.job_id, 0)
    } catch (reason) {
      setError(message(reason))
    } finally {
      setBusy(false)
    }
  }

  function uploadFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) { setError('Choose a file first.'); return }
    if (file.size > 5 * 1024 * 1024) { setError('Files must be at most 5 MiB.'); return }
    void run(() => submitIngestionFile(token, file, fileVisibility, title, replaceSource?.source_id),
      replaceSource ? 'Replacement submitted.' : 'File submitted.', () => {
        setReplaceSource(null); setFile(null); setTitle('')
        if (fileInputRef.current) fileInputRef.current.value = ''
      })
  }

  function uploadPage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void run(() => submitIngestionUrl(token, pageUrl, pageVisibility), 'Page submitted.')
  }

  function uploadSitemap(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void run(() => submitSitemap(token, sitemapUrl, sitemapVisibility, maxPages), 'Sitemap submitted.')
  }

  function selectJob(id: string) {
    setSelectedId(id)
    setPageOffset(0)
    setSelected(null)
    setPages([])
  }

  async function remove(source: IngestedSource) {
    if (!window.confirm(`Remove “${source.title || source.url}” from retrieval?`)) return
    await run(() => removeIngestedSource(token, source.source_id), 'Source removal submitted.')
  }

  async function restore(source: IngestedSource) {
    if (!window.confirm(`Restore “${source.title || source.url}” by fetching and indexing it again?`)) return
    await run(() => restoreIngestedSource(token, source.source_id), 'Source restoration submitted.')
  }

  return (
    <section className="knowledge-panel" aria-label="Knowledge ingestion" ref={panelRef}>
      <div className="knowledge-heading"><div className="eyebrow">ADMIN WORKSPACE</div><h1>Knowledge sources</h1>
        <p>Submit company documents and website pages. The worker processes each job in the background; sources become available to answers only after indexing succeeds.</p></div>
      {error && <div className="form-error" role="alert">{error}</div>}
      {notice && <div className="knowledge-notice" role="status">{notice}</div>}
      <div className="knowledge-cards">
        <form className="knowledge-card" onSubmit={uploadFile}>
          <h2>{replaceSource ? 'Replace a document' : 'Upload a document'}</h2><p>Text PDF, UTF-8 TXT or Markdown; up to 5 MiB. Scanned PDFs need OCR and are not supported yet.</p>
          {replaceSource && <p>Replacing “{replaceSource.title || replaceSource.url}” under the same source ID. <button type="button" onClick={() => setReplaceSource(null)}>Cancel replacement</button></p>}
          <label htmlFor="knowledge-file">File</label><input id="knowledge-file" ref={fileInputRef} type="file" accept=".pdf,.txt,.md" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required />
          <label htmlFor="knowledge-title">Title (optional)</label><input id="knowledge-title" value={title} maxLength={500} onChange={(event) => setTitle(event.target.value)} />
          <label htmlFor="knowledge-file-visibility">Visible to</label><select id="knowledge-file-visibility" value={fileVisibility} onChange={(event) => setFileVisibility(event.target.value as Visibility)}>
            <option value="staff">Staff and admins</option><option value="admin">Admins only</option></select>
          <button type="submit" disabled={busy}>{replaceSource ? 'Replace file' : 'Upload file'}</button>
        </form>
        <form className="knowledge-card" onSubmit={uploadPage}>
          <h2>Add a website page</h2><p>One direct HTTPS page on an allowed host. The worker checks robots rules and extracts descriptive text. To re-add a removed page, use Restore in Registered sources.</p>
          <label htmlFor="knowledge-page-url">Page URL</label><input id="knowledge-page-url" type="url" value={pageUrl} placeholder="https://sardarandco.com/pages/about-us" onChange={(event) => setPageUrl(event.target.value)} required />
          <label htmlFor="knowledge-page-visibility">Visible to</label><select id="knowledge-page-visibility" value={pageVisibility} onChange={(event) => setPageVisibility(event.target.value as Visibility)}>
            <option value="staff">Staff and admins</option><option value="admin">Admins only</option></select>
          <button type="submit" disabled={busy}>Add page</button>
        </form>
        <form className="knowledge-card" onSubmit={uploadSitemap}>
          <h2>Import a sitemap</h2><p>Discover eligible pages and queue each as a separate worker job. Pages with no usable text will show as failed or skipped.</p>
          <label htmlFor="knowledge-sitemap-url">Sitemap XML URL</label><input id="knowledge-sitemap-url" type="url" value={sitemapUrl} onChange={(event) => setSitemapUrl(event.target.value)} required />
          <label htmlFor="knowledge-sitemap-limit">Maximum eligible pages</label><input id="knowledge-sitemap-limit" type="number" min={1} max={1500} value={maxPages} onChange={(event) => setMaxPages(Number(event.target.value))} required />
          <label htmlFor="knowledge-sitemap-visibility">Visible to</label><select id="knowledge-sitemap-visibility" value={sitemapVisibility} onChange={(event) => setSitemapVisibility(event.target.value as Visibility)}>
            <option value="staff">Staff and admins</option><option value="admin">Admins only</option></select>
          <button type="submit" disabled={busy}>Import sitemap</button>
        </form>
      </div>
      <div className="knowledge-grid">
        <section className="knowledge-list"><div className="knowledge-section-heading"><h2>Recent jobs</h2><button onClick={() => void refresh().catch((reason) => setError(message(reason)))}>Refresh</button></div>
          {jobs.length === 0 && <p>No ingestion jobs yet.</p>}
          {jobs.map((job) => <button type="button" key={job.job_id} className={`knowledge-job ${selectedId === job.job_id ? 'selected' : ''}`} onClick={() => selectJob(job.job_id)}>
            <strong>{job.operation === 'crawl' ? 'Sitemap' : job.operation === 'remove' ? 'Remove source' : 'Import source'}</strong><span>{job.status}</span><small>{job.job_id}</small>
          </button>)}
          {selected && <div className="knowledge-job-detail"><h3>Job detail</h3><p>Status: {selected.status} · attempt {selected.attempts}/{selected.max_attempts}</p>
            {selected.error && <p role="alert">{selected.error}</p>}
            {selected.crawl_progress && <p>Pages: {selected.crawl_progress.completed} completed, {selected.crawl_progress.failed} failed, {selected.crawl_progress.pending} pending, {selected.crawl_progress.processing} processing of {selected.crawl_progress.discovered_pages ?? 'unknown'} discovered.</p>}
            {selected.status === 'failed' && selected.attempts < selected.max_attempts && <button disabled={busy} onClick={() => void run(() => retryIngestionJob(token, selected.job_id), 'Retry submitted.')}>Retry job</button>}
            {selected.operation === 'crawl' && <div className="knowledge-pages"><h4>Page jobs</h4>{pages.map((page) => <div key={page.job_id} className="knowledge-page"><span>{page.url}</span><strong>{page.status}</strong>{page.error && <small>{page.error}</small>}{page.status === 'failed' && page.attempts < page.max_attempts && <button disabled={busy} onClick={() => void run(() => retryIngestionJob(token, page.job_id), 'Page retry submitted.')}>Retry</button>}</div>)}
              {pageOffset > 0 && <button onClick={() => setPageOffset(Math.max(0, pageOffset - 50))}>Previous pages</button>}
              {pages.length === 50 && <button onClick={() => setPageOffset(pageOffset + 50)}>Next pages</button>}
            </div>}
          </div>}
        </section>
        <section className="knowledge-list"><div className="knowledge-section-heading"><h2>Registered sources</h2></div>
          {sources.length === 0 && <p>No sources indexed yet.</p>}
          {sources.map((source) => <div key={source.source_id} className="knowledge-source"><div><strong>{source.title || source.url}</strong><small>{source.source_type} · {source.visibility} · {source.index_status}</small></div>
            {source.active && source.url.startsWith('/api/v1/ingestion/files/') && source.visibility !== 'public' && <button type="button" disabled={busy} onClick={() => { setReplaceSource(source); setFileVisibility(source.visibility as Visibility); panelRef.current?.scrollTo({ top: 0, behavior: 'smooth' }); fileInputRef.current?.focus() }}>Replace</button>}
            {!source.active && source.url.startsWith('https://') && ['removed', 'failed'].includes(source.index_status) && <button type="button" disabled={busy} onClick={() => void restore(source)}>Restore</button>}
            {source.active && <button type="button" disabled={busy} onClick={() => void remove(source)}>Remove</button>}
          </div>)}
          {sourceOffset > 0 && <button onClick={() => setSourceOffset(Math.max(0, sourceOffset - 100))}>Previous sources</button>}
          {sources.length === 100 && <button onClick={() => setSourceOffset(sourceOffset + 100)}>More sources</button>}
        </section>
      </div>
    </section>
  )
}
