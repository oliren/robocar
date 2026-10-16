#!/usr/bin/env python3
"""
Camera pan-tilt servo controller — lgpio bit-bang, pulse-burst strategy.

Sends N pulses to reach target angle, then stops.
Servo holds position mechanically — silent between commands, no jitter.

GPIO 7 = pan  (base / horizontal)
GPIO 6 = tilt (camera / vertical)
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

# ── Pin assignment (BCM) ──────────────────────────────────────────────────────
SERVO_PAN_GPIO  = 7
SERVO_TILT_GPIO = 6

# ── Calibrated pulse range (µs) ───────────────────────────────────────────────
PAN_PULSE_MIN   = 500
PAN_PULSE_MAX   = 2400
TILT_PULSE_MIN  = 500
TILT_PULSE_MAX  = 2400

# ── Angle limits ──────────────────────────────────────────────────────────────
PAN_MIN,  PAN_MAX  =   0, 180
TILT_MIN, TILT_MAX =  45, 135

# ── Pulses sent per move command ──────────────────────────────────────────────
SETTLE_PULSES = 5

try:
    import lgpio
    _LGPIO_AVAILABLE = True
except ImportError:
    _LGPIO_AVAILABLE = False
    log.warning('lgpio not available — servo disabled')


def _angle_to_pw(angle: float, pw_min: int, pw_max: int) -> float:
    angle = max(0.0, min(180.0, float(angle)))
    return pw_min + (angle / 180.0) * (pw_max - pw_min)


def _send_pulses(handle, gpio: int, pw_us: float, count: int) -> None:
    hi = pw_us / 1_000_000.0
    lo = 0.020 - hi
    for _ in range(count):
        lgpio.gpio_write(handle, gpio, 1)
        time.sleep(hi)
        lgpio.gpio_write(handle, gpio, 0)
        time.sleep(lo)
    lgpio.gpio_write(handle, gpio, 0)   # stop — servo holds silently


class ServoController:
    """
    Thread-safe servo controller.

    A background worker thread serialises pulse bursts so the
    async event loop is never blocked.
    """

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._handle  = None
        self._pan     = 90.0
        self._tilt    = 90.0
        self._pending: tuple[float, float] | None = None
        self._event   = threading.Event()
        self._stop    = threading.Event()

        if not _LGPIO_AVAILABLE:
            return

        try:
            h = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(h, SERVO_PAN_GPIO,  0)
            lgpio.gpio_claim_output(h, SERVO_TILT_GPIO, 0)
            self._handle = h

            self._worker = threading.Thread(
                target=self._run,
                daemon=True,
                name='servo-worker',
            )
            self._worker.start()

            self.center()

            log.info(
                'ServoController ready — pan=GPIO%d tilt=GPIO%d',
                SERVO_PAN_GPIO, SERVO_TILT_GPIO,
            )

        except Exception as exc:
            log.warning('Servo init failed: %s', exc)
            self._handle = None

    # ── Worker thread ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            triggered = self._event.wait(timeout=0.5)
            if not triggered:
                continue
            self._event.clear()

            with self._lock:
                cmd = self._pending
                self._pending = None

            if cmd is None or self._handle is None:
                continue

            pan_angle, tilt_angle = cmd
            pan_pw  = _angle_to_pw(pan_angle,  PAN_PULSE_MIN,  PAN_PULSE_MAX)
            tilt_pw = _angle_to_pw(tilt_angle, TILT_PULSE_MIN, TILT_PULSE_MAX)

            for _ in range(SETTLE_PULSES):
                if self._stop.is_set() or self._event.is_set():
                    break
                # Pan pulse
                lgpio.gpio_write(self._handle, SERVO_PAN_GPIO, 1)
                time.sleep(pan_pw / 1_000_000.0)
                lgpio.gpio_write(self._handle, SERVO_PAN_GPIO, 0)
                # Tilt pulse
                lgpio.gpio_write(self._handle, SERVO_TILT_GPIO, 1)
                time.sleep(tilt_pw / 1_000_000.0)
                lgpio.gpio_write(self._handle, SERVO_TILT_GPIO, 0)
                # Remainder of 20ms period
                elapsed = (pan_pw + tilt_pw) / 1_000_000.0
                remainder = 0.020 - elapsed
                if remainder > 0:
                    time.sleep(remainder)

            if self._handle is not None:
                lgpio.gpio_write(self._handle, SERVO_PAN_GPIO,  0)
                lgpio.gpio_write(self._handle, SERVO_TILT_GPIO, 0)

    # ── Public API ────────────────────────────────────────────────────────────

    def set(self, pan: float, tilt: float) -> None:
        pan  = max(PAN_MIN,  min(PAN_MAX,  float(pan)))
        tilt = max(TILT_MIN, min(TILT_MAX, float(tilt)))
        with self._lock:
            self._pan  = pan
            self._tilt = tilt
            self._pending = (pan, tilt)
        self._event.set()

    def set_pan(self, angle: float) -> None:
        with self._lock:
            tilt = self._tilt
        self.set(angle, tilt)

    def set_tilt(self, angle: float) -> None:
        with self._lock:
            pan = self._pan
        self.set(pan, angle)

    def center(self) -> None:
        self.set(90.0, 90.0)

    def stop(self) -> None:
        self._stop.set()
        self._event.set()
        if hasattr(self, '_worker'):
            self._worker.join(timeout=2.0)
        if self._handle is not None:
            try:
                lgpio.gpio_write(self._handle, SERVO_PAN_GPIO,  0)
                lgpio.gpio_write(self._handle, SERVO_TILT_GPIO, 0)
                lgpio.gpiochip_close(self._handle)
            except Exception as exc:
                log.debug('Servo stop: %s', exc)
            self._handle = None
        log.info('ServoController stopped')

    @property
    def active(self) -> bool:
        return self._handle is not None

    @property
    def status(self) -> dict:
        return {
            'active': self.active,
            'pan':    round(self._pan,  1),
            'tilt':   round(self._tilt, 1),
        }
