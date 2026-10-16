#!/usr/bin/env python3
"""
Keyestudio 4WD Robot Car - Motor Driver Node
ROS 2 Jazzy | Ubuntu 24.04 | Raspberry Pi 3B

Subscribes: /cmd_vel  (geometry_msgs/Twist)
Publishes:  /motor_speeds (std_msgs/String)

Features:
  - Velocity ramping (acceleration / deceleration control)
  - Safety stop on cmd_vel timeout
  - Tunable parameters at launch time
"""

import lgpio
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import String


# ── Verified Pin Mapping ───────────────────────────────────────────
MOTORS = {
    'M1_LEFT':  {'in1': 22, 'in2': 23, 'pwm': 1 },
    'M2_LEFT':  {'in1': 21, 'in2': 20, 'pwm': 0 },
    'M3_RIGHT': {'in1': 24, 'in2': 25, 'pwm': 12},
    'M4_RIGHT': {'in1': 27, 'in2': 26, 'pwm': 13},
}

LEFT_MOTORS  = ['M1_LEFT',  'M2_LEFT' ]
RIGHT_MOTORS = ['M3_RIGHT', 'M4_RIGHT']
ALL_MOTORS   = LEFT_MOTORS + RIGHT_MOTORS

PWM_FREQ = 100  # Hz


