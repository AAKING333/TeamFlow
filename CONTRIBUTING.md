# Contributing to TeamFlow

Thank you for helping build TeamFlow.

## Branching

- Create a small feature branch from `main`.
- Keep branch names descriptive and short.
- Prefer focused changes with one clear purpose.

## Development workflow

1. Create or activate a virtual environment.
2. Install dependencies from `backend/requirements-dev.txt`.
3. Make a small, testable change.
4. Write or update tests when behavior changes.
5. Run Ruff and pytest before opening a pull request.
6. Keep documentation aligned with the actual implementation.

## Commit conventions

- Use clear, imperative commit messages.
- Keep commits focused on a single concern.
- Include tests with behavior changes when possible.

## Code review expectations

- Review for correctness, readability, and security.
- Avoid introducing hidden state or broad refactors.
- Do not merge code that fails validation or leaves the project in an unclear state.

## Pull request checks

- Ensure all relevant tests pass.
- Confirm lint checks pass.
- Update documentation if the user-facing behavior or project setup changes.
