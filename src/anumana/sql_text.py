"""Small SQL lexical helpers; never execute or interpolate user statements.

This is not a SQL parser. Unknown/complex SQL is left to the database planner;
rewrites deliberately support only a conservative subset.
"""
from __future__ import annotations

import re


def mask_sql(sql: str) -> str:
    """Mask literals/comments/quoted identifiers while retaining token offsets."""
    chars = list(sql)
    i = 0
    while i < len(sql):
        start = i
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end < 0 else end
        elif sql.startswith("/*", i):
            i += 2
            depth = 1
            while i < len(sql) and depth:
                if sql.startswith("/*", i):
                    depth += 1
                    i += 2
                elif sql.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise ValueError("Unterminated SQL comment")
        elif sql[i] in "'\"`[":
            close = "]" if sql[i] == "[" else sql[i]
            i += 1
            while i < len(sql):
                if sql[i] == close:
                    i += 1
                    if i < len(sql) and sql[i] == close:
                        i += 1
                        continue
                    break
                # Backslash escaping is dialect/session dependent. Refuse it
                # instead of allowing ambiguous boundaries through the guard.
                if sql[i] == "\\":
                    raise ValueError("Use standard SQL quoting without backslash escapes")
                i += 1
            else:
                raise ValueError("Unterminated SQL quote")
        elif sql[i] == "$" and (match := re.match(r"\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$", sql[i:])):
            tag = match[0]
            end = sql.find(tag, i + len(tag))
            if end < 0:
                raise ValueError("Unterminated dollar-quoted SQL literal")
            i = end + len(tag)
        else:
            i += 1
            continue
        chars[start:i] = " " * (i - start)
    return "".join(chars)


def single_statement(sql: str) -> str:
    """Refuse stacked statements before a driver sees EXPLAIN + user text."""
    masked = mask_sql(sql)
    semis = [m.start() for m in re.finditer(";", masked)]
    if len(semis) > 1 or (semis and masked[semis[0] + 1:].strip()):
        raise ValueError("Preflight accepts one SQL statement only")
    if not masked.replace(";", "").strip():
        raise ValueError("SQL statement is empty")
    # Remove a terminal delimiter but retain trailing comments.
    return sql[:semis[0]] + sql[semis[0] + 1:] if semis else sql


def bounded_candidate(sql: str, limit: int = 100) -> str | None:
    """Advisory LIMIT for plain SELECT only, never JSON requests or complex SQL."""
    sql = single_statement(sql)
    masked = mask_sql(sql)
    if not re.match(r"\s*SELECT\b", masked, re.I):
        return None
    # Subqueries/CTEs, set ops and locking clauses require a proper SQL AST.
    if len(re.findall(r"\bSELECT\b", masked, re.I)) != 1:
        return None
    if re.search(r"\b(LIMIT|FETCH|INTO|UNION|INTERSECT|EXCEPT|FOR)\b", masked, re.I):
        return None
    # Newline avoids appending LIMIT inside a trailing line comment.
    return sql.rstrip() + f"\nLIMIT {limit}"


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
