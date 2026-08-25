"""Select the worker or UI process from one immutable Cloud Run image."""

from __future__ import annotations

import os


def main() -> None:
    port = os.environ.get("PORT", "8080")
    mode = os.environ.get("SERVICE_MODE", "worker")
    if mode == "worker":
        command = [
            "uvicorn",
            "institutional_risk_fleet.cloud_api:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
        ]
    elif mode == "ui":
        command = [
            "streamlit",
            "run",
            "app/streamlit_app.py",
            "--server.address=0.0.0.0",
            f"--server.port={port}",
            "--server.headless=true",
        ]
    else:
        raise ValueError(f"unsupported SERVICE_MODE: {mode}")
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
