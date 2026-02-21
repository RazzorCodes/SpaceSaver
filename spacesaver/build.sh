

echo "==================================="
echo " Building - Spacesaver (Transcode)"
echo "==================================="

podman build -t spacesaver-transcode:latest -f containerfile/spacesaver-transcode app
