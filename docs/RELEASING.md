# Releasing

Releases are cut **from a tag** by `.github/workflows/release.yml`. One tag publishes both
artifacts, which always share one version:

| Artifact | Registry | How it is published |
| :--- | :--- | :--- |
| `query-builder-engine` (sdist + wheel) | PyPI | Trusted publishing (OIDC, no stored token) via `pypa/gh-action-pypi-publish`; PEP 740 attestations |
| `@jacob-white/query-builder-react` (tarball) | npm | `npm publish <tarball> --provenance --access public` with an npm token |
| GitHub release | GitHub | Notes taken from the matching `CHANGELOG.md` section; assets: sdist, wheel, npm tarball, CycloneDX SBOMs, `SHA256SUMS` |

> **Status of this document.** The workflow, scripts and checks below were written and validated
> locally (builds, `twine check`, `publint`, `attw`, version-gate unit tests, clean-venv smoke tests,
> YAML parsing). **A real publish has never been executed**: no tag was pushed, nothing was uploaded,
> and neither GitHub environments nor registry credentials were touched. As of 2026-10-09 neither
> `query-builder-engine` on PyPI nor `@jacob-white/query-builder-react` on npm exists, so the first
> release will also claim those names. Run a dry run first (below).

## One-time manual setup (maintainer)

None of this can be done from the repository; all of it must exist before the first real release.

### 1. GitHub environments

Settings > Environments: create **`pypi`** and **`npm`**. Recommended for both: *Required reviewers*
(a human approves every publish) and *Deployment branches and tags* restricted to tags matching `v*`.
Publishing jobs reference these environments, so the approval gate happens right before upload.

### 2. PyPI trusted publisher (no token needed)

1. Create/sign in to a PyPI account that will own `query-builder-engine`.
2. PyPI > Your account > Publishing > **Add a new pending publisher** (this works for a project name
   that does not exist yet):
   - PyPI project name: `query-builder-engine`
   - Owner: `Jacob-white`, Repository: `Query-Builder`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. The first successful publish converts the pending publisher into a normal trusted publisher.
4. Enable 2FA on the PyPI account. (Optional: also add the same publisher on TestPyPI and point a
   copy of the publish job at it to rehearse.)

### 3. npm token

1. The `@jacob-white` scope must exist on npm and the publishing account must be able to publish to
   it (`npm org`/user scope). The package is published `--access public`.
2. Create a **granular access token** with *Read and write* on `@jacob-white/query-builder-react`
   only (first publish: scope-wide permission is needed until the package exists), with the shortest
   practical expiry, and 2FA bypass only if your account policy requires it for automation.
3. Save it as secret **`NPM_TOKEN`** in the **`npm` environment** (not as a repository secret), so only
   the approved publish job can read it.
4. `--provenance` needs the job's OIDC token (`id-token: write`, already granted to that job only) and
   a public repository. Once the package exists you may switch to npm *trusted publishing* (configure
   the publisher on npmjs.com, then drop `NPM_TOKEN`); that is a follow-up, not required.

### 4. Repository settings

- Protect `main` (required CI checks, no force pushes) and add a **tag protection / ruleset** for `v*`
  so only maintainers can create release tags. The workflow additionally refuses tags that are not on `main`.
- Enable the **dependency graph** (needed by `actions/dependency-review-action`) and Dependabot alerts.
- Allow GitHub Actions to create releases with the default token (the release job requests
  `contents: write` itself).

## Dry run (do this before every release)

Actions > Release > *Run workflow*, leave `dry_run` ticked (default). It verifies versions, runs the
Python (3.11, 3.13) and React suites, builds sdist + wheel + npm tarball, runs `twine check --strict`,
`publint --strict`, `attw`, builds SBOMs and checksums, and uploads everything as workflow artifacts. It
never publishes. A dry run from a branch skips the "CHANGELOG section exists" requirement (the real
tag run enforces it). Publishing requires **both** a tag ref and `dry_run: false`; a tag push publishes.

## Release checklist

1. Everything intended is merged; CI is green on `main`.
2. Decide the version (`X.Y.Z`, plain release versions only; see "Version for the next release").
3. In one "release prep" PR:
   - set `__version__` in `query_builder/__init__.py` (the Python version is read from there) **and**
     `version` in `packages/react/package.json` to the same value;
   - promote the changelog: rename `## Unreleased` to `## [X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md` (and
     `packages/react/CHANGELOG.md`), add an empty `## Unreleased` above it;
   - update the `SECURITY.md` supported-versions table if the supported line changes;
   - check `python .github/scripts/release_checks.py versions --tag vX.Y.Z` passes locally.
4. Merge the PR. Run the **dry run** on `main` and inspect the artifacts (`pip install` the wheel in a
   scratch venv, `npm pack` contents, SBOMs).
