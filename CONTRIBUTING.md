# Contributing

These rules keep `develop` and `main` working for the whole team. They apply to everyone, including the team leader.

## Team rules

1. Nobody can push directly to `develop` or `main`. GitHub blocks it. Every change reaches `develop` through a pull request.
2. One branch per task. Name it after the task, for example `checker-protected-slots`.
3. Pull before you start, and start each branch from an up-to-date `develop`, never from `main`.
4. Every task pull request goes into `develop`. Only a release pull request goes into `main` (see Releases to main).
5. Every pull request needs one review by another team member and a green CI run before it is merged. If new commits are pushed after the approval, ask the reviewer to look again, because GitHub keeps the approval.
6. A pull request into `develop` is merged with a squash merge. GitHub allows only that there.
7. Never commit an API key, password or token. Keys stay in environment variables or a local `.env` file.

## Steps for one task

1. Update `develop` and create your branch:
   ```
   git checkout develop
   git pull
   git checkout -b your-task-name
   ```
2. Make your change in small commits with clear messages.
3. Run the checks and fix anything they report:
   ```
   ruff check .
   pytest
   ```
4. Check that no key or private file is staged:
   ```
   git status
   git diff --staged
   ```
5. Push your branch and open a pull request on GitHub with base `develop`:
   ```
   git push -u origin your-task-name
   ```
6. Ask a team member to review. Merge only after one approval and a green CI run, using squash merge. GitHub then deletes the branch.

## Releases to main

At milestones, such as before a client demo, Gate B or the paper results, the team leader opens a release pull request from `develop` into `main`. It needs the same review and green CI run. It is merged with a merge commit, not squashed, so the history of `develop` stays intact. `main` receives nothing else.

## If a key was committed

Tell the team leader at once and revoke the key at the provider, then make a new one. Deleting the file in a later commit is not enough, because the key stays in the git history.

## Writing style

Use British spelling in comments, docstrings, documents and commit messages. Write short, plain sentences.

## Design decisions

The design is in the Design Document in the team's OneDrive folder. Do not build an answer to an open decision (Design Document Table 14, OD1 to OD11) before the team has decided it. If your task needs one, raise it in the team first.
