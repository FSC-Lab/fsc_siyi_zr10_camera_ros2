# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

```bash
# Source ROS2 first (required for every terminal session)
source /opt/ros/humble/setup.bash

# Build from the workspace root
cd /home/ubuntu/zr10_camera_control
colcon build --packages-select zr10_camera

# Source the overlay after building
source install/setup.bash

# Launch the full stack (RTSP stream + gimbal control + system stats)
ros2 launch zr10_camera zr10_stream.launch.py

# Optional: also publish raw Image topic (low-rate, CPU-heavy — run in a second terminal)
ros2 launch zr10_camera zr10_raw.launch.py

# Run individual nodes directly
ros2 run zr10_camera zr10_publisher
ros2 run zr10_camera zr10_gimbal
ros2 run zr10_camera zr10_raw_publisher
ros2 run zr10_camera zr10_system_stats
```

## Architecture

This is a ROS2 Humble Python package (`zr10_camera`) with four nodes targeting a **SIYI ZR10 gimbal camera** connected over a dedicated network link at `192.168.144.25`.

### Node overview

| Node | Executable | Role |
|------|-----------|------|
| `zr10_publisher` | `zr10_camera/zr10_publisher.py` | RTSP → CompressedImage publisher |
| `zr10_gimbal` | `zr10_camera/zr10_gimbal.py` | UDP gimbal control + attitude feedback |
| `zr10_raw_publisher` | `zr10_camera/zr10_raw_publisher.py` | CompressedImage → raw Image converter |
| `zr10_system_stats` | `zr10_camera/zr10_system_stats.py` | Jetson CPU/mem/temp/network diagnostics |

### Video pipeline (`zr10_publisher`)

Opens the RTSP H.265 stream directly through OpenCV's GStreamer backend using a hand-crafted pipeline string. The pipeline reads BGRx frames (skipping `videoconvert` for speed), then drops the X channel via numpy slice before JPEG-encoding and publishing as `zr10/image_raw/compressed`.

**Critical platform issue:** The current pipeline uses `nvv4l2decoder` and `nvvidconv`, which are **Jetson-specific** GStreamer plugins:

```python
# Current pipeline (Jetson Orin only)
pipeline = (
    f"rtspsrc location={rtsp_url} latency=0 ! "
    "rtph265depay ! h265parse ! "
    "nvv4l2decoder ! nvvidconv ! "
    "video/x-raw, width=854, height=480, format=BGRx ! "
    "appsink drop=1 max-buffers=1"
)
```

On x86 Linux (this machine), `nvv4l2decoder` is not available. Use one of these alternatives instead:

```python
# x86 software decode (always available)
"rtspsrc location={rtsp_url} latency=0 ! rtph265depay ! h265parse ! "
"avdec_h265 ! videoconvert ! video/x-raw,format=BGRx ! appsink drop=1 max-buffers=1"

# x86 NVIDIA NVDEC hardware decode (requires gstreamer1.0-plugins-bad with nvcodec)
"rtspsrc location={rtsp_url} latency=0 ! rtph265depay ! h265parse ! "
"nvh265dec ! videoconvert ! video/x-raw,format=BGRx ! appsink drop=1 max-buffers=1"
```

The `zr10_raw_publisher` node deliberately avoids a second RTSP connection — it subscribes to the compressed topic and decodes in-process, rate-limited to 5 fps by default.

### Gimbal control (`zr10_gimbal`)

Implements a minimal SIYI SDK over UDP (port 37260). Packets use a fixed 8-byte header (`0x55 0x66` magic, CRC16 trailer). Key command IDs:

| CMD | Action |
|-----|--------|
| `0x05` | Zoom step (+1/0/-1) |
| `0x07` | Rotation speed (yaw, pitch, signed bytes −100…100) |
| `0x08` | Center gimbal |
| `0x0D` | Poll attitude (response: yaw/pitch/roll as `int16 × 0.1°` at offsets 8/10/12) |
| `0x0E` | Set absolute angle (yaw ±135°, pitch −90…+25°, encoded as `int16 × 10`) |
| `0x0F` | Set absolute zoom (1.0×–30.0×, sent as `[int_part, dec_part×10]`) |

All sends are synchronous (blocking `recvfrom` with 0.5 s timeout). On shutdown the node sends a stop-rotation command before closing the socket.

### ROS2 Topics

**Published:**
- `zr10/image_raw/compressed` (`sensor_msgs/CompressedImage`) — main video feed
- `zr10/image_raw` (`sensor_msgs/Image`) — raw frames at low rate (raw publisher node only)
- `zr10/gimbal/attitude` (`geometry_msgs/Vector3`) — yaw/pitch/roll in degrees
- `zr10/gimbal/zoom_level` (`std_msgs/Float32`) — current zoom
- `zr10/stats/*` — individual Float32 topics for CPU, memory, temperature, WiFi, bandwidth
- `zr10/stats/diagnostics` (`diagnostic_msgs/DiagnosticArray`) — aggregated health report

