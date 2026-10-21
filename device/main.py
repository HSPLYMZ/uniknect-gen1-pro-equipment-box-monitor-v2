"""UniKnect Gen1 Pro cabinet monitor. Save this and siblings to board root."""

import gc
import os
import time

try:
    import config
except ImportError:
    import config_template as config

from display import Display
from audio_recorder import AudioRecorder
from events import EventEngine
from location import Location
from queue_store import Outbox
from sensors import Sensors
from sd_store import SdStore
from transport import Transport
from ble_telemetry import BleTelemetry
from runtime import Runtime


def _boot_id():
    try:
        return "{:08x}".format(int.from_bytes(os.urandom(4), "big"))
    except Exception:
        return "t{:x}".format(time.ticks_us())


def run():
    started = time.ticks_ms()
    runtime = Runtime(time)
    boot_id = _boot_id()
    sequence = 0
    outbox = Outbox(config.QUEUE_LIMIT)
    sensors = Sensors()
    engine = EventEngine(config)
    location = Location(config)
    transport = Transport(config)
    storage = SdStore(config, boot_id)
    recorder = AudioRecorder(config, boot_id)
    ble = BleTelemetry(config)
    screen = None
    screen_error = None
    try:
        screen = Display(config)
    except Exception as exc:
        screen_error = str(exc)
        print("DISPLAY_ERROR", screen_error)
    sample = {"temperature_c": None, "humidity_pct": None,
              "light_adc_u16": None, "accel_m_s2": None,
              "valid": False, "errors": {"startup": "not_sampled"}}
    location.start()
    last_sample = None
    pose_at = None
    pose_values = None
    pose_sequence = 0
    last_light = None
    max_light_gap_ms = 0
    light_polls = 0
    last_heartbeat = None
    last_display = None
    last_rendered_alarm = None
    last_send = None
    last_sd_log = None
    last_status = None
    sample_count = 0
    frame_count = 0
    last_button_error = None
    max_render_ms = 0
    max_gc_ms = 0
    gc_count = 0
    display_interval = config.DISPLAY_MS
    free_ram = gc.mem_free()
    max_loop_gap_ms = 0
    last_loop = time.ticks_ms()  # Runtime loop gap excludes hardware initialization.
    last_net_state = transport.state

    def enqueue(kind, now_ms, event=None):
        nonlocal sequence
        if config.TRANSPORT_MODE == "qth":
            return
        payload = {"schema": 1, "device_id": config.DEVICE_ID,
                   "boot_id": boot_id, "seq": sequence,
                   "uptime_ms": runtime.uptime(),
                   "kind": kind, "sample": dict(sample),
                   "active": engine.active(),
                   "calibrated": engine.ready,
                   "location": location.snapshot(now_ms, time.ticks_diff),
                   "network": transport.state,
                   "queue_dropped": outbox.dropped,
                   "max_loop_gap_ms": max_loop_gap_ms,
                   "free_ram_bytes": gc.mem_free(),
                   "replayed": transport.state != "ONLINE"}
        payload["sample"]["errors"] = dict(sample.get("errors", {}))
        if event is not None:
            payload["event"] = event
        suffix = "event" if kind == "event" else "state"
        topic = config.TOPIC_OVERRIDE or ("%s/%s/%s" % (config.TOPIC_PREFIX, config.DEVICE_ID, suffix))
        outbox.put(topic, payload, kind == "event")
        sequence += 1
        print("ENQUEUE", kind, boot_id, sequence - 1, "q", len(outbox))

    def save_sd(kind, now_ms, event=None):
        record = {"schema": 1, "device_id": config.DEVICE_ID,
                  "boot_id": boot_id, "uptime_ms": runtime.uptime(),
                  "kind": kind, "sample": sample, "active": engine.active(),
                  "calibrated": engine.ready,
                  "location": location.snapshot(now_ms, time.ticks_diff),
                  "recording": recorder.recording}
        if event is not None:
            record["event"] = event
        # submit() encodes a snapshot; step() performs one native operation later.
        if hasattr(storage, "submit"):
            storage.submit(record)
        else:
            storage.append(record)

    def render_if_due(now_ms, force=False):
        nonlocal last_display, frame_count, screen_error, last_rendered_alarm, max_render_ms
        if screen is None:
            return
        if (not force and last_display is not None and
                time.ticks_diff(now_ms, last_display) < display_interval):
            return
        last_display = now_ms
        try:
            before = time.ticks_ms()
            flushed = runtime.call("display", screen.render, sample, location.snapshot(now_ms, time.ticks_diff),
                                    engine.active(), transport.state, len(outbox), outbox.dropped,
                                    runtime.uptime() // 1000, free_ram,
                                    engine.ready, recorder.recording, storage.state,
                                    transport.status(now_ms))
            max_render_ms = max(max_render_ms, time.ticks_diff(time.ticks_ms(), before))
            if flushed:
                frame_count += 1
                rendered_alarm = ("light" in engine.active() if
                                  getattr(config, "LIGHT_BACKGROUND_ONLY", True) else bool(engine.active()))
                if rendered_alarm != last_rendered_alarm:
                    print("SCREEN", "ALARM" if rendered_alarm else "NORMAL", "page", screen.page)
                    last_rendered_alarm = rendered_alarm
            screen_error = None
        except Exception as exc:
            if str(exc) != screen_error:
                screen_error = str(exc)
                print("DISPLAY_ERROR", screen_error)

    def handle_transitions(transitions, now_ms):
        # Paint the new state before any synchronous modem/SD/audio calls.
        if not transitions:
            return
        render_if_due(time.ticks_ms(), True)
        for event in transitions:
            enqueue("event", now_ms, event)
        for event in transitions:
            save_sd("event", now_ms, event)

    def poll_light(force=False):
        nonlocal last_light, max_light_gap_ms, light_polls
        now = time.ticks_ms()
        gap = time.ticks_diff(now, last_light) if last_light is not None else 0
        if not force and last_light is not None and gap < config.LIGHT_POLL_MS:
            return
        last_light = now
        max_light_gap_ms = max(max_light_gap_ms, gap)
        light_polls += 1
        value = runtime.call("light_adc", sensors.read_light)
        sample["light_adc_u16"] = value
        errors = sample.setdefault("errors", {})
        if value is None:
            errors["ldr"] = "read_failed"
        else:
            errors.pop("ldr", None)
        sample["valid"] = not errors
        if getattr(config, "LIGHT_MODE", "delta") == "absolute":
            transitions = engine.update_light(value, now)
            if transitions:
                print("LIGHT_EDGE", "EXPOSED" if "light" in engine.active() else "COVERED",
                      "adc", value, "poll_gap_ms", gap)
                handle_transitions(transitions, now)

    try:
        runtime.call("ble_start", ble.start)
        if (getattr(config, "_WATCHDOG", None) is not None and
                ble.enabled and not ble.started):
            raise RuntimeError("BLE startup failed")
        last_loop = time.ticks_ms()
        while True:
            now_ms = time.ticks_ms()
            collect_due = False
            gap = time.ticks_diff(now_ms, last_loop)
            if gap > max_loop_gap_ms:
                max_loop_gap_ms = gap
            last_loop = now_ms

            poll_light()

            # Separate IMU path: preserve 1 Hz event confirmation and AHT20 timing.
            pose_now = time.ticks_ms()
            if ble.pose_subscribed and (pose_at is None or
                    time.ticks_diff(pose_now, pose_at) >= getattr(config, "POSE_SAMPLE_MS", 200)):
                pose_values = runtime.call("pose_read", sensors.read_acceleration)
                pose_at = time.ticks_ms()
                pose_sequence = (pose_sequence + 1) & 65535
                poll_light()

            if screen is not None:
                action = runtime.call("button", screen.poll_button, now_ms, time.ticks_diff)
                if action:
                    print("BUTTON", action, "page", screen.page)
                    # A page change gets drawn before a due sensor read or GC.
                    render_if_due(time.ticks_ms(), True)
                    poll_light()
                if screen.button_error != last_button_error:
                    last_button_error = screen.button_error
                    if last_button_error:
                        print("BUTTON_ERROR", last_button_error)

            if last_sample is None or time.ticks_diff(now_ms, last_sample) >= config.SAMPLE_MS:
                last_sample = now_ms
                sample = runtime.call("sensors", sensors.read)
                sample_count += 1
                transport.submit(sample, time.ticks_ms())
                collect_due = True
                was_calibrated = engine.ready
                transitions = engine.update(sample, now_ms)
                if engine.ready and not was_calibrated:
                    print("CALIBRATED", runtime.uptime() // 1000)
                handle_transitions(transitions, now_ms)
                poll_light()

            if last_heartbeat is None or time.ticks_diff(now_ms, last_heartbeat) >= config.HEARTBEAT_MS:
                last_heartbeat = now_ms
                enqueue("heartbeat", now_ms)

            now_ms = time.ticks_ms()
            render_if_due(now_ms)
            poll_light()
            if collect_due:
                before = time.ticks_ms()
                runtime.call("gc", gc.collect)
                gc_count += 1
                max_gc_ms = max(max_gc_ms, time.ticks_diff(time.ticks_ms(), before))
                free_ram = gc.mem_free()

            if last_status is None or time.ticks_diff(now_ms, last_status) >= 10000:
                last_status = now_ms
                print("APP_STATUS", "uptime", runtime.uptime() // 1000,
                      "samples", sample_count, "frames", frame_count,
                      "page", screen.page if screen is not None else -1,
                      "valid", sample.get("valid", False), "render_max_ms", max_render_ms,
                      "gc_max_ms", max_gc_ms, "gc_runs", gc_count,
                      "loop_max_ms", max_loop_gap_ms, "light_gap_max_ms", max_light_gap_ms,
                      "light_polls", light_polls, "light_adc", sample.get("light_adc_u16"),
                      "ble", ble.state, "ble_sent", ble.sent, "ble_errors", ble.errors,
                      "ble_max_ms", ble.max_notify_ms,
                      "pose_sent", ble.pose_sent, "pose_errors", ble.pose_errors,
                      "pose_max_ms", ble.max_pose_ms,
                      "ram", gc.mem_free())
                print("OP_MAX", runtime.max_ms)
                print("CLOUD_STATUS", transport.status(time.ticks_ms()))

            poll_light()
            runtime.call("audio", getattr(recorder, "step", recorder.sync), engine.active())
            poll_light()
            runtime.call("gnss", location.poll_gnss, time.ticks_ms(), time.ticks_diff)
            poll_light()
            # LBS and network calls are synchronous; render pending UI first.
            if transport.state == "ONLINE":
                runtime.call("lbs", location.poll_lbs, time.ticks_ms(), time.ticks_diff)
                poll_light()

            if (last_sd_log is None or
                    time.ticks_diff(now_ms, last_sd_log) >= getattr(config, "SD_LOG_MS", 10000)):
                last_sd_log = now_ms
                save_sd("sample", now_ms)
                poll_light()

            if hasattr(storage, "step"):
                runtime.call("sd_step", storage.step)
                poll_light()

            runtime.call("net_connect", transport.connect_if_due, time.ticks_ms(), time.ticks_diff, time.sleep)
            poll_light()
            runtime.call("ble_poll", ble.poll, sample, engine.active(), engine.ready, time.ticks_ms(), time)
            poll_light()
            runtime.call("pose_notify", ble.poll_pose, pose_values, pose_sequence, pose_at, time.ticks_ms(), time)
            poll_light()
            if last_send is None or time.ticks_diff(now_ms, last_send) >= 500:
                last_send = now_ms
                if runtime.call("net_send", transport.send_one, outbox, time.ticks_ms()):
                    print("PUBLISHED", "q", len(outbox))
            if transport.state != last_net_state:
                last_net_state = transport.state
                print("NET", last_net_state)
            watchdog = getattr(config, "_WATCHDOG", None)
            if watchdog is not None:
                watchdog.feed()
            healthy = getattr(config, "_BOOT_HEALTH", None)
            if (healthy is not None and runtime.uptime() >= 60000 and
                    sample.get("valid") and frame_count > 0 and
                    (not ble.enabled or ble.started)):
                healthy()
                config._BOOT_HEALTH = None
            elif healthy is not None and runtime.uptime() >= 120000:
                raise RuntimeError("Startup health deadline exceeded")
            runtime.call("idle", time.sleep_ms, 20)
    except KeyboardInterrupt:
        print("STOPPED")
    finally:
        ble.close()
        recorder.close()
        if hasattr(storage, "close"):
            storage.close()
        location.stop()
        transport.close()


if __name__ == "__main__":
    run()
