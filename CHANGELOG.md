# Changelog

All notable changes to PAF are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
