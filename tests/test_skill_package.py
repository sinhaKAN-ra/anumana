"""Prevent the prepared skill/website from overstating engine readiness."""
from pathlib import Path
import json
from html.parser import HTMLParser

import pytest

from anumana.adapters import _REGISTRY, get_adapter
from anumana.registry import Registry
from anumana import server

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/anumana-query-preflight'
ENGINES = json.loads((SKILL / 'references/engine-status.json').read_text())['engines']


def test_prepared_catalog_covers_every_implemented_adapter():
    assert {e['id'] for e in ENGINES} == {cls.name for cls in _REGISTRY.values()}
    assert len(ENGINES) == len({e['id'] for e in ENGINES})
    for engine in ENGINES:
        adapter = get_adapter(engine['id'])
        assert engine['verified_live'] == adapter.verified_live
        for alias in engine['aliases']:
            assert get_adapter(alias) is adapter
        assert (SKILL / 'references' / engine['reference']).is_file()


@pytest.mark.parametrize('engine', ENGINES, ids=[e['id'] for e in ENGINES])
def test_catalog_runner_state_matches_server_dispatch(monkeypatch, engine):
    reg = Registry()
    reg.add({'name': 'check', 'engine': engine['id'], 'dsn': 'placeholder',
             'uri': 'placeholder', 'path': '/placeholder.db', 'region': 'placeholder'})
    monkeypatch.setattr(server, 'registry', lambda: reg)
    # Factories construct callables; no driver/network/database call is made.
    if engine['runner']:
        run, name = server._runner_for('check')
        assert callable(run) and name == engine['id']
    else:
        with pytest.raises(RuntimeError, match='not wired'):
            server._runner_for('check')


def test_website_lists_all_engines_with_matching_statuses():
    class Rows(HTMLParser):
        def __init__(self):
            super().__init__(); self.rows = []
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == 'tr' and 'data-engine-row' in values:
                self.rows.append(values)
    parser = Rows()
    parser.feed((ROOT / 'site/index.html').read_text())
    assert len(parser.rows) == len(ENGINES)
    for row, engine in zip(parser.rows, ENGINES):
        assert engine['id'] in row['data-search']
        assert row['data-runner'] == ('connected' if engine['runner'] else 'not-wired')
        assert row['data-tested'] == ('yes' if engine['verified_live'] else 'no')
