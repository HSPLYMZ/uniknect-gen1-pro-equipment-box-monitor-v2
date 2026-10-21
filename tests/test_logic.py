"""Run on PC: python -m unittest test_logic.py"""

import unittest
from types import SimpleNamespace
from support import DEVICE_DIR
import config_template as cfg
from events import EventEngine
from queue_store import Outbox


def sample(temp=25, hum=50, light=10000, accel=(0, 0, 9.8)):
    return {"temperature_c": temp, "humidity_pct": hum,
            "light_adc_u16": light, "accel_m_s2": accel}


class LogicTests(unittest.TestCase):
    def setUp(self):
        self.previous = {key:getattr(cfg,key) for key in
                         ('LIGHT_MODE','CALIBRATION_SAMPLES','EVENT_CONSECUTIVE','EVENT_COOLDOWN_MS')}
        cfg.LIGHT_MODE = "delta"
        cfg.CALIBRATION_SAMPLES = 2
        cfg.EVENT_CONSECUTIVE = 3
        cfg.EVENT_COOLDOWN_MS = 60000

    def tearDown(self):
        for key,value in self.previous.items():
            setattr(cfg,key,value)

    def ready(self):
        engine = EventEngine(cfg)
        engine.update(sample(), 0)
        engine.update(sample(), 1000)
        return engine

    def test_temperature_hysteresis_and_consecutive(self):
        engine = self.ready()
        self.assertEqual(engine.update(sample(temp=36), 2000), [])
        self.assertEqual(engine.update(sample(temp=36), 3000), [])
        self.assertEqual(engine.update(sample(temp=36), 4000)[0]["transition"], "on")
        self.assertEqual(engine.update(sample(temp=34), 5000), [])
        self.assertEqual(engine.update(sample(temp=32), 6000)[0]["transition"], "clear")

    def test_light_and_tilt_fusion(self):
        engine = self.ready()
        engine.update(sample(light=20000, accel=(9.8, 0, 0)), 2000)
        engine.update(sample(light=20000, accel=(9.8, 0, 0)), 3000)
        kinds = [x["type"] for x in engine.update(sample(light=20000, accel=(9.8, 0, 0)), 4000)]
        self.assertEqual(kinds, ["light", "tilt", "combined"])

    def test_missing_light_does_not_block_temperature(self):
        engine = EventEngine(cfg)
        engine.update(sample(light=None), 0)
        engine.update(sample(light=None), 1000)
        for t in (2000, 3000):
            self.assertEqual(engine.update(sample(temp=36, light=None), t), [])
        self.assertEqual(engine.update(sample(temp=36, light=None), 4000)[0]["type"], "temperature")

    def test_queue_preserves_event_when_full(self):
        q = Outbox(2)
        q.put("state", {"seq": 1})
        q.put("event", {"seq": 2}, priority=True)
        q.put("event", {"seq": 3}, priority=True)
        self.assertEqual([x[1]["seq"] for x in q.items], [2, 3])
        self.assertEqual(q.dropped, 1)
        q.put("state", {"seq": 4})
        self.assertEqual([x[1]["seq"] for x in q.items], [2, 3])
        self.assertEqual(q.dropped, 2)

    def test_light_change_restarts_baseline(self):
        cfg.CALIBRATION_SAMPLES = 3
        engine = EventEngine(cfg)
        engine.update(sample(light=50000), 0)
        engine.update(sample(light=13000), 1000)
        self.assertFalse(engine.ready)
        self.assertEqual(engine.cal_count, 1)
        engine.update(sample(light=13100), 2000)
        engine.update(sample(light=13200), 3000)
        self.assertTrue(engine.ready)
        self.assertLess(abs(engine.light_base - 13100), 1)


class ExposureTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SimpleNamespace(**{k: v for k, v in vars(cfg).items() if k.isupper()})
        self.cfg.LIGHT_MODE = "absolute"
        self.engine = EventEngine(self.cfg)

    def test_exposed_at_boot_without_calibration_then_repeated_fast_cycles(self):
        self.assertFalse(self.engine.ready)
        self.assertEqual(self.engine.update(sample(light=13795), 0)[0],
                         {"type": "light", "transition": "on", "value": 13795})
        for at in (40, 120, 200):
            self.assertEqual(self.engine.update_light(38000, at)[0]["transition"], "clear")
            self.assertEqual(self.engine.update_light(13795, at + 40)[0]["transition"], "on")

    def test_covered_range_and_hysteresis_keep_state(self):
        for value in (38000, 30663, 65535, 24000, 21000, 18001):
            self.assertEqual(self.engine.update_light(value, 0), [])
        self.engine.update_light(18000, 40)
        for value in (18001, 21000, None, 23999):
            self.assertEqual(self.engine.update_light(value, 80), [])
            self.assertIn("light", self.engine.active())
        self.assertEqual(self.engine.update_light(24000, 120)[0]["transition"], "clear")

    def test_cover_clears_combined_immediately(self):
        self.engine.update_light(13795, 0)
        self.engine.last_tilt_ms = 0
        self.engine.latches["tilt"].active = True
        self.engine._update_combined(0)
        events = self.engine.update_light(38000, 40)
        self.assertEqual([(e["type"], e["transition"]) for e in events],
                         [("light", "clear"), ("combined", "clear")])


if __name__ == "__main__":
    unittest.main()
