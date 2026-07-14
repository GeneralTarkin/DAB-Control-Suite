import os
import socket
from pathlib import Path


def env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a safe fallback."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# DABBoard installation
SCAN_FILE = Path(
    os.getenv(
        "DAB_SCAN_FILE",
        "/usr/local/lib/DABBoard/ensemblescan__.json",
    )
)

RADIO_CLI = os.getenv(
    "DAB_RADIO_CLI",
    "/usr/local/lib/DABBoard/radio_cli_v3.1.0",
)

# Icecast
ICECAST_HOST = os.getenv("DAB_ICECAST_HOST", "127.0.0.1")
ICECAST_PORT = env_int("DAB_ICECAST_PORT", 8000)
ICECAST_PASSWORD = os.getenv("DAB_ICECAST_PASSWORD", "hackme")
ICECAST_MOUNT = os.getenv("DAB_ICECAST_MOUNT", "live.mp3")

# Address presented to clients.
# Defaults to the system hostname, e.g. "dabserver".
PUBLIC_HOST = os.getenv("DAB_PUBLIC_HOST", socket.gethostname())

ICECAST_URL = (
    f"http://{PUBLIC_HOST}:{ICECAST_PORT}/{ICECAST_MOUNT}"
)

ICECAST_PUSH = (
    f"icecast://source:{ICECAST_PASSWORD}"
    f"@{ICECAST_HOST}:{ICECAST_PORT}/{ICECAST_MOUNT}"
)

# Flask server
FLASK_HOST = os.getenv("DAB_FLASK_HOST", "0.0.0.0")
FLASK_PORT = env_int("DAB_FLASK_PORT", 8088)

DEFAULT_VOLUME = env_int("DAB_DEFAULT_VOLUME", 50)

DASHBOARD_SELECTION_FILE = Path(
    os.getenv(
        "DAB_DASHBOARD_SELECTION_FILE",
        "cache/dashboard_stations.json",
    )
)
