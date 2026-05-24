# ASTEROIDS -- DEVELOPMENT_WORKFLOW.md

## Development Workflow via Pull Requests

**Version:** 1.0
**Date:** 2026-04-14

## 1. Purpose

Guide Asteroids development through short, safe, and testable PRs, ensuring technical quality and traceability.

## 2. Principles

1. Nothing enters `main` without a Pull Request.
2. Each PR must have a small, cohesive, and validatable scope.
3. The domain (`core/`) is isolated and must not import `client/`.
4. The project must remain functional at the end of each PR.

## 3. Branch and Commit Standards

### 3.1 Branch naming

Use one of these prefixes:

- `feat/<short-description>` -- new feature
- `fix/<short-description>` -- bug fix
- `chore/<short-description>` -- maintenance, configuration, tooling
- `refactor/<short-description>` -- code restructuring without behavior change
- `docs/<short-description>` -- documentation-only change
- `style/<short-description>` -- formatting and code style

Use kebab-case for the description. Examples:

- `feat/multiplayer-lobby`
- `fix/hyperspace-spawn-inside-asteroid`
- `chore/extract-collision-manager`
- `refactor/move-entities`
- `docs/architecture-update`

### 3.2 Commits

All commit messages, PR titles, and PR descriptions are written in idiomatic en-US English, using the imperative mood and a Conventional Commits prefix:

- `feat: objective description`
- `fix: specific fix`
- `chore: structural change`
- `refactor: structural change without behavior modification`
- `docs: documentation update`
- `style: code style or formatting`

Commits should be small, descriptive, and aligned with the PR objective.

## 4. Operational Flow

### 4.1 Preparation

```bash
git checkout main
git pull
git checkout -b feat/feature-name
```

### 4.2 Development

- Implement only the scope defined for the PR.
- Preserve the `core/` (logic) and `client/` (presentation) separation.
- Do not introduce new dependencies without approval.
- Centralize new constants in `core/config.py`.

### 4.3 Local validation

```bash
python main.py
```

Test manually:
- Gameplay works (move, shoot, collisions)
- Menu and game over work
- Sounds play correctly
- No visible regressions

### 4.4 Publishing

```bash
git add <relevant-files>
git commit -m "feat: objective description"
git push origin feat/feature-name
```

## 5. Pull Request Structure

### 5.1 Title

Format: `<prefix>: objective description`, using one of the prefixes listed in §3.2.

### 5.2 Description

Every PR must include:
- **Objective**: problem the PR solves
- **What was implemented**: objective list of changes
- **Technical decisions**: justifications when relevant
- **How to test**: steps to validate the change

## 6. Review Checklist

### Architecture
- [ ] `core/` does not import `client/`
- [ ] No circular imports
- [ ] Constants in `core/config.py`

### Quality
- [ ] Typed code (type hints)
- [ ] No magic numbers outside `config.py`
- [ ] Cohesive and readable functions
- [ ] No overengineering

### Functionality
- [ ] Game runs without errors (`python main.py`)
- [ ] Gameplay functional (move, shoot, collisions)
- [ ] No visible regressions

## 7. Post-Merge Sync

After PR is approved and merged:

```bash
git checkout main
git pull
git branch -d <pr-branch>
git status
```

Confirm that the worktree is clean.

## 8. Short PR Strategy

- Focus on **one main objective** per PR
- Avoid mixing refactoring with new features
- If it grows too large, split: `chore` -> `feat` -> `fix`
- Prefer quality with simplicity over speed
