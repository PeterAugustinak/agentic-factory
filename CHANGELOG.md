# Changelog

All notable changes to PAF are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
