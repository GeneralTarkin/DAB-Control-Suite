#!/usr/bin/env python3

import json
import time
from pathlib import Path

OUT = Path("cache")
OUT.mkdir(exist_ok=True)

while True:
    data = {
        "timestamp": time.time(),
        "alive": True
    }

    (OUT / "metadata.json").write_text(
        json.dumps(data, indent=2)
    )

    time.sleep(2)
