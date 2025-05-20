# Limitless CLI Refactor — Product Requirements Document (PRD)

## 1  Purpose

Deliver a clean, modular, **installable** Python package named `limitless_cli`.
The refactor eliminates the current monolithic script, improves maintainability, and enables both library and command-line use via `pip install limitless-cli` → `limitless …`.

## 2  Goals

| Goal                 | Success Metric                                                                                        |
| -------------------- | ----------------------------------------------------------------------------------------------------- |
| Modular architecture | Code split by concern; no cross-module import cycles                                                  |
| Library + CLI parity | `python -m limitless_cli` **and** `limitless` produce identical results                               |
| High testability     | ≥ 80 % coverage for pure logic; deterministic unit tests                                              |
| Package quality      | `python -m build` yields a wheel that passes `twine check`; installs into a fresh venv with no extras |

## 3  Functional Requirements

1. **CLI commands**

   * `list`, `get`, `week`, relative-period shortcuts (`today`, `this-week`, etc.)
   * Flags mirrored from current script (`--raw`, `--limit`, `--timezone`, `--force-cache`, etc.).
2. **API layer** — encapsulated `ApiClient` with retry/back-off.
3. **Caching layer** — read/write daily JSON cache, completeness metadata, smart-probe logic.
4. **Domain utilities** — date/period parsing, range calculations.
5. **Output layer** — Markdown and JSON rendering isolated from business logic.

## 4  Non-Functional Requirements

* Python 3.9+.
* Style: `black`, `ruff`, `mypy`, `bandit` clean.
* Continuous Integration on GitHub Actions (3.9 – 3.12).
* No network calls at import time; lazily initialise resources.

## 5  Out of Scope (Phase 1)

* Async HTTP client (`httpx`) or `aiohttp`.
* Plugin architecture.
* Alternate cache back-ends (SQLite, Redis).

## 6  Target Project Layout

```
limitless-cli/              # repo root
├── src/
│   └── limitless_cli/
│       ├── __init__.py     # public API re-exports
│       ├── __main__.py     # python -m limitless_cli
│       ├── cli.py          # arg/flag parsing
│       ├── app.py          # orchestration layer
│       ├── api/
│       │   └── client.py
│       ├── cache/
│       │   ├── manager.py
│       │   └── probe.py
│       ├── domain/
│       │   ├── dates.py
│       │   └── range_fetcher.py
│       ├── output/
│       │   ├── markdown.py
│       │   └── json.py
│       ├── settings.py
│       └── utils.py
├── tests/
├── pyproject.toml
├── README.md
└── LICENSE
```

*Src-layout* prevents accidental local-import bleed-through during testing.

## 7  Packaging & Distribution

```toml
# pyproject.toml (excerpt)
[project]
name = "limitless-cli"
version = "0.8.0"
description = "CLI & SDK for the Limitless AI lifelog API"
requires-python = ">=3.9"
dependencies = ["requests>=2.31"]

[project.scripts]
limitless = "limitless_cli.cli:main"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```

Running `pipx install git+https://…/limitless-cli` yields the `limitless` command immediately.

## 8  Migration Plan

| Step | Action                                                                       | Outcome                                                           |
| ---- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 1    | Create `src/limitless_cli/`; move current `limitless.py` to `cli.py` inside. | Package scaffold exists; tests still pass via `pip install -e .`. |
| 2    | Extract pure helpers (dataclasses, date parsing) into `domain/`.             | No functional change; add unit tests.                             |
| 3    | Move API & cache logic into `api/` and `cache/` modules.                     | Monolithic file shrinks; logic becomes testable.                  |
| 4    | Introduce orchestration `app.py`; `cli.py` only delegates.                   | CLI stays thin.                                                   |
| 5    | Add `__init__.py` re-exports for library usage.                              | `from limitless_cli import ApiClient` works.                      |
| 6    | Wire console-script in `pyproject.toml`; validate `limitless --help`.        | CLI available after install.                                      |
| 7    | Retire legacy script; update README.                                         | Single source of truth.                                           |
| 8    | Publish pre-release on TestPyPI; gather feedback.                            | Ready for 1.0 once stable.                                        |

## 9  Acceptance Criteria

* All existing commands behave identically to v0.7.0.
* Unit tests and linting pipelines green.
* `python -m limitless_cli --help` and `limitless --help` work in a clean venv.
* Wheel uploaded to TestPyPI installs and runs on Linux/macOS/Windows runners.

## 10  Risks & Mitigations

| Risk                    | Mitigation                                                                                                |
| ----------------------- | --------------------------------------------------------------------------------------------------------- |
| Cache completeness bugs | Comprehensive unit tests around `CacheManager` and probe logic; regression fixtures from production data. |
| Contributor confusion   | README section “Architecture at a glance”; inline docstrings; diagrams if helpful.                        |
| Packaging edge cases    | CI matrix tests build & install wheel, then run smoke tests.                                              |

---

**Owner:** Drew Colthorp
**Reviewers:** Atomic Object development team
**Target version:** 0.8.0 (internal), 1.0.0 (public)
