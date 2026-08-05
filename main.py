"""
Entry point for Yu-Gi-Oh! TCG Valuer & Collection Tracker web application.
"""
import uvicorn

import config


def main():
    """Launch the local web server (binds to 127.0.0.1 only — never expose this to the network)."""
    print(f"Starting Yu-Gi-Oh! TCG Valuer on http://{config.WEB_HOST}:{config.WEB_PORT}")
    print("Open that URL in your browser. Press Ctrl+C to stop.")
    uvicorn.run("web.app:app", host=config.WEB_HOST, port=config.WEB_PORT)


if __name__ == "__main__":
    main()
