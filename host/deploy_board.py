"""Stage app in /flash/cabinet_monitor_v2 without replacing board boot files."""

import argparse
import base64
from pathlib import Path
import serial
import time
import re


def clean_native_output(body):
    # Firmware AT diagnostics can arrive inside a Python print/base64 chunk.
    # Strip complete color-framed native messages, preserving Python output.
    body = re.sub(rb'\x1b\[[0-9;]*m.*?\x1b\[0m', b'', body, flags=re.DOTALL)
    if b'\x1b' in body or b'[DEBUG]' in body:
        raise RuntimeError('Incomplete native log in raw REPL output; retry in maintenance')
    return body


FILES = ["runtime.py", "ble_telemetry.py", "config_template.py", "events.py", "queue_store.py", "sensors.py",
         "cloud_policy.py", "qth_compat.py",
         "location.py", "display.py", "sd_store.py", "audio_recorder.py",
         "transport.py", "qth_transport.py", "main.py", "logo_asset.py", "logo_160x20.bin"]
EXTRA_PROBES = [name for name in ("baseline_probe.py", "gnss_observation.py", "event_stability_probe.py",
                "refresh_probe.py", "button_probe.py", "display_probe.py", "gnss_probe.py")
                if (Path(__file__).resolve().parents[1] / "probes" / name).is_file()]


def source_path(source_dir, name):
    """Resolve local device/probe/assets files to the existing board filename."""
    version_dir = source_dir.parent
    for directory in (version_dir / "device", version_dir / "probes", version_dir / "device" / "assets"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Missing deployment source: " + name)


class RawRepl:
    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=1)
        self.ser.write(b"\x02\x03\x03\r")
        time.sleep(1)
        self.ser.reset_input_buffer()
        self.ser.write(b"\x01")
        greeting = bytearray()
        deadline = time.monotonic() + 5
        while b"raw REPL" not in greeting or not greeting.endswith(b">"):
            greeting.extend(self.ser.read(self.ser.in_waiting or 1))
            if time.monotonic() > deadline:
                self.ser.close()
                raise RuntimeError("Raw REPL unavailable")
        self.exec("try:\n f.close()\nexcept Exception:\n pass\nglobals().pop('f',None);globals().pop('deploy_payload',None);globals().pop('verify_data',None);import gc;gc.collect()")

    def read_until(self, marker, timeout=10):
        end = time.monotonic() + timeout
        data = bytearray()
        while marker not in data:
            if time.monotonic() > end:
                raise TimeoutError(repr(data[-200:]))
            data.extend(self.ser.read(self.ser.in_waiting or 1))
        return bytes(data)

    def exec(self, code, timeout=10):
        encoded = code.encode("utf-8") + b"\x04"
        for offset in range(0, len(encoded), 48):
            self.ser.write(encoded[offset:offset + 48])
            if len(encoded) > 48:
                time.sleep(0.015)
        # Raw REPL separates stdout and stderr with two EOT bytes. Stderr
        # between them is valid protocol and must not turn into a timeout.
        response = self.read_until(b"\x04>", timeout)
        if not response.startswith(b"OK"):
            raise RuntimeError(repr(response))
        body, error = response[2:-2].split(b"\x04", 1)
        if error:
            raise RuntimeError(error.decode("utf-8", "replace"))
        return clean_native_output(body).decode("utf-8", "replace").strip()

    def close(self):
        self.ser.write(b"\x02")
        self.ser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--files", nargs="+", choices=FILES + EXTRA_PROBES,
                        help="upload only these app files (default: all)")
    if (Path(__file__).resolve().parents[1]/'device/config_baseline_adapter.py').is_file():
        parser.add_argument("--baseline-adapter", action="store_true",
                            help="install private-free config adapter as config.py for short MQTT test")
    args = parser.parse_args()
    raw = RawRepl(args.port)
    try:
        print("FILES", raw.exec("import os; print(os.listdir('/flash'))"))
        print("STATVFS", raw.exec("print(os.statvfs('/flash'))"))
        if not args.upload:
            return
        print("DIRECTORY", raw.exec("import os\ntry:\n os.mkdir('/flash/cabinet_monitor_v2')\nexcept OSError:\n pass\nprint(os.listdir('/flash/cabinet_monitor_v2'))"))
        raw.exec("import ubinascii")
        source_dir = Path(__file__).parent
        for name in args.files or FILES:
            payload = source_path(source_dir, name).read_bytes()
            target = "/flash/cabinet_monitor_v2/" + name
            staging = target + ".new"
            raw.exec("try:\n os.remove(%r)\nexcept OSError:\n pass" % staging)
            raw.exec("_fs=os.statvfs('/flash'); assert _fs[0]*_fs[4] > %d, 'Insufficient staging space'" % (len(payload) + 1024))
            raw.exec("gc.collect(); deploy_payload=bytearray()")
            for offset in range(0, len(payload), 384):
                encoded = base64.b64encode(payload[offset:offset + 384]).decode("ascii")
                raw.exec("deploy_payload.extend(ubinascii.a2b_base64('%s'))" % encoded)
            assembled = int(raw.exec("print(len(deploy_payload))"))
            if assembled != len(payload):
                raise RuntimeError("Assembly length mismatch")
            written = raw.exec("f=open(%r,'wb'); _written=f.write(deploy_payload); f.close(); del deploy_payload; gc.collect();print(_written)" % staging, timeout=60)
            if int(written) != len(payload):
                raise RuntimeError("Short staging write")
            remote_size = raw.exec("print(os.stat(%r)[6])" % staging)
            if int(remote_size) != len(payload):
                raise RuntimeError("Upload size mismatch for %s: %s / %d" % (name, remote_size, len(payload)))
            verified = bytearray()
            raw.exec("f=open(%r,'rb')" % staging)
            try:
                for offset in range(0, len(payload), 384):
                    encoded_readback = raw.exec("print(ubinascii.b2a_base64(f.read(384)).decode().strip())")
                    verified.extend(base64.b64decode(encoded_readback))
            finally:
                raw.exec("f.close();gc.collect()")
            if verified != payload:
                raise RuntimeError("Read-back mismatch for " + name)
            raw.exec("os.rename(%r,%r)" % (staging, target))
            print("UPLOADED_VERIFIED", name, len(payload), flush=True)
        if getattr(args,'baseline_adapter',False):
            target = "/flash/cabinet_monitor_v2/config.py"
            if "config.py" in raw.exec("print(os.listdir('/flash/cabinet_monitor_v2'))"):
                raise RuntimeError("config.py already exists; refusing to replace it")
            payload = source_path(source_dir, "config_baseline_adapter.py").read_bytes()
            raw.exec("f=open(%r,'wb')" % target)
            try:
                for offset in range(0, len(payload), 144):
                    encoded = base64.b64encode(payload[offset:offset + 144]).decode("ascii")
                    raw.exec("f.write(ubinascii.a2b_base64('%s'))" % encoded)
            finally:
                raw.exec("f.close()")
            print("UPLOADED", "config.py", len(payload))
    finally:
        raw.close()


if __name__ == "__main__":
    main()
