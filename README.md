# SIYI ZR10 Camera ROS2

ROS2 Humble package for the SIYI ZR10 gimbal camera. Publishes video from the RTSP stream and provides gimbal control over UDP.

## Requirements

- ROS2 Humble
- OpenCV built with GStreamer support
- `python3-psutil` (for system stats node)
- Camera connected at `192.168.144.25` (dedicated network link)

## Build

```bash
cd ~/zr10_camera_control

source /opt/ros/humble/setup.bash
colcon build --packages-select zr10_camera
source install/setup.bash
```

<<<<<<< HEAD
## Launch

### Full stack (video + gimbal + system stats)

```bash
ros2 launch zr10_camera zr10_stream.launch.py
```

Optional overrides:

```bash
ros2 launch zr10_camera zr10_stream.launch.py \
  rtsp_url:=rtsp://192.168.144.25:8554/main.264 \
  fps:=15.0 \
  jpeg_quality:=80
```

### Raw image publisher (optional, second terminal)

Only needed when downstream nodes require `sensor_msgs/Image` (e.g. object detection). Requires the full stack to be running first.

```bash
ros2 launch zr10_camera zr10_raw.launch.py fps:=5.0
```

## Topics

| Topic | Type | Description |
|-------|------|-------------|
| `zr10/image_raw/compressed` | `sensor_msgs/CompressedImage` | JPEG video at configured fps |
| `zr10/image_raw` | `sensor_msgs/Image` | Raw BGR frames (raw publisher only) |
| `zr10/gimbal/attitude` | `geometry_msgs/Vector3` | Yaw / pitch / roll in degrees |
| `zr10/gimbal/zoom_level` | `std_msgs/Float32` | Current zoom level |
| `zr10/stats/diagnostics` | `diagnostic_msgs/DiagnosticArray` | CPU / memory / temp / network |

### Gimbal control topics

| Topic | Type | Description |
|-------|------|-------------|
| `zr10/gimbal/center` | `std_msgs/Bool` | Publish `True` to center |
| `zr10/gimbal/angle` | `geometry_msgs/Vector3` | x=yaw (±135°), y=pitch (−90…+25°) |
| `zr10/gimbal/rotate` | `geometry_msgs/Vector3` | x=yaw speed, y=pitch speed (−100…100) |
| `zr10/gimbal/zoom` | `std_msgs/Float32` | Absolute zoom 1.0–30.0× |
| `zr10/gimbal/zoom_step` | `std_msgs/Int8` | 1=zoom in, −1=zoom out, 0=stop |

## GStreamer note

The default pipeline in `zr10_publisher.py` uses `nvv4l2decoder` / `nvvidconv`, which are Jetson-specific plugins. On x86 Linux replace with `avdec_h265` (software) or `nvh265dec` (NVIDIA NVDEC).
