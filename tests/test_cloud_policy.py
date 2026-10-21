"""Traffic limits and schedule boundaries, including crashes/reboots."""
import sys, tempfile, unittest, json, random
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "device"))
from cloud_policy import Schedule, TrafficBudget, phase, build_values, decode_signal


class PolicyTests(unittest.TestCase):
    def test_signal_unit_conversion_invalid_sentinels_and_zero(self):
        self.assertEqual(decode_signal((-72,121)),(-72,37.0))
        self.assertEqual(decode_signal((-75,47)),(-75,0.0))
        self.assertEqual(decode_signal((-75,1)),(-75,-23.0))
        self.assertEqual(decode_signal((-75,127)),(-75,40.0))
        self.assertEqual(decode_signal((-75,255)),(-75,None))
        self.assertEqual(decode_signal((99,0)),(None,None))
        self.assertEqual(decode_signal(None),(None,None))

    def test_full_boot_has_exactly_sixty_slots_and_no_send_after_stop(self):
        schedule = Schedule()
        sent = [n for n in range(0, 2000001, 200) if schedule.due(n)]
        expected = [start + delta for start in (300000,600000,900000,1200000,1500000)
                    for delta in range(0,120000,10000)]
        self.assertEqual(sent, expected)
        for n, name in ((299999,"WAIT"),(300000,"REPORT"),(419999,"REPORT"),
                        (420000,"PAUSE"),(600000,"REPORT"),(1620000,"PAUSE"),
                        (1799999,"PAUSE"),(1800000,"ENDED"),(86400000,"ENDED")):
            self.assertEqual(phase(n)[0], name)

    def test_late_loop_does_not_replay_missed_slots(self):
        s = Schedule()
        self.assertTrue(s.due(300001))
        self.assertFalse(s.due(309999))
        self.assertTrue(s.due(340000))
        self.assertFalse(s.due(340001))
        self.assertFalse(s.due(420000))

    def test_real_values_missing_zero_nan_and_ranges(self):
        self.assertEqual(build_values({"temperature_c":0,"humidity_pct":0,"light_adc_u16":0}),
                         {2:0,3:0,4:0,5:7})
        self.assertEqual(build_values({"temperature_c":float("nan"), "humidity_pct":101,
                                       "light_adc_u16":10.5}), {5:0})
        self.assertEqual(build_values({"temperature_c":True,"humidity_pct":42,
                                       "light_adc_u16":65535}), {3:42,4:65535,5:6})

    def test_budget_survives_repeated_reboots_without_refill(self):
        with tempfile.TemporaryDirectory() as d:
            p=str(Path(d)/"budget.json")
            count=0
            for _ in range(200):
                b=TrafficBudget(p,0,lambda a,z:a-z)
                if b.take(0):count+=1
            # Reserving16 before dispatch loses14 units each reboot.
            self.assertEqual(count,15)
            self.assertEqual(b.remaining(),0)

    def test_capacity_and_twenty_four_hour_refill_bound(self):
        with tempfile.TemporaryDirectory() as d:
            b=TrafficBudget(str(Path(d)/"b"),0,lambda a,z:a-z)
            count=0
            for now in range(0,86400000,1000):
                if b.take(now):count+=1
            self.assertLessEqual(count*2,840)
            self.assertGreaterEqual(count,415)

    def test_online_idle_refill_is_saved_before_next_reboot(self):
        with tempfile.TemporaryDirectory() as d:
            p=str(Path(d)/"b")
            b=TrafficBudget(p,0,lambda a,z:a-z)
            for _ in range(120):self.assertTrue(b.take(0))
            self.assertFalse(b.take(0))
            for h in range(1,25):b.checkpoint(h*3600000)
            restarted=TrafficBudget(p,0,lambda a,z:a-z)
            self.assertEqual(restarted.remaining(),120)

    def test_corruption_or_unfinished_write_fails_closed(self):
        for corrupt in ('broken', '[1,999999999,0]', '[1,true,0]'):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/"b";p.write_text(corrupt)
                b=TrafficBudget(str(p),0,lambda a,z:a-z)
                self.assertFalse(b.take(999999999))
                self.assertEqual(b.error,"BUDGET_STORAGE")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"b";Path(str(p)+".new").write_text("partial")
            self.assertFalse(TrafficBudget(str(p),0,lambda a,z:a-z).take(0))

    def test_write_failure_never_dispatches_and_no_refund(self):
        with tempfile.TemporaryDirectory() as d:
            b=TrafficBudget(str(Path(d)/"b"),0,lambda a,z:a-z)
            with patch.object(b,"_save",side_effect=OSError("full")):
                self.assertFalse(b.take(0))
            self.assertFalse(b.take(999999999))

    def test_monotonic_wrap_and_backward_clock_do_not_mint_credits(self):
        with tempfile.TemporaryDirectory() as d:
            mod=1<<30
            diff=lambda a,z:((a-z+mod//2)%mod)-mod//2
            b=TrafficBudget(str(Path(d)/"b"),mod-100,diff)
            self.assertTrue(b.take(mod-100))
            old=b.balance
            b.tick(100)
            self.assertEqual(b.balance,old+200)
            b.tick(90)
            self.assertEqual(b.balance,old+200)


if __name__ == "__main__":unittest.main()
