import cv2
import time
import threading
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CompressedImage
from cv_bridge import CvBridge


class ZR10RawPublisher(Node):
    """
    Optional raw image publisher at low frequency.
    Only run this when you need raw frames for processing
    (e.g. object detection, OpenCV algorithms).
    Subscribes to compressed topic and converts — no extra RTSP connection.
    """
    def __init__(self):
        super().__init__('zr10_raw')

        self.declare_parameter('fps', 5.0)  # low frequency — default 5fps

        self.target_fps = self.get_parameter('fps').value

        self.bridge = CvBridge()

        # Subscribe to compressed (already being published)
        self.create_subscription(
            CompressedImage,
            'zr10/image_raw/compressed',
            self.cb_compressed,
            10)

        # Publish raw
        self.raw_pub = self.create_publisher(Image, 'zr10/image_raw', 10)

        # Rate limiter
        self.last_published = 0.0
        self.min_interval = 1.0 / self.target_fps

        self.get_logger().info(
            f"ZR10 raw publisher ready — {self.target_fps}fps")

    def cb_compressed(self, msg: CompressedImage):
        # Rate limit
        now = time.time()
        if now - self.last_published < self.min_interval:
            return
        self.last_published = now

        try:
            import numpy as np
            np_arr = np.frombuffer(msg.data, np.uint8)
            frame  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                return

            raw_msg = self.bridge.cv2_to_imgmsg(frame, encoding='bgr8')
            raw_msg.header.stamp = msg.header.stamp
            raw_msg.header.frame_id = msg.header.frame_id
            self.raw_pub.publish(raw_msg)

        except Exception as e:
            self.get_logger().warn(f"Raw conversion error: {e}")


def main(args=None):
    rclpy.init(args=args)
    node = ZR10RawPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()