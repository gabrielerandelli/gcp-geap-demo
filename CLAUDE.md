# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Work is in progress. **Read `NEXT_STEPS.md` at the repo root** for the current state and the concrete plan for the remaining work — it lists exactly what's done (Part 1 local + MCP server on Cloud Run + Agent Registry + Cloud Trace) and what's left (Model Armor, agent deploy to Agent Runtime, optional CI/CD).

Tracked on GitHub: `https://github.com/gabrielerandelli/gcp-geap-demo` (private).

## Goal (from `agent-idea.md`)

Build a Gemini Enterprise Agent Platform (GEAP) demo consisting of:

- **MCP server** exposing the four basic math ops (add/sub/multiply/divide).
  - Implemented with **FastMCP**.
  - Deployed locally **and** to **Cloud Run**.
  - Auth via **service accounts**.
  - Registered in the **Agent Registry**.
- **A2A agent** that talks to the MCP server to perform math.
  - Deployed locally **and** to **Agent Runtime**.
  - Registered in the **Agent Registry**.
  - Identity is a **service account** used to auth against the MCP server.
  - **OpenTelemetry** tracing/logging wired in.
  - **Model Armor** integration for prompt-injection + hate/violence filtering (create templates as needed).

Any GCP-side resources (service accounts, Cloud Run service, Model Armor templates, Agent Registry entries) are in scope. If something cannot be created automatically, stop and surface the blocker.

## Toolchain

- **`agents-cli` v1.1.0** is installed globally at `/home/user/.local/bin/agents-cli`. This is the primary CLI for the whole lifecycle:
  - `agents-cli scaffold create` — create a new agent project (prefer this over hand-rolling structure).
  - `agents-cli install` — install project dependencies (run after scaffolding, and after edits to `pyproject.toml`).
  - `agents-cli playground` — local interactive playground.
  - `agents-cli run` — one-shot non-interactive run.
  - `agents-cli lint` — code-quality checks.
  - `agents-cli eval generate` / `agents-cli eval grade` — evaluation loop.
  - `agents-cli scaffold enhance .` — add deployment / CI-CD to an existing project.
  - `agents-cli deploy` — deploy to Agent Runtime / Cloud Run / GKE. On Agent Runtime this **auto-registers** the agent in the GEAP Agent Registry.
  - `agents-cli info` — inspect current project + CLI state.
  - **Do NOT use `agents-cli publish gemini-enterprise`.** That command registers into a Gemini Enterprise **App** (a Discovery Engine chat frontend), which is out of scope here. See the "GEAP ≠ GE App" lesson below.

- **Google ADK skills** (already available in this Claude Code environment). Use them instead of guessing at ADK APIs:
  - `google-agents-cli-workflow` — always the entrypoint for ADK work; covers the full lifecycle and model selection.
  - `google-agents-cli-scaffold` — creating / enhancing / upgrading projects.
  - `google-agents-cli-adk-code` — writing agent code (agent types, tools, callbacks, state).
  - `google-agents-cli-eval` — eval datasets, LLM-as-judge, failure analysis.
  - `google-agents-cli-deploy` — Agent Runtime / Cloud Run / GKE deployment, service accounts, secrets.
  - `google-agents-cli-publish` — Agent Registry publication (ADK vs A2A modes).
  - `google-agents-cli-observability` — Cloud Trace, prompt/response logging, OpenTelemetry wiring.

## GCP Environment

Preconfigured on the workstation — do not reconfigure without asking. Read the current values at session start with `gcloud config list` rather than hard-coding them here:

- Active gcloud project + account: whatever `gcloud config list` reports.
- Region for all deployments: `us-central1` (regional; needed for Agent Registry MCP registration, which is not supported in `us` multi-region).
- An outbound HTTPS proxy may be present in the workstation env. If a call fails with a SOCKS/proxy error, unset `ALL_PROXY` and let httpx fall back to `HTTPS_PROXY`.

## Environment Constraints

- The container's HOME and most system paths are **read-only**. Writes generally succeed under the project directory and `$TMPDIR`. `npm` in particular fails with `EROFS` against `~/.npm` — expect and ignore that noise from `agents-cli info`; it does not indicate a broken install.
- Git metadata for this repo lives at `$TMPDIR/geap-git` (not `.git/` in the working tree) because the sandbox holds `.git/config` "Device or resource busy". `GIT_DIR=$TMPDIR/geap-git GIT_WORK_TREE=/home/user/loropiana-geap-demo` in front of any git command. `git push` works to a URL directly; `git remote add` does not.

## Working Style for This Project

- **Plan before executing.** The spec explicitly asks for a step-by-step plan before scaffolding, deploying, or touching GCP. Use plan mode for anything beyond a trivial edit.
- **Ask, don't guess**, on ADK/GEAP details. The spec says: if a tool/skill is missing or a requirement is ambiguous, pause and surface it rather than improvising.
- **Prefer `agents-cli` + ADK skills over hand-written boilerplate.** The scaffolded layout, deploy config, and publish flow are the supported paths.

