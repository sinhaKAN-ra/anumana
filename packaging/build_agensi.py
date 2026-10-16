"""Build/inspect the prepared Agensi ZIP; only approved, credential-free files."""
from pathlib import Path
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'skills/anumana-query-preflight'
OUTPUT = ROOT / 'dist/anumana-query-preflight.zip'
CATALOG = SOURCE / 'references/engine-status.json'
BASE_FILES = (
    'SKILL.md', 'SETUP.md', 'LICENSE', 'references/workflows.md',
    'references/engines.md', 'references/engine-status.json', 'references/verification.md',
    'assets/mcp-postgres.json', 'assets/mcp-pgvector.json', 'assets/mcp-offline.json',
    'assets/mcp-development.json', 'assets/mcp-sqlite-development.json',
    'assets/mcp-mysql-development.json', 'assets/mcp-mongodb-development.json',
    'assets/mcp-dynamodb-development.json', 'assets/mcp-redshift-development.json',
    'assets/mcp-multi-development.json',
)


def package_files():
    engines = json.loads(CATALOG.read_text())['engines']
    assert len({e['id'] for e in engines}) == 12
    return (*BASE_FILES, *(f"references/{e['reference']}" for e in engines))


def validate_config(path):
    config = json.loads(path.read_text())['mcpServers']['anumana']
    if config['command'] == 'uvx':
        assert config['args'] == ['anumana-mcp==0.2.1']
    else:
        assert config['command'] == 'uv'
        assert config['args'] == ['--directory', 'REPLACE_WITH_ANUMANA_CHECKOUT', 'run', '--no-sync', 'anumana-mcp']
    env = config.get('env', {})
    assert set(env) <= {'ANUMANA_DSN', 'ANUMANA_ENGINE', 'ANUMANA_TARGETS'}
    if 'ANUMANA_DSN' in env:
        assert env['ANUMANA_DSN'].startswith('REPLACE_WITH_'), 'Do not package filled credentials'
    if 'ANUMANA_TARGETS' in env:
        targets = json.loads(env['ANUMANA_TARGETS'])
        connected = {e['id'] for e in json.loads(CATALOG.read_text())['engines'] if e['runner']}
        assert len({t['name'] for t in targets}) == len(targets)
        for target in targets:
            assert target['engine'] in connected, 'No runnable template for an unwired engine'
            for key, value in target.items():
                if key not in {'name', 'engine'}:
                    assert isinstance(value, str) and value.startswith('REPLACE_WITH_'), 'Do not package filled configuration'


def main():
    files = package_files()
    skill = (SOURCE / 'SKILL.md').read_text()
    frontmatter = re.match(r'\A---\n(.*?)\n---\n', skill, re.S)
    assert frontmatter, 'Missing YAML frontmatter'
    fields = dict(line.split(': ', 1) for line in frontmatter[1].splitlines())
    assert fields['name'] == SOURCE.name
    assert re.fullmatch(r'[a-z0-9-]{1,64}', fields['name'])
    assert 0 < len(fields['description']) <= 1024
    assert len(skill.splitlines()) < 500
    for name in files:
        path = SOURCE / name
        assert path.is_file() and not path.is_symlink(), name
        if path.parent.name == 'assets' and path.suffix == '.json':
            validate_config(path)
        if path.suffix == '.md':
            for link in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if '://' not in link:
                    target = (path.parent / link).resolve()
                    assert target.is_relative_to(SOURCE.resolve()) and target.is_file(), (name, link)
    OUTPUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (SOURCE / name).read_bytes())
    with zipfile.ZipFile(OUTPUT) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(files)
        assert archive.read('SKILL.md') == (SOURCE / 'SKILL.md').read_bytes()
    print(f'Validated {len(files)} files across 12 engine profiles; built {OUTPUT}')


if __name__ == '__main__':
    main()
