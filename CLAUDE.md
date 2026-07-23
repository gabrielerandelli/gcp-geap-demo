# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

This repository currently contains only a specification (`agent-idea.md`). No agent project has been scaffolded yet. The first meaningful action for most tasks is to bootstrap the code with `agents-cli scaffold create` (or `agents-cli create`), not to hand-write files.

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
  - `agents-cli deploy` — deploy to Agent Runtime / Cloud Run / GKE.
  - `agents-cli publish gemini-enterprise` — register in the Agent Registry.
  - `agents-cli info` — inspect current project + CLI state.

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
- No git repository is initialized in this directory yet. Do not assume `git` commands work until one exists.

## Working Style for This Project

- **Plan before executing.** The spec explicitly asks for a step-by-step plan before scaffolding, deploying, or touching GCP. Use plan mode for anything beyond a trivial edit.
- **Ask, don't guess**, on ADK/GEAP details. The spec says: if a tool/skill is missing or a requirement is ambiguous, pause and surface it rather than improvising.
- **Prefer `agents-cli` + ADK skills over hand-written boilerplate.** The scaffolded layout, deploy config, and publish flow are the supported paths.
