#!/usr/bin/env bash
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
VERSION_FILE="app/version.txt"
REGISTRY="zot.lan:5000"
NEW_VERSION=""

# ── Parse Arguments ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    -ver|--version)
      NEW_VERSION="$2"
      shift 2
      ;;
    -r|--registry)
      REGISTRY="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

# ── Determine version ─────────────────────────────────────────────────────────
if [ -z "$NEW_VERSION" ]; then
    # Read current version and auto-increment
    CURRENT=$(cat "$VERSION_FILE" | tr -d '[:space:]')

    # Parse vMAJOR.MINOR.PATCH[-SUFFIX]
    # e.g. v0.0.0-alpha  →  MAJOR=0 MINOR=0 PATCH=0 SUFFIX=alpha
    SEMVER=$(echo "$CURRENT" | grep -oP '\d+\.\d+\.\d+')
    SUFFIX=$(echo "$CURRENT" | grep -oP '(?<=-)\w+' || true)
    MAJOR=$(echo "$SEMVER" | cut -d. -f1)
    MINOR=$(echo "$SEMVER" | cut -d. -f2)
    PATCH=$(echo "$SEMVER" | cut -d. -f3)

    # Increment patch
    PATCH=$((PATCH + 1))

    if [ -n "$SUFFIX" ]; then
        NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}-${SUFFIX}"
    else
        NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}"
    fi

    echo "$NEW_VERSION" > "$VERSION_FILE"
else
    echo "Using manual version: $NEW_VERSION"
    # Optional: Update version file anyway? The request says "use string as version instead", 
    # but "do not autoincrement". It doesn't explicitly say whether to update version.txt.
    # Usually, it's good to keep it in sync.
    echo "$NEW_VERSION" > "$VERSION_FILE"
fi

# ── Build ─────────────────────────────────────────────────────────────────────
echo "==================================="
echo " Building - Spacesaver (Transcode)"
echo " Version:  $NEW_VERSION"
echo " Registry: $REGISTRY"
echo "==================================="

podman build \
    --build-arg CACHE_BUST="$(date +%s)" \
    -t "spacesaver-transcode:${NEW_VERSION}" \
    -t "spacesaver-transcode:latest" \
    -f containerfile/spacesaver-transcode \
    app

echo "Done: spacesaver-transcode:${NEW_VERSION} (also tagged :latest)"

# ── Upload ────────────────────────────────────────────────────────────────────
IMAGE="spacesaver-transcode"

echo "==> Uploading versioned image..."
./upload-container.sh --source "localhost/${IMAGE}:${NEW_VERSION}" --dest "${REGISTRY}/${IMAGE}:${NEW_VERSION}"

echo "==> Uploading latest image..."
./upload-container.sh --source "localhost/${IMAGE}:latest" --dest "${REGISTRY}/${IMAGE}:latest"

echo "==================================="
echo " Build & Upload Complete"
echo " Version: $NEW_VERSION"
echo "==================================="
