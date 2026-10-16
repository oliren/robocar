#!/usr/bin/env python3
"""
Camera pan-tilt servo controller — pigpiod burst-then-stop.

Strategy: send N pulses via pigpiod, then stop (pulsewidth=0).
Servo holds position mechanically — silent, no jitter.

GPIO 7 = pan  (base / horizontal)
GPIO 6 = tilt (camera / vertical)
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

SERVO_PAN_GPIO  = 7
SERVO_TILT_GPIO = 6

PAN_PULSE_MIN   = 500
PAN_PULSE_MAX   = 2400
TILT_PULSE_MIN  = 500
TILT_PULSE_MAX  = 2400

PAN_MIN,  PAN_MAX  =   0, 180
TILT_MIN, TILT_MAX =  45, 135

SETTLE_PULSES = 5      # pulses per move — enough to reach position, then silent

try:
    import pigpio
    _PIGPIO_AVAILABLE = True
except ImportError:
    _PIGPIO_AVAILABLE = False
    log.warning('pigpio not installed — servo disabled')


def _angle_to_pw(angle: float, pw_min: int, pw_max: int) -> int:
    angle = max(0.0, min(180.0, float(angle)))
    return int(pw_min + (angle / 180.0) * (pw_max - pw_min))


class ServoController:
    """
    Thread-safe servo controller backed by pigpiod.

    Uses burst-then-stop: sends SETTLE_PULSES pulses to reach
    target angle, then sets pulsewidth=0. Servo holds silently.
    """

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._pi      = None
        self._pan     = 90.0
        self._tilt    = 90.0
        self._pending: tuple[float, float] | None = None
        self._event   = threading.Event()
        self._stop    = threading.Event()

        if not _PIGPIO_AVAILABLE:
            return

        try:
            pi = pigpio.pi()
            if not pi.connected:
                log.warning('pigpiod not running — start with: sudo systemctl start pigpiod')
                return

            self._pi = pi

            self._worker = threading.Thread(
                target=self._run,
                daemon=True,
                name='servo-worker',
            )
            self._worker.start()

            self.center()

            log.info(
                'ServoController ready (pigpiod) — pan=GPIO%d tilt=GPIO%d',
                SERVO_PAN_GPIO, SERVO_TILT_GPIO,
            )

        except Exception as exc:
            log.warning('Servo init failed: %s', exc)
            self._pi = None

    # ── Worker ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._event.wait(timeout=0.5):
                continue
            self._event.clear()

            with self._lock:
                cmd = self._pending
                self._pending = None

            if cmd is None or self._pi is None:
                continue

            pan_angle, tilt_angle = cmd
            pan_pw  = _angle_to_pw(pan_angle,  PAN_PULSE_MIN,  PAN_PULSE_MAX)
            tilt_pw = _angle_to_pw(tilt_angle, TILT_PULSE_MIN, TILT_PULSE_MAX)

            # Burst: send pulses to reach position
            for _ in range(SETTLE_PULSES):
                if self._stop.is_set() or self._event.is_set():
                    break
                self._pi.set_servo_pulsewidth(SERVO_PAN_GPIO,  pan_pw)
                self._pi.set_servo_pulsewidth(SERVO_TILT_GPIO, tilt_pw)
                time.sleep(0.02)   # one 50Hz period

            # Stop — servo holds silently
            if self._pi is not None:
                self._pi.set_servo_pulsewidth(SERVO_PAN_GPIO,  0)
                self._pi.set_servo_pulsewidth(SERVO_TILT_GPIO, 0)

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
        if self._pi is not None:
            try:
                self._pi.set_servo_pulsewidth(SERVO_PAN_GPIO,  0)
                self._pi.set_servo_pulsewidth(SERVO_TILT_GPIO, 0)
                self._pi.stop()
            except Exception as exc:
                log.debug('Servo stop: %s', exc)
            self._pi = None
        log.info('ServoController stopped')

    @property
    def active(self) -> bool:
        return self._pi is not None

    @property
    def status(self) -> dict:
        return {
            'active': self.active,
            'pan':    round(self._pan,  1),
            'tilt':   round(self._tilt, 1),
        }