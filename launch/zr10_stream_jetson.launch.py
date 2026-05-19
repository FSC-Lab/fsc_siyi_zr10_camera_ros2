from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('rtsp_url',
            default_value='rtsp://192.168.144.25:8554/main.264',
            description='RTSP stream URL'),
        DeclareLaunchArgument('fps',
            default_value='15.0',
            description='Publishing frame rate'),
        DeclareLaunchArgument('jpeg_quality',
            default_value='80',
            description='JPEG compression quality 1-100'),

        # ── Jetson-specific: nvv4l2decoder + nvvidconv ────────────────────────
        Node(
            package='zr10_camera',
            executable='zr10_publisher',
            name='zr10_camera',
            output='screen',
            parameters=[{
                'rtsp_url':     LaunchConfiguration('rtsp_url'),
                'fps':          LaunchConfiguration('fps'),
                'jpeg_quality': LaunchConfiguration('jpeg_quality'),
                'decoder':      'jetson',       # nvv4l2decoder + nvvidconv (JetPack)
            }]
        ),

        Node(
            package='zr10_camera',
            executable='zr10_gimbal',
            name='zr10_gimbal',
            output='screen',
            parameters=[{
                'host':          '192.168.144.25',
                'port':          37260,
                'attitude_rate': 10.0,
            }]
        ),

        # ── Jetson-specific: wlP1p1s0 WiFi, eno1 Ethernet ───────────────────
        Node(
            package='zr10_camera',
            executable='zr10_system_stats',
            name='zr10_system_stats',
            output='screen',
            parameters=[{
                'rate':       1.0,
                'wifi_iface': 'wlP1p1s0',      # Jetson Orin default
                'eth_iface':  'eno1',           # Jetson Orin default
            }]
        ),
    ])
