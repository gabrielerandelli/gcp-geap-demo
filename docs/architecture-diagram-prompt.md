# Nano-Banana prompts — GEAP demo architecture diagrams

This file contains two independent, self-contained image-generation prompts for **nano banana** (Gemini 2.5 Flash Image). Each prompt renders one diagram of the deployed Gemini Enterprise Agent Platform (GEAP) demo:

1. **Diagram 1 — Runtime flow.** How a user request travels through the deployed system.
2. **Diagram 2 — CI/CD + deployment.** How GitHub Actions provisions and updates that system.

**How to use.** Copy one prompt block at a time (from `START PROMPT` to `END PROMPT`) into nano banana. The two prompts share a common visual language section — repeated verbatim inside each block so they can be used independently and still produce a matching pair. If the first render is off, see the **Iteration hints** at the bottom of this file.

---

## Diagram 1 — Runtime flow

```
START PROMPT ─────────────────────────────────────────────────────

Generate a clean, high-legibility Google Cloud reference architecture diagram
titled "GEAP Demo — Runtime Flow". Landscape 16:9 canvas, white background,
no decorative shading, no drop shadows, no 3D. Use official Google Cloud
product iconography (the colored hexagon-style icons from cloud.google.com):
Cloud Run, Vertex AI, Cloud Trace, Cloud Logging, Cloud Storage, IAM, and
generic "GCP product" hexagons for services that don't have a public icon
(Agent Registry, Agent Runtime / Reasoning Engine, Agent Identity, Model
Armor, Memory Bank). Sans-serif labels (Product Sans / Google Sans style),
14pt minimum. Thin (1.5px) arrows with small filled arrowheads. Arrow labels
sit above the arrow in 11pt italic. All numbered flow-arrow badges are small
filled circles with white numerals.

── Canvas layout ─────────────────────────────────────────────────

Left edge: a single "User" person icon labeled "User" at vertical center.
Right edge: one small external cloud icon labeled "freecurrencyapi.com".

Center of canvas: one large rounded rectangle outlined in Google blue
(#1a73e8) with a translucent light-blue fill (#e8f0fe), title bar top-left:
"Google Cloud · project: <PROJECT_ID> · region: us-central1".

Inside that project box, arrange four sub-container rounded rectangles
(outlined in medium gray #5f6368, white fill, header label in bold):

  TOP-LEFT sub-container — "GEAP control plane"
    · Agent Registry            (icon: purple hexagon "AR")
    · Agent Runtime             (icon: purple hexagon "Reasoning Engine
                                  <REASONING_ENGINE_ID>")
    · Model Armor               (icon: red shield hexagon,
                                  "template: math-agent-armor")
    · Memory Bank               (icon: purple hexagon "MB",
                                  small caption: "same reasoning engine")
    · Agent Identity            (icon: gray key hexagon,
                                  "authProvider: currency-freeapi (apiKey)")

  TOP-RIGHT sub-container — "Vertex AI"
    · Gemini model              (Vertex AI icon,
                                  label: "gemini-flash-latest")

  BOTTOM-LEFT sub-container — "Compute"
    · Cloud Run service         (Cloud Run icon,
                                  label: "math-mcp",
                                  caption: "FastMCP · /mcp · JSON-RPC 2.0")

  BOTTOM-RIGHT sub-container — "Observability"
    · Cloud Trace               (Cloud Trace icon)
    · Cloud Logging             (Cloud Logging icon)
    · Cloud Storage bucket      (Cloud Storage icon,
                                  label: "gs://…/completions/")

Anchor a small IAM strip at the bottom of the project box (outside the four
sub-containers) containing two IAM identity chips:
    · math-agent-sa      (IAM icon, caption: "agent runtime identity")
    · math-mcp-sa        (IAM icon, caption: "MCP runtime identity")

── Connection map (draw numbered arrows in this order) ───────────

Each arrow has a small numbered badge at its midpoint, and a short italic
label above it in the form "<transport> / <auth>".

  ①  User  →  Agent Runtime
        label: "HTTPS · :query / :streamQuery"

  ②  Agent Runtime  →  Model Armor
        label: "sanitize_user_prompt · before_model_callback"

  ③  Agent Runtime  →  Gemini (Vertex AI)
        label: "call_llm"

  ④  Agent Runtime  →  Agent Registry
        label: "get_mcp_toolset — discover endpoint"

  ⑤  Agent Runtime  →  Cloud Run math-mcp   (make this arrow the thickest)
        label: "JSON-RPC · ID token (aud=Cloud Run URL) · traceparent"
        small tag near the arrow: "math-agent-sa · roles/run.invoker"

  ⑥  Cloud Run math-mcp  →  Cloud Trace
        label: "execute_tool span · GEAP schema (gen_ai.*, mcp.*)"

  ⑦  Agent Runtime  →  Cloud Trace
        label: "agent spans · same traceId (HTTPXClientInstrumentor)"

  ⑧  Agent Runtime  →  Model Armor
        label: "sanitize_model_response · after_model_callback"

  ⑨  Agent Runtime  →  Memory Bank
        label: "add_events_to_memory · wait_for_completion=True"

  ⑩  Agent Runtime  →  Agent Identity  →  freecurrencyapi.com
        (two-hop arrow crossing the project boundary on the right)
        label on first hop:  "retrieve_credentials"
        label on second hop: "REST · X-GOOG-API-KEY"

  ⑪  Agent Runtime  →  Cloud Logging / Cloud Storage
        label: "prompt/response bodies · OTel GenAI GCS uploader"

── Legend (bottom-right corner, small) ───────────────────────────

Three legend rows:
  · Solid blue arrow      = synchronous request/response
  · Dashed gray arrow     = telemetry export (use dashed style for ⑥, ⑦, ⑪)
  · Small IAM chip        = runtime service-account identity

Bottom-left corner, in small gray caption text:
    "GEAP demo · runtime view · us-central1"

Do NOT invent components not listed above. Do NOT add Kubernetes, Pub/Sub,
BigQuery, load balancers, or generic "database" icons. The diagram must
render exactly the elements and arrows specified above.

END PROMPT ───────────────────────────────────────────────────────
```

