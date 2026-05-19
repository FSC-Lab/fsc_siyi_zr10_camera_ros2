import time
import threading
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage


class ZR10Publisher(Node):
    def __init__(self):
        super().__init__('zr10_camera')

        self.declare_parameter('rtsp_url', 'rtsp://192.168.144.25:8554/main.264')
        self.declare_parameter('fps', 15.0)
        self.declare_parameter('jpeg_quality', 80)
        # decoder: 'jetson'   → nvv4l2decoder + nvvidconv  (Jetson Orin/AGX/NX)
        #          'nvdec'    → nvh265dec + videoconvert    (x86 NVIDIA GPU)
        #          'software' → avdec_h265 + videoconvert   (any platform)
        self.declare_parameter('decoder', 'software')

        rtsp_url          = self.get_parameter('rtsp_url').value
        self.target_fps   = self.get_parameter('fps').value
        self.jpeg_quality = int(self.get_parameter('jpeg_quality').value)
        decoder           = self.get_parameter('decoder').value

        self.compressed_pub = self.create_publisher(
            CompressedImage, 'zr10/image_raw/compressed', 10)

        decode_segment = {
            'jetson':   'nvv4l2decoder ! nvvidconv !',
            'nvdec':    'nvh265dec ! videoconvert !',
            'software': 'avdec_h265 ! videoconvert !',
        }.get(decoder, 'avdec_h265 ! videoconvert !')

        self.pipeline = (
            f"rtspsrc location={rtsp_url} latency=0 ! "
            "rtph265depay ! h265parse ! "
            f"{decode_segment} "
            "video/x-raw,format=BGRx ! "
            "appsink drop=1 max-buffers=1"
        )
        self.get_logger().info(f"Decoder: {decoder}")

        self.cap     = None
        self.running = True
        self.thread  = threading.Thread(target=self.capture_loop, daemon=True)
        self.thread.start()

    def _open_stream(self) -> bool:
        self.get_logger().info(f"Connecting to: {self.get_parameter('rtsp_url').value}")
        cap = cv2.VideoCapture(self.pipeline, cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            cap.release()
            return False
        self.cap = cap
        self.get_logger().info(
            f"Stream opened — {self.target_fps}fps q={self.jpeg_quality}")
        return True

    def capture_loop(self):
        frame_time    = 1.0 / self.target_fps
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        retry_delay   = 5.0

        while self.running and rclpy.ok():
            if self.cap is None or not self.cap.isOpened():
                if not self._open_stream():
                    self.get_logger().error(
                        f"Failed to open RTSP stream — retrying in {retry_delay:.0f}s")
                    time.sleep(retry_delay)
                    continue

            loop_start = time.time()
            ret, frame = self.cap.read()
            if not ret:
                self.get_logger().warn("Lost stream — reconnecting")
                self.cap.release()
                self.cap = None
                continue

            bgr = frame[:, :, :3]

            ret_enc, jpeg = cv2.imencode('.jpg', bgr, encode_params)
            if not ret_enc:
                continue

            msg = CompressedImage()
            msg.header.stamp    = self.get_clock().now().to_msg()
            msg.header.frame_id = 'zr10_camera'
            msg.format          = 'jpeg'
            msg.data            = jpeg.tobytes()
            self.compressed_pub.publish(msg)

            elapsed    = time.time() - loop_start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def destroy_node(self):
        self.running = False
        if hasattr(self, 'thread'):
            self.thread.join(timeout=2.0)
        if self.cap is not None:
            self.cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ZR10Publisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()