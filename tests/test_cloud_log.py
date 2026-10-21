"""Acceptance logs must not turn partial, failed or mixed boots into a pass."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "cloud_log_review", Path(__file__).resolve().parents[1] / "host/analyze_cloud_log.py")
LOG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOG)


def complete_log():
    rows = ["BOOT_V2_START ble-cloud-window attempt 1 wdt_ms 15000",
            "APP_STATUS uptime 2 valid True ram 20000 ble_errors 0 pose_errors 0"]
    count = 0
    for window in range(5):
        for offset in range(12):
            count += 1
            rows.append("CLOUD_SEND %s slot %s result CALLED remaining 30" %
                        (count, 30 + window * 30 + offset))
    for uptime, ping in ((1802, 30), (1862, 31), (1922, 32)):
        rows.append("APP_STATUS uptime %s valid True ram 19000 ble_errors 0 pose_errors 0" % uptime)
        rows.append("CLOUD_STATUS " + repr({"phase": "ENDED", "network": "ONLINE",
                    "sent": 60, "pings": ping, "ping_errors": 0}))
    return rows


class CloudLogAcceptanceTests(unittest.TestCase):
    def analyze(self, rows):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cycle.log"
            path.write_text("\n".join(rows), encoding="utf8")
            return LOG.analyze([path])

    def test_complete_cycle_requires_post_end_keepalive(self):
        report = self.analyze(complete_log())
        self.assertTrue(report["complete_cycle_verified"])
        self.assertEqual(report["calls_by_window"], [12] * 5)
        self.assertFalse(self.analyze(complete_log()[:-2])["complete_cycle_verified"])

    def test_failed_send_or_missing_window_cannot_pass(self):
        rows = complete_log()
        rows[2] = rows[2].replace("CALLED", "FAIL")
        report = self.analyze(rows)
        self.assertFalse(report["complete_cycle_verified"])
        self.assertEqual(report["failed_business_calls"], 1)
        self.assertFalse(self.analyze(complete_log()[0:2] + complete_log()[3:])["complete_cycle_verified"])

    def test_duplicates_forbidden_slots_and_post_end_calls_cannot_pass(self):
        for replacement in ("slot 31", "slot 42"):
            rows = complete_log()
            rows[2] = rows[2].replace("slot 30", replacement)
            self.assertFalse(self.analyze(rows)["complete_cycle_verified"])
        rows = complete_log()
        rows.append(rows.pop(2))
        report = self.analyze(rows)
        self.assertEqual(report["business_calls_after_end"], 1)
        self.assertFalse(report["complete_cycle_verified"])

    def test_multiple_boots_and_device_errors_cannot_pass(self):
        for line in ("BOOT_V2_START ble-cloud-window attempt 1 wdt_ms 15000",
                     "APP_STATUS uptime 1 valid True ram 18000",
                     "APP_STATUS uptime 1923 valid False ram 18000",
                     "APP_STATUS uptime 1923 valid True ram 18000 pose_errors 1",
                     "CLOUD_EVENT 2 -17924", "CLOUD_PING_ERROR 1"):
            self.assertFalse(self.analyze(complete_log() + [line])["complete_cycle_verified"])

    def test_ping_error_event_and_status_are_not_double_counted(self):
        rows = complete_log() + ["CLOUD_PING_ERROR 1", "CLOUD_STATUS " + repr(
            {"phase": "ENDED", "network": "ONLINE", "sent": 60, "pings": 32, "ping_errors": 1})]
        report = self.analyze(rows)
        self.assertEqual(report["protocol_ping_errors"], 1)
        self.assertFalse(report["complete_cycle_verified"])


if __name__ == "__main__":
    unittest.main()
