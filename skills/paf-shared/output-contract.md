# Agent output contract — parsing rules (shared)

Every PAF agent returns its result as **exactly one fenced ` ```yaml ` block** as its final message. This file is the single, shared definition of how a skill parses and validates that block. Skills reference it instead of repeating these rules. It mirrors `docs/architecture.md` §4–§5.

## The schema

```yaml
agent: "<agent-name>"            # required
status: "success"               # required — one of: success | failure | needs_retry
summary: |                       # required — the agent's primary textual output
  one paragraph (or, for issue-writer, the full drafted issue)
artifacts:                       # always present; [] when none
  - path: "<relative file path>"
    action: "created"           # one of: created | modified | deleted
issues:                          # always present; [] when none
  - severity: "error"           # one of: error | warning
    message: "<description>"
    location: "<file:line, or omitted>"
```

## How to parse (every agent step)

1. Take the agent's final message and extract the **last** fenced ` ```yaml ` block.
2. Parse it as YAML and **validate**:
   - required keys present: `agent`, `status`, `summary`, `artifacts`, `issues`;
   - `status` ∈ {`success`, `failure`, `needs_retry`};
   - every `issues[].severity` ∈ {`error`, `warning`};
   - every `artifacts[].action` ∈ {`created`, `modified`, `deleted`}.
3. On **any** failure — missing block, YAML parse error, missing key, or invalid enum value — **STOP the run and escalate to the developer, quoting the agent's raw final message** so the failure is diagnosable. Never proceed on a partial or guessed parse.

## Severity semantics

- `error` = **blocker**: stops the flow, requires developer action.
- `warning` = **minor / non-blocking**: passed forward or surfaced for the developer to decide on.