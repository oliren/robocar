#!/usr/bin/env python3
"""
ROS 2 node — publishes geometry_msgs/Twist on /cmd_vel.
"""
from __future__ import annotations

import logging

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

log = logging.getLogger(__name__)


class WebControlNode(Node):

    def __init__(self) -> None:
        super().__init__('web_control_node')
        self._pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.get_logger().info('WebControlNode ready → /cmd_vel')

    def send_cmd_vel(self, linear: float, angular: float) -> None:
        # Guard: rclpy context may already be shut down (e.g. Ctrl+C)
        if not rclpy.ok():
            return
        msg           = Twist()
        msg.linear.x  = float(linear)
        msg.angular.z = float(angular)
        try:
            self._pub.publish(msg)
        except Exception as exc:
            log.debug('publish skipped during shutdown: %s', exc)

    def stop(self) -> None:
        """Publish zero velocity — safe to call during shutdown."""
        self.send_cmd_vel(0.0, 0.0)
