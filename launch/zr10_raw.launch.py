from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('fps',
            default_value='5.0',
            description='Raw image publishing rate (keep low)'),

        # Raw image publisher
        # Requires zr10_stream.launch.py to be running first
        Node(
            package='zr10_camera',
            executable='zr10_raw_publisher',
            name='zr10_raw',
            output='screen',
            parameters=[{
                'fps': LaunchConfiguration('fps'),
            }]
        ),
    ])