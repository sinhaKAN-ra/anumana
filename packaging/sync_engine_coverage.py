"""Render the website's database list from the skill's readiness catalog."""
from pathlib import Path
from html import escape
import json
import re

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'skills/anumana-query-preflight/references/engine-status.json'
START = '<!-- ENGINE_COVERAGE_START -->'
END = '<!-- ENGINE_COVERAGE_END -->'


def main():
    engines = json.loads(CATALOG.read_text())['engines']
    rows = []
    for e in engines:
        search = escape(' '.join([e['name'], e['id'], *e['aliases'], e['paradigm']]).lower(), quote=True)
        runner = 'connected' if e['runner'] else 'not-wired'
        verified = 'yes' if e['verified_live'] else 'no'
        test = '<span class="db-status tested">Live-tested</span>' if e['verified_live'] else '<span class="db-status pending">Pending</span>'
        rows.append(f'<tr data-engine-row data-search="{search}" data-runner="{runner}" data-tested="{verified}">'
                    f'<th scope="row">{escape(e["name"])}<small>{escape(e["paradigm"])}</small></th>'
                    f'<td>{escape(e["input"])}</td><td>{escape(e["signal"])}</td>'
                    '<td><span class="db-status implemented">Implemented</span></td>'
                    f'<td><span class="db-status {runner}">{"Connected" if e["runner"] else "Not wired"}</span></td>'
                    f'<td>{test}</td></tr>')
    content = '\n'.join(rows)
    page = ROOT / 'site/index.html'
    source = page.read_text()
    before, rest = source.split(START, 1)
    _, after = rest.split(END, 1)
    updated = before + START + '\n' + content + '\n' + END + after
    counts = {'db-adapter-total': len(engines), 'db-runner-total': sum(e['runner'] for e in engines),
              'db-tested-total': sum(e['verified_live'] for e in engines)}
    for name, count in counts.items():
        updated, matches = re.subn(f'(<strong id="{name}">)[^<]*(</strong>)',
                                   lambda m: m[1] + str(count) + m[2], updated)
        assert matches == 1, name
    updated = re.sub(r'(<p id="db-count"[^>]*>)[^<]*(</p>)',
                     lambda m: m[1] + f'{len(engines)} of {len(engines)} database families' + m[2], updated)
    page.write_text(updated)
    print(f'Updated website coverage for {len(engines)} adapter families')


if __name__ == '__main__':
    main()
