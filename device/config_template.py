"""Copy as config.py on the board. Keep credentials out of shared code."""

DEVICE_ID = "cabinet-01"
BROKER = "CHANGE_ME"
PORT = 1883
USERNAME = ""
PASSWORD = ""
CLIENT_ID = "cabinet-01"
TOPIC_PREFIX = "uniknect"
TOPIC_OVERRIDE = ""  # Optional: use one exact topic when a test Broker restricts ACL.

# Intervals in milliseconds. 0 disables a feature where documented.
SAMPLE_MS = 1000
LIGHT_POLL_MS = 40  # Fast ADC path; temperature/IMU retain their own 1-second sampling.
HEARTBEAT_MS = 60000
DISPLAY_MS = 100  # Check changed content at 10 Hz; unchanged screens do no I/O.
SD_LOG_MS = 10000  # Preserve a 10-second history without writing every sensor sample.
GNSS_POLL_MS = 5000
LBS_POLL_MS = 300000  # 0 disables LBS. It may block for 15 seconds.
LOCATION_MAX_AGE_MS = 900000
MQTT_RETRY_MS = 5000
MQTT_RETRY_MAX_MS = 60000
QUEUE_LIMIT = 24  # Start conservatively; raise only after measuring free RAM.

# Calibrate against the assembled cabinet; raw light ADC has no lux unit.
TEMP_HIGH_C = 35.0
TEMP_CLEAR_C = 33.0
HUMIDITY_HIGH_PCT = 80.0
HUMIDITY_CLEAR_PCT = 75.0
LIGHT_DELTA_TRIGGER = 8000
LIGHT_DELTA_CLEAR = 5000
LIGHT_MODE = "absolute"
LIGHT_EXPOSED_LOW = True  # This board's ADC rises when the LDR is covered.
LIGHT_EXPOSED_TRIGGER = 18000  # Exposed approximately 13795: <= threshold turns red.
LIGHT_EXPOSED_CLEAR = 24000  # Covered approximately 38000: >= threshold turns black.
LIGHT_BACKGROUND_ONLY = True  # Other alarms retain events; background follows exposure.
TILT_TRIGGER_DEG = 30
TILT_CLEAR_DEG = 20
EVENT_CONSECUTIVE = 3
EVENT_COOLDOWN_MS = 60000
FUSION_WINDOW_MS = 10000
CALIBRATION_SAMPLES = 10
CALIBRATION_LIGHT_SPAN = 3000  # Restart baseline if light changes sharply during boot.

# Shield joystick is an ADC resistor ladder on Arduino A3 = STM32 PC1.
# A press is any sustained deviation from the idle ADC level. Adjust the
# delta only after measuring the joystick idle and pressed values.
BUTTON_PIN = "C1"
BUTTON_DELTA = 3000
BUTTON_LONG_MS = 1000
BUTTON_IDLE_U16 = 65535
BUTTON_DEBOUNCE_MS = 50

# A tap or one long press cycles Logo -> Author -> Live Monitor -> Cloud.
ENABLE_SD_LOG = True
SD_LOG_PREFIX = "cabinet"
SD_MIN_FREE_BYTES = 2 * 1024 * 1024
SD_MAX_SESSION_BYTES = 8 * 1024 * 1024  # Stop with LIMIT; preserve existing history.
SD_RETRY_MS = 30000
ENABLE_EVENT_AUDIO = True
AUDIO_PREFIX = "alarm"
AUDIO_MAX_MS = 30000  # One bounded recording per continuously active alarm.
AUDIO_RETRY_MS = 30000

# Boot the UI and sensors even without a usable cloud transport.
TRANSPORT_MODE = "mqtt"  # "mqtt" or "qth"
ENABLE_MQTT = False  # Resident local/BLE profile; cloud requires explicit configuration.
ENABLE_GNSS = True
ENABLE_LBS = False  # Enable after an independent indoor LBS test.
ENABLE_BLE = True
BLE_NAME = "UniKnect_V2"
BLE_NOTIFY_MS = 1000
POSE_SAMPLE_MS = 200  # Independent IMU path; environmental/event sampling stays 1 Hz.
BLE_POSE_MS = 200

# Quectel IoT Cloud (Qth). Copy to private config.py, fill these values, then
# set TRANSPORT_MODE="qth". Do not commit or share config.py.
ENABLE_QTH = False
QTH_PRODUCT_KEY = "CHANGE_ME"
QTH_PRODUCT_SECRET = "CHANGE_ME"
QTH_DEVICE_KEY = "CHANGE_ME"
QTH_SERVER = "mqtt://iot-south.quectelcn.com:1883"
QTH_VERSION = "V2.2.0-cloud-window"
