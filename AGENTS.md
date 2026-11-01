# AGENTS.md — xingtu-tools

## Repository role
This repository maintains reusable engineering scripts and tool integrations.

## Source of truth
Start with `README.md`, then inspect `scripts/ and project tool directories` and any more specific instructions in the directory being changed. The current code and tests take precedence over unverified README examples.

## Project-specific guardrails
Verify each script's dependencies and side effects before execution. Treat database and production access as read-only unless explicitly approved; never embed connection strings or private paths. Keep mirrored CLI components consistent with their upstream source.

## Shared capabilities
Reusable Skills live in [xingtu-skills](https://github.com/xingtu1996/xingtu-skills), while shared rules, hooks and SDD assets are maintained in their respective repositories. A link to another repository is **not** automatic instruction inheritance or skill installation. Verify compatibility and use an explicit, reviewable install/version mechanism before invoking shared assets.

## Change protocol
1. Inspect existing repository instructions, source and relevant tests.
2. For nontrivial work, write or update an SDD spec with acceptance criteria before implementation.
3. Work on an isolated branch and open a reviewable PR. Do not change visibility, licenses, secrets, release settings or default branches as part of routine governance.
4. Run only safe, applicable checks; report exact commands, results and unrun checks as NOT_RUN.
5. Do not publish private Vault contents, internal paths, credentials or personal data. Keep changes reversible and record the commit SHA.
