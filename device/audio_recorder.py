"""Record the abnormal interval to a WAV file on the TF card."""
from runtime import ticks_ms, ticks_diff


class AudioRecorder:
    def __init__(self, cfg, boot_id):
        self.cfg = cfg
        self.boot_id = boot_id
        self.enabled = getattr(cfg, "ENABLE_EVENT_AUDIO", True)
        self.audio = None
        self.recording = False
        self.sequence = 0
        self.path = None
        self.state = "DISABLED" if not self.enabled else "INIT"
        self.error = None
        self.last_attempt = None
        self.started_ms = None
        self.limited = False
        self.phase = "idle"

    def step(self, active):
        """One modem operation per turn, including cancellation during startup."""
        required = self.enabled and ("tilt" in active or "light" in active)
        now = ticks_ms()
        if not required:
            self.limited = False
        if self.recording and (not required or (self.started_ms is not None and
                ticks_diff(now, self.started_ms) >= getattr(self.cfg, "AUDIO_MAX_MS", 30000))):
            if required:
                self.limited = True
            self.phase = "stop"
        if not required and self.phase in ("init", "start"):
            self.phase = "deinit" if self.audio is not None else "idle"
            self.last_attempt = None  # Cancellation is not a failed start.
        try:
            if self.phase == "idle":
                if not required or self.limited:
                    return
                if self.last_attempt is not None and ticks_diff(now, self.last_attempt) < getattr(self.cfg, "AUDIO_RETRY_MS", 30000):
                    return
                from quectel import File
                self.last_attempt = now
                if File.statvfs("SD")[1] < getattr(self.cfg, "SD_MIN_FREE_BYTES", 2 * 1024 * 1024):
                    raise OSError("SD reserve reached")
                self.phase = "init"
            elif self.phase == "init":
                from quectel import Audio
                self.audio = Audio()
                if not self.audio.init():
                    raise OSError("Audio init failed")
                self.phase = "start"
            elif self.phase == "start":
                self.path = "SD:%s_%s_%03d.wav" % (getattr(self.cfg, "AUDIO_PREFIX", "alarm"), self.boot_id, self.sequence)
                self.sequence += 1
                self.audio.record_start(self.path)
                self.recording = True
                self.started_ms = ticks_ms()
                self.state = "RECORDING"
                self.error = None
                self.last_attempt = None
                self.phase = "recording"
                print("AUDIO_START", self.path)
            elif self.phase == "stop":
                self.audio.record_stop()
                self.recording = False
                self.started_ms = None
                self.phase = "deinit"
                print("AUDIO_STOP", self.path)
            elif self.phase == "deinit":
                audio, self.audio = self.audio, None
                if audio is not None:
                    audio.deinit()
                self.phase = "idle"
                self.state = "ERROR" if self.error else ("LIMIT" if self.limited else "READY")
        except Exception as exc:
            self.error = type(exc).__name__
            self.state = "ERROR"
            self.recording = False
            self.started_ms = None
            self.last_attempt = now
            self.phase = "deinit" if self.audio is not None else "idle"
            print("AUDIO_ERROR", self.error)

    def _start(self):
        try:
            from quectel import Audio
            from quectel import File
            if File.statvfs("SD")[1] < getattr(self.cfg, "SD_MIN_FREE_BYTES", 2 * 1024 * 1024):
                raise OSError("SD reserve reached")
            self.audio = Audio()
            if not self.audio.init():
                raise OSError("Audio init failed")
            self.path = "SD:%s_%s_%03d.wav" % (
                getattr(self.cfg, "AUDIO_PREFIX", "alarm"), self.boot_id, self.sequence)
            self.sequence += 1
            self.audio.record_start(self.path)
            self.recording = True
            self.started_ms = ticks_ms()
            self.state = "RECORDING"
            self.error = None
            print("AUDIO_START", self.path)
            return True
        except Exception as exc:
            self.state = "ERROR"
            self.error = str(exc)
            print("AUDIO_ERROR", self.error)
            self.close()
            return False

    def _stop(self):
        if self.audio is None:
            return
        try:
            self.audio.record_stop()
            print("AUDIO_STOP", self.path)
        except Exception as exc:
            self.error = str(exc)
            print("AUDIO_ERROR", self.error)
        self.recording = False
        self.started_ms = None
        self.state = "READY" if self.error is None else "ERROR"
        try:
            self.audio.deinit()
        except Exception:
            pass
        self.audio = None

    def sync(self, active):
        required = self.enabled and ("tilt" in active or "light" in active)
        now = ticks_ms()
        if not required:
            self.limited = False
        if self.recording and self.started_ms is not None and ticks_diff(now, self.started_ms) >= getattr(self.cfg, "AUDIO_MAX_MS", 30000):
            self._stop()
            self.limited = True
            if self.state != "ERROR":
                self.state = "LIMIT"
        if required and not self.recording and not self.limited:
            if self.last_attempt is None or ticks_diff(now, self.last_attempt) >= getattr(self.cfg, "AUDIO_RETRY_MS", 30000):
                self.last_attempt = now
                if self._start():
                    self.last_attempt = None  # Backoff applies to failures, not distinct alarms.
        elif not required and self.recording:
            self._stop()

    def close(self):
        if self.recording:
            self._stop()
        elif self.audio is not None:
            try:
                self.audio.deinit()
            except Exception:
                pass
            self.audio = None
