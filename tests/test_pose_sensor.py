"""Pose polling must not invoke slow temperature conversions or retry setup."""
import importlib.util
import types
import unittest
from unittest.mock import patch
from support import DEVICE_DIR


class PoseSensorTests(unittest.TestCase):
    def test_fast_path_reads_only_imu_and_rejects_bad_vectors(self):
        spec=importlib.util.spec_from_file_location('pose_sensor_fixture',DEVICE_DIR/'sensors.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules',{
                'machine':types.SimpleNamespace(),
                'ahtx0':types.SimpleNamespace(AHT20=object),
                'lis2dh12':types.SimpleNamespace(LIS2DH12=object)}):
            spec.loader.exec_module(module)
        sensor=module.Sensors.__new__(module.Sensors)
        sensor._recover_missing=lambda:self.fail('Fast path must not recover all sensors')
        sensor.lis=types.SimpleNamespace(acceleration=(-9.81,0,9.81))
        self.assertEqual(sensor.read_acceleration(),(-9.81,0,9.81))
        for vector in ((0,float('nan'),0),(0,0),(161,0,0)):
            sensor.lis.acceleration=vector
            self.assertIsNone(sensor.read_acceleration())
        sensor.lis=None
        self.assertIsNone(sensor.read_acceleration())
