#!/usr/bin/env bash
# One-time setup for the tag-triggered GitHub Actions release pipeline.
#
# Provisions: WIF pool + OIDC provider (locked to a single GitHub repo),
# a deployer service account, and the IAM bindings the workflow needs.
#
# Idempotent: every gcloud step guards with `describe || create` and IAM
# grants use `add-iam-policy-binding` which is a no-op when the binding
# already exists.
#
# Prereqs:
#   - `gcloud auth login` as a principal with Owner or equivalent on the project.
#   - The runtime SAs (math-agent-sa, math-mcp-sa) already exist.
#   - The MCP server is already registered in Agent Registry.
#   - `git remote get-url origin` points at the target GitHub repo.
#
# Usage:
#   bash scripts/bootstrap-cicd.sh
#   PROJECT_ID=my-proj GITHUB_REPO=owner/repo REGION=us-central1 bash scripts/bootstrap-cicd.sh
#
# At the end, prints the exact GitHub repo variables to add.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
GITHUB_REPO="${GITHUB_REPO:-$(git remote get-url origin 2>/dev/null | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')}"
REGION="${REGION:-us-central1}"

if [ -z "${PROJECT_ID}" ]; then
  echo "ERROR: PROJECT_ID not set and \`gcloud config get-value project\` is empty." >&2
  echo "Run \`gcloud config set project <id>\` or export PROJECT_ID=<id>." >&2
  exit 1
fi
if [ -z "${GITHUB_REPO}" ] || [[ "${GITHUB_REPO}" != */* ]]; then
  echo "ERROR: GITHUB_REPO must be 'owner/repo'. Got '${GITHUB_REPO}'." >&2
  echo "Set the origin remote or export GITHUB_REPO=owner/repo." >&2
  exit 1
fi

POOL_ID="github-pool"
PROVIDER_ID="github-provider"
DEPLOYER_SA_NAME="github-deployer"
AGENT_SA="math-agent-sa@${PROJECT_ID}.iam.gserviceaccount.com"
MCP_SA="math-mcp-sa@${PROJECT_ID}.iam.gserviceaccount.com"
MODEL_ARMOR_TEMPLATE="projects/${PROJECT_ID}/locations/${REGION}/templates/math-agent-armor"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
DEPLOYER_SA="${DEPLOYER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "▶ Project:        ${PROJECT_ID} (${PROJECT_NUMBER})"
echo "▶ GitHub repo:    ${GITHUB_REPO}"
echo "▶ Region:         ${REGION}"
echo "▶ Deployer SA:    ${DEPLOYER_SA}"
echo

echo "== 1. Enable iamcredentials API =="
gcloud services enable iamcredentials.googleapis.com --project="${PROJECT_ID}"

echo
echo "== 2. WIF pool =="
if ! gcloud iam workload-identity-pools describe "${POOL_ID}" \
    --location=global --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "${POOL_ID}" \
    --location=global --project="${PROJECT_ID}" \
    --display-name="GitHub Actions"
else
  echo "  pool ${POOL_ID} already exists — skipping"
fi

echo
echo "== 3. WIF OIDC provider (locked to ${GITHUB_REPO}) =="
if ! gcloud iam workload-identity-pools providers describe "${PROVIDER_ID}" \
    --workload-identity-pool="${POOL_ID}" --location=global \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
    --workload-identity-pool="${POOL_ID}" --location=global \
    --project="${PROJECT_ID}" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'"
else
  echo "  provider ${PROVIDER_ID} already exists — skipping"
fi

echo
echo "== 4. Deployer SA =="
if ! gcloud iam service-accounts describe "${DEPLOYER_SA}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${DEPLOYER_SA_NAME}" \
    --project="${PROJECT_ID}" \
    --display-name="GitHub Actions release deployer"
else
  echo "  SA ${DEPLOYER_SA} already exists — skipping"
fi

echo
echo "== 5. Project-level roles on deployer SA =="
for ROLE in \
  roles/aiplatform.user \
  roles/run.developer \
  roles/artifactregistry.writer \
  roles/cloudbuild.builds.editor \
  roles/storage.admin \
  roles/logging.viewer; do
  echo "  ${ROLE}"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER_SA}" --role="${ROLE}" \
    --condition=None --quiet >/dev/null
done

echo
echo "== 6. iam.serviceAccountUser on runtime SAs (needed to attach them at deploy) =="
for TARGET in "${AGENT_SA}" "${MCP_SA}"; do
  echo "  ${TARGET}"
  gcloud iam service-accounts add-iam-policy-binding "${TARGET}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER_SA}" \
    --role=roles/iam.serviceAccountUser --quiet >/dev/null
done

echo
echo "== 7. WIF principal → workloadIdentityUser on deployer SA =="
FEDERATED_PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPO}"
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_SA}" \
  --project="${PROJECT_ID}" \
  --member="${FEDERATED_PRINCIPAL}" \
  --role=roles/iam.workloadIdentityUser --quiet >/dev/null
echo "  ${FEDERATED_PRINCIPAL}"

echo
echo "== 8. Resolve MCP server name + URN =="
MCP_INFO="$(gcloud alpha agent-registry mcp-servers list \
  --project="${PROJECT_ID}" --location="${REGION}" \
  --format='value(name,mcpServerId)' | head -n1)"
MCP_SERVER_NAME="$(echo "${MCP_INFO}" | awk '{print $1}')"
MCP_SERVER_URN="$(echo "${MCP_INFO}" | awk '{print $2}')"
if [ -z "${MCP_SERVER_NAME}" ]; then
  echo "  ⚠ No MCP server found in Agent Registry — register one first, then re-run."
fi

WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"

cat <<EOF

╔════════════════════════════════════════════════════════════════════════════╗
║  Done. Now add the following as GitHub Actions repository variables:      ║
║    Settings → Secrets and variables → Actions → Variables (New variable)  ║
║                                                                            ║
║  Or via gh CLI:                                                            ║
║    gh variable set NAME --body "VALUE" --repo ${GITHUB_REPO}
╚════════════════════════════════════════════════════════════════════════════╝

GCP_PROJECT_ID       = ${PROJECT_ID}
GCP_PROJECT_NUMBER   = ${PROJECT_NUMBER}
GCP_REGION           = ${REGION}
WIF_PROVIDER         = ${WIF_PROVIDER}
DEPLOYER_SA          = ${DEPLOYER_SA}
AGENT_SA             = ${AGENT_SA}
MCP_SA               = ${MCP_SA}
MCP_SERVER_NAME      = ${MCP_SERVER_NAME}
MCP_SERVER_URN       = ${MCP_SERVER_URN}
MODEL_ARMOR_TEMPLATE = ${MODEL_ARMOR_TEMPLATE}

After adding the variables, cut a test tag to verify:
    git tag -a v0.0.1-cicd-test -m "CI verification"
    git push origin v0.0.1-cicd-test
    gh run watch
EOF
