# SpaceSaver Transcode

SpaceSaver is a media transcoder designed to automatically optimize your media library for space efficiency by converting videos to H.265 (HEVC) MKV format.

## Key Features

- **Space Optimization**: Converts videos to H.265 using `libx265`, significantly reducing file size while maintaining high quality.
- **Background Orchestration**: Smart thread pooling through a central Governor ensures background tasks don't block the API.
- **REST API**: Simple interface for monitoring status, scanning media, and enqueuing files for transcode.
- **SQLite Database Tracking**: Tracks file metadata, resolution, duration, codec, and status (UNKNOWN, PENDING, PROCESSING, DONE, ERROR, ABORTED).
- **Graceful Shutdowns & Safety**: Safe against early termination with proper task cleanup and temporary intermediate files to prevent corrupting source media.

## Important note: Multiple services should not run concurrently due to SQLite database file locking & resulting duplicated work.
- It is not designed to run on multiple nodes or scale horizontally against a single SQLite instances.
- What it is really is a fancy ffmpeg orchestrator for very lazy people.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/version` | Returns the current application version container label. |
| GET | `/status` | Returns the current transcoder status and live frame progress of active transcode jobs. |
| GET | `/list` | Lists all indexed files. |
| PUT | `/process/{hash}` | Pushes a target media file (identified by hash) to the transcode queue. |
| PUT | `/scan` | Triggers a quick or deep probe scan over the media path configuration folder to identify eligible files. |
| DELETE | `/cancel/{uuid}` | Instantly aborts a running Scan or Transcode activity by its task UUID. |

## Configuration

Configuration is loaded from environment variables (powered by `pydantic_settings`):

- `APP_HOST`: The host interface to bind the API (Default: `0.0.0.0`).
- `APP_PORT`: The HTTP port for the API (Default: `8000`).
- `MEDIA_PATH`: The directory containing the multimedia library (Default: `/media`).
- `DB_PATH`: The SQLite database location (Default: `/storage/spacesaver-transcode/main.db`).

## Setup and Deployment

### Prerequisites
- Container runtime (Podman or Docker)
- NFS or local storage accessible by the container for `/media` and `/storage`.

### Build and Push
Use the provided script to increment the version, build the container image, and seamlessly push it to your local registry.

```bash
cd transcoder
./build.sh --registry zot.lan:5000
```
*(The build script automatically sources `upload-container.sh` to mirror `latest` and versioned tags).*

### Local Container Deployment (Podman / Docker)

1. Ensure your volumes are mapped properly for your media library configuration.
2. Spin up the test environment:
```bash
cd transcoder/test
podman-compose up -d  # or docker compose up -d
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
