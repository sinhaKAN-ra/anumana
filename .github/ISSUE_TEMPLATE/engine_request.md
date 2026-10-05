name: Engine request
about: Ask for support for a new database engine
title: "[engine] "
labels: enhancement, engine
---

**Which engine?**
Name + link.

**Paradigm**
Relational / document / key-value / graph / wide-column / vector / warehouse.

**Cost signal — the key question**
How does this engine let you see what a query will do WITHOUT running it?
(e.g. `EXPLAIN`, a dry-run API, a profiler, a deterministic rule on the query
shape.) Anumana can only support an engine that exposes a cost signal — if there
is none, it can't get an adapter.

**Why it matters to you**
What are you building, and what would Anumana catch for you on this engine?
