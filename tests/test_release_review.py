"""Fault and long-running regressions found in the release review."""
import contextlib
import importlib.util
import io
import types
import sys
import unittest
from unittest.mock import patch
from support import DEVICE_DIR
import config_template
import events
from runtime import Runtime
from sd_store import SdStore
from audio_recorder import AudioRecorder


def cfg(**changes):
    values = {k:v for k,v in vars(config_template).items() if k.isupper()}
    values.update(changes)
    return types.SimpleNamespace(**values)


class ReleaseReviewTests(unittest.TestCase):
    def test_cooldown_and_fusion_across_tick_wrap(self):
        diff = lambda a,b: ((a-b+4096)%8192)-4096
        with patch.object(events, 'ticks_diff', diff):
            latch=events._Latch(1,2000)
            self.assertEqual(latch.update(True,False,7500),'on')
            latch.update(False,True,7600)
            self.assertIsNone(latch.update(True,False,100))
            self.assertEqual(latch.update(True,False,2000),'on')
            engine=events.EventEngine(cfg(FUSION_WINDOW_MS=500))
            engine.last_light_ms,engine.last_tilt_ms=8000,50
            engine.latches['light'].active=engine.latches['tilt'].active=True
            self.assertEqual(engine._update_combined(50)[0]['type'],'combined')

    def test_uptime_accumulates_multiple_tick_wraps(self):
        clock=types.SimpleNamespace(now=7000)
        clock.ticks_ms=lambda:clock.now
        clock.ticks_diff=lambda a,b:((a-b+4096)%8192)-4096
        runtime=Runtime(clock)
        for _ in range(20):
            clock.now=(clock.now+1000)%8192
            runtime.uptime()
        self.assertEqual(runtime.elapsed_ms,20000)
        with self.assertRaises(OSError):
            runtime.call('failed_io',lambda:(_ for _ in ()).throw(OSError()))
        self.assertIn('failed_io',runtime.max_ms)

    def test_invalid_calibration_does_not_claim_ready_or_block_temperature(self):
        engine=events.EventEngine(cfg(CALIBRATION_SAMPLES=3,EVENT_CONSECUTIVE=3))
        seen=[]
        for now in range(20):
            seen+=engine.update({'temperature_c':40,'light_adc_u16':38000,'accel_m_s2':None},now*1000)
        self.assertFalse(engine.ready)
        self.assertTrue(any(e['type']=='temperature' and e['transition']=='on' for e in seen))

    def test_i2c_devices_fail_independently_and_bad_values_are_missing(self):
        spec=importlib.util.spec_from_file_location('review_sensors',DEVICE_DIR/'sensors.py')
        module=importlib.util.module_from_spec(spec)
        machine=types.SimpleNamespace(I2C=lambda *a,**k:object(),Pin=lambda p:p,
            ADC=lambda p:types.SimpleNamespace(read_u16=lambda:38000))
        accel=types.SimpleNamespace(acceleration=(0,0,9.8))
        with patch.dict(sys.modules,{'machine':machine,
             'ahtx0':types.SimpleNamespace(AHT20=lambda bus:(_ for _ in ()).throw(OSError('fixture'))),
             'lis2dh12':types.SimpleNamespace(LIS2DH12=lambda bus:accel)}):
            spec.loader.exec_module(module)
            sensor=module.Sensors()
        self.assertEqual(sensor.read()['accel_m_s2'],(0,0,9.8))
        sensor.aht=types.SimpleNamespace(temperature=float('nan'),relative_humidity=150)
        sample=sensor.read()
        self.assertIsNone(sample['temperature_c']);self.assertIsNone(sample['humidity_pct'])
        self.assertFalse(sample['valid'])
        module.AHT20=lambda bus:types.SimpleNamespace(temperature=25,relative_humidity=50)
        sensor.aht=None
        with patch.object(module,'ticks_ms',lambda:sensor.last_retry+10001):
            self.assertTrue(sensor.read()['valid'])

    def test_short_sd_write_is_error_and_handle_is_closed(self):
        handle=types.SimpleNamespace(closed=False)
        handle.write=lambda b:len(b)-1
        handle.close=lambda:setattr(handle,'closed',True)
        file=types.SimpleNamespace(statvfs=lambda p:(10000000,9000000),open=lambda *a:handle)
        with patch.dict(sys.modules,{'quectel':types.SimpleNamespace(File=file)}),contextlib.redirect_stdout(io.StringIO()):
            storage=SdStore(cfg(),'fixture')
            self.assertFalse(storage.append({'value':1}))
            self.assertEqual(storage.state,'ERROR')
            self.assertEqual(storage.writes,0)
            self.assertTrue(handle.closed)
            self.assertTrue(storage.damaged)
            handle.closed=False
            self.assertFalse(storage.append({'value':2}))
            self.assertFalse(handle.closed)  # No second open/write into the torn file.
            handle.write=lambda b:(_ for _ in ()).throw(OSError('partial transfer'))
            storage=SdStore(cfg(),'second_fixture')
            self.assertFalse(storage.append({'value':3}))
            self.assertTrue(storage.damaged)
            self.assertTrue(handle.closed)

    def test_sd_limit_does_not_open_or_delete_files(self):
        file=types.SimpleNamespace(open=lambda *a:self.fail('Must not open'),remove=lambda *a:self.fail('Must not delete'))
        with patch.dict(sys.modules,{'quectel':types.SimpleNamespace(File=file)}),contextlib.redirect_stdout(io.StringIO()):
            storage=SdStore(cfg(SD_MAX_SESSION_BYTES=1),'fixture')
            self.assertFalse(storage.append({'value':1}));self.assertEqual(storage.state,'LIMIT')

    def test_continuous_audio_alarm_is_bounded_and_rearms_after_clear(self):
        import audio_recorder
        clock=types.SimpleNamespace(now=0)
        audio=types.SimpleNamespace(init=lambda:True,record_start=lambda p:None,record_stop=lambda:None,deinit=lambda:None)
        file=types.SimpleNamespace(statvfs=lambda p:(10000000,9000000))
        with patch.dict(sys.modules,{'quectel':types.SimpleNamespace(Audio=lambda:audio,File=file)}),\
             patch.object(audio_recorder,'ticks_ms',lambda:clock.now),contextlib.redirect_stdout(io.StringIO()):
            recorder=AudioRecorder(cfg(AUDIO_MAX_MS=100,AUDIO_RETRY_MS=100),'fixture')
            recorder.sync(['light']);self.assertTrue(recorder.recording)
            clock.now=10;recorder.sync([]);self.assertFalse(recorder.recording)
            clock.now=20;recorder.sync(['light']);self.assertTrue(recorder.recording)
            clock.now=121;recorder.sync(['light']);self.assertFalse(recorder.recording)
            clock.now=1000;recorder.sync(['light']);self.assertFalse(recorder.recording)
            recorder.sync([]);recorder.sync(['light']);self.assertTrue(recorder.recording)
            recorder.close()



if __name__=='__main__':unittest.main()
