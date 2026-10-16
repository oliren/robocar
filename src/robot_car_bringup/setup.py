import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'robot_car_bringup'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # Install every launch file into share/<pkg>/launch
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Oliren',
    maintainer_email='nersis.oliren@gmail.com',
    description='Bringup / launch package for the Keyestudio 4WD robot car',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [],
    },
)