class MotorDriverNode(Node):

    def __init__(self):
        super().__init__('motor_driver_node')

        # ── Parameters ─────────────────────────────────────────────
        self.declare_parameter('max_linear_vel',  0.2)   # m/s
        self.declare_parameter('max_angular_vel', 1.0)   # rad/s
        self.declare_parameter('min_duty_cycle',  35.0)  # %
        self.declare_parameter('stop_timeout',    0.5)   # seconds

        # Acceleration parameters
        # 1.0 = goes from 0 to full speed in 1 second
        # 2.0 = goes from 0 to full speed in 0.5 seconds (faster)
        # 0.5 = goes from 0 to full speed in 2 seconds (slower)
        self.declare_parameter('acceleration',    1.0)   # units/s
        self.declare_parameter('deceleration',    2.0)   # units/s (usually faster than accel)
        self.declare_parameter('control_rate',   50.0)   # Hz

        self._max_lin   = self.get_parameter('max_linear_vel').value
        self._max_ang   = self.get_parameter('max_angular_vel').value
        self._min_duty  = self.get_parameter('min_duty_cycle').value
        self._timeout   = self.get_parameter('stop_timeout').value
        self._accel     = self.get_parameter('acceleration').value
        self._decel     = self.get_parameter('deceleration').value
        ctrl_rate       = self.get_parameter('control_rate').value
        self._dt        = 1.0 / ctrl_rate   # seconds per tick

        # ── Velocity State ─────────────────────────────────────────
        # Target: set by cmd_vel callback
        # Current: ramped toward target by control loop
        self._target_left   = 0.0
        self._target_right  = 0.0
        self._current_left  = 0.0
        self._current_right = 0.0

        # ── GPIO Setup ─────────────────────────────────────────────
        self._h = lgpio.gpiochip_open(0)
        if self._h < 0:
            self.get_logger().fatal(f'Failed to open gpiochip0: {self._h}')
            raise RuntimeError('GPIO init failed')

        for name, pins in MOTORS.items():
            e1 = lgpio.gpio_claim_output(self._h, pins['in1'], 0)
            e2 = lgpio.gpio_claim_output(self._h, pins['in2'], 0)
            e3 = lgpio.gpio_claim_output(self._h, pins['pwm'], 0)
            if e1 < 0 or e2 < 0 or e3 < 0:
                self.get_logger().fatal(
                    f'Failed to claim pins for {name}: '
                    f'IN1={e1} IN2={e2} PWM={e3}')
                raise RuntimeError(f'Pin claim failed for {name}')

        self.get_logger().info('GPIO initialized successfully')

        # ── ROS 2 Subscriber ───────────────────────────────────────
        self._cmd_vel_sub = self.create_subscription(
            Twist,
            '/cmd_vel',
            self._cmd_vel_callback,
            10)

        # ── Debug Publisher ────────────────────────────────────────
        self._debug_pub = self.create_publisher(String, '/motor_speeds', 10)

        # ── Control Loop Timer (50Hz) ──────────────────────────────
        # Handles both ramping AND driving motors
        self._last_cmd_time  = self.get_clock().now()
        self._control_timer  = self.create_timer(self._dt, self._control_loop)

        self.get_logger().info(
            f'\n'
            f'  ✅ Motor Driver Node started!\n'
            f'  Listening on  : /cmd_vel\n'
            f'  Debug topic   : /motor_speeds\n'
            f'  Max linear    : {self._max_lin} m/s\n'
            f'  Max angular   : {self._max_ang} rad/s\n'
            f'  Min duty      : {self._min_duty}%\n'
            f'  Acceleration  : {self._accel} (0→full in {1/self._accel:.1f}s)\n'
            f'  Deceleration  : {self._decel} (full→0 in {1/self._decel:.1f}s)\n'
            f'  Control rate  : {ctrl_rate} Hz\n'
            f'  Stop timeout  : {self._timeout}s'
        )

    # ── cmd_vel Callback ───────────────────────────────────────────
    # Only sets TARGET speeds — does NOT drive motors directly
    def _cmd_vel_callback(self, msg: Twist):
        self._last_cmd_time = self.get_clock().now()

        linear  = msg.linear.x
        angular = msg.angular.z

        # Normalize to [-1, 1]
        lin = max(-1.0, min(1.0, linear  / self._max_lin))
        ang = max(-1.0, min(1.0, angular / self._max_ang))

        # Differential drive mixing
        left  = lin - ang
        right = lin + ang

        # Re-normalize
        scale = max(abs(left), abs(right), 1.0)
        self._target_left  = left  / scale
        self._target_right = right / scale

    # ── Control Loop (50Hz) ────────────────────────────────────────
    # This is the ONLY place motors are driven
    def _control_loop(self):

        # Safety stop: no cmd_vel received recently?
        elapsed = (
            self.get_clock().now() - self._last_cmd_time
        ).nanoseconds / 1e9

        if elapsed > self._timeout:
            self._target_left  = 0.0
            self._target_right = 0.0

        # ── Ramp current speeds toward targets ─────────────────────
        self._current_left  = self._ramp(
            self._current_left,  self._target_left)
        self._current_right = self._ramp(
            self._current_right, self._target_right)

        # ── Drive motors with CURRENT (ramped) speeds ──────────────
        for name in LEFT_MOTORS:
            self._drive_motor(name, self._current_left)
        for name in RIGHT_MOTORS:
            self._drive_motor(name, self._current_right)

        # ── Publish debug info ─────────────────────────────────────
        msg = String()
        msg.data = (
            f'target=({self._target_left:.2f},{self._target_right:.2f}) '
            f'current=({self._current_left:.2f},{self._current_right:.2f})'
        )
        self._debug_pub.publish(msg)

    # ── Velocity Ramp Helper ───────────────────────────────────────
    def _ramp(self, current: float, target: float) -> float:
        """
        Step current value toward target value.
        Uses acceleration when speeding up (|current| increasing).
        Uses deceleration when slowing down (|current| decreasing).

        Example with accel=1.0, decel=2.0, dt=0.02:
          accel step = 1.0 * 0.02 = 0.02 per tick
          decel step = 2.0 * 0.02 = 0.04 per tick
        """
        diff = target - current

        # Are we speeding up or slowing down?
        # Slowing down = moving toward zero OR reversing direction
        speeding_up = (abs(target) > abs(current)) and \
                      (target * current >= 0)   # same sign

        max_step = (self._accel if speeding_up else self._decel) * self._dt

        # Clamp the step
        if abs(diff) <= max_step:
            return target                              # close enough → snap
        return current + max_step * (1.0 if diff > 0 else -1.0)

    # ── Motor Drive ────────────────────────────────────────────────
    def _drive_motor(self, name: str, speed: float):
        pins = MOTORS[name]
        duty = abs(speed) * 100.0

        if duty < 1.0:
            lgpio.gpio_write(self._h, pins['in1'], 0)
            lgpio.gpio_write(self._h, pins['in2'], 0)
            lgpio.tx_pwm(self._h, pins['pwm'], PWM_FREQ, 0)
        else:
            duty = self._min_duty + duty * (100.0 - self._min_duty) / 100.0
            duty = min(duty, 100.0)
            if speed > 0:
                lgpio.gpio_write(self._h, pins['in1'], 1)
                lgpio.gpio_write(self._h, pins['in2'], 0)
            else:
                lgpio.gpio_write(self._h, pins['in1'], 0)
                lgpio.gpio_write(self._h, pins['in2'], 1)
            lgpio.tx_pwm(self._h, pins['pwm'], PWM_FREQ, duty)

    def _stop_all(self):
        for name in ALL_MOTORS:
            self._drive_motor(name, 0.0)

    # ── Cleanup ────────────────────────────────────────────────────
    def destroy_node(self):
       # Use print() not get_logger() — context may already be invalid
        print('[motor_driver_node] Shutting down motor driver...')

        # Stop all motors
        self._stop_all()

        # Explicitly zero out all PWM signals
        for name in ALL_MOTORS:
            pins = MOTORS[name]
            lgpio.gpio_write(self._h, pins['in1'], 0)
            lgpio.gpio_write(self._h, pins['in2'], 0)
            lgpio.tx_pwm(self._h, pins['pwm'], PWM_FREQ, 0)

        lgpio.gpiochip_close(self._h)
        print('[motor_driver_node] GPIO cleaned up.')
        super().destroy_node() 

# ── Entry Point ────────────────────────────────────────────────────
def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = MotorDriverNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        print(f'Fatal error: {e}')
    finally:
        if node:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
