# scripts/

Installer and utility scripts. These are development and distribution tools — they are not installed to the target machine.

## What belongs here

- `install.sh` — the PAF installer
- `uninstall.sh` — removes an installed PAF
- `pre-merge.sh` — full pre-merge validation gate (syntax + tests); the command `CLAUDE.md` names for `/paf:check-out`
- Any future utility scripts for maintenance or CI

## File naming

`<purpose>.sh` — lowercase, hyphenated. All scripts must be executable (`chmod +x`).

## Install target

Scripts are not installed. They run from the repository during setup or CI.
