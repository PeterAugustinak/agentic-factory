# clean-up

Human-facing documentation for the `clean-up` skill. The operational definition is [`skills/paf-clean-up/SKILL.md`](../../skills/paf-clean-up/SKILL.md). This file explains how the skill works and is not loaded by Claude at run time.

## Purpose

Run the post-merge housekeeping you would otherwise type by hand after `/paf:check-out`'s MR/PR is merged: switch to the base branch, pull it, and delete the local feature branch. `clean-up` is a **helper skill**: you invoke it yourself, it sits outside the feature pipeline, and it invokes no agents.

## When and how to invoke

Merge the MR/PR on GitHub or GitLab. Then, with the merged feature branch still checked out, run:

```
/paf:clean-up
```

It takes no argument. Invoking it is your confirmation that the branch is merged. The skill does not check.

## How it works

`clean-up` runs entirely in the main thread, with plain `git` only, so it behaves the same for GitHub and GitLab.

1. **Read the branch.** `git branch --show-current` names the branch checked out at invocation.
2. **Switch.** `git switch '<base>'`. The base branch comes from the project instructions (`CLAUDE.md` / `AGENTS.md`). It is used only when it is a plain branch name (the same rule `/paf:init` applies), otherwise the skill stops and asks.
3. **Pull.** `git pull origin '<base>'`.
4. **Delete.** `git branch -D '<branch>'`. The delete is forced because after a squash merge `git branch -d` can refuse: it requires the branch to be merged into its upstream, or into `HEAD` when no upstream is set ([git-branch docs](https://git-scm.com/docs/git-branch)).

If any command fails, the skill prints its output and stops without running the rest. You decide what to do next. On success it prints one line: `Switched to <base>, pulled origin/<base>, deleted <branch>.`

Out of scope: the remote branch is not deleted, and there is no merge check, platform query, or confirmation prompt.

## Agents used

`clean-up` calls no agents.

## Orchestration

```text
/paf:clean-up   (on the merged feature branch)
     |
     v
  [skill] git branch --show-current  -> <branch>
     |
     v
  [skill] git switch '<base>'        --fail--> print output, stop
     |
     v
  [skill] git pull origin '<base>'   --fail--> print output, stop
     |
     v
  [skill] git branch -D '<branch>'   --fail--> print output, stop
     |
     v
  print "Switched to <base>, pulled origin/<base>, deleted <branch>."
```

Legend: `[skill]` = work the skill does itself in the main thread. The diagram reads top to bottom.

## Cost

`clean-up` does not report cost. Helper skills are on the exemption list in [`architecture.md` §5](../architecture.md#cost-reporting): they invoke no agents, so their cost is near zero.

## Related files

- [`skills/paf-clean-up/SKILL.md`](../../skills/paf-clean-up/SKILL.md): the skill.
- [`scripts/install.sh`](../../scripts/install.sh): lists it under Helper skills.
