"""Copy to config_private.py and fill your own product credentials."""
CONFIG = {
    "product_key": "CHANGE_ME",
    "product_secret": "CHANGE_ME",
    "device_key": "cabinet01",
    "server": "mqtt://iot-south.quectelcn.com:1883",
    "connect_timeout_seconds": 90,
    "observe_seconds": 60,
    "report_seconds": 10,
    # Enable only for this firmware's confirmed /flash/usr EEXIST issue.
    "storage_directory_compatibility": False,
}
