import argparse
import time
from contextlib import asynccontextmanager

import uvicorn

from governors.governor import Governor
from models.config import AppConfig

def asgi_factory():
    """Factory function for Uvicorn to initialize the app and Governor context."""
    config = AppConfig()
    gov = Governor(config)
    
    @asynccontextmanager
    async def lifespan(app):
        # Startup
        gov.setup()
        gov.start_endpoint()
        yield
        # Shutdown
        gov.shutdown()

    app = gov.api_app
    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SpaceSaver Transcoder")
    parser.add_argument(
        "mode", 
        nargs="?", 
        choices=["serve", "headless"], 
        default="headless", 
        help="Run mode (default: headless)"
    )
    parser.add_argument(
        "--reload", 
        action="store_true", 
        help="Enable uvicorn auto-reload (only applies to 'serve' mode)"
    )
    args = parser.parse_args()

    if args.mode == "serve":
        # 1. Run the FastAPI application through Uvicorn
        # It handles port, host, threading, and reload capabilities cleanly
        config = AppConfig()
        uvicorn.run(
            "app:asgi_factory", 
            factory=True, 
            host=config.app_host, 
            port=config.app_port, 
            reload=args.reload
        )
    else:
        # 2. Run Headless
        config = AppConfig()
        gov = Governor(config)

        gov.setup()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nCtrl+C received! Shutting down...")
            gov.shutdown()
