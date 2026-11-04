# Contributing

These rules keep `main` working for the whole team. They apply to everyone, including the team leader.

## Team rules

1. Never push to `main`. Every change reaches `main` through a pull request.
2. One branch per task. Name it after the task, for example `checker-protected-slots`.
3. Pull before you start, so your branch begins from the latest `main`.
4. Every pull request needs one review by another team member before it is merged.
5. Never commit an API key, password or token. Keys stay in environment variables or a local `.env` file.

## Steps for one task

1. Update `main` and create your branch:
   ```
   git checkout main
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
5. Push your branch and open a pull request on GitHub:
   ```
   git push -u origin your-task-name
   ```
6. Ask a team member to review. Merge only after one approval and a green CI run, then delete the branch.

## If a key was committed

Tell the team leader at once and revoke the key at the provider, then make a new one. Deleting the file in a later commit is not enough, because the key stays in the git history.

## Writing style

Use British spelling in comments, docstrings, documents and commit messages. Write short, plain sentences.

## Design decisions

The design is in the Design Document in the team's OneDrive folder. Do not build an answer to an open decision (Design Document Table 14, OD1 to OD11) before the team has decided it. If your task needs one, raise it in the team first.
