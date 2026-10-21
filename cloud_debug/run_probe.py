"""Run --check locally or --run for a temporary cloud test and V2 recovery."""
import argparse
import ast
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time
from datetime import datetime

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent


def attach_live_output(raw, on_event=None):
    """Show only explicitly encoded probe JSON; native modem logs stay in RAM."""
    def read_until(marker, timeout=10):
        end = time.monotonic() + timeout
        data = bytearray()
        pending = bytearray()
        while marker not in data:
            if time.monotonic() > end:
                raise TimeoutError("Remote probe timeout")
            chunk = raw.ser.read(raw.ser.in_waiting or 1)
            data.extend(chunk)
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, remaining = pending.partition(b"\n")
                pending = bytearray(remaining)
                line = line.rstrip(b"\r")
                if line.startswith(b"OKCLOUD_PROBE "):
                    line = line[2:]
                if line.startswith(b"CLOUD_PROBE "):
                    try:
                        event = json.loads(line[len(b"CLOUD_PROBE "):].decode("utf8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if on_event is not None:
                        on_event(event)
                    print("CLOUD_PROBE_LIVE " + json.dumps(event, ensure_ascii=True), flush=True)
        return bytes(data)
    raw.read_until = read_until


def execute_probe(raw, code, timeout):
    """Keep native diagnostic bytes private; JSON events are captured live."""
    payload = code.encode("utf8") + b"\x04"
    for offset in range(0, len(payload), 48):
        raw.ser.write(payload[offset:offset + 48])
        time.sleep(.015)
    response = raw.read_until(b"\x04>", timeout)
    if not response.startswith(b"OK") or b"\x04" not in response[2:-2]:
        raise RuntimeError("Invalid raw REPL response")
    _, error = response[2:-2].split(b"\x04", 1)
    if error.strip():
        raise RuntimeError("Remote probe execution error; native output withheld")


def load_config():
    private = HERE / "config_private.py"
    if not private.is_file():
        raise RuntimeError("Copy config_example.py to config_private.py and fill credentials")
    cfg = runpy.run_path(str(private))["CONFIG"]
    for key in ("product_key", "product_secret", "device_key", "server"):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip() or cfg[key] == "CHANGE_ME":
            raise RuntimeError("Missing private configuration: " + key)
    for key, maximum in (("connect_timeout_seconds", 120), ("observe_seconds", 120),
                         ("report_seconds", 120)):
        if not isinstance(cfg.get(key), int) or not 1 <= cfg[key] <= maximum:
            raise RuntimeError("Invalid duration: " + key)
    if cfg["report_seconds"] < 10:
        raise RuntimeError("Diagnostic report interval must be at least 10 seconds")
    return cfg


def main():
    p = argparse.ArgumentParser(description=__doc__)
    action = p.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="local checks only; does not open serial or connect cloud")
    action.add_argument("--run", action="store_true", help="interrupt V2, register/login and upload real samples, then restore V2")
    p.add_argument("--port", default="COM3")
    args = p.parse_args()
    cfg = load_config()
    source = (HERE / "probe.py").read_text(encoding="utf8")
    ast.parse(source)
    print("CLOUD_PROBE_LOCAL_CHECK_OK ids=2,3,4,5 credentials=present", flush=True)
    if args.check:
        return 0

    sys.path.insert(0, str(PROJECT / "host"))
    import resident_board
    from deploy_board import RawRepl
    log_dir = HERE / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / ("probe_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".jsonl")
    raw = None
    maintenance_attempted = False
    events = []
    output = None
    try:
        print("CLOUD_PROBE_ENTERING_MAINTENANCE BLE will disconnect", flush=True)
        maintenance_attempted = True
        resident_board.maintenance(args.port)
        raw = RawRepl(args.port)
        output = log_path.open("w", encoding="utf8")
        def save_event(event):
            events.append(event)
            output.write(json.dumps(event, ensure_ascii=True) + "\n")
            output.flush()
        attach_live_output(raw, save_event)
        # Credentials travel over the local serial link, never through CLI arguments or saved board files.
        script = source + "\nrun_probe(" + repr(cfg) + ")\n"
        timeout = cfg["connect_timeout_seconds"] + cfg["observe_seconds"] + 90
        print("CLOUD_PROBE_RUNNING wait for results; native logs are filtered", flush=True)
        execute_probe(raw, script, timeout)
    except Exception as exc:
        print("CLOUD_PROBE_HOST_ERROR", type(exc).__name__, flush=True)
    finally:
        if output is not None:
            output.close()
            print("CLOUD_PROBE_LOG", str(log_path), flush=True)
        if raw is not None:
            # Interrupt a timed-out remote probe before returning to the normal launcher.
            try:
                raw.ser.write(b"\x03\x02\r")
                raw.ser.flush()
            except Exception:
                pass
            try:
                raw.close()
            except Exception:
                pass
        if maintenance_attempted:
            print("CLOUD_PROBE_RESTORING_V2", flush=True)
            recovered = subprocess.run([
                sys.executable, "-B", "-u", str(PROJECT / "host/resident_board.py"),
                "resume", "--port", args.port, "--seconds", "95",
            ]).returncode == 0
            if not recovered:
                print("CLOUD_PROBE_RECOVERY_NOT_CONFIRMED run resident_board.py resume", flush=True)
                return 2
    summaries = [e for e in events if e.get("event") == "summary"]
    passed = bool(summaries and summaries[-1].get("online_observed")
                  and summaries[-1].get("accepted", 0) > 0)
    if (not passed and summaries and summaries[-1].get("online_observed")
            and summaries[-1].get("unconfirmed_send_returns", 0) > 0):
        print("CLOUD_PROBE_DEVICE_ONLINE_SEND_RETURN_UNCONFIRMED", flush=True)
        print("CLOUD_PROBE_VERIFY_VALUES_ON_EXACT_DEVICE_KEY", flush=True)
        return 3
    print("CLOUD_PROBE_DEVICE_UPLINK_OK" if passed else "CLOUD_PROBE_DEVICE_UPLINK_NOT_CONFIRMED", flush=True)
    print("CLOUD_PROBE_PLATFORM_AND_APP_VALUES_REQUIRE_SEPARATE_CHECK", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
