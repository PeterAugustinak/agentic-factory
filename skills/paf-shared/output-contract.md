# Agent output contract — parsing rules (shared)

Every PAF agent returns its result as **exactly one fenced ` ```yaml ` block** as its final message, closed by a ` ``` ` line as the very last line. This file is the single, shared definition of how a skill parses and validates that block. Skills reference it instead of repeating these rules. It mirrors `docs/architecture.md` §4–§5.

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

1. Take the agent's final message and extract the **last** fenced ` ```yaml ` block. A block with no closing fence is still a block: it runs to the end of the message (CommonMark, fenced code blocks), so extract it rather than treating it as missing.
2. Parse it as YAML and **validate**:
   - required keys present: `agent`, `status`, `summary`, `artifacts`, `issues`;
   - `status` ∈ {`success`, `failure`, `needs_retry`};
   - every `issues[].severity` ∈ {`error`, `warning`};
   - every `artifacts[].action` ∈ {`created`, `modified`, `deleted`}.
3. On **any** failure — missing block, YAML parse error, missing key, or invalid enum value — **STOP the run and escalate to the developer, quoting the agent's raw final message** so the failure is diagnosable. Never proceed on a partial or guessed parse.
4. If the block had no closing fence and passed step 2, continue, but tell the developer `<agent>: report had no closing fence, so it may be truncated` and repeat it in the run's final report. The closing fence is the only sign a report was not cut off, and a cut between two `issues` entries still validates.

## Severity semantics

- `error` = **blocker**: stops the flow, requires developer action.
- `warning` = **minor / non-blocking**: passed forward or surfaced for the developer to decide on.