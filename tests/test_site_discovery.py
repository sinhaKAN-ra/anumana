"""Search/discovery invariants for the public static deployment."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.robotparser import RobotFileParser
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
CANONICAL = 'https://anumana.aolbeam.com/'


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.meta = {}; self.links = []; self.ids = []
        self.jsonld = []; self.in_jsonld = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[attrs.get('name', attrs.get('property'))] = attrs.get('content')
        if tag in {'a', 'link'}:
            self.links.append(attrs)
        if attrs.get('id'):
            self.ids.append(attrs['id'])
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.in_jsonld = True
    def handle_endtag(self, tag):
        if tag == 'script': self.in_jsonld = False
    def handle_data(self, data):
        if self.in_jsonld: self.jsonld.append(data)


def page():
    result = Page(); result.feed((SITE / 'index.html').read_text()); return result


def test_canonical_and_social_metadata_agree():
    parsed = page()
    assert [x['href'] for x in parsed.links if x.get('rel') == 'canonical'] == [CANONICAL]
    assert parsed.meta['og:url'] == parsed.meta['twitter:url'] == CANONICAL
    assert parsed.meta['description'] == parsed.meta['og:description'] == parsed.meta['twitter:description']
    assert parsed.meta['twitter:card'] == 'summary'
    assert len(parsed.ids) == len(set(parsed.ids))


def test_structured_data_identifies_this_product_without_fabricated_commerce():
    data = json.loads(''.join(page().jsonld))
    assert data['@context'] == 'https://schema.org'
    software = next(node for node in data['@graph'] if 'SoftwareApplication' in node['@type'])
    assert software['url'] == CANONICAL and software['name'] == 'Anumana'
    assert software['codeRepository'] == 'https://github.com/sinhaKAN-ra/anumana'
    for node in data['@graph']:
        assert not {'offers', 'aggregateRating', 'review', 'sponsor', 'affiliation'} & node.keys()


def test_related_projects_are_crawlable_and_not_a_self_link():
    parsed = page()
    assert 'explore-aolbeam' in parsed.ids
    assert any(link.get('href') == '#explore-aolbeam' for link in parsed.links)
    for url in ('https://www.aolbeam.com/practice', 'https://ask.aolbeam.com'):
        link = next(link for link in parsed.links if link.get('href') == url)
        assert 'nofollow' not in link.get('rel', '')


def test_discovery_alias_and_internal_section_links():
    content = (SITE / 'llms.txt').read_text()
    assert content == (SITE / 'llm.txt').read_text()
    assert content.startswith('# Anumana\n')
    assert 'https://anumana.vercel.app' not in content
    assert 'https://ask.aolbeam.com' in content
    assert 'https://www.aolbeam.com/practice' in content
    import re
    for fragment in re.findall(r'https://anumana\.aolbeam\.com/#([\w-]+)', content):
        assert fragment in page().ids


def test_robots_allows_public_search_and_excludes_internal_paths():
    parser = RobotFileParser()
    parser.parse((SITE / 'robots.txt').read_text().splitlines())
    assert parser.site_maps() == [CANONICAL + 'sitemap.xml']
    for agent in ('Googlebot', 'Bingbot', 'PerplexityBot'):
        for path in ('/', '/llms.txt', '/llm.txt', '/styles.css', '/app.js', '/sitemap.xml'):
            assert parser.can_fetch(agent, CANONICAL.rstrip('/') + path)
        for path in ('/account', '/dashboard/test', '/api/query', '/internal', '/private'):
            assert not parser.can_fetch(agent, CANONICAL.rstrip('/') + path)


def test_sitemap_contains_only_launched_canonical_page():
    xml = ET.parse(SITE / 'sitemap.xml')
    assert [element.text for element in xml.findall('{*}url/{*}loc')] == [CANONICAL]


def test_static_deployment_does_not_expose_source_or_create_private_route_fallback():
    config = json.loads((ROOT / 'vercel.json').read_text())
    assert config['outputDirectory'] == 'site'
    assert not config.get('rewrites')
    for name in ('api', 'account', 'dashboard', 'internal', 'private', '.git', '.env'):
        assert not (SITE / name).exists()
    protected = [entry for entry in config['headers'] if any(
        h['key'] == 'X-Robots-Tag' and 'noindex' in h['value'] for h in entry['headers'])]
    assert {entry['source'] for entry in protected} >= {'/api/:path*', '/dashboard/:path*', '/account/:path*'}
