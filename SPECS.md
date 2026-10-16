# Robot Car Project Specification

## Overview

A Raspberry Pi 3B-based 4WD robot car with ROS 2 control, live camera streaming,
and a mobile-friendly web interface. Built on Ubuntu 24.04 + ROS 2 Jazzy.

---

## Hardware

### Platform
| Component | Details |
|---|---|
| Robot Kit | Keyestudio KS0223 4WD BLE Robot Car Kit |
| SBC | Raspberry Pi 3B (1 GB RAM, quad-core ARMv8 1.2GHz) |
| OS | Ubuntu 24.04 Server (64-bit) |
| ROS | ROS 2 Jazzy |

### Motor Driver
| Item | Value |
|---|---|
| Chip | TB6612A3 dual H-bridge (direct GPIO, no I2C) |
| Left motors M1+M2 | Direction: GPIO 22/23, 21/20 · PWM: GPIO 1, 0 (software) |
| Right motors M3+M4 | Direction: GPIO 24/25, 27/26 · PWM: GPIO 12, 13 (hardware) |
| Hardware PWM | GPIO 12 & 13 via `dtoverlay=pwm-2chan` |

### Camera
| Item | Value |
|---|---|
| Module | Raspberry Pi Camera Module v1.3 |
| Sensor | OmniVision OV5647 |
| Interface | CSI ribbon cable |
| Library | libcamera (Raspberry Pi fork v0.7.2+rpt20261009) |
| Python API | picamera2 |
| Encoder | MJPEGEncoder (V4L2 hardware) · bitrate 2 Mbps |
| Resolution | 640×480 @ 15 fps |

### Servos (Camera Pan-Tilt)
| Item | Value |
|---|---|
| Pan servo | GPIO 7 (BCM) |
| Tilt servo | GPIO 6 (BCM) |
| Pulse range | 500–2400 µs (calibrated) |
| Period | 20 ms (50 Hz) |
| Center | 90° = 1450 µs |
| Tilt limits | 45°–135° (mechanical safety range) |
| PWM method | pigpiod DMA burst (5 pulses per command, then stop — silent hold) |

### Other Peripherals (on board, not yet integrated)
| Component | GPIO |
|---|---|
| Ultrasonic sensor | Trig: GPIO 14 · Echo: GPIO 4 |
| Line tracking (3ch) | L: GPIO 19 · M: GPIO 18 · R: GPIO 17 |
| IR receiver | GPIO 15 |
| Passive buzzer | GPIO 16 |
| LED matrix (TM1604) | SCL: GPIO 8 · SDA: GPIO 9 |
| Ultrasonic servo | GPIO 5 |

---

## System Configuration

### `/boot/firmware/config.txt`
```ini
dtparam=i2c_arm=off
dtparam=i2c_vc=off
dtparam=spi=off
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
disable_fw_kms_setup=1
enable_uart=1
camera_auto_detect=0
dtoverlay=ov5647
gpu_mem=128
```

---

## Known Limitations & Notes

| Issue | Status | Notes |
|---|---|---|
| Servo jitter during movement | Accepted | lgpio software PWM on non-RT kernel. 5-pulse burst then silent — holds position cleanly |
| Servo pulse range | Calibrated | Hardware range 500–2400 µs (not standard 500–2500 µs) |
| picamera2 on Ubuntu | Workaround | pykms stub required; installed via `pip --no-deps` |
| `/dev/dma_heap/vidbuf_cached` warning | Harmless | Falls back to `/dev/dma_heap/system` automatically |
| camera_ros build | Abandoned | `libcamera::Span` deprecation + cv_bridge OpenCV deps — picamera2 subprocess used instead |
| RPi 3B RAM | 1 GB | colcon builds use `--parallel-workers 1`; libcamera built with `ninja -j1` |
| SPI disabled | Required | `dtparam=spi=off` — SPI claimed GPIO 7 (pan servo pin) |
