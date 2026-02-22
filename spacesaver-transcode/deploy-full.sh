#!/usr/bin/env bash
# deploy.sh — Build (if needed) and deploy SpaceSaver Transcoder to Kubernetes.
#
# Usage:
#   ./deploy-full.sh             # build image if missing, then deploy (idempotent)
#   ./deploy-full.sh --delete    # tear everything down
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
# Namespace and image name
NAMESPACE="kube-idle"
IMAGE_NAME="spacesaver-transcode"

# Version tag: read from app/version.txt
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

  echo "==> Deleting cluster-scoped resources…"
  kubectl delete -f "$MANIFESTS_DIR/priorityclass.yaml" --ignore-not-found

  echo "==> Done. Namespace '$NAMESPACE' left intact."
  exit 0
fi

# ── check_image_exists ────────────────────────────────────────────────────────
check_image_exists() {
  local tag="$1"
  local status
  status=$(curl -sf -o /dev/null -w "%{http_code}" --connect-timeout 5 \
    "http://${REGISTRY_HOST}/v2/${IMAGE_NAME}/manifests/${tag}" || echo "404")

  [[ "$status" == "200" ]]
}

# ── Deploy ────────────────────────────────────────────────────────────────────

echo "==> Targeted image: ${IMAGE_NAME}:${IMAGE_TAG}"

DEPLOY_TAG=""

if check_image_exists "$IMAGE_TAG"; then
  echo "    Found versioned image: ${IMAGE_TAG}"
  DEPLOY_TAG="$IMAGE_TAG"
elif check_image_exists "latest"; then
  echo "    WARNING: Version ${IMAGE_TAG} not found. Falling back to 'latest'."
  DEPLOY_TAG="latest"
else
  echo "ERROR: Neither ${IMAGE_TAG} nor 'latest' found in registry."
  echo "Please run ./build.sh first."
  exit 1
fi

# 2. Cluster-scoped: PriorityClass (no namespace)
echo "==> Applying PriorityClass…"
kubectl apply -f "$MANIFESTS_DIR/priorityclass.yaml"

# 3. Namespace (idempotent)
echo "==> Ensuring namespace '$NAMESPACE' exists…"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# 4. Everything else via Kustomize
echo "==> Applying kustomization (image tag: ${DEPLOY_TAG})…"
(cd "$MANIFESTS_DIR" && kustomize edit set image "${REGISTRY_HOST}/${IMAGE_NAME}:${DEPLOY_TAG}")
kubectl apply -k "$MANIFESTS_DIR"

echo ""
echo "==> Deployed. Checking pod status:"
kubectl -n "$NAMESPACE" get pods,pvc,svc -l app=spacesaver