## Lessons learned

Durable knowledge accumulated so far. When something surprises you, add to this section.

### Sandbox / workstation environment

Every session should apply these before doing anything real. `NEXT_STEPS.md` has the exact copy-pasteable one-liners.

- **`gcloud` config**: the persisted workstation config sets `proxy/type=https` which gcloud rejects, and `~/.config/gcloud` is read-only. Fix per session: `cp -r /home/user/.config/gcloud/* $TMPDIR/gcloud-cfg/`, then export `CLOUDSDK_CONFIG=$TMPDIR/gcloud-cfg CLOUDSDK_PROXY_TYPE=http CLOUDSDK_PROXY_ADDRESS=localhost CLOUDSDK_PROXY_PORT=3128`. Expect harmless `WARNING: Could not setup log file in /home/user/.config/gcloud/logs` — the read-only logs dir doesn't break commands.
- **`uv` cache**: `~/.cache/uv` is read-only. `export UV_CACHE_DIR=$TMPDIR/uv-cache`.
- **`cookiecutter`** (used by `agents-cli scaffold create`): needs its replay dir under `$TMPDIR`. Set `COOKIECUTTER_CONFIG=$TMPDIR/cookiecutter.yaml` with `replay_dir` + `cookiecutters_dir` under `$TMPDIR`.
- **FastMCP startup version check** dies on the SOCKS proxy → **always** `export FASTMCP_CHECK_FOR_UPDATES=off`.
- **Python HTTPS clients** pick up `ALL_PROXY=socks5h://…` and blow up with "socksio not installed". Prepend `env -u ALL_PROXY -u all_proxy -u GRPC_PROXY -u grpc_proxy` to `agents-cli run` and any Python call that hits Google APIs. Keep `HTTPS_PROXY=http://localhost:3128` (that's the working HTTP proxy).
- **Each Bash tool call = its own network namespace.** A server started in a background task is NOT reachable from a subsequent Bash call. Test locally by starting server + client in the _same_ shell invocation. For an interactive browser session, the user must run the server via `!<cmd>` on the workstation host — sandbox ports aren't reachable from the Cloud Workstations `https://<port>-$WEB_HOST/` preview.
- **`gh` CLI**: needs explicit `HTTPS_PROXY=http://localhost:3128` on every call (`gh auth status`, `gh repo create`, etc.), otherwise "context deadline exceeded".
- **Git**: see Environment Constraints above.
- **`gcloud auth print-identity-token --audiences=<URL>` fails for user accounts** ("Invalid account type for --audiences. Requires valid service account"). To mint an audience-scoped ID token for Cloud Run, impersonate an SA that has `run.invoker` on the target service: `gcloud auth print-identity-token --impersonate-service-account=<sa>@… --audiences=<URL>`. Grant `roles/iam.serviceAccountTokenCreator` on that SA first, and expect **~30-60s IAM propagation** before the first impersonation call works.
- **`gcloud run deploy --source` uploads the whole directory.** Always ship a `.gcloudignore` in every source directory excluding `.venv/`, `__pycache__/`, `.claude/`, etc. A 100+ MB `.venv` uploading over the sandbox proxy hangs silently for many minutes and never triggers Cloud Build.

### GEAP-specific

- **GEAP ≠ Gemini Enterprise App.** Gemini Enterprise Agent Platform (GEAP) is the underlying platform (Agent Runtime, Agent Registry, Model Armor integration, Agent Gateway). "Gemini Enterprise App" is a Discovery Engine chat frontend (`projects/.../engines/<app>`). This project uses **only GEAP**. Do not create a GE App, do not call `agents-cli publish gemini-enterprise`, do not offer "publish to Gemini Enterprise" as a step. See `.claude/projects/-home-user-loropiana-geap-demo/memory/geap_vs_ge_app.md`.
- **Agent Registry MCP tool spec requires `inputSchema` per tool.** The example in `https://docs.cloud.google.com/agent-registry/register-mcp-servers` omits it, but the API rejects specs without it. Use standard JSON-Schema (`{"type":"object","properties":{...},"required":[...]}`).
- **Agent Registry MCP registration is not supported in `us`/`eu` multi-region.** Use a regional endpoint — `us-central1` is the project default.
- **Agent Runtime auto-registration is `type: CUSTOM`, not `A2A_AGENT`, and there is currently no supported path to a single fully-wired A2A entry on Agent Runtime.** When Vertex creates the reasoning engine, Agent Registry gets one `agents/agentregistry-…` entry with two `HTTP_JSON` interfaces on the reasoning-engine `:query` / `:streamQuery` URLs (native ADK/reasoning-engine contract). `agents-cli deploy` does NOT publish an A2A face (the `is_a2a: true` in `deployment_metadata.json` only feeds `agents-cli publish gemini-enterprise`, out of scope). Manually registering a Service with `--agent-spec-type=a2a-agent-card` DOES create an `A2A_AGENT` catalog entry, but `Agent.attributes` is `readOnly` per the v1 REST schema — so `system/RuntimeIdentity`, `system/RuntimeReference`, and `system/Framework` cannot be attached, leaving the entry with no Identity, no Traces, and no clickable actions in the Agent Platform UI. `bindings` is for source→target/auth-provider delegation, not for wiring runtime attributes. **Practical takeaway**: on Agent Runtime, use the auto-registered CUSTOM entry as the operational face; a proper A2A face requires redeploying to Cloud Run / GKE (where A2A is the default and only registration type per the publish skill). MCP servers on Cloud Run also need manual registration (`gcloud agent-registry services create <name> --mcp-server-spec-type=tool-spec --mcp-server-spec-content=<file> --interfaces=url=...,protocolBinding=JSONRPC`).
- **Cloud Run auth = ID token, not access token.** Callers must send `Authorization: Bearer <id_token>` where the JWT's `aud` claim is the service URL. The caller principal needs `roles/run.invoker` on the specific service.

- **Memory Bank rides on the same reasoning engine as the agent** — no separate resource needed. Pass the runtime ID (auto-injected as `GOOGLE_CLOUD_AGENT_ENGINE_ID` on Agent Runtime) to `VertexAiMemoryBankService(project, location, agent_engine_id)`, and to `VertexAiSessionService` with the same value. `math-agent-sa`'s existing `roles/aiplatform.reasoningEngineServiceAgent` already carries `aiplatform.memories.generate/retrieve` — no IAM changes needed. Critical detail: `add_events_to_memory(...)` defaults to buffered `ingest_events` which does NOT auto-generate facts; to force synchronous `memories.generate` (facts appear immediately) pass `custom_metadata={"wait_for_completion": True}`. Also: the default extractor only surfaces personal info / preferences — pure arithmetic events produce zero memories, which is correct behavior, not a bug.

### MCP + Cloud Trace observability

The GEAP Observability tab requires MCP servers to emit spans with a specific attribute schema (docs: `https://docs.cloud.google.com/mcp/monitor-mcp-tool-use-with-cloud-trace`). Only `tools/call` spans are surfaced; only W3C `traceparent` headers are honoured. Required attributes:

- **Resource**: `cloud.provider=gcp`, `cloud.account.id`, `gcp.project_id`, `gcp.mcp.server.id` (per docs this is the URN of the MCP server — use the `mcpServerId` field returned by `gcloud alpha agent-registry mcp-servers describe`, which has the form `urn:mcp:projects-{num}:projects:{num}:locations:{loc}:agentregistry:services:{id}`). **Status 2026-07-24**: even with the URN set, the Agent Registry "Observability" tab reports no data — root cause not confirmed yet (likely the missing `gcp.server.service` scope attribute, or a required Auth Provider Binding, or some other schema/routing requirement not documented on the tracing page).
- **Span**: `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name=<tool>`, `mcp.method.name=tools/call`, `mcp.protocol.version`, `jsonrpc.protocol.version`, plus `error.type`/`error.message` on failures.

Implementation pattern that works: `FastMCP` `Middleware.on_call_tool` starts an OTel span with these attributes; `StarletteInstrumentor.instrument_app(mcp.http_app(...))` extracts `traceparent` from incoming HTTP; `BatchSpanProcessor(CloudTraceSpanExporter(project_id=...))` exports. See `math-mcp-server/server.py` for a working reference.

### FastMCP specifics (v3.4)

- ASGI app builder is `mcp.http_app(path="/mcp", transport="http")` — **not** `streamable_http_app()` (that doesn't exist).
- FastMCP does its own OTel emission via `fastmcp/telemetry.py` when a `TracerProvider` is set — you'll see extra `fastmcp.*` spans alongside your middleware's spans. That's fine.

### Python packaging quirks encountered

- `google-cloud-modelarmor` and `opentelemetry-exporter-gcp-trace` transitively depend on `opentelemetry-resourcedetector-gcp` whose stable 1.13.0 was yanked, forcing the pre-release resolver. In `pyproject.toml`, add `[tool.uv] prerelease = "allow"`; in the Dockerfile, use `pip install --pre .`.
- The scaffolded agent's `google-adk[gcp]` extra does **not** include the `mcp` extra. Add `google-adk[gcp,mcp]` (and `[gcp,mcp,otel-gcp]` when you wire up Cloud Trace on the agent side).

### Anti-goals — do not do these

- Do not put GCP project ID, admin email, or workstation-specific values in tracked files. They were leaked once in a public repo and had to be deleted. Session-specific values belong in `.env` or `gcloud config`.
- Do not change the Gemini model (`gemini-flash-latest`) without being asked — the workflow skill's Principle 1 (Code Preservation), and the user has already confirmed this choice.
- Do not run destructive `gcloud` commands (`… delete`) without explicit user approval, even during rollback / re-deploy loops.
