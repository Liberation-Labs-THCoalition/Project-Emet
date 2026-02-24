# _future/ — Quarantined Modules

These modules contain ~18K lines of code that are **not currently imported**
by any core code path (agent, MCP, API, CLI, FtM adapters). They were moved
here during the pre-release audit to reduce codebase noise.

## Modules

| Module | Lines | Purpose | Status |
|--------|-------|---------|--------|
| `bdi/` | 592 | BDI agent architecture | Prototype, not wired in |
| `integrations/` | 289 | Third-party integrations | Placeholder |
| `plugins/` | 2,977 | Plugin system | Designed but unused |
| `multitenancy/` | 2,539 | Multi-org support | Future feature |
| `tuning/` | 1,753 | EFE prompt tuning | Experimental |
| `skills/` | 4,614 | Skill chip system | Designed but unused |
| `adapters/discord/` | 2,063 | Discord bot adapter | Built, not integrated |
| `adapters/email/` | 3,689 | Email adapter (IMAP/SMTP) | Built, not integrated |

## To restore a module

```bash
mv _future/<module> emet/<module>
```

Then wire it into the appropriate entry point (cli.py, api/app.py, etc.).