---

## Diagram 2 — CI/CD + deployment

```
START PROMPT ─────────────────────────────────────────────────────

Generate a clean, high-legibility Google Cloud reference architecture diagram
titled "GEAP Demo — CI/CD & Deployment". Landscape 16:9 canvas, white
background, no decorative shading, no drop shadows, no 3D. Same visual
language as the runtime diagram: official Google Cloud product iconography
(Cloud Run, Cloud Build, Artifact Registry, Vertex AI, IAM) and generic
"GCP product" hexagons for services that don't have a public icon (Agent
Registry, Agent Runtime, Workload Identity Federation pool). Sans-serif
labels (Product Sans / Google Sans style), 14pt minimum. Thin (1.5px)
arrows with small filled arrowheads. Arrow labels sit above the arrow in
11pt italic. Numbered flow-arrow badges are small filled circles with
white numerals.

── Canvas layout ─────────────────────────────────────────────────

Left column (outside the GCP project box):
    · Developer icon (person)   label: "Developer"
        arrow down to ↓
    · GitHub icon (Octocat)     label: "GitHub · gabrielerandelli/gcp-geap-demo"
        arrow down to ↓
    · GitHub Actions icon       label: "release.yaml (tag v*)"
        caption below in small text:
        "two parallel jobs:  deploy-mcp   |   deploy-agent"

Center + right of canvas: one large rounded rectangle outlined in Google
blue (#1a73e8), translucent light-blue fill (#e8f0fe), title bar top-left:
"Google Cloud · project: <PROJECT_ID> · region: us-central1".

Inside the project box, arrange the following elements in three horizontal
bands, top to bottom:

  BAND 1 — Auth (top strip)
    · Workload Identity Federation pool  (gray hexagon "WIF")
        caption: "trusts principalSet://…/attribute.repository/
                  gabrielerandelli/gcp-geap-demo"
    · Service account chip: "github-deployer@…"  (IAM icon)
        caption (small, wrapped):
          "roles/aiplatform.user, run.developer, artifactregistry.writer,
           cloudbuild.builds.editor, storage.admin
           + iam.serviceAccountUser on runtime SAs"

  BAND 2 — Build & artifact (middle strip)
    · Cloud Build icon           label: "Cloud Build"
        caption: "gcloud run deploy --source math-mcp-server/"
    · Artifact Registry icon     label: "Artifact Registry"

  BAND 3 — Runtime targets (bottom strip, two sub-boxes)

    LEFT sub-box — "MCP path"
      · Cloud Run icon           label: "math-mcp"
      · IAM chip                 label: "math-mcp-sa (runtime identity)"

    RIGHT sub-box — "Agent path"
      · Vertex AI Agent Runtime  (purple hexagon "Reasoning Engine")
                                 caption: "agents-cli deploy from math-agent/"
      · IAM chip                 label: "math-agent-sa (runtime identity)"
      · Agent Registry           (purple hexagon "AR")
                                 caption: "auto-register · type: CUSTOM ·
                                          HTTP_JSON  :query / :streamQuery"

Small callout box in the bottom-right corner, outlined in dashed gray, NOT
connected by any arrow to the main flow, caption in italic gray:
    "Terraform  (math-agent/deployment/terraform/single-project/)
     present but NOT the live deploy path
     — CI/CD uses gcloud + agents-cli"

── Connection map (draw numbered arrows in this order) ───────────

  ①  Developer  →  GitHub
        label: "git push tag v*"

  ②  GitHub  →  GitHub Actions runner
        label: "tag trigger fires release.yaml"

  ③  GitHub Actions runner  →  Workload Identity Federation pool
        (arrow crosses into the GCP project box)
        label: "OIDC · google-github-actions/auth@v2 · no secret keys"

  ④  WIF pool  →  github-deployer SA
        label: "impersonate"

  ⑤a github-deployer SA  →  Cloud Build
        label: "deploy-mcp job · build image"

  ⑤b github-deployer SA  →  Vertex AI Agent Runtime
        label: "deploy-agent job · agents-cli deploy"

  ⑥  Cloud Build  →  Artifact Registry
        label: "push container image"

  ⑦  Artifact Registry  →  Cloud Run math-mcp
        label: "pull image · new revision"
        small tag: "runtime identity: math-mcp-sa"

  ⑧  Vertex AI Agent Runtime  (self-loop or short right-arrow inside sub-box)
        label: "new reasoning-engine revision"
        small tag: "runtime identity: math-agent-sa"

  ⑨  Vertex AI Agent Runtime  →  Agent Registry
        label: "auto-register · type: CUSTOM"

Additionally draw two thin dotted lines (no numbers, no arrowhead) from the
github-deployer SA chip to each runtime SA chip (math-mcp-sa, math-agent-sa),
each labeled in tiny gray text: "iam.serviceAccountUser (act as)".

── Legend (bottom-left corner, small) ────────────────────────────

Three legend rows:
  · Solid blue arrow      = deploy-time action
  · Dotted gray line      = IAM impersonation permission
  · IAM chip              = service-account identity

Bottom-right corner (below the Terraform callout), in small gray caption:
    "GEAP demo · CI/CD view · us-central1"

Do NOT invent components not listed above. Do NOT add Kubernetes, GKE, Cloud
Deploy, Pub/Sub, or a separate staging environment. The diagram must render
exactly the elements and arrows specified above.

END PROMPT ───────────────────────────────────────────────────────
```

