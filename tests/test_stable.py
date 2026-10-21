"""Cooperative I/O boundaries and resident boot recovery regressions."""
import ast
import contextlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from support import DEVICE_DIR
from test_release_review import cfg
from sd_store import SdStore
from audio_recorder import AudioRecorder


class StableTests(unittest.TestCase):
    def test_v2_logo_loads_its_own_resource(self):
        source=(DEVICE_DIR/'logo_asset.py').read_text()
        pixels=(DEVICE_DIR/'assets/logo_160x20.bin').read_bytes()
        with patch('builtins.open',return_value=io.BytesIO(pixels)) as opened:
            namespace={}
            exec(compile(source,'logo_asset.py','exec'),namespace)
        opened.assert_called_once_with('/flash/cabinet_monitor_v2/logo_160x20.bin','rb')
        self.assertEqual(namespace['Quectel_Icon_160x20'],pixels)

    def test_sd_steps_bound_native_calls_and_preserve_exact_record(self):
        calls, output = [], bytearray()
        handle = types.SimpleNamespace()
        def write(data):
            calls.append('write'); output.extend(data); return len(data)
        handle.write = write
        handle.close = lambda:calls.append('close')
        file = types.SimpleNamespace(statvfs=lambda p:(calls.append('stat') or (10**8,10**8)),
                                     open=lambda *a:(calls.append('open') or handle))
        storage = SdStore(cfg(), 'fixture')
        record = {'kind':'sample','text':'x'*900}
        import json
        expected = json.dumps(record).encode()+b'\n'
        self.assertTrue(storage.submit(record))
        record['text']='changed after submission'
        with patch.dict(sys.modules,{'quectel':types.SimpleNamespace(File=file)}):
            for _ in range(12):
                before=len(calls); storage.step()
                self.assertLessEqual(len(calls)-before,1)
        self.assertEqual(output,expected)
        self.assertEqual(storage.writes,1)
        self.assertEqual(storage.state,'READY')

    def test_sd_pending_priority_and_short_write_cleanup(self):
        storage=SdStore(cfg(),'fixture')
        for _ in range(4):storage.submit({'kind':'event'})
        self.assertFalse(storage.submit({'kind':'sample'}))
        self.assertTrue(storage.submit({'kind':'event'}))
        self.assertEqual(len(storage.pending),4)
        self.assertEqual(storage.dropped,2)
        closed=[]
        handle=types.SimpleNamespace(write=lambda b:1,close=lambda:closed.append(1))
        file=types.SimpleNamespace(statvfs=lambda p:(10**8,10**8),open=lambda *a:handle)
        with patch.dict(sys.modules,{'quectel':types.SimpleNamespace(File=file)}),contextlib.redirect_stdout(io.StringIO()):
            storage.step();storage.step();storage.step()
            self.assertTrue(storage.damaged)
            self.assertEqual(closed,[])
            storage.step()
            self.assertEqual(closed,[1])
            self.assertFalse(storage.submit({'kind':'sample'}))
            self.assertEqual(storage.writes,0)

    def test_audio_steps_cancel_startup_and_stop_at_duration(self):
        import audio_recorder
        calls=[]; clock=types.SimpleNamespace(now=0)
        audio=types.SimpleNamespace(init=lambda:(calls.append('init') or True),
            record_start=lambda p:calls.append('start'),record_stop=lambda:calls.append('stop'),
            deinit=lambda:calls.append('deinit'))
        file=types.SimpleNamespace(statvfs=lambda p:(calls.append('stat') or (10**8,10**8)))
        with patch.dict(sys.modules,{'quectel':types.SimpleNamespace(File=file,Audio=lambda:audio)}),\
                patch.object(audio_recorder,'ticks_ms',lambda:clock.now),contextlib.redirect_stdout(io.StringIO()):
            recorder=AudioRecorder(cfg(AUDIO_MAX_MS=100),'fixture')
            recorder.step(['light']);recorder.step(['light']);recorder.step([])
            self.assertEqual(calls,['stat','init','deinit'])
            clock.now=10  # A distinct alarm is eligible immediately after cancel.
            for _ in range(3):
                before=len(calls);recorder.step(['light']);self.assertLessEqual(len(calls)-before,1)
            self.assertTrue(recorder.recording)
            clock.now+=101
            recorder.step(['light']);self.assertFalse(recorder.recording)
            recorder.step(['light']);self.assertEqual(recorder.state,'LIMIT')
            before=len(calls)
            recorder.step(['light']);self.assertEqual(len(calls),before)
            recorder.step([])
            for _ in range(3):recorder.step(['light'])
            self.assertTrue(recorder.recording)

    def boot_module(self, directory):
        # Load launcher definitions without executing the entrypoint's final try.
        tree=ast.parse((DEVICE_DIR/'startup_v2.py').read_text())
        tree.body=tree.body[:-1]
        module=types.ModuleType('boot_fixture')
        with patch.dict(sys.modules,{'machine':types.SimpleNamespace()}):
            exec(compile(tree,'startup_v2.py','exec'),module.__dict__)
        module.ROOT=str(directory)+'/'
        module.time=types.SimpleNamespace(sleep_ms=lambda n:None,ticks_ms=lambda:0)
        return module

    def test_three_failed_boots_latch_v1_without_arming_watchdog(self):
        with tempfile.TemporaryDirectory() as directory:
            module=self.boot_module(directory)
            module.time=types.SimpleNamespace(sleep_ms=lambda n:None,ticks_ms=lambda:0)
            module.machine.WDT=lambda **kw:self.fail('Must choose fallback before WDT')
            module.write('v2_failures',2);module.write('v2_pending',1)
            called=[];module.fallback=lambda:called.append('V1')
            with contextlib.redirect_stdout(io.StringIO()):module.start()
            self.assertEqual(called,['V1'])
            self.assertTrue(module.exists('v2_fallback'))
            module.remove('v2_pending')
            with contextlib.redirect_stdout(io.StringIO()):module.start()
            self.assertEqual(called,['V1','V1'])

    def test_healthy_boot_clears_pending_and_maintenance_never_arms_wdt(self):
        with tempfile.TemporaryDirectory() as directory:
            module=self.boot_module(directory)
            module.write('v2_failures',2);module.write('v2_pending',1)
            with contextlib.redirect_stdout(io.StringIO()):module.mark_healthy()
            self.assertEqual(module.failure_count(),0)
            self.assertFalse(module.exists('v2_pending'))
            module.write('disable_v2_autostart',1)
            module.machine.WDT=lambda **kw:self.fail('Maintenance must stay accessible')
            with contextlib.redirect_stdout(io.StringIO()):module.start()

    def test_standalone_without_previous_application_leaves_repl_accessible(self):
        with tempfile.TemporaryDirectory() as directory:
            module=self.boot_module(directory)
            module.time=types.SimpleNamespace(sleep_ms=lambda n:None,ticks_ms=lambda:0)
            module.machine.WDT=lambda **kw:self.fail('Recovery must not arm WDT')
            module.machine.reset=lambda:self.fail('Recovery must not reset forever')
            module.write('v2_failures',2);module.write('v2_pending',1)
            output=io.StringIO()
            with contextlib.redirect_stdout(output):module.start()
            self.assertIn('BOOT_V2_RECOVERY',output.getvalue())
            self.assertTrue(module.exists('v2_fallback'))

    def test_launch_exception_resets_and_keeps_failure_marker(self):
        class Reset(BaseException):pass
        with tempfile.TemporaryDirectory() as directory:
            module=self.boot_module(directory)
            folder=Path(directory)/'cabinet_monitor_v2';folder.mkdir()
            (folder/'main.py').write_text("raise ValueError('private detail must not print')")
            watchdog=object()
            module.machine.WDT=lambda **kw:watchdog
            module.machine.reset=lambda:(_ for _ in ()).throw(Reset())
            module.time=types.SimpleNamespace(sleep_ms=lambda n:None,ticks_ms=lambda:0)
            config=cfg()
            output=io.StringIO()
            original_path=sys.path[:]
            try:
                with patch.dict(sys.modules,{'config_template':config}),contextlib.redirect_stdout(output):
                    with self.assertRaises(Reset):module.start()
            finally:sys.path[:]=original_path
            self.assertTrue(module.exists('v2_pending'))
            self.assertIs(config._WATCHDOG,watchdog)
            self.assertIn('BOOT_V2_ERROR ValueError',output.getvalue())
            self.assertNotIn('private detail',output.getvalue())

    def test_unwritable_boot_bookkeeping_falls_back_without_reset_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            module=self.boot_module(directory)
            called=[]
            module.start=lambda:(_ for _ in ()).throw(OSError('full flash'))
            module.fallback=lambda:called.append('V1')
            module.machine.reset=lambda:self.fail('Must not reset without persistent counter')
            tree=ast.parse((DEVICE_DIR/'startup_v2.py').read_text())
            tree.body=tree.body[-1:]
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(tree,'startup_v2.py','exec'),module.__dict__)
            self.assertEqual(called,['V1'])


if __name__=='__main__':unittest.main()
