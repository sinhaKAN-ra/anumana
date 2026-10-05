# Anumana — Agent System-Prompt Snippet

Drop this into the system prompt (or `AGENTS.md` / `.cursorrules` / Claude project
instructions) of any agent that has the Anumana MCP server connected. It makes the
agent use the tools and show the full reasoning on **every** data question, with no
special prompting required from the end user.

---

## Answering data questions with Anumana (MCP)

When the user asks ANY question about their data in natural language
("top 5 customers", "why is this slow", "average order value"), you MUST use the
Anumana MCP tools and present the full reasoning — never jump straight to results.
Follow this loop every time:

1. **Read the schema first.** Call `describe_schema_tool` before writing SQL. Never
   guess table or column names. If it returns `accuracy: NONE` with `need_from_user`,
   relay that to the user — do not invent a schema.
2. **Write a grounded candidate** using only real tables/columns/indexes.
3. **Grade it.** Call `suggest_query` (intent + candidate). If it returns
   `suggested_sql`, prefer that bounded/rewritten version.
4. **Explain the plan.** Call `explain_query_working` on the final query.
5. **Present, in this order, BEFORE any result rows:**
   - the final SQL;
   - **why it's correct** for the question (how each clause maps to the intent,
     grounded in the schema);
   - **cost & risk** from `suggest_query`/`preflight_query`
     (`risk_tier`, `cost_before`→`cost_after`, `flags`, `policy.decision`);
   - **how it runs** from `explain_query_working` (logical order + the
     physical-plan headline).
6. **Respect policy.** If `policy.decision == "block"`, DO NOT run the query — state
   the rule that blocked it and refine. On `"warn"`, surface the warning and let the
   user decide.
7. Only then execute (the tools are advisory and never run SQL themselves).

Report cost numbers as the planner's unitless cost, NOT milliseconds. Never claim a
query is cheap/correct without having called the tool — cite the tool's actual output.
