# Query-Builder Documentation & Technical Specifications 📚

Query-Builder is open-source software owned and maintained by **HobbyHabbit LLC** under the **MIT License**. This directory contains developer guides, API specifications, and platform architectural blueprints for the query compilation engine and visual studio.

---

## 🚀 Developer Guides & Reference

- **[5-Minute Quickstart Guide](quickstart.md)** — Step-by-step onboarding for Python backend (FastAPI/Django/Ninja), declarative query compilation, security governance, and the React visual studio.
- **[Complete API Reference](api_reference.md)** — Exhaustive technical reference for all Python models, functions, classes, CLI commands, MCP server tools, and TypeScript visual components.
- **[Security Policy & Sandboxing Guide](../SECURITY.md)** — Threat model, AST validation, zero-trust query isolation, network egress checks, and vulnerability disclosure procedures.

---

## ⚛️ Ecosystem & Integration Packages

- **[React Visual Query Studio Package](../packages/react/README.md)** — Comprehensive documentation for `@jacob-white/query-builder-react` including subpath imports, typed client, compound components, headless hooks, controlled mode, and in-memory OLAP engine.
- **[Full-Stack Starter Template](../examples/fullstack_starter/README.md)** — Turnkey runnable reference implementation combining FastAPI + React 18 + Vite + SQLite.

---

## 🏛️ Architectural Specifications & Roadmaps

- **[Project Overview & Architectural Blueprint](../PROJECT.md)** — High-level engine architecture, data flows, AST compilation pipeline, and dialect support matrix.
- **[Database Connectors Blueprint](../MISSING_CONNECTORS_PLAN.md)** — Specifications and roadmap for the database connectors across relational, lakehouse, cloud warehouse, and document engines. The real, generated inventory (138 connector classes: 89 sync + 49 async, reachable through 306 registered names including aliases) and how each one is verified live in **[CONNECTORS.md](CONNECTORS.md)**.
- **[Live Engine Testing](TESTING_LIVE.md)** — How to run the opt-in live conformance suite against real engines (Docker Compose, env vars, cloud credentials) and how verification tiers are computed.
- **[Test Infrastructure & Quality Invariants](../TEST_INFRA.md)** — Zero-suppression test execution rules, resource-throttled Vitest/pytest patterns, and verification standards.
- **[Test Readiness & Verification Certification](../TEST_READY.md)** — Verification records certifying 100.0% statement, branch, function, and line coverage.

---

## 📄 License & Ownership

Query-Builder is open-source software owned and maintained by **HobbyHabbit LLC** under the **MIT License**. See **[LICENSE](../LICENSE)** for complete details.
