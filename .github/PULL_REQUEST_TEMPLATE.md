## What this does

Short description of the change.

## Type
- [ ] New engine adapter
- [ ] New / improved cost flag
- [ ] Bug fix
- [ ] Docs
- [ ] Other

## Honesty-rail checklist (required)
- [ ] Does **not** execute the agent's query (EXPLAIN / dry-run / catalog reads only)
- [ ] Does **not** fake a cost where no cost signal exists
- [ ] Planner cost reported as unitless, not milliseconds
- [ ] New adapters marked `verified_live = False` until proven against a real instance

## Testing
What did you run? Paste the result.

```
uv run pytest
```

## Related issues
Closes #
