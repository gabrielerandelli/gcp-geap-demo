# math-mcp-server

FastMCP server exposing four arithmetic tools (`add`, `sub`, `multiply`, `divide`) for the GEAP math-agent demo. Transport: **Streamable HTTP** on `/mcp`.

## Run locally

```bash
uv run --with 'fastmcp~=3.4' python server.py
# listens on http://localhost:8080/mcp
```

The server has no built-in auth. Locally that's fine; on Cloud Run it will run behind `--no-allow-unauthenticated`, so only principals holding `roles/run.invoker` can reach it.

## Files

- `server.py` — FastMCP server (Streamable HTTP transport).
- `toolspec.json` — tool specification uploaded to the Agent Registry when registering this MCP server.
- `Dockerfile` — container image for Cloud Run.
- `pyproject.toml` — Python packaging metadata.
