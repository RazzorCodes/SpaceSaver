# SpaceSaver Transcode

SpaceSaver is a Kubernetes-native media transcoder designed to automatically optimize your media library for space efficiency by converting videos to H.265 (HEVC) MKV format during system idle times.

## Key Features

- **Space Optimization**: Converts videos to H.265 using `libx265`, significantly reducing file size while maintaining high quality.
- **Smart Decision Making**: Skips files that are already in HEVC format or have a bitrate below a certain threshold to avoid wasteful re-encoding.
- **Kubernetes Native**: Designed to run as a Deployment with `idle-priority`, ensuring it only uses CPU cycles when the node is otherwise idle.
- **Live Mutable Configuration**: Update CRF (Constant Rate Factor) and resolution caps at runtime via API without restarting the pod.
- **REST API**: Simple interface for monitoring status, listing files, and manual enqueueing.

## Important note: Multiple services should not run concurrently due to SQLite database file locking & resulting duplicated work. 
- As this was intended as a last-resort space saving tool, it is not designed to run on multiple nodes.
- What it is really is a fancy ffmpeg call for very lazy people

## Architecture

SpaceSaver consists of:
- **Flask API**: Handles incoming requests and provides status updates.
- **Background Worker**: A dedicated thread that manages the transcode queue and executes `ffmpeg` jobs.
- **SQLite Database**: Tracks file metadata, status (PENDING, QUEUED, IN_PROGRESS, DONE), and transcoding progress.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/version` | Returns the current application version. |
| GET | `/status` | Returns the current transcoder status and progress of the active job. |
| GET | `/list` | Lists all indexed files and their current status. |
| GET | `/list/<uuid>` | Shows details for a specific file. |
| POST | `/request/enqueue/best` | Automatically enqueues the "best" candidate for transcoding (largest non-optimized file). |
| POST | `/request/enqueue/<uuid>` | Enqueues a specific file by its UUID. |

## Configuration

Configuration is loaded from environment variables (typically via a Kubernetes ConfigMap):

- `TV_CRF`: Default CRF for TV shows (Default: `18`).
- `MOVIE_CRF`: Default CRF for movies (Default: `16`).
- `TV_RES_CAP`: Resolution cap for TV shows (e.g., `1080`).
- `MOVIE_RES_CAP`: Resolution cap for movies (e.g., `2160`).

## Setup and Deployment

### Prerequisites
- A Kubernetes cluster.
- `kubectl` configured.
- NFS storage accessible by the cluster for `/source` and `/dest`.

### Build and Push
Use the provided scripts to build and upload the container image to your local registry:
```bash
./spacesaver-transcode/build.sh
./spacesaver-transcode/upload-container.sh
```

### Deploy to Kubernetes
Deploy to Kubernetes using the `deploy-full.sh` script:
```bash
./spacesaver-transcode/deploy-full.sh
```

### Container Deployment (Docker / Podman Compose)
SpaceSaver can also be deployed as a pure container without Kubernetes. A sample `docker-compose.yml` is provided in the `spacesaver-transcode/test` directory.

To run with Compose:
1. Ensure `ffmpeg` is available in your container environment (the build process handles this).
2. Configure your volumes to point to your media library.
3. Run the following:
```bash
cd spacesaver-transcode/test
podman-compose up -d  # or docker-compose up -d
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
