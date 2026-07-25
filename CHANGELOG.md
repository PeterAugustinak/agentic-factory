# Changelog

All notable changes to PAF are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.0] - 2026-07-25

Graded MINOR rather than PATCH despite #38 being labelled partly documentation: it adds two
capabilities the project did not have — a pre-merge validation gate and a test suite — which is an
enhancement under the bump rules, not a bug fix. Nothing the installer ships changes: the installed
skills, agents, and hook are byte-identical to 0.9.1.

### Added

- `scripts/pre-merge.sh` — the full pre-merge validation gate that `/paf:check-out` step 7 runs
  against PAF itself. Standard library only: `py_compile` over the repository's `.py` files,
  `bash -n` over its shell scripts, then `python3 -m unittest`. All three stages always run, so one
  invocation reports every problem, and it exits non-zero if any failed. Shell scripts are matched by
  extension **and** by shebang (the shebang read restricted to executable files, so the stage never
  opens arbitrary binaries), which is what covers the extensionless `skills/paf-shared/paf-vcs`
  (#38).
- `tests/` — a standard-library `unittest` suite, factory-development only and excluded from
  installation by `install.sh`'s allowlist copying. It covers `PreToolUse-agent-guard.py`'s pure
  helpers and deny regexes directly, and its allow/deny/defer decisions by driving the hook as a
  subprocess with crafted stdin payloads — the hook always exits 0, so the decision is read from
  stdout, never from the exit code. It also covers `paf-report-cost.py`'s pure functions, including
  its cost arithmetic, transcript de-duplication, and invocation slicing. The hook itself is
  unchanged (#38).

### Changed

- `docs/templates/CLAUDE-template.md` is now a format-agnostic checklist of the content areas PAF's
  skills read — branch strategy, base branch, labels and merge strategy, environment setup, the test
  command, the code-standards command, and the pre-merge command — rather than a fixed form to fill
  in. The "Factory skills" table is removed: it described how PAF works, not what an adopting
  project's `CLAUDE.md` should contain. A short example remains, labelled as one possible format
  (#38).
- PAF's own `CLAUDE.md` now carries the project context its skills read at runtime (branch
  convention, base branch `develop`, stdlib-only environment, `python3 -m unittest`,
  `py_compile`/`bash -n`, `./scripts/pre-merge.sh`), so the factory satisfies the checklist it
  advises for everyone else. Before this, running `/paf:check-out` against PAF itself always halted
  at step 7 for an undefined pre-merge command. The file's stated line cap is tightened from 300 to
  200 to match `architecture.md` §6 (#38).

## [0.9.1] - 2026-07-25

Graded PATCH rather than MINOR: #36 adds no capability and changes no skill interface. It removes a
redundant hook branch (with no observable product behaviour change, since web access is already
gated upstream by each agent's `tools:` allowlist) and corrects an inaccurate architecture claim — a
backward-compatible cleanup.

### Changed

- The `PreToolUse` hook no longer special-cases `agent == "issue-validator"` for `WebSearch`/
  `WebFetch`; it now allows any web call that reaches it. Web access is already enforced upstream by
  each agent's `tools:` allowlist (`architecture.md` §3 layer 2, harness-level), so only
  web-authorized agents can ever reach the hook — the branch was a redundant second source of truth
  that could drift. `READ_ONLY_AGENTS` is kept as-is (the sole home of the read-only-vs-build/test
  Bash distinction, which `tools:` cannot express) with a clarifying comment (#36).
- `architecture.md` §3 replaces the inaccurate "adding an agent needs no change here" claim with an
  honest account of the small explicit `READ_ONLY_AGENTS` set and why it must exist, and adds a
  web-ingress accepted-residual-risk note paralleling the main-thread one (#36).

## [0.9.0] - 2026-07-24

Graded MINOR rather than PATCH despite #33 being labelled a bug: the fix changes the
interface between the skills and `paf-report-cost.py` — a new `mark` subcommand that all three
`SKILL.md` files now invoke at the start of a run, and a `record` output that no longer carries
wall-clock — which is an interface change under the bump rules, not merely an internal fix.

### Added

- A `mark` subcommand in `paf-report-cost.py` that records an invocation's start, keyed by
  session and skill, so `record` prices only the transcript from that mark onward. This scopes
  cost to a single `/paf:` invocation, eliminating the same-session double-count (an
  `implement-issue` run followed by `check-out`) and the whole-session figure a `create-issue`
  run produced inside a large session (#33).

### Changed

- `record` prices only from the invocation's mark (or `--since`) onward; with neither present it
  prices the whole transcript and warns. Unpriced models are now priced at the latest known
  same-family rate — never silently dropped — with a note to update `pricing.json`. Wall-clock is
  removed from `record` output, the ledger entry, and the aggregate table, and displayed cost is
  rounded to two decimal places. The three `SKILL.md` files, `architecture.md` §5,
  `docs/skills/*`, and `skill-definition-format.md` are updated to describe the new behaviour (#33).

### Fixed

- Argument validation in `paf-report-cost.py`: the issue number must be digits-only and the
  session, skill, and project identifiers are restricted to a safe character set. The
  `<issue-number>` placeholder is quoted in the `SKILL.md` templates (#33).

## [0.8.0] - 2026-07-23

Graded MINOR rather than PATCH despite #30 being labelled a bug: the fix revises the
`issue-validator` output contract that both skills consume — the meaning of `summary` and the shape
of each finding `message` — which is an interface change under the bump rules, not merely an
internal fix.

### Fixed

- `implement-issue`'s step-3 issue comment now carries **only** the validator's actual findings —
  one line per finding, and no comment at all when there are none — instead of also echoing the
  validator's verdict and a narration of every claim it confirmed (#30). `issue-validator`'s Output
  section is tightened to match: each finding is a single concise line, and `summary` is a brief
  verdict rather than a confirmed-claims recap.

## [0.7.2] - 2026-07-22

Graded PATCH rather than MINOR: #21 adds no new capability — it standardises `issue-writer`'s
existing output into a fixed house-style template and title convention, a backward-compatible
refinement of one agent's formatting.

### Added

- A fixed six-section issue body template (`Problem`, `Goal`, `Approach`, `Scope of changes`,
  `Acceptance criteria`, `References`, always present and in order) and a type-based title
  convention (`Bug: …` for defects, an imperative "what will be built" statement otherwise) in the
  `issue-writer` agent, so every drafted issue shares one house style. The `create-issue` skill docs
  reflect the template (#21).

## [0.7.1] - 2026-07-21

### Fixed

- The `PreToolUse` hook now allows the main thread unconditionally instead of gating its `Bash`
  calls on a command-family allow-list, so compound, piped, and `cd`-prefixed orchestration
  commands no longer fall through to a permission prompt mid-run (#22). Hardened alongside this:
  a non-dict JSON payload (`null`, a list, a bare string) now defers like a malformed one instead
  of raising an uncaught `AttributeError`, and the main thread is now identified by the *absence*
  of the `agent_type` key rather than by its value being falsy, so a payload that carries the key
  with an empty or null value is correctly treated as a restricted agent, not the main thread.

## [0.7.0] - 2026-07-21

Graded MINOR rather than PATCH despite #25 being labelled a bug: the fix grants `issue-validator`
a new capability (`Grep`/`Glob`) and widens what it validates, which is an enhancement under the
bump rules in the README.

### Changed

- `issue-validator` now validates a proposed approach against **both** authoritative external
  documentation **and** the actual repository — that named paths exist, that the described
  current behaviour matches the code, and that the approach is feasible against the existing
  implementation. It also enumerates every load-bearing claim and checks the cited spec's
  caveats, edge conditions and scope limits rather than confirming only the headline rule (#25).
- `create-issue` passes the **whole** drafted issue to the validator, and is explicitly
  forbidden from narrowing its scope ("take this as given") or skipping the validation step —
  including when a draft carries no externally-verifiable claims, since claims about the
  repository are always checkable (#25).

### Added

- `Grep` and `Glob` in `issue-validator`'s tool scope, so it can discover code a draft does not
  name by exact path. Both are read-only and outside the `PreToolUse` hook matcher; `architecture.md`
  §3 records the resulting lack of read path-containment as an accepted residual risk (#25).
- An explicit rule in `issue-validator` that file content read from the repository is data to
  inspect, never instructions to follow (#25).

## [0.6.0] - 2026-07-19

### Added

- `VERSION` file at the repo root carrying the project's semantic version.
- This changelog, seeded with the reconstructed history from 0.1.0 onward.
- `scripts/install.sh` reports the installed version and whether the run was a new
  installation, an upgrade, or a reinstall, using a `~/.claude/paf/VERSION` marker that
  survives reinstalls.
- `scripts/uninstall.sh` reports the version being removed and removes the marker.
- Versioning scheme documented in `README.md`; bump cadence documented in
  `docs/CONTRIBUTING.md`.

## [0.5.0] - 2026-07-19

### Changed

- `implement-issue` uses native plan mode for the plan→build phase, keeping exploration,
  the concrete plan, and execution in one shared context instead of splitting them across
  a planner agent and a builder agent (#18).

## [0.4.0] - 2026-07-18

### Added

- Provider-agnostic VCS adapter so the skills run against GitHub or GitLab, auto-detected
  from the git `origin` remote (#14).

### Fixed

- Handling of issue-validator findings.

## [0.3.1] - 2026-07-18

### Changed

- Agents read memory more narrowly, staying strictly within the repository's content.

## [0.3.0] - 2026-07-18

### Added

- `issue-validator` agent, wired into the `create-issue` skill.

### Fixed

- Hook and permission handling.

## [0.2.2] - 2026-07-16

### Fixed

- `create-issue` skill and cost-report fixes.

## [0.2.1] - 2026-07-16

### Changed

- Skill directories carry a `paf-` prefix.

### Added

- `.gitignore`.

### Fixed

- Cost report.

## [0.2.0] - 2026-07-15

### Added

- `scripts/uninstall.sh` — removes exactly what the installer adds and nothing else.

## [0.1.0] - 2026-07-15

### Added

- Initial PAF: project structure, architecture documentation, agent definitions, the three
  core skills (`create-issue`, `implement-issue`, `check-out`), the tool-restriction hook,
  and the installer.
