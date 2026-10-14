# Agent Instructions

## Agent skills

### Issue tracker

Issues are tracked on Forgejo (`nbt1/pere_noel_fremo`) via the `forgejo` MCP server. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context (`GLOSSARY.md` + `docs/adr/` at repo root). See `docs/agents/domain.md`.

### Git workflow & PR resolution

Strict linear fast-forward policy (`pull.ff only`, `pull.rebase true`). On Forgejo, pull requests are resolved strictly via `fast-forward-only` merge without merge commits or squash. PR branches must be rebased on top of target branch before merge. See ADR-0011.
