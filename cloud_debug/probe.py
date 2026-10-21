"""Temporary MicroPython Qth probe; uploaded/executed in RAM by run_probe.py."""
import math
import json
import time


def emit(event, **fields):
    fields["event"] = event
    print("CLOUD_PROBE " + json.dumps(fields))


def result_info(value):
    return {"return_type": type(value).__name__,
            "return_code": value if isinstance(value, (bool, int)) else None}


def connected_state(Qth):
    value = Qth.state()
    if isinstance(value, bool) or (isinstance(value, int) and value in (0, 1)):
        return bool(value)
    raise RuntimeError("Unsupported cloud state result")


def build_values(sample):
    """This product: 2=temp, 3=humidity, 4=raw ADC, 5=validity mask."""
    values = {}
    mask = 0
    for field, fid, lo, hi, bit in (
        ("temperature_c", 2, -40, 85, 1),
        ("humidity_pct", 3, 0, 100, 2),
        ("light_adc_u16", 4, 0, 65535, 4),
    ):
        value = sample.get(field)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and lo <= value <= hi):
            if fid == 4:
                if value != int(value):
                    continue
                value = int(value)
            values[fid] = value
            mask |= bit
    # Bit3 is reserved; this first probe does not upload acceleration.
    values[5] = mask
    return values


