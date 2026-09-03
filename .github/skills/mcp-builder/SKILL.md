---
name: mcp-builder
description: Design and build MCP (Model Context Protocol) servers. Use when creating, migrating, or extending an MCP server - choosing tools/resources/prompts, designing schemas, handling auth and config, picking transports, and structuring the implementation. Language-agnostic with Go (modelcontextprotocol/go-sdk) and Python (FastMCP) specifics.
---

# MCP Builder

Guidance for designing and building MCP servers that agents can use reliably. Use this skill whenever you create, migrate, or extend an MCP server.

## Design First: Tools, Resources, Prompts

Decide the surface area before writing code:

- **Tools** are for actions and queries with side effects or computation. Prefer a small set of well-scoped tools over many overlapping ones. Each tool needs: a `snake_case` name, a one-sentence description an agent can route on, and typed parameters with descriptions.
- **Resources** are for read-only data addressable by URI (files, records). Use resource templates for parameterized reads.
- **Prompts** are reusable instruction templates that reference the server's tools. Keep them few and high-value.

Tool design rules:
- Return concise, structured results. Filter and aggregate server-side; never dump unbounded API payloads into context.
- Output JSON strings for structured data; keep human-readable summaries short.
- Make parameters optional where sensible defaults exist; document units and formats in the description.
- Tool names must be stable - agents and saved prompts depend on them. Treat renames as breaking.

## Authentication and Configuration

- Read config from environment variables; fail fast at startup with a clear message listing which variables are missing.
- Never log secrets. Never commit credentials.
- For token-based upstream APIs: acquire the token lazily on first use, attach it to requests, and document refresh/expiry behavior. Note in the spec whether tokens are cached or re-acquired per call.
- Document the exact env var contract in the README and spec (names, defaults, examples).

## Transport and Lifecycle

- Default to **stdio** for local agent integration (VSCode, Copilot CLI). Only add HTTP/SSE when remote hosting is a requirement - it pulls in auth and TLS concerns.
- Handle SIGINT/SIGTERM for graceful shutdown.
- Log to stderr, never stdout (stdout is the protocol channel on stdio).

## Error Handling

- Return tool errors as MCP error results the agent can read, not process crashes.
- Distinguish: config errors (fail at startup), upstream API errors (surface status + message), bad tool input (validation error naming the parameter).
- Timeouts on every upstream HTTP call; document the values.

## Testing and Verification

- Unit-test the API client against recorded or mocked responses.
- Smoke-test the server end to end by listing tools and calling each one (e.g. `mcp-inspect`, or a script over stdio).
- Verify in a real client (VSCode `mcp.json` or equivalent) before shipping.

## Distribution

- Go: single static binary; document build and `mcp.json` entry.
- Python: `uvx`-installable package or Docker image; pin dependencies.

## Go SDK Specifics (github.com/modelcontextprotocol/go-sdk)

- Server: `mcp.NewServer(&mcp.Implementation{Name, Version}, nil)`; run with `s.Run(ctx, &mcp.StdioTransport{})`.
- Tools: `mcp.AddTool(s, &mcp.Tool{Name, Description}, handler)` where handler is `func(ctx, *mcp.CallToolRequest, Params) (*mcp.CallToolResult, Result, error)`. Params/Result are structs with `json` and `jsonschema` tags - the SDK derives the input schema from the struct.
- Resources: `s.AddResource` / `s.AddResourceTemplate` with URI templates.
- Prompts: `s.AddPrompt` with typed `PromptArgument`s.
- Session logging: `req.Session.Log(ctx, &mcp.LoggingMessageParams{...})`.

## Python (FastMCP) Specifics

- `@mcp.tool()` / `@mcp.prompt()` decorators; docstrings become descriptions.
- Run with `mcp.run(transport="stdio")`.

## Migration Checklist (any language port)

1. Inventory the existing server: tools (names, params, output shapes), resources, prompts, auth flow, config vars.
2. Preserve tool names, parameter names, and output formats exactly - behavioral parity.
3. Port the upstream API client first, with tests.
4. Port tools, then resources/prompts.
5. Diff tool listings and sample outputs old vs new.
6. Update README and client configuration docs.
