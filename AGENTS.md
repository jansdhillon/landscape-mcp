# AGENTS.md

Instructions for agents working in this repository. Everything here is a default, not law: when the code in front of you contradicts this file, flag the conflict rather than silently obeying either. The credential and spec-scope rules below are invariants: surface a conflict with those and stop, rather than routing around them.

## Repo shape

Go MCP server for the Landscape API (`cmd/landscape-mcp/`, `internal/server/` for tools and prompts, `internal/landscape/` for the API client), plus a Kubernetes charm in Python (`charm/`) and a rock (`rockcraft.yaml`) that the charm deploys. Specs and change history live in the separate canonical/landscape-internal-docs OpenSpec store (see `openspec/config.yaml`), not in `openspec/specs/` here.

## Traps

- **`.env` holds real Landscape API credentials.** It is gitignored; do not read, print, or commit it. Pass `LANDSCAPE_API_KEY` and `LANDSCAPE_API_SECRET` via the environment, and never put real values in tests, docs, or commit messages.
- **Missing credentials are not a startup error.** The server starts without them so clients can list tools; tool calls return an error naming the missing variables. Keep that behavior when touching `NewClientFromEnv` or `missingCredentials` in `internal/landscape/client.go`.
- **Two API paths, do not merge them.** v2 calls (e.g. `ListComputers`) use the generated `landscape-go-api-client`. Legacy actions (`GetAccounts`, `GetLicenses`) go through `Client.Legacy`, because the legacy query-param API cannot be described in OpenAPI. Do not hand-write HTTP for an endpoint that is already in the spec, and do not add legacy actions to the spec.
- **A new v2 endpoint needs the spec first.** Add it to landscape-openapi-spec, regenerate the client, bump the `landscape-go-api-client` version in `go.mod`, then call the typed method. Only when a consumer needs it. The workflow is in `.github/skills/landscape-openapi-endpoint/SKILL.md`; read it before touching the spec or the client dependency.
- **Do not hand-edit generated client code** (it lives in the `landscape-go-api-client` module, not here). Fix it in the spec or the client repo.
- **Stdio transport owns stdout.** In `-transport stdio` mode stdout carries the MCP protocol, so log to stderr only; a stray `fmt.Println` corrupts the session.
- **The charm and rock are coupled to the binary's flags and env.** `rockcraft.yaml` starts it with `-transport http -addr :8080`, and the charm supplies `LANDSCAPE_API_URI/KEY/SECRET`. Renaming a flag or variable means updating `rockcraft.yaml`, `charm/src/charm.py`, and the README tables together.
- **The Go and charm toolchains differ.** Go commands run at the repo root; charm lint and tests run from `charm/` via `uv` (`charm/Makefile`). `charm/lib/` is vendored and excluded from ruff; do not reformat it.
- **Never commit build artifacts**: `landscape-mcp` (binary), `*.rock`, `*.charm`, `charm/.venv/`. They are gitignored; check `git status` before `git add -A`.
- **PR titles are conventional commits** (`feat:`, `fix:`, `chore:`, `docs:`), matching the history. `fix:` is for bugs, not any change.

## PR body

Keep the body to three parts, in order:

1. The Jira ticket URL on its own line (e.g. `https://warthogs.atlassian.net/browse/LNDENG-1234`), when the change has one.
2. A brief explanation of the change: what and, where useful, why. One short paragraph, not a changelog.
3. `## Manual testing`: numbered steps a reviewer can run as-is, with copy-pasteable commands and the expected output after each block. Unit tests and lint are CI's job; never list them. Omit the section entirely when there is nothing meaningful to run (e.g. docs-only).

No em-dashes, no emoji, no bold text in the explanation or manual testing sections.

## Before calling work done

- Go changes: `gofmt -l .`, `go vet ./...`, `go test ./...`. Charm changes: `make check` and `make test` in `charm/`. Tests must not call a live Landscape; the existing tests under `internal/` are the model for faking the API.
- Don't run `rockcraft pack`, `charmcraft pack`, or `juju` commands, and don't hit a real Landscape server with real credentials, yourself; give the human the steps.
- "It compiles" is not finished: re-read your own diff adversarially, and prefer the smallest test that exercises the failure mode the change addresses.
- Push back when a request conflicts with what the code shows; a well-argued objection beats compliance.

## Pointers

- `README.md`: tools and prompts table, configuration variables, transports. Update it when you add a tool.
- `charm/README.md`: build and deploy steps for the rock and charm.
- `.github/skills/mcp-builder/`: MCP server design guidance, for adding tools.
- `.github/skills/openspec-*` and `.github/prompts/opsx-*`: the OpenSpec propose/apply/archive workflow.