**Subscribed (gimbal control):**
- `zr10/gimbal/center` (`std_msgs/Bool`)
- `zr10/gimbal/angle` (`geometry_msgs/Vector3`) — x=yaw, y=pitch (degrees)
- `zr10/gimbal/rotate` (`geometry_msgs/Vector3`) — x=yaw_speed, y=pitch_speed (−100…100)
- `zr10/gimbal/zoom` (`std_msgs/Float32`) — absolute zoom 1.0–30.0
- `zr10/gimbal/zoom_step` (`std_msgs/Int8`) — 1/−1/0

### Network assumptions

- Camera IP: `192.168.144.25` (dedicated link, not routed)
- RTSP stream: `rtsp://192.168.144.25:8554/main.264` (H.265, 854×480)
- Gimbal UDP: port `37260`
- WiFi interface for stats: `wlP1p1s0`; Ethernet: `eno1` (Jetson defaults — update for other hardware)

---

## New device checklist

Work through these in order before launching.

### 1. Network — assign a static IP on the camera's subnet

The camera lives at `192.168.144.25` on a dedicated Ethernet link. The host interface on that cable must be on the same `/24`.

```bash
# Find which interface is connected to the camera (look for the one that just got a cable)
ip link show

# Assign a static IP (replace eno1 with your actual interface name)
sudo ip addr add 192.168.144.10/24 dev eno1

# Verify — expect <1 ms RTT
ping 192.168.144.25
```

Common failure modes:
- `ping` returns `Destination Host Unreachable` — your machine has no interface on `192.168.144.x`. Run the `ip addr add` command above.
- `ping` returns `100% packet loss` with no error — wrong interface name, or cable not plugged in.
- `Cannot find device "eth0"` — interface is named `eno1`, `enp3s0`, etc. Use `ip link show` to find the right name.

> This IP assignment is lost on reboot. To make it persistent use NetworkManager:
> ```bash
> nmcli con add type ethernet ifname eno1 ip4 192.168.144.10/24
> nmcli con up ethernet-eno1
> ```

### 2. GStreamer decoder — pick the right one for this platform

The `decoder` launch argument selects the H.265 decode path. Wrong choice = silent pipeline failure.

| Platform | `decoder` value | Requires |
|----------|----------------|---------|
| Jetson Orin / AGX / NX | `jetson` | JetPack (nvv4l2decoder + nvvidconv) |
| x86 + NVIDIA GPU | `nvdec` | `gstreamer1.0-plugins-bad` with nvcodec |
| x86 / any (safe default) | `software` | `gstreamer1.0-libav` (avdec_h265) |

```bash
# Check which decoders are available
gst-inspect-1.0 nvv4l2decoder 2>/dev/null && echo "jetson OK"
gst-inspect-1.0 nvh265dec     2>/dev/null && echo "nvdec OK"
gst-inspect-1.0 avdec_h265    2>/dev/null && echo "software OK"
```

Launch with explicit decoder:
```bash
ros2 launch zr10_camera zr10_stream.launch.py decoder:=software   # x86 default
ros2 launch zr10_camera zr10_stream.launch.py decoder:=jetson     # Jetson
```

### 3. Verify OpenCV has GStreamer support

```bash
python3 -c "import cv2; info = cv2.getBuildInformation(); \
  print('GStreamer:', 'YES' if 'GStreamer:                   YES' in info else 'NO')"
```

If NO: install `python3-opencv` from ROS or build OpenCV from source with `-DWITH_GSTREAMER=ON`. The `pip` opencv packages do **not** include GStreamer support.

### 4. Update interface names in the launch file

[zr10_stream.launch.py](launch/zr10_stream.launch.py) hardcodes WiFi/Ethernet interface names for the system stats node:

```python
'wifi_iface': 'wlP1p1s0',   # Jetson default — change to wlo1, wlan0, etc.
'eth_iface':  'eno1',        # change to match your machine
```

Find the correct names with `ip link show`, then edit the launch file or pass as arguments:
```bash
ros2 launch zr10_camera zr10_stream.launch.py  # after editing defaults in the launch file
```

### 5. Confirm the stack is working

After launching, check each node is alive and publishing:

```bash
# Should show zr10_camera, zr10_gimbal, zr10_system_stats
ros2 node list

# Should show compressed frames arriving (~15 Hz)
ros2 topic hz /zr10/image_raw/compressed

# Should show gimbal attitude updates (~10 Hz)
ros2 topic hz /zr10/gimbal/attitude
```

If `zr10/image_raw/compressed` has no data, check the publisher node log for `Failed to open RTSP stream` — it retries every 5 s, so the most likely cause is step 1 (network) or step 2 (decoder).
