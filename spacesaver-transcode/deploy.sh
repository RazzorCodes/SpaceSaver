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
REGISTRY_HOST="192.168.0.127:5000"   # <-- CHANGE to master hostname/IP

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

  # ── Wait for the pod to be schedulable / running ────────────────────────
  echo "==> Waiting for build pod to start…"
  local build_pod=""
  for i in $(seq 1 72); do   # 72 × 5s = 6 min max wait for scheduling
    build_pod=$(kubectl -n "$NAMESPACE" get pods \
      -l job-name=spacesaver-build \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [[ -n "$build_pod" ]]; then
      local phase
      phase=$(kubectl -n "$NAMESPACE" get pod "$build_pod" \
        -o jsonpath='{.status.phase}' 2>/dev/null || true)
      [[ "$phase" == "Running" || "$phase" == "Succeeded" || "$phase" == "Failed" ]] && break
    fi
    echo "    ($i) pod not ready yet — retrying in 5s…"
    sleep 5
  done

  if [[ -z "$build_pod" ]]; then
    echo "ERROR: Build pod never started. Check node/image/configmap."
    kubectl -n "$NAMESPACE" describe job spacesaver-build || true
    exit 1
  fi

  # ── Stream logs live ──────────────────────────────────────────────────────
  echo "==> Streaming Kaniko build logs (pod: $build_pod)…"
  echo "────────────────────────────────────────────────────"
  kubectl -n "$NAMESPACE" logs -f "$build_pod" --all-containers || true
  echo "────────────────────────────────────────────────────"

  # ── Check final job outcome ───────────────────────────────────────────────
  if kubectl wait job/spacesaver-build \
      -n "$NAMESPACE" \
      --for=condition=complete \
      --timeout=60s 2>/dev/null; then
    echo "==> Build succeeded: ${REGISTRY_HOST}/${IMAGE_NAME}:${tag}"
  else
    echo "ERROR: Build job failed. Last 50 lines:"
    kubectl -n "$NAMESPACE" logs "$build_pod" --all-containers --tail=50 || true
    exit 1
  fi
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
