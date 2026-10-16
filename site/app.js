'use strict';

// Marketplace URL is intentionally the homepage until a listing is published.
// Set this to the reviewed Anumana listing URL when it is available.
const AGENSI_LISTING_URL = '';
if (AGENSI_LISTING_URL) {
  const url = new URL(AGENSI_LISTING_URL);
  if (url.protocol === 'https:' && (url.hostname === 'agensi.io' || url.hostname === 'www.agensi.io')) {
    document.getElementById('agensi-link').href = url.href;
    document.getElementById('agensi-link').textContent = 'Get the skill on Agensi ↗';
    document.getElementById('agensi-status').textContent = 'View the package, price and installation options on Agensi.';
  }
}

const examples = {
  postgres: {
    tool: 'preflight_query', sql: 'SELECT *\nFROM orders\nWHERE customer_id = 42;',
    context: 'A customer lookup without a supporting index.',
    title: 'A selective lookup.\nA sequential scan.',
    description: 'The planner may choose sequential access when no suitable index serves this filter. Check the scan estimate and selectivity before proposing an index.',
    flags: ['SEQ_SCAN_LARGE', 'SELECT_STAR_WIDE', 'UNBOUNDED_RESULT'],
    next: 'Next: inspect the plan, project required columns, and review index options.'
  },
  vector: {
    tool: 'preflight_vector_search', sql: "SELECT id\nFROM documents\nORDER BY embedding <=> '[0.1,0.2,0.3]'\nLIMIT 200;",
    context: 'A cosine similarity search without a matching vector index.',
    title: 'Only 200 results.\nPotentially every vector.',
    description: 'A small result set can still require calculating distance across the collection. Review vector index availability, top-k, and any filter/recall trade-offs.',
    flags: ['FULL_VECTOR_SCAN', 'TOP_K_TOO_LARGE'],
    next: 'Next: review a metric-matched index and the result count the application needs.'
  },
  offline: {
    tool: 'preflight_schema_only', sql: 'CREATE TABLE orders (\n  id bigint PRIMARY KEY,\n  customer_id bigint,\n  total numeric\n);\n\n-- Candidate query\nSELECT * FROM orders;',
    context: 'DDL + SQL. No database connection or credentials.',
    title: 'Start with the schema.\nKeep the limits clear.',
    description: 'Flag broad projections and an unbounded result against supplied DDL. Without live statistics, this is a heuristic review rather than a database cost prediction.',
    flags: ['HEURISTIC', 'SELECT_STAR_WIDE', 'UNBOUNDED_RESULT'],
    next: 'Next: clarify required columns and row count; use live preflight when available.'
  }
};

document.querySelectorAll('[data-example]').forEach(button => {
  button.addEventListener('click', () => {
    const example = examples[button.dataset.example];
    if (!example) return;
    document.querySelectorAll('[data-example]').forEach(other => other.setAttribute('aria-pressed', String(other === button)));
    document.getElementById('demo-tool').textContent = example.tool;
    document.getElementById('demo-sql').textContent = example.sql;
    document.getElementById('demo-context').textContent = example.context;
    const title = document.getElementById('demo-title');
    title.replaceChildren();
    example.title.split('\n').forEach((line, index) => {
      if (index) title.append(document.createElement('br'));
      title.append(document.createTextNode(line));
    });
    document.getElementById('demo-description').textContent = example.description;
    const flags = document.getElementById('demo-flags');
    flags.replaceChildren(...example.flags.map(flag => {
      const code = document.createElement('code');
      code.textContent = flag;
      return code;
    }));
    document.getElementById('demo-next').textContent = example.next;
  });
});

const configMode = document.getElementById('config-mode');
configMode.addEventListener('change', () => {
  const server = { command: 'uvx', args: ['anumana-mcp==0.2.1'] };
  if (configMode.value !== 'offline') {
    server.env = { ANUMANA_DSN: 'REPLACE_WITH_READ_ONLY_POSTGRES_DSN', ANUMANA_ENGINE: configMode.value };
  }
  document.getElementById('mcp-config').textContent = JSON.stringify({ mcpServers: { anumana: server } }, null, 2);
  document.getElementById('config-help').textContent = configMode.value === 'offline'
    ? 'No DSN is needed. Ask your agent to call preflight_schema_only with supplied CREATE TABLE DDL and a SQL query. Findings are heuristic.'
    : configMode.value === 'pgvector'
      ? 'Use your own read-only PostgreSQL DSN with pgvector installed. The pgvector engine enables vector-aware checks; recall is not predicted.'
      : 'Replace the DSN placeholder locally with your own read-only PostgreSQL connection. Keep credentials out of source control.';
});

const clients = {
  claude: { root: '.claude/skills', docs: 'https://code.claude.com/docs/en/skills' },
  cursor: { root: '.cursor/skills', docs: 'https://cursor.com/help/customization/skills' },
  copilot: { root: '.github/skills', docs: 'https://docs.github.com/en/copilot/concepts/agents/about-agent-skills' }
};
document.getElementById('skill-client').addEventListener('change', event => {
  const client = clients[event.target.value];
  if (!client) return;
  document.getElementById('skill-path').textContent = `${client.root}/anumana-query-preflight/SKILL.md`;
  document.getElementById('skill-docs').href = client.docs;
});

let toastTimer;
document.querySelectorAll('[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    const element = document.getElementById(button.dataset.copy);
    const status = document.getElementById('copy-status');
    try {
      await navigator.clipboard.writeText(element.textContent);
      status.textContent = button.dataset.copy === 'mcp-config' ? 'Configuration copied. Replace the DSN locally.' : 'Prompt copied.';
      if (configMode.value === 'offline' && button.dataset.copy === 'mcp-config') status.textContent = 'Offline configuration copied.';
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(element);
      selection.removeAllRanges();
      selection.addRange(range);
      status.textContent = 'Text selected. Use your device’s Copy command.';
    }
    clearTimeout(toastTimer);
    status.classList.add('visible');
    toastTimer = setTimeout(() => status.classList.remove('visible'), 3500);
  });
});

// Keep every database visible by default, including untested/unwired adapters.
const dbSearch = document.getElementById('db-search');
const dbFilter = document.getElementById('db-filter');
const dbRows = [...document.querySelectorAll('[data-engine-row]')];
function filterDatabases() {
  const query = dbSearch.value.trim().toLowerCase();
  let visible = 0;
  for (const row of dbRows) {
    const matchesName = row.dataset.search.includes(query);
    const matchesState = dbFilter.value === 'all'
      || (dbFilter.value === 'connected' && row.dataset.runner === 'connected')
      || (dbFilter.value === 'tested' && row.dataset.tested === 'yes')
      || (dbFilter.value === 'not-wired' && row.dataset.runner === 'not-wired');
    row.hidden = !(matchesName && matchesState);
    if (!row.hidden) visible++;
  }
  document.getElementById('db-count').textContent = `${visible} of ${dbRows.length} database families`;
  document.getElementById('db-empty').hidden = visible !== 0;
}
dbSearch.addEventListener('input', filterDatabases);
dbFilter.addEventListener('change', filterDatabases);