---

## Iteration hints

Nano banana usually gets the layout right on the first try but occasionally slips on the details. Common misses and quick fixes:

- **Wrong icon for Agent Runtime / Agent Registry / Model Armor / Memory Bank / Agent Identity.** These are GEAP surfaces without public GCP icons. If the render invents wrong icons, add to the prompt: _"For Agent Runtime, Agent Registry, Model Armor, Memory Bank, and Agent Identity, use identical generic purple/red hexagons with the two-letter monogram inside — do not use any pre-existing icon set."_
- **Arrow labels missing or truncated.** Re-run and add: _"Every numbered arrow must show its full italic label. If a label is long, wrap it onto two lines rather than shrinking the text."_
- **Container boxes dropped or merged.** Add: _"Preserve every sub-container as a separately outlined rounded rectangle with a header label. Do not merge sub-containers."_
- **Extra invented services** (BigQuery, Pub/Sub, GKE). Re-run and repeat the closing constraint: _"Render exactly the elements listed. Do not add any component that is not named in the prompt."_
- **User / Developer / GitHub placed inside the GCP project box.** Add: _"The User (Diagram 1) and the Developer/GitHub/GitHub Actions column (Diagram 2) live outside the Google Cloud project rectangle. Only the Workload Identity Federation pool is the first element inside the project."_
- **Text too small to read.** Add: _"Minimum font size 14pt for element labels, 11pt for arrow labels. Prioritize legibility over fitting everything — trim captions if needed."_

## Source-of-truth values used in the prompts

Should you need to tweak the prompts, these identifiers come from the live deployment (`NEXT_STEPS.md`, `math-agent/deployment_metadata.json`, `math-mcp-server/server.py`, `.github/workflows/release.yaml`):

| Field                        | Value                                                                     |
| ---------------------------- | ------------------------------------------------------------------------- |
| GCP project                  | `<PROJECT_ID>`                                                            |
| Region                       | `us-central1`                                                             |
| Reasoning engine ID          | `<REASONING_ENGINE_ID>`                                                   |
| Cloud Run service URL        | `https://math-mcp-<PROJECT_NUMBER>.us-central1.run.app` (endpoint `/mcp`) |
| Model                        | `gemini-flash-latest`                                                     |
| Model Armor template         | `math-agent-armor` (endpoint `modelarmor.us-central1.rep.googleapis.com`) |
| Agent Identity auth provider | `currency-freeapi` (apiKey)                                               |
| Runtime SAs                  | `math-agent-sa`, `math-mcp-sa`                                            |
| CI/CD SA                     | `github-deployer@…`                                                       |
| GitHub repo                  | `gabrielerandelli/gcp-geap-demo`                                          |
| Workflow file                | `.github/workflows/release.yaml` (trigger: tag `v*`)                      |
