# Spyglass

Spyglass is the web interface for the **SpaceSaver** media transcoder. It provides a somewhat modern, user-friendly dashboard to monitor your transcode queue, manage quality settings, and trigger library scans.

## Features

-   **Dashboard Overview**: View live progress of active transcode jobs.
-   **Library Management**: Browse all indexed files and their current status.
-   **On-Demand Processing**: Manually trigger transcodes for specific files.
-   **Library Scanning**: Initiate scans to discover new media.
-   **Quality Settings**: Configure global transcode parameters directly from the UI.

## Technology Stack

-   **Backend**: Flask (Python)
-   **Frontend**: HTML5, Vanilla CSS, JavaScript
-   **API Communication**: RESTful interface with the SpaceSaver transcoder service.

## Getting Started

### Prerequisites

-   A running instance of the **SpaceSaver** transcoder.
-   Docker or Podman (for containerized deployment).

### Configuration

Spyglass is primarily configured via environment variables:

-   `TRANSCODER_URL`: The URL of the SpaceSaver transcoder service (Default: `http://localhost:8000`).
-   `APP_PORT`: The port on which Spyglass will listen (Default: `5000`).

### Running Locally

1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
2.  Set the `TRANSCODER_URL` environment variable.
3.  Run the application:
    ```bash
    python src/app.py
    ```

### Container Deployment

You can build and push the Spyglass container image using the provided scripts:

```bash
./build.sh --registry your-registry
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
