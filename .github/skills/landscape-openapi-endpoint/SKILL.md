---
name: landscape-openapi-endpoint
description: Add a Landscape Server API endpoint to the landscape-openapi-spec repo and cascade it through the generated Go client to consumers (landscape-mcp, Terraform provider). Use when a consumer needs a v2 endpoint that is not yet specced, or when updating an existing endpoint definition.
---

# Adding a Landscape endpoint to the OpenAPI spec

The `landscape-openapi-spec` repo is a **working spec scoped to downstream consumers** - it is NOT an attempt to author the authoritative Landscape API spec. Canonical may produce a real one later; this repo must stay trivially replaceable by it. That frames every decision below.

## The golden rules

1. **Demand-driven only.** Add an endpoint only when a consumer (landscape-mcp tool, Terraform resource, gh-aw workflow) actually needs it. Name the consumer in the commit message and PR body. Never spec endpoints "for completeness".
2. **Model the real server, not your assumptions.** The source of truth is the handler code in `landscape-server` (`canonical/landscape/api/`). Field names, types, defaults, and query params must come from reading the handler and its schema (`@with_schema(...)`), never from memory or from the legacy API docs.
3. **Legacy API stays out.** The legacy query-param API (`?action=GetAccounts&version=2011-08-01`) is not OpenAPI-specifiable (see the `rm-legacy-api` branch history) and must never be re-added. Legacy consumers use a hand-written shim.
4. **The cascade is the point.** Spec change -> `make bundle` -> regenerate `landscape-go-api-client` -> consumers call typed methods. Don't hand-write client code for specced endpoints.

## Workflow

### 1. Find the handler in landscape-server

- Routes live in `canonical/landscape/api/urls.py` (e.g. `Rule("/computers", methods=["GET"], endpoint=computers_list_handler)`).
- Read the handler for: request schema (`@with_schema`), query params (including defaults), response shape, and decorators (`@paginated` adds `count`/`next`/`previous`/`results` and `offset`/`limit` params).
- Response fields come from model serializers (e.g. `Computer.serialize()` in `canonical/landscape/model/main/computer.py`). Read them; don't invent fields.

### 2. Write the spec files (house pattern)

Three files per domain, under `openapi/components/`:

```
paths/<domain>.yaml       # path items; each operation refs a RESPONSE file
responses/<domain>.yaml   # response objects; each refs a SCHEMA file
schemas/<domain>.yaml     # the models
```

Then wire into `openapi/openapi.yaml`: the path `$ref`, the component schema `$ref`s, a tag, and a version bump.

Style rules (follow the existing `script.yaml` files exactly):

- Path refs from `openapi.yaml` use fragment syntax: `./components/paths/computer.yaml#/paths/~1api~1computers` ( `/` -> `~1` ).
- `operationId` is snake_case (`list_computers`).
- **Paths ref response files; response files ref schema files.** Do not $ref a schema directly from a path's response content - it trips the repo's validator (see Gotchas).
- `nullable: true` is the repo convention (OpenAPI 3.0-ism). Yes, the spec declares 3.1 and redocly complains - the repo already lives with this; `make validate` (swagger-cli) is the gate that must pass, and it rejects the 3.1 union form. Do not "fix" this repo-wide without a dedicated PR.
- Wide/dynamic response objects (fields appearing per query flags): model the known fields and set `additionalProperties: true` with a comment explaining why.
- **No self-referential `$ref` cycles** (e.g. `Computer.children` -> `Computer`). swagger-cli fails with a misleading `#/paths/... must NOT have unevaluated properties` error. Break the cycle with a separate schema (`ChildComputer`) - this usually matches reality anyway (`Computer.serialize(include_children=False)`).

### 3. Validate and bundle

```bash
make validate   # swagger-cli - MUST pass, CI gates on it
make lint       # spectral -F warn - warnings OK, errors not
make bundle     # regenerates openapi/landscape_api.bundle.yaml
```

Tools are Node CLIs; `npx --yes @apidevtools/swagger-cli` / `@stoplight/spectral-cli` work without global installs.

If `make validate` fails with `must NOT have unevaluated properties` on your path: the error is lying about location. It means something in your *schema* breaks swagger-cli's partial 3.1 support - check for self-referential $refs first, then 3.1-only syntax (union `type: [x, "null"]` arrays).

### 4. Regenerate the Go client

In `landscape-go-api-client` (expects the spec repo checked out as a sibling):

```bash
cd client && go generate ./...
go build ./... && go test ./...
```

Commit `client.gen.go` on a feature branch. Build failures in `cmd/` after regen mean the spec drifted from what those examples use - check which spec branch you're on before blaming your change.

### 5. Update the consumer

In landscape-mcp: `go get github.com/jansdhillon/landscape-go-api-client@<sha>`, call the typed method, and decide per tool:

- **Raw passthrough** (`ListComputers` + `io.ReadAll`) when the tool returns the upstream JSON verbatim (output parity).
- **Typed handling** (`...WithResponse`, `resp.JSON200`) when the tool filters/transforms.

### 6. PRs

Open the chain bottom-up and cross-link: spec PR -> client PR -> consumer PR. Each body names its consumer and links the layer below.

## Gotchas (learned the hard way)

- **Self-referential schema $refs break `make validate`** with a misleading path-level error. Use a child schema.
- **Direct path->schema $refs** (skipping the response file) break validation. Always go path -> response -> schema.
- **3.1 union types** (`type: ["string", "null"]`) fail swagger-cli; use `nullable: true` per repo convention.
- **Regenerating from the wrong spec branch** silently drops operations other code uses. Check `git branch` in the spec repo first; branch your spec work off `main`.
- **`go generate` runs with CWD = the package dir** (`client/`); running oapi-codegen by hand from elsewhere writes `client.gen.go` to the wrong place.
- The generated client's login providers panic on non-JSON 200 responses - if you hit a nil `JSON200`, check `Content-Type` on your test stub before suspecting your code.
