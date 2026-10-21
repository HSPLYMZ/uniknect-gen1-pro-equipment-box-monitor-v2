"""Four-page ST7735 UI with debounced tap/hold page switching."""

import machine

# Two 16x16 monochrome glyphs for "作者". The LCD's ASCII font does not
# require a Chinese font table; these 16 rows add only a small constant.
_AUTHOR_ROWS = (
    0x10800200, 0x11000202, 0x21ff3fe4, 0x22400218,
    0x24400230, 0x6440ffff, 0x687e0380, 0xa0400e00,
    0xa0403ffc, 0x2040f004, 0x207f1ffc, 0x20401004,
    0x20401004, 0x20401ffc, 0x20401004, 0x00000000,
)

try:
    from logo_asset import Quectel_Icon_160x20
except (ImportError, OSError, ValueError, MemoryError):
    Quectel_Icon_160x20 = None


def _fmt(value, digits=1):
    if value is None:
        return "--"
    return ("%." + str(digits) + "f") % value


def _hms(seconds):
    seconds = max(0, int(seconds))
    return "%02d:%02d:%02d" % (seconds // 3600, (seconds // 60) % 60, seconds % 60)


class Button:
    """The A3/PC1 ladder; a tap or hold changes exactly one page."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.adc = machine.ADC(machine.Pin(cfg.BUTTON_PIN))
        # PC1 is pulled high when released. A held key at startup must not
        # become the release baseline and hide every subsequent press.
        self.idle = getattr(cfg, "BUTTON_IDLE_U16", 65535)
        self.debounce_ms = getattr(cfg, "BUTTON_DEBOUNCE_MS", 50)
        self.release_at = None
        self.down_at = None
        self.emitted = False

    def poll(self, now_ms, diff):
        value = self.adc.read_u16()
        down = abs(value - self.idle) >= self.cfg.BUTTON_DELTA
        if not down:
            if self.down_at is not None:
                if self.release_at is None:
                    self.release_at = now_ms
                if diff(now_ms, self.release_at) < self.debounce_ms:
                    return None
                action = "next" if (not self.emitted and
                         diff(self.release_at, self.down_at) >= self.debounce_ms) else None
                self.down_at = None
                self.release_at = None
                self.emitted = False
                return action
            self.down_at = None
            self.emitted = False
            self.idle = (self.idle * 15 + value) // 16
            return None
        self.release_at = None
        if self.down_at is None:
            self.down_at = now_ms
        if not self.emitted and diff(now_ms, self.down_at) >= self.cfg.BUTTON_LONG_MS:
            self.emitted = True
            return "next"
        return None


class Display:
    def __init__(self, cfg):
        from st7735 import LCD
        spi = machine.SPI(1, baudrate=10000000, polarity=0, phase=0)
        self.lcd = LCD(spi, dc_pin="F12", cs_pin="D14")
        self.lcd.set_rotation(1)
        self.light_background_only = getattr(cfg, "LIGHT_BACKGROUND_ONLY", True)
        self.page = getattr(cfg, "START_PAGE", 0) % 4
        self._rendered_page = None
        self._last_lines = None
        self._last_alarm = None
        self._clear_strip = None
        self._clear_color = None
        self._clear_width = 0
        try:
            self.button = Button(cfg)
            self.button_error = None
        except Exception as exc:
            self.button = None
            self.button_error = str(exc)

    def poll_button(self, now_ms, diff):
        if self.button is None:
            return None
        try:
            action = self.button.poll(now_ms, diff)
            self.button_error = None
        except Exception as exc:
            # A transient ADC error must not stop LCD refresh.
            self.button_error = str(exc)
            return None
        if action == "next":
            self.page = (self.page + 1) % 4
        return action

    def _line(self, y, text, color, bg, size=12, x=0):
        self.lcd.show_string(x, y, text, color, bg, size)

    def _fill(self, x, y, width, height, color):
        lcd = self.lcd
        if not (hasattr(lcd, "set_address_window") and hasattr(lcd, "write_data") and
                hasattr(lcd, "write_command")):
            if x == 0 and y == 0 and width == lcd.WIDTH and height == lcd.HEIGHT:
                lcd.fill_screen(color)
            else:
                lcd.fill_rectangle(x, y, width, height, color)
            return
        # Reuse a small RGB565 strip rather than allocating a second screen.
        # The board's write_data16 serializes colors as high byte, low byte.
        if (getattr(self, "_clear_strip", None) is None or
                self._clear_color != color or self._clear_width != width):
            self._clear_strip = bytes((color >> 8, color & 255)) * (width * 12)
            self._clear_color = color
            self._clear_width = width
        lcd.set_address_window(x, y, x + width - 1, y + height - 1)
        lcd.write_command(lcd.RAMWR)
        for row in range(0, height, 12):
            remaining = min(12, height - row)
            data = self._clear_strip if remaining == 12 else memoryview(self._clear_strip)[:width * remaining * 2]
            lcd.write_data(data)

    def _render_logo(self, bg):
        lcd = self.lcd
        self._fill(0, 0, lcd.WIDTH, lcd.HEIGHT, bg)
        if Quectel_Icon_160x20 is not None:
            lcd.show_image(0, (lcd.HEIGHT - 20) // 2, 160, 20, Quectel_Icon_160x20)
        else:
            self._line(58, "Quectel", lcd.WHITE, bg, 16, 48)

    def _render_author(self, bg):
        lcd = self.lcd
        self._fill(0, 0, lcd.WIDTH, lcd.HEIGHT, bg)
        # Draw the Chinese title directly, then use the verified 6x12 ASCII
        # font. Split at natural address boundaries instead of clipping.
        title_x = (lcd.WIDTH - 32) // 2
        if (hasattr(lcd, "set_address_window") and hasattr(lcd, "write_data") and
                hasattr(lcd, "write_command")):
            pixels = bytearray(bytes((bg >> 8, bg & 255)) * (32 * 16))
            for row, bits in enumerate(_AUTHOR_ROWS):
                for col in range(32):
                    if bits & (1 << (31 - col)):
                        offset = (row * 32 + col) * 2
                        pixels[offset] = lcd.WHITE >> 8
                        pixels[offset + 1] = lcd.WHITE & 255
            lcd.set_address_window(title_x, 12, title_x + 31, 27)
            lcd.write_command(lcd.RAMWR)
            lcd.write_data(pixels)
        else:
            for row, bits in enumerate(_AUTHOR_ROWS):
                for col in range(32):
                    if bits & (1 << (31 - col)):
                        lcd.draw_point(title_x + col, 12 + row, lcd.WHITE)
        lines = (
            (38, "huangshengping2025", lcd.WHITE),
            (54, "@163.com", lcd.WHITE),
            (82, "https://github.com/", lcd.CYAN),
            (98, "HSPLYMZ", lcd.CYAN),
        )
        for y, text, color in lines:
            self._line(y, text, color, bg, 12, (lcd.WIDTH - len(text) * 6) // 2)

    def _render_live(self, sample, location, active, uptime_s, recording, storage_state, full):
        lcd = self.lcd
        bg = lcd.RED if active else lcd.BLACK
        if full:
            self._fill(0, 0, lcd.WIDTH, lcd.HEIGHT, bg)
        fg = lcd.WHITE
        title = lcd.WHITE if active else lcd.CYAN
        accel = sample.get("accel_m_s2") or (None, None, None)
        pos = location.get("status", "--")
        if location.get("valid"):
            pos = "%s %.4f,%.4f" % (location.get("source", "POS"),
                                      location.get("latitude"), location.get("longitude"))
        lines = [
            "LIVE " + _hms(uptime_s),
            "T:%sC H:%s%%" % (_fmt(sample.get("temperature_c")), _fmt(sample.get("humidity_pct"))),
            "Light:%s" % (sample.get("light_adc_u16") if sample.get("light_adc_u16") is not None else "--"),
            "AX:%s AY:%s" % (_fmt(accel[0], 2), _fmt(accel[1], 2)),
            "AZ:%s" % _fmt(accel[2], 2),
            "POS:" + pos,
            "REC:%s SD:%s" % ("ON" if recording else "OFF", storage_state),
        ]
        lines = tuple(line[:26] for line in lines)
        previous = None if full else self._last_lines
        changed = False
        for i, line in enumerate(lines):
            old = None if previous is None else previous[i]
            if line == old:
                continue
            y = 2 + i * 18
            if old is not None:
                # The installed font writes a slightly larger area than its
                # six-pixel advance. Erase a complete 16-pixel row explicitly
                # so glyph edges and shorter values cannot leave ghosts.
                self._fill(0, y, lcd.WIDTH, 16, bg)
            self._line(y, line, title if i == 0 else fg, bg, 12)
            changed = True
        return lines, changed

    def _render_cloud(self, status, active, full):
        lcd = self.lcd
        bg = lcd.RED if active else lcd.BLACK
        if full:
            self._fill(0, 0, lcd.WIDTH, lcd.HEIGHT, bg)
        rsrp = status.get("rsrp_dbm")
        sinr = status.get("sinr_db")
        seconds = status.get("phase_s", 0)
        lines = ("NETWORK / CLOUD 4/4", "MQTT:" + status.get("network", "--"),
                 "LTE RSRP:%sdBm" % (rsrp if rsrp is not None else "--"),
                 "LTE SINR:%sdB" % _fmt(sinr),
                 "TX:%s %02d:%02d" % (status.get("phase", "--"), seconds // 60, seconds % 60),
                 "Calls:%s Left:%s" % (status.get("sent", 0), status.get("budget", 0)),
                 "Last:%s" % status.get("last_result", "--"))
        lines = tuple(line[:26] for line in lines)
        changed = False
        for i, line in enumerate(lines):
            old = None if full or self._last_lines is None else self._last_lines[i]
            if old == line:
                continue
            y = 2 + i * 18
            if old is not None:
                self._fill(0, y, lcd.WIDTH, 16, bg)
            self._line(y, line, lcd.CYAN if i == 0 and not active else lcd.WHITE, bg, 12)
            changed = True
        return lines, changed

    def render(self, sample, location, active, network, queue_len, dropped, uptime_s, mem_free,
               calibrated=True, recording=False, storage_state="--", cloud_status=None):
        active = ("light" in active) if getattr(self, "light_background_only", True) else bool(active)
        full = (getattr(self, "_rendered_page", None) != self.page or
                getattr(self, "_last_alarm", None) != active)
        if self.page not in (2, 3) and not full:
            return False
        lines = None
        try:
            if self.page == 0:
                self._render_logo(self.lcd.RED if active else self.lcd.BLACK)
            elif self.page == 1:
                self._render_author(self.lcd.RED if active else self.lcd.BLACK)
            elif self.page == 3:
                lines, changed = self._render_cloud(cloud_status or {"network": network}, active, full)
                if not changed:
                    return False
            else:
                lines, changed = self._render_live(sample, location, active, uptime_s,
                                                   recording, storage_state, full)
                if not changed:
                    return False
            self.lcd.flush()
        except Exception:
            # Part of the old image may have been overwritten. Invalidate
            # only after failure, and commit the new cache only after success.
            self._rendered_page = None
            raise
        self._rendered_page = self.page
        self._last_lines = lines
        self._last_alarm = bool(active)
        return True
