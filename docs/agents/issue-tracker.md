# Issue tracker: Forgejo / Gitea

Issues and specs for this repo live as Forgejo / Gitea issues. Prefer the `forgejo` MCP server tools (Tier 1) with `tea` CLI as authorized fallback.

## Conventions

### Tier 1: Forgejo MCP Server (Preferred)

- **Repository**: `owner: "nbt1"`, `repo: "pere_noel_fremo"`
- **Create an issue**: Call `create_issue(owner="nbt1", repo="pere_noel_fremo", title, body, labels)`.
- **Read an issue**: Call `get_issue_by_index(owner="nbt1", repo="pere_noel_fremo", index)` and `list_issue_comments(owner="nbt1", repo="pere_noel_fremo", index)`.
- **List issues**: Call `list_repo_issues(owner="nbt1", repo="pere_noel_fremo", state="open", labels=[...])`.
- **Comment on an issue**: Call `create_issue_comment(owner="nbt1", repo="pere_noel_fremo", index, body)`.
- **Apply / remove labels**: Call `add_issue_labels(owner="nbt1", repo="pere_noel_fremo", index, labels=[...])` / `remove_issue_labels(...)`.
- **Close an issue**: Call `issue_state_change(owner="nbt1", repo="pere_noel_fremo", index, state="closed")`.
- **Native dependencies**: Call `add_issue_dependency(owner="nbt1", repo="pere_noel_fremo", index, dependency_index)` to establish blocking edges.

### Tier 2: `tea` CLI (Fallback)

- **Create an issue**: `tea issues create --title "..." --body "..." --labels "..."`
- **Read an issue**: `tea issues show <number>` and comments.
- **List issues**: `tea issues list --state open`
- **Comment on an issue**: `tea comment <number> "..."`
- **Close an issue**: `tea issues close <number>`

Infer owner and repo from `git remote -v`.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using Forgejo MCP PR tools (`get_pull_request_by_index`, `list_repo_pull_requests`, `update_pull_request`) or `tea pr` equivalents.

## When a skill says "publish to the issue tracker"

Create a Forgejo issue using `create_issue` (or `tea issues create`).

## When a skill says "fetch the relevant ticket"

Call `get_issue_by_index(owner, repo, index)` (or `tea issues show <number>`).

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body.
- **Child ticket**: an issue linked to the map via `Part of #<map>` at the top of the body, labelled `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`).
- **Blocking**: Forgejo's **native issue dependencies**. Call `add_issue_dependency(owner, repo, index=child_index, dependency_index=blocker_index)` or fall back to `Blocked by: #<n>` in the ticket body.
- **Frontier query**: list open children via `list_repo_issues`, inspect dependencies via `list_issue_dependencies`, and select unblocked tickets.
- **Resolve**: post resolution comment, close issue (`issue_state_change`), and append context pointer to map.
