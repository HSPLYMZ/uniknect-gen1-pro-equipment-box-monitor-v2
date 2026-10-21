"""Resident V2 launcher with bounded boot retries and preserved V1 fallback."""
import os
import sys
import time
import machine
import json

ROOT = "/flash/"


def exists(name):
    try:
        os.stat(ROOT + name)
        return True
    except OSError:
        return False


def write(name, value):
    with open(ROOT + name + ".new", "w") as handle:
        handle.write(str(value))
    os.rename(ROOT + name + ".new", ROOT + name)


def remove(name):
    try:
        os.remove(ROOT + name)
    except OSError:
        pass


def read_source(path):
    with open(path) as handle:
        return handle.read()


def failure_count():
    try:
        with open(ROOT + "v2_failures") as handle:
            return max(0, min(3, int(handle.read())))
    except Exception:
        # A torn counter is a failed previous boot, never permission to loop.
        return 1 if exists("v2_failures") else 0


def mark_healthy():
    remove("v2_pending")
    remove("v2_failures")
    print("BOOT_V2_HEALTHY")


def fallback():
    # A standalone V2 installation needs no local V1 project. A new board may
    # have no previous application; leave its REPL accessible after failures.
    if not exists("main_v1.py") or not exists("cabinet_monitor/main.py"):
        print("BOOT_V2_RECOVERY", "No previous application; maintenance REPL ready")
        return
    print("BOOT_V2_FALLBACK", "V1")
    sys.path.insert(0, ROOT + "cabinet_monitor")
    exec(read_source(ROOT + "main_v1.py"), {"__name__": "__main__"})


def start():
    boot_ticks = time.ticks_ms()
    if exists("disable_v2_autostart"):
        print("BOOT_V2_DISABLED")
        return
    print("BOOT_V2_WAIT", "Ctrl-C within 2 seconds enters maintenance")
    time.sleep_ms(2000)
    count = failure_count()
    if exists("v2_pending"):
        count += 1
    if exists("v2_fallback") or count >= 3:
        if not exists("v2_fallback"):
            write("v2_fallback", 1)
        fallback()
        return
    write("v2_failures", count)
    write("v2_pending", 1)
    # Start only after choosing V2; fallback V1 never inherits an active WDT.
    try:
        watchdog = machine.WDT(timeout=15000)
        sys.path.insert(0, ROOT + "cabinet_monitor_v2")
        import config_template as config
        # Private cloud profile is optional; local monitoring boots without it.
        config.ENABLE_MQTT = False
        config.ENABLE_QTH = False
        config.ENABLE_LBS = False
        config.START_PAGE = 2
        config._CLOUD_BOOT_TICKS = boot_ticks
        profile = "local-ble"
        try:
            with open(ROOT + "cloud_private.json") as handle:
                cloud = json.load(handle)
            for name in ("product_key", "product_secret", "device_key", "server"):
                if (not isinstance(cloud.get(name), str) or not cloud[name] or
                        cloud[name] == "CHANGE_ME" or len(cloud[name]) > 128):
                    raise ValueError("cloud configuration")
            if cloud.get("enabled") is True:
                config.QTH_PRODUCT_KEY = cloud["product_key"]
                config.QTH_PRODUCT_SECRET = cloud["product_secret"]
                config.QTH_DEVICE_KEY = cloud["device_key"]
                config.QTH_SERVER = cloud["server"]
                config.TRANSPORT_MODE = "qth"
                config.ENABLE_QTH = True
                profile = "ble-cloud-window"
            del cloud
        except OSError:
            pass
        except Exception:
            print("CLOUD_PROFILE", "invalid; local monitoring retained")
        config._WATCHDOG = watchdog
        config._BOOT_HEALTH = mark_healthy
        sys.modules["config"] = config
        print("BOOT_V2_START", profile, "attempt", count + 1, "wdt_ms", 15000)
        exec(read_source(ROOT + "cabinet_monitor_v2/main.py"), {"__name__": "__main__"})
        raise RuntimeError("Unexpected application return")
    except KeyboardInterrupt:
        # The watchdog cannot be disabled. Reset, then interrupt the boot delay
        # to enter maintenance before it is armed on the next boot.
        print("BOOT_V2_RESTART", "maintenance available during next boot delay")
        machine.reset()
    except Exception as exc:
        print("BOOT_V2_ERROR", type(exc).__name__)
        time.sleep_ms(300)
        machine.reset()


try:
    start()
except KeyboardInterrupt:
    print("BOOT_V2_INTERRUPTED")
except Exception as exc:
    # If boot bookkeeping itself fails (e.g. full Flash), it cannot reliably
    # count retries. Run V1 directly rather than reset forever without a count.
    print("BOOT_V2_LAUNCH_ERROR", type(exc).__name__)
    try:
        fallback()
    except KeyboardInterrupt:
        print("BOOT_V2_INTERRUPTED")
    except Exception as fallback_exc:
        print("BOOT_V2_FALLBACK_ERROR", type(fallback_exc).__name__)