5. Tag the merge commit and push the tag: `git tag -s vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.
6. Approve the `pypi` and `npm` environment deployments when prompted.
7. Verify: PyPI page + attestations, `npm view @jacob-white/query-builder-react dist.attestations`,
   the GitHub release (notes, assets, `SHA256SUMS`), and a fresh-venv `pip install query-builder-engine==X.Y.Z`.

If a job fails after one registry already accepted its upload (versions are immutable), do **not**
re-tag: fix forward with the next patch version. PyPI releases can be *yanked*, npm versions
*deprecated* (`npm deprecate`); neither can be replaced.

## Version for the next release

Both packages currently say `1.0.0` and nothing has been published. The accumulated changes in
`CHANGELOG.md` are breaking for anyone who has been consuming this repository:

- Python **3.11+** is required (3.9/3.10 never actually worked);
- Node **22.22.2+** is required for the React toolchain;
- React public types were tightened (`any` removed; `QueryBuilderApiError.data`, `request<T>()`,
  filter `value` types now `unknown`/`FilterValue`);
- the React package is now `"type": "module"` with per-condition type declarations, `react` is a required
  peer dependency, and its tarball no longer contains `src/` or stray `dist/*.js` files;
- Python extras changed meaning: `mysql` installs `pymysql` (native `mysqlclient` is `mysql-native`),
  `h2`/`derby` install `JayDeBeApi`, `pinecone` installs `pinecone`, `prestodb` installs
  `presto-python-client`, `greptimedb` installs `psycopg`; `all` is now the portable set and
  `all-native` is the old "everything" set.
- tenant/row-level-security predicates are now enforced outside the client's filter group.

These **warrant a major version: release as `2.0.0`**. (Only if the maintainers consider `1.0.0`
never released may they ship `1.0.0` instead; the first-ever publish makes the SemVer argument moot, but
the changelog and `SECURITY.md` then need adjusting. This is a maintainer decision; the version was
intentionally **not** bumped by the packaging work.)

### Exact checklist for 2.0.0

- [ ] `query_builder/__init__.py`: `__version__ = "2.0.0"`
- [ ] `packages/react/package.json`: `"version": "2.0.0"`
- [ ] `CHANGELOG.md`: `## Unreleased` -> `## [2.0.0] - <date>`; new empty `## Unreleased`; Breaking section
      lists Python 3.11+, Node 22.22.2+, React type tightening, extras changes above
- [ ] `packages/react/CHANGELOG.md`: same promotion, including the "Type tightenings" note
- [ ] `SECURITY.md` supported-versions table mentions `2.x`
- [ ] README/docs install snippets match the extras (`[server]`, `[django]`, `[all]`, `[all-native]`)
- [ ] Add a short "Migrating from 1.x" section to the changelog entry (extras renames; React type narrowing)
- [ ] Release-prep PR merged, dry run green, tag `v2.0.0` pushed, environments approved, post-release checks done
- [ ] After release: open a PR bumping `main` to the next development state only if you use `.devN`
      versions (this repository does not; `Unreleased` in the changelog is the marker)

## What each automated gate protects

| Gate | Location | Fails when |
| :--- | :--- | :--- |
| Version agreement | `.github/scripts/release_checks.py` | tag, `query_builder.__version__`, npm `version` disagree; not plain `X.Y.Z`; no non-empty `## [X.Y.Z]` changelog section; tag not on `main` |
| Python tests/lint | `release.yml` `test-python` | ruff, format, pytest or coverage floor fail on 3.11 / 3.13 |
| Python artifacts | `build-python` | `python -m build` or `twine check --strict` fail, or the wheel's clean-venv smoke test (import, `query-builder --version`, `query-builder-mcp`, FastAPI integration with the `server` extra) fails |
| npm artifacts | `build-npm` | typecheck, lint, build, `check:package` (exports exist and load as ESM+CJS, `publint --strict`, `attw`) or coverage fail |
| Dependency audit | `ci.yml` `supply-chain` | `pip-audit` / `pnpm audit --audit-level high` report an unlisted vulnerability |

## Deferred / known limitations

- The React main entry still re-exports everything (charts, ERD, DuckDB driver, performance advisor), so
  importing it pulls the whole library into non-tree-shaken bundles. Splitting these into separate subpath
  entries (for example `/charts`, `/erd`, `/duckdb`, `/advisor`) while keeping the root re-exports for
  compatibility is a follow-up. `"sideEffects": false` lets bundlers drop unused exports in the meantime.
- npm trusted publishing (tokenless) and `actions/attest-build-provenance` for the GitHub assets are not wired up.
- Third-party action SHAs are pinned; Dependabot proposes updates weekly.
