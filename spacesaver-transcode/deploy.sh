#!/usr/bin/env bash
# deploy.sh — Deploy SpaceSaver Transcoder to Kubernetes.
#
# Usage:
#   ./deploy.sh             # apply (idempotent, safe to re-run)
#   ./deploy.sh --delete    # tear everything down
#
# Prerequisites:
#   - kubectl configured and pointing at the right cluster
#   - manifests/kustomization.yaml edited (namespace, registry, node name)
#   - pv-nas-slow.yaml matches your NFS server/path
set -euo pipefail

MANIFESTS_DIR="$(cd "$(dirname "$0")/manifests" && pwd)"
NAMESPACE="kube-idle"

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
  kubectl delete -f "$MANIFESTS_DIR/pv-nas-slow.yaml"     --ignore-not-found
  kubectl delete -f "$MANIFESTS_DIR/priorityclass.yaml"   --ignore-not-found

  echo "==> Done. Namespace '$NAMESPACE' left intact (delete manually if needed)."
  exit 0
fi

# ── Deploy ────────────────────────────────────────────────────────────────────

# 1. Cluster-scoped: PersistentVolume (no namespace)
echo "==> Applying PersistentVolume…"
kubectl apply -f "$MANIFESTS_DIR/pv-nas-slow.yaml"

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
