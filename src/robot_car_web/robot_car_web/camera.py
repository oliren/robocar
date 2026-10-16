#!/usr/bin/env python3
"""
Camera stream — wraps picamera2 MJPEGEncoder.
Gracefully degrades when no camera hardware / picamera2 is present.
"""
from __future__ import annotations

import io
import logging
import threading
from typing import Optional

log = logging.getLogger(__name__)

try:
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput
    _PICAM2_AVAILABLE = True
except ImportError:
    _PICAM2_AVAILABLE = False
    log.warning('picamera2 not installed — camera stream disabled')


class StreamOutput(io.BufferedIOBase):
    def __init__(self) -> None:
        self._frame:     Optional[bytes] = None
        self._cond       = threading.Condition()
        self.frame_count = 0

    def write(self, buf: bytes) -> int:
        with self._cond:
            self._frame      = bytes(buf)
            self.frame_count += 1
            self._cond.notify_all()
        return len(buf)

    def wait_for_frame(self, timeout: float = 1.0) -> Optional[bytes]:
        with self._cond:
            notified = self._cond.wait(timeout)
            return self._frame if notified else None

    @property
    def latest_frame(self) -> Optional[bytes]:
        return self._frame


class CameraStream:
    def __init__(
        self,
        width:   int = 640,
        height:  int = 480,
        fps:     int = 15,
        bitrate: int = 2_000_000,   # bits/sec — V4L2 MJPEGEncoder parameter
    ) -> None:
        self.width   = width
        self.height  = height
        self.fps     = fps
        self.bitrate = bitrate
        self.output  = StreamOutput()
        self.active  = False
        self._cam: Optional['Picamera2'] = None
        self._start()

    def _start(self) -> None:
        if not _PICAM2_AVAILABLE:
            log.warning('picamera2 unavailable — skipping camera init')
            return
        try:
            cameras = Picamera2.global_camera_info()
            if not cameras:
                log.warning('No cameras detected by libcamera')
                return
            log.info('Detected cameras: %s', [c['Model'] for c in cameras])

            cam = Picamera2()
            cfg = cam.create_video_configuration(
                main={'size': (self.width, self.height), 'format': 'YUV420'},
                raw=None,
                controls={
                    'FrameDurationLimits': (
                        1_000_000 // self.fps,
                        1_000_000 // self.fps,
                    ),
                },
            )
            cam.configure(cfg) 
            # MJPEGEncoder takes an integer quality, NOT a Quality enum
            cam.start_recording(MJPEGEncoder(self.bitrate), FileOutput(self.output))

            self._cam   = cam
            self.active = True
            log.info(
                'Camera started: %dx%d @ %d fps bitrate=%d',
                self.width, self.height, self.fps, self.bitrate,
            )

        except Exception as exc:
            log.warning('Camera init failed: %s', exc)

    def stop(self) -> None:
        if self._cam is not None:
            try:
                self._cam.stop_recording()
                self._cam.close()
            except Exception:
                pass
            self._cam   = None
            self.active = False
            log.info('Camera stopped')

    @property
    def status(self) -> dict:
        return {
            'active': self.active,
            'frames': self.output.frame_count,
            'width':  self.width,
            'height': self.height,
            'fps':    self.fps,
        }
