#!/usr/bin/env python3
"""
ZR10 System Stats Node
Publishes Jetson system information over ROS2:
  - CPU usage (%)
  - Memory usage (%)
  - WiFi signal strength (dBm)
  - WiFi link quality (%)
  - CPU temperature (°C)
  - Network bandwidth (Mbps)
"""

import subprocess
import psutil
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue


class ZR10SystemStats(Node):
    def __init__(self):
        super().__init__('zr10_system_stats')

        self.declare_parameter('rate',       1.0)
        self.declare_parameter('wifi_iface', 'wlP1p1s0')
        self.declare_parameter('eth_iface',  'eno1')
        self.declare_parameter('history_size', 5)

        rate               = self.get_parameter('rate').value
        self.wifi_iface    = self.get_parameter('wifi_iface').value
        self.eth_iface     = self.get_parameter('eth_iface').value
        self.history_size  = self.get_parameter('history_size').value

        # Individual topic publishers
        self.cpu_pub       = self.create_publisher(Float32, 'zr10/stats/cpu_percent',    10)
        self.mem_pub       = self.create_publisher(Float32, 'zr10/stats/mem_percent',    10)
        self.temp_pub      = self.create_publisher(Float32, 'zr10/stats/cpu_temp',       10)
        self.wifi_sig_pub  = self.create_publisher(Float32, 'zr10/stats/wifi_signal',    10)
        self.wifi_qual_pub = self.create_publisher(Float32, 'zr10/stats/wifi_quality',   10)
        self.wifi_bw_pub   = self.create_publisher(Float32, 'zr10/stats/wifi_bandwidth', 10)
        self.eth_bw_pub    = self.create_publisher(Float32, 'zr10/stats/eth_bandwidth',  10)
        self.cpu_total_pub = self.create_publisher(Float32, 'zr10/stats/cpu_total', 10)
        
        # Diagnostic publisher
        self.diag_pub = self.create_publisher(
            DiagnosticArray, 'zr10/stats/diagnostics', 10)

        # Bandwidth tracking
        self.last_net          = psutil.net_io_counters(pernic=True)
        self.last_time         = time.time()
        self.wifi_bw_history   = []
        self.eth_bw_history    = []

        # Initialize cpu_percent — first call always returns 0.0
        psutil.cpu_percent(interval=None, percpu=True)

        # Timer
        self.create_timer(1.0 / rate, self.publish_stats)

        self.get_logger().info(
            f"System stats node ready — "
            f"WiFi: {self.wifi_iface}  ETH: {self.eth_iface}  "
            f"rate: {rate}Hz")

    # ── Data collectors ───────────────────────────────────────────────────────

    def get_cpu(self) -> tuple:
        """
        Returns (avg, total):
          avg   = average across all cores (0-100%) — system health indicator
          total = sum across all cores — matches top's per-process display
        """
        per_cpu = psutil.cpu_percent(interval=None, percpu=True)
        avg     = sum(per_cpu) / len(per_cpu)
        total   = sum(per_cpu)
        return avg, total

    def get_memory(self) -> float:
        return psutil.virtual_memory().percent

    def get_cpu_temp(self) -> float:
        """Read Jetson CPU temperature from thermal_zone0 (cpu-thermal)"""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                return float(f.read().strip()) / 1000.0
        except Exception as e:
            self.get_logger().debug(f"Temp read error: {e}")
            return -1.0

    def get_wifi_stats(self) -> tuple:
        """Parse iwconfig for signal strength and link quality"""
        signal  = -100.0
        quality = 0.0
        try:
            result = subprocess.run(
                ['iwconfig', self.wifi_iface],
                capture_output=True, text=True, timeout=2)
            output = result.stdout

            for line in output.split('\n'):
                if 'Signal level' in line:
                    parts = line.split('Signal level=')
                    if len(parts) > 1:
                        sig_str = parts[1].split(' ')[0].replace('dBm', '')
                        signal  = float(sig_str)
                if 'Link Quality' in line:
                    parts = line.split('Link Quality=')
                    if len(parts) > 1:
                        qual_str = parts[1].split(' ')[0]
                        if '/' in qual_str:
                            num, den = qual_str.split('/')
                            quality  = (float(num) / float(den)) * 100.0
        except Exception as e:
            self.get_logger().debug(f"WiFi stats error: {e}")
        return signal, quality

    def get_bandwidth(self) -> tuple:
        """
        Calculate WiFi and Ethernet bandwidth in Mbps since last call.
        Uses rolling average over history_size samples for smooth output.
        """
        wifi_mbps = 0.0
        eth_mbps  = 0.0
        try:
            now     = time.time()
            elapsed = now - self.last_time
            if elapsed <= 0:
                return wifi_mbps, eth_mbps

            current_net = psutil.net_io_counters(pernic=True)

            # WiFi bandwidth
            if self.wifi_iface in current_net and self.wifi_iface in self.last_net:
                wifi_bytes = (
                    current_net[self.wifi_iface].bytes_sent +
                    current_net[self.wifi_iface].bytes_recv -
                    self.last_net[self.wifi_iface].bytes_sent -
                    self.last_net[self.wifi_iface].bytes_recv
                )
                wifi_mbps = (wifi_bytes * 8) / (elapsed * 1_000_000)

            # Ethernet bandwidth
            if self.eth_iface in current_net and self.eth_iface in self.last_net:
                eth_bytes = (
                    current_net[self.eth_iface].bytes_sent +
                    current_net[self.eth_iface].bytes_recv -
                    self.last_net[self.eth_iface].bytes_sent -
                    self.last_net[self.eth_iface].bytes_recv
                )
                eth_mbps = (eth_bytes * 8) / (elapsed * 1_000_000)

            self.last_net  = current_net
            self.last_time = now

            # Rolling average
            self.wifi_bw_history.append(wifi_mbps)
            self.eth_bw_history.append(eth_mbps)
            if len(self.wifi_bw_history) > self.history_size:
                self.wifi_bw_history.pop(0)
            if len(self.eth_bw_history) > self.history_size:
                self.eth_bw_history.pop(0)

            wifi_mbps = sum(self.wifi_bw_history) / len(self.wifi_bw_history)
            eth_mbps  = sum(self.eth_bw_history)  / len(self.eth_bw_history)

        except Exception as e:
            self.get_logger().debug(f"Bandwidth error: {e}")

        return wifi_mbps, eth_mbps

    # ── Publisher ─────────────────────────────────────────────────────────────

    def publish_stats(self):
        cpu_avg, cpu_total = self.get_cpu()
        mem                = self.get_memory()
        temp               = self.get_cpu_temp()
        sig, qual          = self.get_wifi_stats()
        wifi_bw, eth_bw    = self.get_bandwidth()

        # Publish individual topics
        self._pub_float(self.cpu_pub,       cpu_avg)
        self._pub_float(self.mem_pub,       mem)
        self._pub_float(self.temp_pub,      temp)
        self._pub_float(self.wifi_sig_pub,  sig)
        self._pub_float(self.wifi_qual_pub, qual)
        self._pub_float(self.wifi_bw_pub,   wifi_bw)
        self._pub_float(self.eth_bw_pub,    eth_bw)
        self._pub_float(self.cpu_total_pub, cpu_total)
        # Publish diagnostic summary
        diag              = DiagnosticArray()
        diag.header.stamp = self.get_clock().now().to_msg()

        status             = DiagnosticStatus()
        status.name        = 'ZR10 Jetson System'
        status.hardware_id = 'jetson_orin'
        status.level       = DiagnosticStatus.OK
        status.message     = 'Running'
        status.values      = [
            KeyValue(key='CPU avg (%)',       value=f'{cpu_avg:.1f}'),
            KeyValue(key='CPU total (%)',     value=f'{cpu_total:.1f}'),
            KeyValue(key='Memory (%)',        value=f'{mem:.1f}'),
            KeyValue(key='CPU Temp (°C)',     value=f'{temp:.1f}'),
            KeyValue(key='WiFi Signal (dBm)', value=f'{sig:.1f}'),
            KeyValue(key='WiFi Quality (%)',  value=f'{qual:.1f}'),
            KeyValue(key='WiFi BW (Mbps)',    value=f'{wifi_bw:.2f}'),
            KeyValue(key='ETH BW (Mbps)',     value=f'{eth_bw:.2f}'),
        ]

        # Warning / error thresholds
        if temp > 80:
            status.level   = DiagnosticStatus.ERROR
            status.message = 'CPU overheating!'
        elif cpu_avg > 85:
            status.level   = DiagnosticStatus.WARN
            status.message = 'High CPU usage'
        elif temp > 70:
            status.level   = DiagnosticStatus.WARN
            status.message = 'CPU temp elevated'

        diag.status.append(status)
        self.diag_pub.publish(diag)

        self.get_logger().debug(
            f"CPU avg:{cpu_avg:.1f}% total:{cpu_total:.1f}% "
            f"MEM:{mem:.1f}% TEMP:{temp:.1f}°C "
            f"WiFi:{sig:.0f}dBm({qual:.0f}%) "
            f"BW WiFi:{wifi_bw:.1f}Mbps ETH:{eth_bw:.1f}Mbps")

    def _pub_float(self, publisher, value: float):
        msg      = Float32()
        msg.data = float(value)
        publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = ZR10SystemStats()
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