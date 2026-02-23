mkdir -p /tmp/spacesaver-workdir
chmod 777 /tmp/spacesaver-workdir

podman run -d \
  --name spacesaver \
  --replace \
  --network=host \
  --security-opt label=disable \
  -v /mnt/nas-slow/media:/media:rw \
  -v /tmp/spacesaver-workdir:/workdir:rw \
  -e TV_CRF=18 \
  -e MOVIE_CRF=16 \
  -e TV_RES_CAP=1080 \
  -e MOVIE_RES_CAP=2160 \
  -e RESCAN_INTERVAL=600 \
  --cpu-shares=2 \
  localhost/spacesaver-transcode:latest