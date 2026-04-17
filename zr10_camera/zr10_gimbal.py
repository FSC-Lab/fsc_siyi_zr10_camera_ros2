#!/usr/bin/env python3
"""
SIYI ZR10 Gimbal ROS2 Node - Jetson Orin side
Listens to control commands and publishes attitude feedback

Subscribed Topics:
  /zr10/gimbal/center   std_msgs/Bool        - True to center
  /zr10/gimbal/angle    geometry_msgs/Vector3 - x=yaw, y=pitch (degrees)
  /zr10/gimbal/rotate   geometry_msgs/Vector3 - x=yaw_speed, y=pitch_speed (-100~100)
  /zr10/gimbal/zoom     std_msgs/Float32      - 1.0 to 30.0
  /zr10/gimbal/zoom_step std_msgs/Int8        - 1=zoom in, -1=zoom out, 0=stop

Published Topics:
  /zr10/gimbal/attitude geometry_msgs/Vector3 - x=yaw, y=pitch, z=roll (degrees)
  /zr10/gimbal/zoom_level std_msgs/Float32    - current zoom level
"""

import socket
import struct
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from geometry_msgs.msg import Vector3
from std_msgs.msg import Bool, Float32, Int8


# ── SIYI SDK ──────────────────────────────────────────────────────────────────

def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc

def build_packet(cmd_id, data=b'', seq=0):
    header = bytes([
        0x55, 0x66,
        0x01,
        len(data) & 0xFF,
        (len(data) >> 8) & 0xFF,
        seq & 0xFF,
        (seq >> 8) & 0xFF,
        cmd_id,
    ])
    payload = header + data
    return payload + struct.pack('<H', crc16(payload))


# ── ROS2 Node ─────────────────────────────────────────────────────────────────

class ZR10GimbalNode(Node):
    def __init__(self):
        super().__init__('zr10_gimbal')

        # Parameters
        self.declare_parameter('host', '192.168.144.25')
        self.declare_parameter('port', 37260)
        self.declare_parameter('attitude_rate', 10.0)

        self.host = self.get_parameter('host').value
        self.port = self.get_parameter('port').value
        attitude_rate = self.get_parameter('attitude_rate').value

        # UDP socket
        self.seq = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)
        self.target = (self.host, self.port)

        # State tracking
        self.current_zoom = 1.0
        self.current_yaw = 0.0
        self.current_pitch = 0.0
        self.current_roll = 0.0

        # QoS
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        # ── Subscribers ───────────────────────────────────────────────────────
        self.create_subscription(Bool,    'zr10/gimbal/center',    self.cb_center,    10)
        self.create_subscription(Vector3, 'zr10/gimbal/angle',     self.cb_angle,     10)
        self.create_subscription(Vector3, 'zr10/gimbal/rotate',    self.cb_rotate,    10)
        self.create_subscription(Float32, 'zr10/gimbal/zoom',      self.cb_zoom,      10)
        self.create_subscription(Int8,    'zr10/gimbal/zoom_step', self.cb_zoom_step, 10)

        # ── Publishers ────────────────────────────────────────────────────────
        self.attitude_pub   = self.create_publisher(Vector3, 'zr10/gimbal/attitude',   10)
        self.zoom_level_pub = self.create_publisher(Float32, 'zr10/gimbal/zoom_level', 10)

        # ── Timers ────────────────────────────────────────────────────────────
        self.create_timer(1.0 / attitude_rate, self.poll_attitude)

        self.get_logger().info(
            f"ZR10 gimbal node ready — UDP {self.host}:{self.port}")

    # ── UDP send/receive ──────────────────────────────────────────────────────

    def _send(self, cmd_id, data=b''):
        packet = build_packet(cmd_id, data, self.seq)
        self.seq = (self.seq + 1) % 65536
        try:
            self.sock.sendto(packet, self.target)
            resp, _ = self.sock.recvfrom(1024)
            return resp
        except socket.timeout:
            return b''
        except Exception as e:
            self.get_logger().warn(f"UDP error: {e}")
            return b''

    # ── Command callbacks ─────────────────────────────────────────────────────

    def cb_center(self, msg: Bool):
        if msg.data:
            self._send(0x08, bytes([0x01]))
            self.get_logger().info("Gimbal centered")

    def cb_angle(self, msg: Vector3):
        yaw   = max(-135.0, min(135.0, msg.x))
        pitch = max(-90.0,  min(25.0,  msg.y))
        self._send(0x0E, struct.pack('<hh',
            int(yaw * 10), int(pitch * 10)))
        self.get_logger().info(f"Set angle yaw={yaw:.1f}° pitch={pitch:.1f}°")

    def cb_rotate(self, msg: Vector3):
        yaw_spd   = int(max(-100, min(100, msg.x)))
        pitch_spd = int(max(-100, min(100, msg.y)))
        self._send(0x07, struct.pack('bb', yaw_spd, pitch_spd))
        self.get_logger().debug(f"Rotate yaw_spd={yaw_spd} pitch_spd={pitch_spd}")

    def cb_zoom(self, msg: Float32):
        level = max(1.0, min(30.0, msg.data))
        int_part = int(level)
        dec_part = int((level - int_part) * 10)
        resp = self._send(0x0F, bytes([int_part, dec_part]))
        self.current_zoom = level
        self.get_logger().info(f"Zoom set to {level:.1f}x")
        # Publish zoom level feedback
        zoom_msg = Float32()
        zoom_msg.data = float(self.current_zoom)
        self.zoom_level_pub.publish(zoom_msg)

    def cb_zoom_step(self, msg: Int8):
        """1=zoom in, -1=zoom out, 0=stop"""
        direction = max(-1, min(1, int(msg.data)))
        self._send(0x05, struct.pack('b', direction))
        if direction == 1:
            self.get_logger().debug("Zooming in")
        elif direction == -1:
            self.get_logger().debug("Zooming out")
        else:
            self.get_logger().debug("Zoom stopped")

    # ── Attitude polling ──────────────────────────────────────────────────────

    def poll_attitude(self):
        resp = self._send(0x0D)
        if len(resp) >= 20:
            yaw   = struct.unpack_from('<h', resp, 8)[0]  / 10.0
            pitch = struct.unpack_from('<h', resp, 10)[0] / 10.0
            roll  = struct.unpack_from('<h', resp, 12)[0] / 10.0

            self.current_yaw   = yaw
            self.current_pitch = pitch
            self.current_roll  = roll

            msg = Vector3()
            msg.x = yaw
            msg.y = pitch
            msg.z = roll
            self.attitude_pub.publish(msg)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def destroy_node(self):
        self.get_logger().info("Shutting down — stopping rotation")
        self._send(0x07, struct.pack('bb', 0, 0))
        self.sock.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ZR10GimbalNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()