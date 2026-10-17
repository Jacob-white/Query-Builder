# Query-Builder Documentation & Technical Specifications 📚

Query-Builder is open-source software owned and maintained by **HobbyHabbit LLC** under the **MIT License**. This directory contains developer guides, API specifications, and platform architectural blueprints for the query compilation engine and visual studio.

---

## 🚀 Developer Guides & Reference

- **[5-Minute Quickstart Guide](quickstart.md)** — Step-by-step onboarding for Python backend (FastAPI/Django/Ninja), declarative query compilation, security governance, and the React visual studio.
- **[Complete API Reference](api_reference.md)** — Exhaustive technical reference for all Python models, functions, classes, CLI commands, MCP server tools, and TypeScript visual components.
- **[Security Policy & Sandboxing Guide](../SECURITY.md)** — Threat model, AST validation, zero-trust query isolation, network egress checks, and vulnerability disclosure procedures.
- **[Building an AI Query Helper](AI_HELPER_PATTERNS.md)** — Patterns for a helper that turns plain English into a query spec: shortlisting tables and join routes, a glossary and worked examples as data, checking an answer before the database does, counts-only diagnosis of empty results, and measuring it.
- **[llms.txt AI Context Guide](../llms.txt)** — Comprehensive cheat sheet and architecture context for LLMs, coding agents, and external application developers.

---

## ⚛️ Ecosystem & Integration Packages

- **[React Visual Query Studio Package](../packages/react/README.md)** — Comprehensive documentation for `@jacob-white/query-builder-react` including subpath imports, typed client, compound components, headless hooks, controlled mode, and in-memory OLAP engine.
- **[Full-Stack Starter Template](../examples/fullstack_starter/README.md)** — Turnkey runnable reference implementation combining FastAPI + React 18 + Vite + SQLite.

---

## 🤝 Contributing & Integrating

- **[AGENTS.md](../AGENTS.md)** — Start here if you are an AI coding agent (or a new contributor in a hurry): layout, commands, the rules that are not optional, and the things that bite.
- **[Adding a Connector](ADDING_A_CONNECTOR.md)** — Step by step: the class, what the base class does for you, introspection, every file to wire it into, tests, running it against the real engine, and a definition of done.
- **[Dialect Guide](DIALECT_GUIDE.md)** — What each dialect setting does, how to add a dialect, golden snapshots, and a catalogue of engine quirks found by live runs with the fix for each.
- **[Secure Deployment](SECURE_DEPLOYMENT.md)** — What you must set yourself before exposing the library, the HTTP server or the MCP server; what each entry point trusts; how to verify what is enforced.
- **[Live Engine Testing](TESTING_LIVE.md)** — How to run the opt-in conformance suite against real engines (Docker Compose, env vars, cloud credentials), practical pitfalls, and how verification tiers are earned.
- **[Typing](TYPING.md)** — The mypy ratchet: every module is strict; rules for `type: ignore`.
- **[Releasing](RELEASING.md)** — How a release is cut.

---

## 🏛️ Architecture, Threat Model & Generated Status

- **[Threat Model](THREAT_MODEL.md)** — What is guaranteed per layer, residual risks, and explicit non-guarantees.
- **[Connector Status](CONNECTORS.md)** — Generated inventory of every connector class (138: 89 sync + 49 async, 306 registered names) and how each is verified (`certified`, `basic`, `emulated`, `verified`).

### Historical records (not current; kept for context)

- **[Project Overview](../PROJECT.md)** — Planning record of the security-framework milestones.
- **[Database Connectors Blueprint](../MISSING_CONNECTORS_PLAN.md)** — Connector-gap analysis and plan from an earlier milestone. Today's inventory is [CONNECTORS.md](CONNECTORS.md).
- **[Test Infrastructure Notes](../TEST_INFRA.md)** and **[Test Readiness Report](../TEST_READY.md)** — Earlier milestone records; the coverage targets in them are not what CI enforces (see [CONTRIBUTING](../CONTRIBUTING.md)).

---

## 📄 License & Ownership

Query-Builder is open-source software owned and maintained by **HobbyHabbit LLC** under the **MIT License**. See **[LICENSE](../LICENSE)** for complete details.
