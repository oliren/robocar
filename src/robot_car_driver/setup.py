from setuptools import find_packages, setup

package_name = 'robot_car_driver'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Oliren',
    maintainer_email='nersis.oliren@gmail.com',
    description='Keyestudio 4WD motor driver for ROS 2 Jazzy',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'motor_driver = robot_car_driver.motor_driver_node:main',
        ],
    },
)
