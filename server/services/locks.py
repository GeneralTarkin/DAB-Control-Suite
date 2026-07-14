import fcntl
import threading
import time
from contextlib import contextmanager
from pathlib import Path

CLI_LOCK = threading.Lock()
LOCK_FILE = Path("/tmp/mwi-dab-radio-cli.lock")


@contextmanager
def cli_file_lock(timeout=10):
    LOCK_FILE.touch(exist_ok=True)
    with LOCK_FILE.open("w") as f:
        start = time.time()
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - start > timeout:
                    raise TimeoutError("radio_cli ist gerade beschäftigt")
                time.sleep(0.1)

        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
