"""Admin sitemap discovery, durable page fan-out and safe progress."""

import httpx
import pytest
from sqlalchemy import select

from app.db.models import IngestionJob, SourceRegistration, User
from app.ingestion.documents import valid_sitemap_url, valid_web_url
from app.ingestion.extract_worker import ExtractionFailure, sitemap_urls
from app.ingestion.worker import process_one
from app.schemas.ingestion import SitemapSubmission
from test_ingestion_api import runtime


INDEX = b'''<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://sardarandco.com/child.xml</loc></sitemap></sitemapindex>'''
PAGES = b'''<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://sardarandco.com/pages/about-us</loc></url><url><loc>https://sardarandco.com/blogs/news/bathroom-guide</loc></url><url><loc>https://other.test/private</loc></url><url><loc>https://sardarandco.com/cart</loc></url></urlset>'''


def test_bounded_sitemap_discovery_filters_off_host_and_non_descriptive(monkeypatch):
    monkeypatch.setattr('app.ingestion.extract_worker.public_addresses', lambda _host: ['93.184.215.14'])

    def fetch(_host, _address, path, _limit, **_options):
        return {'/robots.txt': b'User-agent: *\nAllow: /', '/sitemap.xml': INDEX, '/child.xml': PAGES}[path]

    monkeypatch.setattr('app.ingestion.extract_worker.fetch', fetch)
    result = sitemap_urls('https://sardarandco.com/sitemap.xml', ['sardarandco.com'], 2)
    assert result['urls'] == ['https://sardarandco.com/pages/about-us', 'https://sardarandco.com/blogs/news/bathroom-guide']
    assert result['skipped_urls'] == 2 and result['xml_files'] == 2
    with pytest.raises(ExtractionFailure, match='page limit'):
        sitemap_urls('https://sardarandco.com/sitemap.xml', ['sardarandco.com'], 1)


def test_sitemap_rejects_entities_and_off_host_xml(monkeypatch):
    monkeypatch.setattr('app.ingestion.extract_worker.public_addresses', lambda _host: ['93.184.215.14'])
    monkeypatch.setattr('app.ingestion.extract_worker.fetch', lambda *_args, **_kwargs: b'User-agent: *\nAllow: /' if _args[2] == '/robots.txt' else b'<!DOCTYPE foo><urlset/>')
    with pytest.raises(ExtractionFailure, match='forbidden entities'):
        sitemap_urls('https://sardarandco.com/sitemap.xml', ['sardarandco.com'], 10)


def test_sitemap_follows_same_host_numeric_range_and_keeps_query_on_fetch(monkeypatch):
    child = 'https://sardarandco.com/sitemap_pages_1.xml?from=89310855233&to=116980482113'
    index = ('<?xml version="1.0"?><sitemapindex><sitemap><loc>' + child.replace('&', '&amp;')
             + '</loc></sitemap></sitemapindex>').encode()
    requested = []
    monkeypatch.setattr('app.ingestion.extract_worker.public_addresses', lambda _host: ['93.184.215.14'])

    def fetch(_host, _address, path, _limit, **_options):
        requested.append(path)
        return {'/robots.txt': b'User-agent: *\nAllow: /', '/sitemap.xml': index,
                '/sitemap_pages_1.xml?from=89310855233&to=116980482113': PAGES}[path]

    monkeypatch.setattr('app.ingestion.extract_worker.fetch', fetch)
    result = sitemap_urls('https://sardarandco.com/sitemap.xml', ['sardarandco.com'], 2)
    assert result['xml_files'] == 2 and len(result['urls']) == 2
    assert '/sitemap_pages_1.xml?from=89310855233&to=116980482113' in requested
    assert SitemapSubmission(url=child).url == child
    assert not valid_web_url(child)  # Page URLs keep their stricter no-query rule.