def run_probe(cfg):
    import sys
    sys.path.insert(0, "/flash/cabinet_monitor_v2")
    import Qth
    from sensors import Sensors
    from cloud_policy import TrafficBudget

    pending_reads = []
    cached = {5: 0}
    sample_at = None
    counters = {"reports": 0, "accepted": 0, "read_replies": 0, "errors": 0,
                "unconfirmed_send_returns": 0, "read_reply_calls": 0}

    def dev_event(event, result):
        # Never forward arbitrary native diagnostic strings or credentials.
        emit("sdk_event", code=event if isinstance(event, int) else None,
             result=result if isinstance(result, int) else None)

    def read_tsl(ids, pkg_id):
        if len(pending_reads) < 4:
            pending_reads.append((list(ids)[:32], pkg_id))

    started = False
    online_observed = False
    traced_storage = []
    try:
        budget = TrafficBudget('/flash/cloud_budget.json', time.ticks_ms(), time.ticks_diff)
        if budget.error:
            emit('budget_storage_blocked')
            return
        emit("initializing")
        emit("sdk_api", methods=[name for name in dir(Qth) if not name.startswith("_")])
        initialized = Qth.init()
        emit("init_result", **result_info(initialized))
        if initialized is False:
            emit("initialization_failed")
            return
        if cfg.get("diagnose_connection", False):
            mqtt_class = Qth.qth_dmp.MQTTClient
            mqtt_connect = mqtt_class.connect
            mqtt_init = mqtt_class.__init__

            def mqtt_init_trace(self, *args, **kwargs):
                try:
                    client_id = args[0] if args else kwargs.get("client_id", "")
                    if isinstance(client_id, bytes):
                        client_id = client_id.decode()
                    if isinstance(client_id, str):
                        allowed = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        emit("mqtt_identity_shape", client_id_length=len(client_id),
                             has_expected_pk=cfg["product_key"] in client_id,
                             has_expected_dk=cfg["device_key"] in client_id,
                             punctuation="".join(c for c in client_id if c not in allowed)[:80])
                except Exception as exc:
                    emit("diagnostic_error", error_type=type(exc).__name__)
                return mqtt_init(self, *args, **kwargs)

            def mqtt_connect_trace(self, *args, **kwargs):
                emit("mqtt_connecting", host=getattr(self, "server", None),
                     port=getattr(self, "port", None))
                try:
                    return mqtt_connect(self, *args, **kwargs)
                except Exception as exc:
                    emit("mqtt_exception", error_type=type(exc).__name__,
                         numeric_args=[v for v in exc.args if isinstance(v, int)])
                    raise

            traced_storage.append((mqtt_class, "__init__", mqtt_init))
            traced_storage.append((mqtt_class, "connect", mqtt_connect))
            mqtt_class.__init__ = mqtt_init_trace
            mqtt_class.connect = mqtt_connect_trace
        if cfg.get("storage_directory_compatibility", False):
            # Firmware SDK unconditionally mkdir('/flash/usr') in write_file.
            # Keep its serialization/encryption and verify every saved payload.
            import os
            import _thread
            qfile = Qth.qth_file
            original_write_file = qfile.write_file
            storage_lock = _thread.allocate_lock()

            class StorageOs:
                def __getattr__(self, name):
                    return getattr(os, name)

                def mkdir(self, path, *args):
                    try:
                        return os.mkdir(path, *args)
                    except OSError as exc:
                        if (path == "/flash/usr" and exc.args and exc.args[0] == 17
                                and os.stat(path)[0] & 0x4000):
                            return None
                        raise

            def compatible_write_file(path, data):
                storage_lock.acquire()
                saved = {name: sys.modules.get(name) for name in ("os", "uos")}
                try:
                    proxy = StorageOs()
                    sys.modules["os"] = proxy
                    sys.modules["uos"] = proxy
                    result = original_write_file(path, data)
                finally:
                    for name, value in saved.items():
                        if value is None:
                            sys.modules.pop(name, None)
                        else:
                            sys.modules[name] = value
                    storage_lock.release()
                # MicroPython ujson serializes SDK SHA bytes as text.
                expected = json.loads(json.dumps(data))
                if result is True and qfile.read_file(path) != expected:
                    raise RuntimeError("SDK storage readback mismatch")
                emit("storage_verified", saved=result is True,
                     path=path if path == "/flash/usr/qth_config.ini" else None)
                return result

            traced_storage.append((qfile, "write_file", original_write_file))
            qfile.write_file = compatible_write_file
            emit("storage_directory_compatibility_enabled")
        if cfg.get("diagnose_storage", False):
            qfile = Qth.qth_file
            for method in ("write", "write_file", "read_file"):
                fn = getattr(qfile, method, None)
                namespace = getattr(fn, "__globals__", {})
                emit("storage_function", method=method, function_type=type(fn).__name__,
                     module=getattr(fn, "__module__", None),
                     global_names=list(namespace.keys()) if isinstance(namespace, dict) else [])
            for method in ("write", "write_file"):
                original = getattr(qfile, method, None)
                if original is None:
                    continue
                def make_trace(name, function):
                    def traced(*args, **kwargs):
                        path = None
                        if args and isinstance(args[0], str):
                            value = args[0]
                            if len(value) < 120 and any(part in value.lower() for part in
                                    ("config", "bootstrap", "qth", "/", ".json", ".cfg")):
                                path = value
                                for secret in (cfg["product_key"], cfg["product_secret"], cfg["device_key"]):
                                    path = path.replace(secret, "<redacted>")
                        try:
                            result = function(*args, **kwargs)
                            emit("storage_call", method=name, path=path,
                                 argument_types=[type(v).__name__ for v in args], **result_info(result))
                            return result
                        except Exception as exc:
                            code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
                            emit("storage_exception", method=name, path=path,
                                 error_type=type(exc).__name__, errno=code)
                            raise
                    return traced
                traced_storage.append((qfile, method, original))
                setattr(qfile, method, make_trace(method, original))
            emit("sdk_config_state", sdk_running=getattr(Qth.qth_init, "_qth_isRun", None))
        for name, fn, args in (
            ("product", Qth.setProductInfo, (cfg["product_key"], cfg["product_secret"])),
            ("device", Qth.setDK, (cfg["device_key"],)),
            ("server", Qth.setServer, (cfg["server"],)),
        ):
            result = fn(*args)
            emit("configuration_result", stage=name, **result_info(result))
            if result is False:
                if name == "product":
                    module = Qth.qth_config
                    emit("product_memory_check",
                         key_matches=getattr(module, "_config_pk", None) == cfg["product_key"],
                         secret_matches=getattr(module, "_config_ps", None) == cfg["product_secret"])
                emit("configuration_failed", stage=name)
                return
        Qth.setVer("V2.2.0-cloud-probe")
        Qth.setEventCb({"devEvent": dev_event, "readTsl": read_tsl})
        result = Qth.start()
        emit("start_result", **result_info(result))
        if result is False:
            emit("start_failed")
            return
        started = True
        emit("sdk_started")
        began = time.ticks_ms()
        while not connected_state(Qth):
            if time.ticks_diff(time.ticks_ms(), began) >= cfg["connect_timeout_seconds"] * 1000:
                emit("login_timeout")
                return
            time.sleep_ms(200)
        online_observed = True
        emit("online", device_key=cfg["device_key"])

        sensors = Sensors()
        began = time.ticks_ms()
        last_report = None
        was_connected = True
        while time.ticks_diff(time.ticks_ms(), began) < cfg["observe_seconds"] * 1000:
            if counters["reports"] + counters["read_reply_calls"] >= 12:
                emit("diagnostic_call_limit", maximum=12)
                break
            now = time.ticks_ms()
            connected = connected_state(Qth)
            if connected != was_connected:
                emit("connection_changed", connected=connected)
                was_connected = connected
            if connected and (last_report is None or
                    time.ticks_diff(now, last_report) >= cfg["report_seconds"] * 1000):
                if not budget.take(now, 2):
                    emit('budget_exhausted')
                    break
                cached = build_values(sensors.read())
                sample_at = time.ticks_ms()
                last_report = sample_at
                result = Qth.sendTsl(1, cached)
                accepted = bool(result) if result is not None else None
                counters["reports"] += 1
                counters["accepted"] += int(accepted is True)
                counters["errors"] += int(accepted is False)
                counters["unconfirmed_send_returns"] += int(accepted is None)
                emit("report", accepted=accepted, values=cached, **result_info(result))
            if connected and pending_reads:
                ids, pkg_id = pending_reads.pop(0)
                fresh = sample_at is not None and time.ticks_diff(time.ticks_ms(), sample_at) <= 15000
                snapshot = cached if fresh else {5: 0}
                answer = {}
                for fid in ids:
                    try:
                        fid = int(fid)
                    except (ValueError, TypeError):
                        continue
                    if fid in snapshot:
                        answer[fid] = snapshot[fid]
                # Unsupported standard lux ID1 is never given fabricated data.
                if answer:
                    if counters["reports"] + counters["read_reply_calls"] >= 12 or not budget.take(time.ticks_ms(), 2):
                        emit('diagnostic_reply_budget_exhausted')
                        break
                    counters["read_reply_calls"] += 1
                    result = Qth.ackTsl(1, answer, pkg_id)
                    accepted = bool(result) if result is not None else None
                    counters["read_replies"] += int(accepted is True)
                    counters["errors"] += int(accepted is False)
                    emit("read_reply", accepted=accepted, values=answer, fresh=fresh, **result_info(result))
                else:
                    emit("read_unsupported_or_invalid")
            time.sleep_ms(100)
        emit("summary", online_observed=online_observed, **counters)
    except KeyboardInterrupt:
        emit("interrupted")
    except Exception as exc:
        emit("exception", error_type=type(exc).__name__)
    finally:
        try:
            Qth.stop()
            emit("stopped")
        except Exception as exc:
            emit("stop_failed", error_type=type(exc).__name__)
        finally:
            for obj, name, original in reversed(traced_storage):
                setattr(obj, name, original)

