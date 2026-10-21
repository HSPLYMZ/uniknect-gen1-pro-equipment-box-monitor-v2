"""Append monitor records to the TF card through Quectel's SD: file system."""

import json
from runtime import ticks_ms, ticks_diff


class SdStore:
    def __init__(self, cfg, boot_id):
        self.enabled = getattr(cfg, "ENABLE_SD_LOG", True)
        self.path = "SD:%s_%s.jsonl" % (getattr(cfg, "SD_LOG_PREFIX", "cabinet"), boot_id)
        self.state = "DISABLED" if not self.enabled else "INIT"
        self.error = None
        self.writes = 0
        self.bytes_written = 0
        self.max_bytes = getattr(cfg, "SD_MAX_SESSION_BYTES", 8 * 1024 * 1024)
        self.min_free = getattr(cfg, "SD_MIN_FREE_BYTES", 2 * 1024 * 1024)
        self.retry_ms = getattr(cfg, "SD_RETRY_MS", 30000)
        self.last_error_ms = None
        self.damaged = False
        self.pending = []
        self.dropped = 0
        self.handle = None
        self.buffer = None
        self.offset = 0
        self.phase = "idle"

    def submit(self, record):
        """Snapshot now; defer modem I/O to step(). Keep at most four records."""
        if not self.enabled or self.state == "LIMIT" or self.damaged:
            return False
        encoded = json.dumps(record).encode() + b"\n"
        priority = record.get("kind") == "event"
        if len(self.pending) >= 4:
            victim = next((i for i, item in enumerate(self.pending) if not item[1]), None)
            if victim is None and not priority:
                self.dropped += 1
                return False
            self.pending.pop(0 if victim is None else victim)
            self.dropped += 1
        self.pending.append((encoded, priority))
        return True

    def step(self):
        """At most ONE native SD call. Main polls light between these steps."""
        if self.phase == "cleanup":
            handle, self.handle = self.handle, None
            self.phase = "idle"
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            return
        if not self.enabled or self.state == "LIMIT" or self.damaged:
            return
        now = ticks_ms()
        if self.last_error_ms is not None and ticks_diff(now, self.last_error_ms) < self.retry_ms:
            return
        try:
            from quectel import File
            if self.phase == "idle":
                if not self.pending:
                    return
                self.buffer, _ = self.pending.pop(0)
                self.offset = 0
                if self.bytes_written + len(self.buffer) > self.max_bytes:
                    self.state = "LIMIT"
                    self.buffer = None
                    self.pending = []
                    print("SD_LIMIT", "session_bytes", self.bytes_written)
                    return
                if File.statvfs("SD")[1] < self.min_free + len(self.buffer):
                    raise OSError("SD reserve reached")
                self.phase = "open"
            elif self.phase == "open":
                self.handle = File.open(self.path, "a")
                self.phase = "write"
            elif self.phase == "write":
                chunk = self.buffer[self.offset:self.offset + 256]
                # Assume a failed write can have partially changed the file.
                self.damaged = True
                written = self.handle.write(chunk)
                self.bytes_written += written if isinstance(written, int) and written > 0 else 0
                if written != len(chunk):
                    raise OSError("SD short write")
                self.damaged = False
                self.offset += written
                if self.offset == len(self.buffer):
                    self.phase = "close"
            elif self.phase == "close":
                self.damaged = True
                self.handle.close()
                self.handle = None
                self.damaged = False
                self.buffer = None
                self.phase = "idle"
                self.writes += 1
                self.state = "READY"
                self.error = None
                self.last_error_ms = None
        except Exception as exc:
            self.state = "ERROR"
            self.error = type(exc).__name__
            self.last_error_ms = now
            self.buffer = None
            self.pending = []
            self.phase = "cleanup" if self.handle is not None else "idle"
            print("SD_ERROR", self.error)

    def close(self):
        # A shutdown mid-record must never resume appending behind a torn line.
        if self.handle is not None:
            self.damaged = True
            try:
                self.handle.close()
            except Exception:
                pass
            self.handle = None

    def append(self, record):
        if not self.enabled:
            return False
        if self.state == "LIMIT" or self.damaged:
            return False
        now = ticks_ms()
        if self.last_error_ms is not None and ticks_diff(now, self.last_error_ms) < self.retry_ms:
            return False
        writing = False
        try:
            from quectel import File
            encoded = json.dumps(record).encode() + b"\n"
            if self.bytes_written + len(encoded) > self.max_bytes:
                self.state = "LIMIT"
                print("SD_LIMIT", "session_bytes", self.bytes_written)
                return False
            if File.statvfs("SD")[1] < self.min_free + len(encoded):
                raise OSError("SD reserve reached")
            handle = File.open(self.path, "a")
            try:
                writing = True
                written = handle.write(encoded)
                self.bytes_written += written if isinstance(written, int) and written > 0 else 0
                if written != len(encoded):
                    self.damaged = True  # Do not append good records behind a torn JSON line.
                    raise OSError("SD short write")
            finally:
                handle.close()
            self.writes += 1
            self.state = "READY"
            self.error = None
            self.last_error_ms = None
            return True
        except Exception as exc:
            self.damaged = self.damaged or writing
            self.state = "ERROR"
            self.error = str(exc)
            self.last_error_ms = now
            print("SD_ERROR", self.error)
            return False
