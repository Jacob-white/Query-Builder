## Summary

<!-- What does this change and why? Link issues. Do NOT describe security vulnerabilities here
     if this fixes an undisclosed one: use the private process in SECURITY.md. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change (public API, supported Python/Node versions, extras names)
- [ ] Security hardening
- [ ] Docs / tooling / CI only

## Checklist

- [ ] `python -m ruff check .` and `python -m ruff format --check .` are clean
- [ ] `python -m pytest` passes (coverage floor 99%)
- [ ] React changes: `pnpm run typecheck`, `lint`, `build`, `test:coverage` and `check:package` pass in `packages/react`
- [ ] No new `any`, no new `eslint-disable` / `@ts-ignore` / `# noqa` without a justification
- [ ] New or changed regexes that touch user/SQL input have a linear-time test
- [ ] Security-sensitive changes (validator, policy, tenant isolation, SSRF, connectors) include adversarial tests
- [ ] `CHANGELOG.md` has an entry under `## Unreleased` (and `packages/react/CHANGELOG.md` for React changes)
- [ ] New dependencies are justified and are optional extras where possible

## Testing

<!-- Commands you ran, and for connector changes whether you ran the live-database suite
     (docs/TESTING_LIVE.md). -->
