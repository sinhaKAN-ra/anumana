"""Check public discovery URLs without credentials; never deploy or modify a site.

Default: serve only site/ on a temporary loopback port. Use --base-url to check
an existing deployment after publishing has separately been authorized.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import argparse
import xml.etree.ElementTree as ET

CANONICAL = 'https://anumana.aolbeam.com/'
ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ('/', '/llms.txt', '/llm.txt', '/robots.txt', '/sitemap.xml')
PRIVATE = ('/account', '/dashboard', '/api', '/internal', '/private', '/.git/config')


def fetch(base, path, agent):
    try:
        with urlopen(Request(base.rstrip('/') + path, headers={'User-Agent': agent}), timeout=20) as result:
            return result.status, result.read(), result.geturl()
    except HTTPError as exc:
        return exc.code, b'', exc.geturl()


def verify(base):
    for agent in ('Mozilla/5.0 (Anumana public-site verification)', 'PerplexityBot'):
        bodies = {}
        for path in PUBLIC:
            status, body, final = fetch(base, path, agent)
            assert status == 200, (agent, path, status)
            assert urlsplit(final).path == path, ('Unexpected redirect/login', final)
            bodies[path] = body
        assert bodies['/llms.txt'] == bodies['/llm.txt'], 'Alias content differs'
        assert CANONICAL.encode() in bodies['/'], 'Canonical domain missing'
        sitemap = ET.fromstring(bodies['/sitemap.xml'])
        links = [n.text for n in sitemap.findall('{*}url/{*}loc')]
        assert links == [CANONICAL], 'Only the launched homepage belongs in the sitemap'
        for url in links:
            assert fetch(base, urlsplit(url).path, agent)[0] == 200
        print(f'{agent}: five public URLs HTTP 200; sitemap destinations HTTP 200; no login redirects')
    for path in PRIVATE:
        status, _, _ = fetch(base, path, 'Mozilla/5.0 (Anumana public-site verification)')
        assert status in {401, 403, 404}, ('Unexpected public internal content', path, status)
    print('Private/internal probe paths unavailable (401/403/404); no real account routes exist in this static project')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', help='Optional existing public deployment to verify read-only')
    args = parser.parse_args()
    if args.base_url:
        verify(args.base_url)
        return
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'site')))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        verify(f'http://127.0.0.1:{server.server_port}')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('Local static HTTP checks passed; Vercel header/firewall enforcement requires post-deployment verification')


if __name__ == '__main__':
    main()