@pytest.mark.parametrize('child', [
    'https://other.test/sitemap_pages_1.xml?from=1&to=2',
    'https://sardarandco.com/sitemap_pages_1.xml?next=https://other.test/',
])
def test_sitemap_rejects_unsafe_child_xml_before_fetch(monkeypatch, child):
    index = ('<sitemapindex><sitemap><loc>' + child.replace('&', '&amp;')
             + '</loc></sitemap></sitemapindex>').encode()
    requested = []
    monkeypatch.setattr('app.ingestion.extract_worker.public_addresses', lambda _host: ['93.184.215.14'])

    def fetch(_host, _address, path, _limit, **_options):
        requested.append(path)
        return b'User-agent: *\nAllow: /' if path == '/robots.txt' else index

    monkeypatch.setattr('app.ingestion.extract_worker.fetch', fetch)
    with pytest.raises(ExtractionFailure, match='invalid or off-host XML'):
        sitemap_urls('https://sardarandco.com/sitemap.xml', ['sardarandco.com'], 10)
    assert requested == ['/robots.txt', '/sitemap.xml']


@pytest.mark.parametrize('url', [
    'https://other.test/sitemap_pages_1.xml?from=1&to=2',
    'https://sardarandco.com:444/sitemap.xml?from=1&to=2',
    'https://sardarandco.com/sitemap.xml?from=1&to=2&redirect=https://other.test/',
    'https://sardarandco.com/sitemap.xml?from=1&from=2&to=3',
    'https://sardarandco.com/sitemap.xml?from=2&to=1',
    'https://sardarandco.com/sitemap.xml?from=%31&to=2',
    'https://sardarandco.com/sitemap.xml?from=1&to=2#fragment',
])
def test_sitemap_query_rejects_unapproved_forms(url, monkeypatch):
    # The allowed host is checked by the submission service and the crawler;
    # the URL validator itself intentionally supports other configured hosts.
    if 'other.test' not in url.split('?', 1)[0]:
        assert not valid_sitemap_url(url)
        with pytest.raises(ValueError):
            SitemapSubmission(url=url)
    else:
        assert valid_sitemap_url(url)
        monkeypatch.setattr('app.ingestion.extract_worker.public_addresses', lambda _host: ['93.184.215.14'])
        with pytest.raises(ExtractionFailure, match='not permitted'):
            sitemap_urls(url, ['sardarandco.com'], 10)


def _run_once(sessions, settings, services):
    with httpx.Client(transport=httpx.MockTransport(services.handle)) as client:
        return process_one(sessions, settings, client)


def test_sitemap_body_is_bounded_after_authentication(runtime):
    client, _sessions, _settings, _services, headers = runtime
    body = b'{"url":"https://sardarandco.com/sitemap.xml","padding":"' + b'a' * 4096 + b'"}'
    assert client.post('/api/v1/ingestion/sitemaps', content=body, headers={'content-type': 'application/json'}).status_code == 401
    assert client.post('/api/v1/ingestion/sitemaps', content=body,
                       headers={**headers['admin'], 'content-type': 'application/json'}).status_code == 413


