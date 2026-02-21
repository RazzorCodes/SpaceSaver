podman run -d \
  --name spacesaver \
  --replace \
  -p 8000:8000 \
  -v /mnt/nas-slow/media:/source:ro \
  -v /mnt/nas-slow/media:/dest:rw \
  -v /tmp/spacesaver-workdir:/workdir:rw \
  -e TV_CRF=18 \
  -e MOVIE_CRF=16 \
  -e TV_MAX_RESOLUTION=1080 \
  -e MOVIE_MAX_RESOLUTION=2160 \
  -e RESCAN_INTERVAL_MINUTES=10 \
  --cpu-shares=2 \
  localhost/spacesaver-transcode:latest