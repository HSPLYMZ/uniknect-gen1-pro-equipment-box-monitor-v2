"""Observe a running app without interrupting it; save filtered output only."""
import argparse
from pathlib import Path
import time
import serial
from serial_log import print_safe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    import contextlib
    import io
    pending = ""
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
    output = args.out.open("a", encoding="utf-8") if args.out else None
    ser = None
    try:
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            try:
                if ser is None:
                    ser = serial.Serial(args.port, 115200, timeout=0.2)
                    pending = ""
                captured = io.StringIO()
                with contextlib.redirect_stdout(captured):
                    pending = print_safe(ser.read(4096), pending)
                safe = captured.getvalue()
                if safe:
                    print(safe, end="", flush=True)
                    if output:
                        output.write(safe)
                        output.flush()
            except serial.SerialException:
                if ser is not None:
                    ser.close()
                    ser = None
                time.sleep(0.5)
    finally:
        if ser is not None:
            ser.close()
        if output:
            output.close()


if __name__ == "__main__":
    main()
