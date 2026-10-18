# Git Branch & Pull Request Workflow

## Branching & Push Constraints
1. **Never push directly to `main` or production default branches.**
2. Always create a descriptive topic/feature branch:
   - Format: `feat/<feature-name>`, `fix/<issue-name>`, or `docs/<scope>`
3. Push exclusively to the feature branch (`git push origin <branch-name>`).

## Pull Request Submission
1. Open a Pull Request using GitHub CLI:
   `gh pr create --title "..." --body "..."`
2. Never auto-merge without explicit user review and approval.
3. Verify that CI workflow runs on the PR branch pass completely before requesting merge.

## Detailed PR Description Structure
Every PR description must follow this structure:
- **Summary**: Concise context and problem statement.
- **Key Changes**:
  - **Backend**: Compiler, security, schema, dialect, or server modifications.
  - **Frontend / UI**: Visual Query Builder, editors, charts, or state handling.
  - **Tooling & Docs**: CLI, MCP, typings, docs, and changelog updates.
- **Verification Evidence**:
  - Specific unit/integration test suites executed and pass rates.
  - Typecheck (`mypy`, `tsc`) and lint (`ruff`, `eslint`) results.
  - CI workflow run links and job matrix results.
- **Breaking Changes**: Any altered defaults, API parameters, or schema contracts.

## Automation & Headless Invariants
1. Pre-configure git credentials via `gh auth setup-git` before pushing.
2. In Node/pnpm environments, ensure Node 22+ (e.g. Node 24) is active and set `COREPACK_ENABLE_DOWNLOAD_PROMPT=0` to avoid interactive download hangs.