def test_admin_crawl_fans_out_and_reports_page_results(runtime, monkeypatch):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = 'worker'
    urls = ['https://sardarandco.com/pages/about-us', 'https://sardarandco.com/pages/bathroom-guide']
    monkeypatch.setattr('app.ingestion.sitemap_jobs.discover_sitemap', lambda *_args: {'urls': urls, 'skipped_urls': 2, 'xml_files': 1})
    monkeypatch.setattr('app.ingestion.materialize.extract_url', lambda url, _settings: (
        b'<html><main>Verified descriptive sample.</main></html>', url.rsplit('/', 1)[-1],
        f'Sardars descriptive content for {url.rsplit("/", 1)[-1]}.'
    ))
    body = {'url': 'https://sardarandco.com/sitemap.xml', 'visibility': 'staff', 'max_pages': 2}
    assert client.post('/api/v1/ingestion/sitemaps', json=body).status_code == 401
    assert client.post('/api/v1/ingestion/sitemaps', headers=headers['staff'], json=body).status_code == 403
    created = client.post('/api/v1/ingestion/sitemaps', headers=headers['admin'], json=body)
    assert created.status_code == 202
    parent_id = created.json()['job_id']
    with sessions() as db:
        assert db.get(IngestionJob, parent_id).status == 'pending'
        assert list(db.scalars(select(SourceRegistration))) == []
    assert _run_once(sessions, settings, services)
    detail = client.get('/api/v1/ingestion/jobs/' + parent_id, headers=headers['admin']).json()
    assert detail['status'] == 'completed' and detail['operation'] == 'crawl'
    assert detail['crawl_progress'] == {'discovered_pages': 2, 'queued_pages': 2, 'pending': 2, 'processing': 0, 'completed': 0, 'failed': 0}
    assert 'urls' not in detail['result'] and 'about-us' not in str(detail['result'])
    pages = client.get(f'/api/v1/ingestion/jobs/{parent_id}/pages', headers=headers['admin']).json()
    assert {page['url'] for page in pages} == set(urls)
    assert client.get(f'/api/v1/ingestion/jobs/{parent_id}/pages', headers=headers['staff']).status_code == 403
    assert _run_once(sessions, settings, services)
    assert _run_once(sessions, settings, services)
    detail = client.get('/api/v1/ingestion/jobs/' + parent_id, headers=headers['admin']).json()
    assert detail['crawl_progress']['completed'] == 2
    with sessions() as db:
        assert len(list(db.scalars(select(SourceRegistration)))) == 2
    assert client.get('/api/v1/ingestion/sources', headers=headers['staff']).status_code == 200
    assert len(client.get('/api/v1/ingestion/jobs', headers=headers['admin']).json()) == 1


def test_crawl_retry_reuses_saved_urls_and_revoked_admin_cannot_continue(runtime, monkeypatch):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = 'worker'
    urls = ['https://sardarandco.com/pages/about-us', 'https://sardarandco.com/pages/bathroom-guide']
    discovered = []

    def discover(*_args):
        discovered.append(True)
        return {'urls': urls, 'skipped_urls': 0, 'xml_files': 1}

    monkeypatch.setattr('app.ingestion.sitemap_jobs.discover_sitemap', discover)
    original_enqueue = __import__('app.ingestion.sitemap_jobs', fromlist=['enqueue']).enqueue
    child_calls = []

    def fail_once(*args, **kwargs):
        if kwargs.get('parent_job_id'):
            child_calls.append(True)
            if len(child_calls) == 2:
                raise OSError('controlled enqueue failure')
        return original_enqueue(*args, **kwargs)

    monkeypatch.setattr('app.ingestion.sitemap_jobs.enqueue', fail_once)
    created = client.post('/api/v1/ingestion/sitemaps', headers=headers['admin'], json={
        'url': 'https://sardarandco.com/sitemap.xml', 'max_pages': 2,
    })
    parent_id = created.json()['job_id']
    assert _run_once(sessions, settings, services)
    with sessions() as db:
        parent = db.get(IngestionJob, parent_id)
        assert parent.status == 'failed' and parent.result['urls'] == urls
        assert len(list(db.scalars(select(IngestionJob).where(IngestionJob.parent_job_id == parent_id)))) == 1
    assert client.post(f'/api/v1/ingestion/jobs/{parent_id}/retry', headers=headers['admin']).status_code == 202
    assert _run_once(sessions, settings, services)
    assert discovered == [True]
    with sessions() as db:
        assert db.get(IngestionJob, parent_id).status == 'completed'
        children = list(db.scalars(select(IngestionJob).where(IngestionJob.parent_job_id == parent_id)))
        assert len(children) == 2
    with sessions.begin() as db:
        db.scalar(select(User).where(User.email == 'admin@test.local')).role = 'staff'
    assert _run_once(sessions, settings, services)
    assert _run_once(sessions, settings, services)
    with sessions() as db:
        assert all(db.get(IngestionJob, child.id).status == 'failed' for child in children)
        assert list(db.scalars(select(SourceRegistration))) == []
