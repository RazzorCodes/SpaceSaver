#!/usr/bin/env bash
# deploy.sh — Build (if needed) and deploy SpaceSaver Transcoder to Kubernetes.
#
# Usage:
#   ./deploy.sh             # build image if missing, then deploy (idempotent)
#   ./deploy.sh --delete    # tear everything down
#
# Prerequisites:
#   - kubectl configured and pointing at the right cluster
#   - manifests/kustomization.yaml edited (node name, etc.)
#   - nfs-storage-slow StorageClass present in the cluster (dynamic provisioner)
#   - kaniko pre-seeded in the local registry (run once on master node):
#       skopeo copy --dest-tls-verify=false \
#         docker://gcr.io/kaniko-project/executor:latest \
#         docker://127.0.0.1:5000/kaniko/executor:latest
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFESTS_DIR="$SCRIPT_DIR/manifests"

# ── Configuration ─────────────────────────────────────────────────────────────
# Registry running on the master node (hostNetwork, plain HTTP)
REGISTRY_HOST="homelab-master-01:5000"   # <-- CHANGE to master hostname/IP

# Node to run the Kaniko build job on
BUILD_NODE="homelab-worker-01"

# Namespace and image name
NAMESPACE="kube-idle"
IMAGE_NAME="spacesaver"

# Version tag: read from app/version.txt (same source as build.sh)
IMAGE_TAG=$(cat "$SCRIPT_DIR/app/version.txt" | tr -d '[:space:]')

# ── Parse flags ───────────────────────────────────────────────────────────────
DELETE=false
for arg in "$@"; do
  [[ "$arg" == "--delete" ]] && DELETE=true
done

# ── Tear-down ─────────────────────────────────────────────────────────────────
if $DELETE; then
  echo "==> Deleting namespaced resources (kustomize)…"
  kubectl delete -k "$MANIFESTS_DIR" --ignore-not-found

  echo "==> Deleting build job and context ConfigMap (if still around)…"
  kubectl delete job spacesaver-build -n "$NAMESPACE" --ignore-not-found
  kubectl delete configmap spacesaver-build-ctx -n "$NAMESPACE" --ignore-not-found

  echo "==> Deleting cluster-scoped resources…"
  kubectl delete -f "$MANIFESTS_DIR/priorityclass.yaml" --ignore-not-found

  echo "==> Done. Namespace '$NAMESPACE' left intact (delete manually if needed)."
  exit 0
fi

# ── build_if_missing ──────────────────────────────────────────────────────────
build_if_missing() {
  local tag="$1"

  echo "==> Checking registry for ${IMAGE_NAME}:${tag}…"

  local existing
  existing=$(curl -sf --connect-timeout 5 \
    "http://${REGISTRY_HOST}/v2/${IMAGE_NAME}/tags/list" 2>/dev/null \
    | grep -o "\"${tag}\"" || true)

  if [[ -n "$existing" ]]; then
    echo "    Image ${IMAGE_NAME}:${tag} found in registry — skipping build."
    return
  fi

  echo "    Image not found. Packaging build context…"

  # ── Create/update ConfigMap from local files ─────────────────────────────
  # The ConfigMap becomes the /workspace volume inside the Kaniko pod.
  # Key "Dockerfile" = the Containerfile; remaining keys are the app sources.
  kubectl create configmap spacesaver-build-ctx \
    -n "$NAMESPACE" \
    --from-file="Dockerfile=$SCRIPT_DIR/containerfile/spacesaver-transcode" \
    $(for f in "$SCRIPT_DIR/app/"*.py \
               "$SCRIPT_DIR/app/requirements.txt" \
               "$SCRIPT_DIR/app/version.txt"; do
        echo "--from-file=$(basename "$f")=$f"
      done) \
    --dry-run=client -o yaml \
    | kubectl apply -f -

  echo "    Build context uploaded. Launching Kaniko job…"

  # Delete any previous orphaned job
  kubectl delete job spacesaver-build -n "$NAMESPACE" --ignore-not-found --wait=true

  # Render job template (envsubst) and apply
  REGISTRY_HOST="$REGISTRY_HOST" \
  IMAGE_NAME="$IMAGE_NAME" \
  IMAGE_TAG="$tag" \
  BUILD_NODE="$BUILD_NODE" \
    envsubst < "$MANIFESTS_DIR/job-build.yaml" \
    | kubectl apply -f -

  echo "==> Waiting for build to complete (timeout: 30m)…"
  if ! kubectl wait job/spacesaver-build \
      -n "$NAMESPACE" \
      --for=condition=complete \
      --timeout=30m; then
    echo "ERROR: Build job failed or timed out. Logs:"
    kubectl -n "$NAMESPACE" logs job/spacesaver-build --all-containers --tail=100 || true
    exit 1
  fi

  echo "==> Build succeeded: ${REGISTRY_HOST}/${IMAGE_NAME}:${tag}"
}

# ── Deploy ────────────────────────────────────────────────────────────────────

echo "==> Image tag: ${IMAGE_TAG}"

# 1. Build image if not already in registry
build_if_missing "$IMAGE_TAG"

# 2. Cluster-scoped: PriorityClass (no namespace)
echo "==> Applying PriorityClass…"
kubectl apply -f "$MANIFESTS_DIR/priorityclass.yaml"

# 3. Namespace (idempotent)
echo "==> Ensuring namespace '$NAMESPACE' exists…"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# 4. Everything else via Kustomize
echo "==> Applying kustomization…"
kubectl apply -k "$MANIFESTS_DIR"

echo ""
echo "==> Deployed. Checking pod status:"
kubectl -n "$NAMESPACE" get pods,pvc,svc -l app=spacesaver
