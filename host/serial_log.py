"""Print only filtered application logs; do not expose native modem output."""

SAFE_PREFIXES = ("OP_MAX", "SLOW_OP", "SD_LIMIT", "BLE_", "BOOT_V1", "BOOT_V2", "LIGHT_EDGE", "RAM_BEFORE_APP", "CALIBRATED", "SCREEN", "ENQUEUE", "PUBLISHED", "DISPLAY_ERROR",
                 "BUTTON", "APP_STATUS", "STOPPED", "NET", "SD_ERROR", "AUDIO_START", "AUDIO_STOP", "AUDIO_ERROR", "CLOUD_")


def print_safe(raw, pending, status=None):
    pending += raw.decode("utf-8", "replace").replace("\r", "")
    while "\n" in pending:
        line, pending = pending.split("\n", 1)
        # Native AT debug output can interrupt a Python status line mid-print.
        # Retain only the safe application prefix before its ANSI debug marker.
        line = line.split("\x1b", 1)[0]
        if line.startswith(SAFE_PREFIXES):
            print(line, flush=True)
            if status is not None and line.startswith("APP_STATUS"):
                status["running"] = True
        elif line.startswith("Traceback") or line.startswith(("MemoryError", "SyntaxError", "ImportError", "NameError")):
            # Never expose exception messages, which may contain private config.
            print("APP_START_ERROR", line.split(":", 1)[0] if ":" in line else "Traceback", flush=True)
            if status is not None:
                status["error"] = True
    return pending

