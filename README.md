# Robot Car Workspace

A ROS 2 workspace for driving a **Keyestudio 4WD robot car** on a Raspberry Pi, with a
browser-based control interface that streams the camera, drives the motors, and aims a
pan-tilt camera mount.

- **Target platform:** Raspberry Pi 3B, Ubuntu 24.04, ROS 2 Jazzy
- **GPIO backend:** [`lgpio`](https://abyz.me.uk/lg/py_lgpio.html)
- **Camera:** Raspberry Pi camera via [`picamera2`](https://github.com/raspberrypi/picamera2)
- **Web stack:** FastAPI + Uvicorn, served over WebSocket + MJPEG

## Packages

| Package | Description |
| --- | --- |
| [`robot_car_driver`](src/robot_car_driver) | Motor driver node. Subscribes to `/cmd_vel` and drives the four motors over GPIO with velocity ramping and a safety stop. |
| [`robot_car_web`](src/robot_car_web) | FastAPI web server node. Serves a control UI, publishes `/cmd_vel`, streams the camera (MJPEG), and controls the pan-tilt servos. |

## Architecture

```
Browser  ──WebSocket──▶  web_server (robot_car_web)
   ▲                        │  publishes
   │  MJPEG /video_feed     ▼
   └────────────────   /cmd_vel  (geometry_msgs/Twist)
                            │
                            ▼
                     motor_driver (robot_car_driver)
                            │  GPIO (lgpio)
                            ▼
                    4 DC motors + pan/tilt servos
```

- The browser talks to the **web server** over a WebSocket (`/ws`) for drive and servo
  commands, and receives the camera as an MJPEG stream at `/video_feed`.
- The web server runs a ROS 2 node (`web_control_node`) that publishes
  `geometry_msgs/Twist` on `/cmd_vel`.
- The **motor driver** node (`motor_driver_node`) subscribes to `/cmd_vel`, mixes it into
  left/right wheel speeds, ramps them smoothly, and drives the motor pins over GPIO. It
  also publishes a debug string on `/motor_speeds`.
- Servos (pan/tilt) and the camera are driven directly by the web server process on the
  Pi; they are not ROS topics.

## Hardware

### Motor GPIO pins (BCM)

Defined in `robot_car_driver/robot_car_driver/motor_driver_node.py`.

| Motor | IN1 | IN2 | PWM |
| --- | --- | --- | --- |
| M1 (left) | 22 | 23 | 1 |
| M2 (left) | 21 | 20 | 0 |
| M3 (right) | 24 | 25 | 12 |
| M4 (right) | 27 | 26 | 13 |

PWM frequency: 100 Hz.

### Servo GPIO pins (BCM)

Defined in `robot_car_web/robot_car_web/servo.py`.

| Servo | GPIO | Range |
| --- | --- | --- |
| Pan (horizontal) | 7 | 0–180° |
| Tilt (vertical) | 6 | 45–135° |

## Build

From the workspace root (`robot_ws`):

```bash
# Install ROS 2 Jazzy and source it first, then:
sudo apt install python3-lgpio
colcon build
source install/setup.bash
```

The camera stream additionally requires `picamera2`, which ships with Raspberry Pi OS /
is installed via `apt` on the Pi. Both the camera and the servos degrade gracefully: if
`picamera2` or `lgpio` is unavailable, those features are disabled and the rest of the
system keeps running.

## Run

Run each node in its own sourced terminal.

```bash
# Terminal 1 — motor driver
ros2 run robot_car_driver motor_driver

# Terminal 2 — web server
ros2 run robot_car_web web_server
```

Then open the control page in a browser:

```
http://<raspberry-pi-ip>:8080
```

The web server prints its detected address and port on startup.

## Motor driver parameters

The motor driver node exposes tunable parameters (set them at launch with `-p`):

| Parameter | Default | Description |
| --- | --- | --- |
| `max_linear_vel` | 0.2 | Max linear velocity (m/s) used to normalize `/cmd_vel`. |
| `max_angular_vel` | 1.0 | Max angular velocity (rad/s) used to normalize `/cmd_vel`. |
| `min_duty_cycle` | 35.0 | Minimum PWM duty cycle (%) the motors need to turn. |
| `stop_timeout` | 0.5 | Safety stop if no `/cmd_vel` is received within this many seconds. |
| `acceleration` | 1.0 | Ramp-up rate (0→full in `1/acceleration` seconds). |
| `deceleration` | 2.0 | Ramp-down rate (full→0 in `1/deceleration` seconds). |
| `control_rate` | 50.0 | Control-loop / ramping frequency (Hz). |

Example:

```bash
ros2 run robot_car_driver motor_driver --ros-args -p max_linear_vel:=0.3 -p acceleration:=1.5
```

## Web server endpoints

Served by `robot_car_web/robot_car_web/web_server_node.py` on port `8080`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | HTML control page. |
| `GET` | `/video_feed` | MJPEG camera stream (`multipart/x-mixed-replace`). |
| `GET` | `/camera/status` | JSON camera status. |
| `GET` | `/servo/status` | JSON servo status. |
| `WS` | `/ws` | Drive and servo commands. |

### WebSocket message types

Send JSON objects on `/ws`:

```jsonc
{ "type": "cmd_vel", "linear": 0.5, "angular": 0.0 }  // drive
{ "type": "stop" }                                     // stop motors
{ "type": "servo", "pan": 90, "tilt": 90 }             // aim camera
{ "type": "servo_center" }                             // recenter camera
```

## ROS topics

| Topic | Type | Direction | Node |
| --- | --- | --- | --- |
| `/cmd_vel` | `geometry_msgs/Twist` | web → driver | published by `web_control_node`, consumed by `motor_driver_node` |
| `/motor_speeds` | `std_msgs/String` | debug out | published by `motor_driver_node` |

## License

Apache-2.0. See the `LICENSE` file in each package.
