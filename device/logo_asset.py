"""Load the official RGB565 Logo without compiling thousands of integers."""

with open("/flash/cabinet_monitor_v2/logo_160x20.bin", "rb") as source:
    Quectel_Icon_160x20 = bytearray(source.read())
if len(Quectel_Icon_160x20) != 160 * 20 * 2:
    raise ValueError("Invalid Logo resource size")
