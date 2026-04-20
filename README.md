# HomeReef

HomeReef is an automated media transcode suite designed to optimize your media library for space efficiency by converting videos to H.265 (HEVC) MKV format.

The project consists of two main components:
- **Transflux**: The heavy-lifting backend engine that orchestrates media scanning and transcoding.
- **Seaglass**: A modern web-based dashboard for monitoring and managing your HomeReef instance.

## Project Structure

- `transflux/`: The core transcoding engine (FastAPI + Jackfield message bus).
- `seaglass/`: The web user interface (Flask + Vanilla JS).
- `containerfiles/`: Orchestration configurations (Docker Compose).
- `test-data/`: Sample data and environment for testing.

---

## Transflux (Backend)

Transflux is a "fancy ffmpeg orchestrator" that manages a queue of transcode jobs, tracks file metadata in a SQLite database, and ensures background tasks don't interfere with the responsiveness of the system.

### Key Features
- **Space Optimization**: Converts videos to H.265 using `libx265` and Matroska (MKV) containers.
- **Background Orchestration**: Smart thread pooling through a central Governor ensures API responsiveness.
- **REST API**: Full programmatic control over status, scanning, and transcoding.
- **SQLite Tracking**: Persistent state tracking for all media files (Hash-based indexing).
- **Configurable Quality**: Support for built-in presets (Low, Mid, High) or custom CRF/preset settings via TOML persistence.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/version` | Returns the current Transflux version. |
| GET | `/status` | Returns live progress of active jobs and system status. |
| GET | `/list` | Lists all indexed media files and their status. |
| PUT | `/process/{hash}` | Enqueues a file (by hash) for transcoding. |
| PUT | `/scan` | Triggers a scan of the `MEDIA_PATH`. |
| DELETE | `/cancel/{uuid}` | Aborts a running task by its UUID. |
| GET | `/quality` | Retrieves current quality settings and presets. |
| POST | `/quality` | Updates quality settings (preset or custom). |

---

## Seaglass (Web UI)

Seaglass provides a user-friendly interface to interact with Transflux without using the CLI or API directly.

### Features
- **Dashboard**: Real-time progress bars for active transcodes.
- **Library Browser**: Search and filter your media library, view transcode status.
- **One-Click Transcode**: Trigger processing for any file in the library.
- **Quality Management**: Switch between quality presets directly from the dashboard.

---

## Setup & Deployment

The easiest way to run HomeReef is using Docker Compose.

### Quick Start (Local)

1. Clone the repository.
2. Configure your media directory:
   ```bash
   export MEDIA_DIR=/path/to/your/videos
   ```
3. Launch the stack:
   ```bash
   cd containerfiles
   docker-compose up -d
   ```
4. Access the UI at `http://localhost:5000` and the API at `http://localhost:8000`.

### Configuration

Both services are configured via environment variables:

**Transflux:**
- `MEDIA_PATH`: Root directory of your media library (Default: `/media`).
- `DB_PATH`: Path to the SQLite database (Default: `/storage/homereef-transflux/main.db`).
- `CACHE_PATH`: Path for persistent quality settings and cache (Default: `/cache`).
- `APP_PORT`: Port to bind the API (Default: `8000`).

**Seaglass:**
- `TRANSFLUX_URL`: URL where Seaglass can reach Transflux (Default: `http://homereef-transflux:8000`).

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
