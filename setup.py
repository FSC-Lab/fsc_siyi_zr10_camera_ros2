from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'zr10_camera'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='your_name',
    maintainer_email='your@email.com',
    description='SIYI ZR10 camera ROS2 publisher',
    license='MIT',
    entry_points={
        'console_scripts': [
            'zr10_publisher     = zr10_camera.zr10_publisher:main',
            'zr10_gimbal        = zr10_camera.zr10_gimbal:main',
            'zr10_raw_publisher = zr10_camera.zr10_raw_publisher:main',
            'zr10_system_stats  = zr10_camera.zr10_system_stats:main',
        ],
    },
)
