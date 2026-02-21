#!/usr/bin/env bash
# upload-container.sh — Upload a locally built container image to a remote registry.
#
# Usage:
#   ./upload-container.sh --source localhost/spacesaver-transcode:v1.0.1 --dest 192.168.0.127:5000/spacesaver:v1.0.1

set -euo pipefail

SOURCE=""
DEST=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      SOURCE="$2"
      shift 2
      ;;
    --dest)
      DEST="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 --source <source> --dest <dest>"
      exit 1
      ;;
  esac
done

if [[ -z "$SOURCE" || -z "$DEST" ]]; then
  echo "Error: Both --source and --dest are required."
  echo "Usage: $0 --source <source_image> --dest <dest_image>"
  echo "Example: $0 --source localhost/spacesaver-transcode:latest --dest 192.168.0.127:5000/spacesaver:latest"
  exit 1
fi

echo "==> Uploading container image..."
echo "    Source: $SOURCE"
echo "    Dest:   $DEST"

# Copy from local podman (containers-storage) to remote registry
skopeo copy --dest-tls-verify=false "containers-storage:${SOURCE}" "docker://${DEST}"

echo "==> Upload complete!"
