from pathlib import Path

SCAN_FILE = Path("/usr/local/lib/DABBoard/ensemblescan__.json")
RADIO_CLI = "/usr/local/lib/DABBoard/radio_cli_v3.1.0"

ICECAST_HOST = "127.0.0.1"
ICECAST_PORT = 8000
ICECAST_PASSWORD = "hackme"
ICECAST_MOUNT = "live.mp3"

PUBLIC_HOST = "192.168.123.168"

ICECAST_URL = f"http://{PUBLIC_HOST}:{ICECAST_PORT}/{ICECAST_MOUNT}"
ICECAST_PUSH = f"icecast://source:{ICECAST_PASSWORD}@{ICECAST_HOST}:{ICECAST_PORT}/{ICECAST_MOUNT}"

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 8088

DEFAULT_VOLUME = 50

RADIO_CLI = "/usr/local/lib/DABBoard/radio_cli_v3.1.0"
