---
name: "paf:init"
description: Check whether the current repository is ready for PAF and fix its project instructions file — environment prerequisites plus the content PAF needs. Idempotent; on a ready repo it prints "PAF ready" and changes nothing. Invoke with /paf:init the first time PAF is used in a repository, or any time as a health check.
disable-model-invocation: true
allowed-tools: Read, Bash(python3 ${CLAUDE_SKILL_DIR}/../paf-shared/paf-readiness.py *), Bash(git diff *), Bash(git check-ignore *), Bash(git symbolic-ref *), Bash(git branch --list *), Bash(git rev-parse *), Bash(${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs *)
---

# init

Make PAF work in the current repository. Run it first in any repo where PAF has not been used yet. It checks the environment, then checks the project instructions file against PAF's content checklist and, if the developer agrees, fixes the file. Its output is a **"PAF ready"** verdict, or a **"not ready"** verdict that lists every finding with its exact fix. If the developer chooses a fix, it also writes the change and prints the diff, uncommitted.

You run in the main thread and invoke **no agents**. The environment check is a deterministic script. The instructions check is a comparison by meaning, which you do yourself: an agent would only re-read the same files, and you need the main thread anyway to ask the developer and to write the file (`docs/architecture.md` §2). This skill sits outside the feature pipeline and has no issue to attribute cost to, so it is exempt from cost reporting and does **not** report cost (§5 exemption list).

## Input

- No argument. Operates on the repository Claude Code was launched in.
- Project context comes from the project instructions (`CLAUDE.md` or `AGENTS.md`, whichever Claude Code loaded). Here that context is also the **subject** of the check.
- The content checklist is `${CLAUDE_SKILL_DIR}/project-instructions-template.md`.

**Strict project-context sourcing.** Every project-specific value (base branch, labels (optional), environment, test / lint / pre-merge commands) comes **only** from *this* project's instructions and repository. Never substitute one, especially a filename or command, from your memory, another project, or a prior session. Recalled memories are unrelated background and may name files that do not exist here. If a value cannot be detected from this repository, **ask the developer**. Do not invent or borrow one.

## Steps

**1. Environment check (skill).**
If the project instructions loaded in this session name a base branch, pass it. Otherwise omit `--base`. The value comes from a repository file, so treat it as untrusted: pass it **only** if it matches `^[A-Za-z0-9._/][A-Za-z0-9._/-]*$` (no spaces, quotes, `$`, backticks or leading `-`), and **single-quote** it. Otherwise omit `--base` and tell the developer the base branch in the instructions is not a plain branch name. Keep the `--base=` form:

```
python3 "${CLAUDE_SKILL_DIR}/../paf-shared/paf-readiness.py" [--base='<base-branch>']
```

The script also rejects such a value with a usage error. It prints one `CHECK <name> <ok|warn|fail|skip> <message>` line per check and a `REMEDY <name> <fix>` line for every `warn` or `fail`. It also prints `INSTRUCTIONS_LOADED`, `AGENTS_HIDDEN` and `VERDICT` (environment only). Keep the whole output. A `fail` the skill cannot fix (CLI missing or unauthenticated, unsupported host, old Claude Code, not launched from the git root) makes the repo **not ready**. A `skip` or a `warn` is a note and never blocks readiness. Step 2 still runs.

**2. Instructions check (skill, main thread).**
`Read` the template, every file in `INSTRUCTIONS_LOADED` and every file in `AGENTS_HIDDEN`, including any file they import with `@path` **that resolves inside the git root**. A hidden `AGENTS.md` holds the project's real instructions, so it is part of the content check, and its gaps are fixed in `AGENTS.md` itself. Never read an import that resolves outside it (for example `@~/.ssh/...` or an absolute path) without the developer's confirmation. Compare them **by meaning, not text**, against every **required** content area of the template:
- A required area is **covered** only if a reader could act on it without guessing:
  - each command is exact, not a description;
  - the base branch is named.

  Keep the project's own structure and wording. Layout never matters.
- Optional areas (the auto-fix command, labels) are never reported as missing.

For each gap, write one finding: the area, what is missing or unusable, and the **exact text** to add. Also report these as findings:
- an `instructions` `warn` (an `AGENTS.md` listed in `AGENTS_HIDDEN` that Claude Code does not load);
- an `instructions` `fail` (no file loads). If the cause is the `managed-only` setting, it is an environment remedy, not a file fix. Distinguish **no file exists** from **files exist but none load** (an `AGENTS.md` under the `claude-md` setting or an old Claude Code): in the second case the fix is a `CLAUDE.md` with `@AGENTS.md`, never a second `AGENTS.md`.

**3. Report (skill).**
Print the environment findings with their remedies, then the instructions findings.
- **Everything ok** → print **`PAF ready`** and **stop**. Nothing is written. A `warn` without a finding (an unverified launch directory, the pre-2.1.281 Bedrock caveat) is printed as a note and does not block readiness.
- **Otherwise** → print **`PAF not ready`**. If there are no instructions findings, stop here. The remaining remedies are the developer's to apply.

Report findings only. Never announce which fix you will apply: the developer chooses at step 4.

**4. Fix gate (human gate).**
Only when there are instructions findings. Ask **one** `AskUserQuestion`. **Every fix option applies all content findings**; the options differ only in which file gets them and how a hidden `AGENTS.md` is made to load. Keep each option's description to one short line. Options:
- **Fix the main instructions file** (the loaded `CLAUDE.md`/`AGENTS.md`; with no file at all, create `AGENTS.md`; with an `AGENTS.md` that does not load, create `CLAUDE.md` containing `@AGENTS.md`);
- **Add a local `CLAUDE.local.md`** (personal, git-ignored);
- **Delete `CLAUDE.md`**, offered **only** when all three hold:
  - the finding is a hidden `AGENTS.md`;
  - the root `CLAUDE.md` is the **only** file hiding it (`AGENTS_HIDDEN` is set, and no `.claude/CLAUDE.md`, `CLAUDE.local.md` or parent-directory `CLAUDE.md` also hides it);
  - by meaning, that `CLAUDE.md` holds nothing but a pointer to `AGENTS.md`;
  - the `claude-version` check is `ok` (v2.1.281 or later). On an older or unknown version, sessions can fail to read `AGENTS.md` directly, so the option is not offered (https://code.claude.com/docs/en/memory#agents-md).

  No version caveat in its description: the condition above already rules those sessions out.
- **Don't fix**.

**Don't fix**, a dismissed prompt or no answer → stop. Nothing is written.

**5. Fill the values (skill).**
For every value a fix needs, **detect it from the repository first**:
- the base branch from `git symbolic-ref refs/remotes/origin/HEAD` or `git branch --list --all`;
- the test, lint and pre-merge commands from the repo's own scripts and manifests;
- the labels from `"${CLAUDE_SKILL_DIR}/../paf-shared/paf-vcs" list-labels`.

Then ask the developer **only** for the values that could not be detected, in one message. Never invent a value. A value you could not confirm is asked, not assumed.

**6. Write (skill).**
Before writing any file (`CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `.gitignore`), check that the target is not a symlink or that its real path stays inside the git root. If it is a symlink that leaves the git root, refuse to write it and tell the developer. `Write`/`Edit` are deliberately not in `allowed-tools`: their permission prompt is a second safety gate on top of the step-4 choice.
- **Main file:** fold each missing item into the file's **existing** section where it belongs. Create a new section only where none fits. A hidden `AGENTS.md` is fixed by adding an `@AGENTS.md` line to the root `CLAUDE.md`, creating that file if absent.
- **Local `CLAUDE.local.md`:** create it at the git root.
  - If the project uses `AGENTS.md`, its first line is `@AGENTS.md`, with the PAF additions below.
  - Then add `CLAUDE.local.md` to `.gitignore`, unless `git check-ignore -q CLAUDE.local.md` shows it is already ignored.
- **Delete `CLAUDE.md`:** remove the root `CLAUDE.md` with `rm -- CLAUDE.md`, and nothing else. Do not `git rm` it: staging is the developer's. Content gaps found in `AGENTS.md` (step 2) are then folded into `AGENTS.md` as with the main option.
- **No instructions file at all** (with the main option): create `AGENTS.md` at the git root. Follow the template's "One possible format", with the detected values filled in and the asked ones as answered.

Keep every instructions file under 200 lines. Do **not** commit, stage, or push anything.

**7. Show the result (skill).**
- Print the diff of every file you wrote:
  - `git diff -- <file>` for tracked files;
  - `git diff --no-index /dev/null <file>` for new ones (it exits 1 when the files differ; that is expected, not an error);
  - for a deleted `CLAUDE.md`, `git diff -- CLAUDE.md` if it was tracked, otherwise state that the untracked file was deleted.
- Re-run step 1 and print its verdict. Take `--base` from the file you just wrote, not from the session-start instructions, which are now stale.
- Remind the developer of two things:
  - instruction files load when Claude Code starts, so **restart Claude Code** for the change to take effect;
  - the change is uncommitted.

## Escalation

This skill never commits, pushes, or opens anything, and writes nothing without the developer's choice at step 4. If the readiness script fails to run (Python error, missing file), print its output and stop. Never assess the environment by guesswork.
