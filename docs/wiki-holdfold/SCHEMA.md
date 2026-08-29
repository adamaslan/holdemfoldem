# Wiki Schema — holdemfoldemapp

The LLM owns this layer entirely. You (the user) curate sources and ask questions. The LLM writes and maintains every wiki page. This schema mirrors `gcp3-mobile/docs/wiki-mobile/SCHEMA.md` — keep them in sync.

## Three Layers

```
docs/wiki-holdfold/raw/      — IMMUTABLE source documents. User drops files here. LLM reads, never writes.
docs/wiki-holdfold/          — LLM-written pages: entities, concepts, decisions, incidents.
docs/wiki-holdfold/SCHEMA.md — This file. Governs all wiki behavior.
```

## Directory Layout

```
docs/wiki-holdfold/
├── SCHEMA.md              — This file
├── index.md               — Catalog of every page
├── log.md                 — Append-only operations log
├── overview.md            — System map, stack, current health
├── entity-*.md            — One page per named component (the hubs)
├── concept-*.md           — Cross-cutting patterns
├── incident-*.md          — One page per production incident
├── decision-*.md          — Recorded design decisions
└── raw/                   — Immutable source documents
```

## Page Types & Required Sections

### Entity Pages
- **What it is**
- **Where used**
- **Known failures**
- **Open questions**
- **See also**

### Concept Pages
- **The pattern**
- **Where it appears**
- **Contradictions / tensions**
- **See also**

### Decision Pages
- **Decision** (one sentence)
- **Date**
- **Context**
- **Alternatives considered**
- **Consequences**
- **Validated by**
- **See also**

### Incident Pages
- **Date & severity**
- **What happened**
- **Root cause**
- **Resolution**
- **Impact on design**
- **Open items**

## Frontmatter

```yaml
---
date: 2026-05-31
type: entity | concept | decision | incident | overview
tags: [holdfold, backend, signals]
sources: [../backend/main.py]
---
```

## Secret Policy

Never write real API keys, GCP project IDs, Cloud Run hostnames, or service account credentials into wiki pages. Use placeholders: `{gcp-project-id}`, `{holdfold-backend-url}`, `{alphavantage-api-key}`.

## Cross-Repo Boundary

This wiki is holdemfoldemapp-only. For mobile references, link by path:
```
See `gcp3-mobile/docs/wiki-mobile/entity-client-holdfold.md` for the mobile client.
```

Per cross-repo rule 7: never edit gcp3-mobile or gcp3 wikis from a holdfold session.

## Log Format

```
## [2026-05-31] sync | sources: {files} | pages touched: N
## [2026-05-31] ingest | {source title} | pages touched: N
## [2026-05-31] ingest | PR #{number} {title} | pages touched: N
```

## On PR Creation

Whenever a PR is opened for this repo (`gh pr create`), treat the PR as an
ingest source before finishing the task: secret scan the diff, update the
relevant `entity-*`/`concept-*`/`decision-*`/`incident-*` pages (never copy
the diff or PR description verbatim), update `index.md` if new pages were
added, and append to `log.md` using the PR log format above.
