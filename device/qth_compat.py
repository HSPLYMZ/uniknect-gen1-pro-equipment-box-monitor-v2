"""Narrow workaround for Beta20260721 SDK's unconditional usr mkdir."""
import os
import sys
import json
import _thread


def install(Qth):
    qfile = Qth.qth_file
    original = qfile.write_file
    lock = _thread.allocate_lock()

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

    def write_file(path, data):
        lock.acquire()
        saved = (sys.modules.get("os"), sys.modules.get("uos"))
        try:
            proxy = StorageOs()
            sys.modules["os"] = proxy
            sys.modules["uos"] = proxy
            try:
                result = original(path, data)
            finally:
                for name, value in zip(("os", "uos"), saved):
                    if value is None:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = value
            if result is True and qfile.read_file(path) != json.loads(json.dumps(data)):
                raise RuntimeError("SDK storage verification")
            return result
        finally:
            lock.release()

    qfile.write_file = write_file
    return original
