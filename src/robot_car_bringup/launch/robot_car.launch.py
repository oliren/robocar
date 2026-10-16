"""Bring up the whole robot car: motor driver + web server.

Launches both nodes together so a single systemd service starts the
entire robot. Each node respawns on exit so a crash of one does not
permanently take down the other.
"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    motor_driver = Node(
        package='robot_car_driver',
        executable='motor_driver',
        name='motor_driver_node',
        output='screen',
        respawn=True,
        respawn_delay=2.0,
    )

    web_server = Node(
        package='robot_car_web',
        executable='web_server',
        name='web_control_node',
        output='screen',
        respawn=True,
        respawn_delay=2.0,
    )

    return LaunchDescription([motor_driver, web_server])
