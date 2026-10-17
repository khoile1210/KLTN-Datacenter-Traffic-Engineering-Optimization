#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ebpf_loader.py - Userspace eBPF / XDP Loader & Graceful Fallback Manager
Quản lý vòng đời của chương trình eBPF/XDP trong Linux Kernel:
  1. Kiểm tra môi trường & Tự động kích hoạt cơ chế Fallback 3 Tầng nếu thiếu dependencies.
  2. Nạp chương trình C (ebpf_telemetry.c) vào Kernel thông qua BCC.
  3. Tự động ánh xạ ifindex của các cổng veth vào DPID của Switch trong Root Namespace.
  4. Lắng nghe sự kiện Microburst thời gian thực qua BPF Perf Event Ring Buffer.
  5. Cung cấp API truy xuất số liệu độ phân giải micro-giây cho management_plane.py.
"""

import os
import sys
import time
import socket
import logging
import threading
import subprocess

logger = logging.getLogger("eBPF_Loader")

# Kiểm tra sự sẵn sàng của thư viện BCC
BCC_AVAILABLE = False
try:
    if sys.platform.startswith("linux"):
        from bcc import BPF
        BCC_AVAILABLE = True
except ImportError:
    BCC_AVAILABLE = False


class EBPFTelemetryManager:
    """
    Quản lý tập trung toàn bộ hạ tầng eBPF / XDP Telemetry.
    Đảm bảo tính trong suốt, không bao giờ làm sập hệ thống khi thiếu quyền hạn hoặc kernel headers.
    """
    def __init__(self, c_src_path=None):
        if c_src_path is None:
            c_src_path = os.path.join(os.path.dirname(__file__), "ebpf_telemetry.c")
        self.c_src_path = c_src_path
        self.bpf = None
        self.is_active = False
        self.active_tier = "Tier 3: Baseline Dynamic Attribution (Fallback)"
        self.attached_interfaces = []
        self.burst_events_log = []
        self.lock = threading.Lock()
        self.perf_thread = None
        self.running = False

        # Khởi động kiểm tra và nạp eBPF
        self._initialize()

    def _initialize(self):
        """Kiểm tra điều kiện môi trường và nạp eBPF nếu đủ điều kiện."""
        # 1. Kiểm tra hệ điều hành Linux
        if not sys.platform.startswith("linux"):
            logger.info("[eBPF] Hệ điều hành không phải Linux (%s). Kích hoạt Tier 3 Fallback.", sys.platform)
            return

        # 2. Kiểm tra quyền Root
        if os.geteuid() != 0:
            logger.warning("[eBPF] Cần quyền root (CAP_BPF / CAP_NET_ADMIN) để nạp XDP. Kích hoạt Tier 3 Fallback.")
            return

        # 3. Kiểm tra thư viện BCC
        if not BCC_AVAILABLE:
            logger.warning("[eBPF] Chưa cài đặt python3-bpfcc / bpfcc-tools. Kích hoạt Tier 3 Fallback.")
            return

        # 4. Kiểm tra file mã nguồn C
        if not os.path.exists(self.c_src_path):
            logger.warning("[eBPF] Không tìm thấy file mã nguồn C tại: %s. Kích hoạt Tier 3 Fallback.", self.c_src_path)
            return

        # 5. Tiến hành biên dịch và nạp eBPF vào Kernel
        try:
            logger.info("[eBPF] Đang biên dịch và nạp %s vào Linux Kernel...", self.c_src_path)
            self.bpf = BPF(src_file=self.c_src_path, cflags=["-Wno-macro-redefined"])
            self.is_active = True
            self.active_tier = "Tier 1: Full High-Res eBPF/XDP + Perf Ring Buffer"
            logger.info("[eBPF] Nạp thành công chương trình eBPF vào Kernel! (%s)", self.active_tier)

            # Đính kèm Tracepoints ngắt mạng
            self._attach_tracepoints()

            # Khởi động luồng đọc Perf Event Ring Buffer
            self._start_perf_reader()

        except Exception as e:
            logger.error("[eBPF] Lỗi khi nạp eBPF bytecode vào Kernel: %s. Chuyển sang Tier 3 Fallback.", str(e))
            self.is_active = False
            self.bpf = None

    def _attach_tracepoints(self):
        """Gắn Tracepoints theo dõi ngắt mềm softirq NET_RX."""
        if not self.is_active or not self.bpf:
            return
        try:
            self.bpf.attach_tracepoint(tp="irq:softirq_entry", fn_name="trace_softirq_entry")
            self.bpf.attach_tracepoint(tp="irq:softirq_exit", fn_name="trace_softirq_exit")
            logger.info("[eBPF] Đã kích hoạt Tracepoints irq:softirq_entry/exit.")
        except Exception as e:
            logger.warning("[eBPF] Không thể gắn Tracepoints softirq: %s", str(e))

    def _start_perf_reader(self):
        """Khởi động luồng đọc Ring Buffer nhận sự kiện Microburst theo thời gian thực."""
        if not self.is_active or not self.bpf:
            return

        def _perf_callback(cpu, data, size):
            evt = self.bpf["burst_events"].event(data)
            rec = {
                "timestamp_ns": evt.timestamp_ns,
                "ifindex": evt.ifindex,
                "dpid": evt.dpid,
                "duration_ns": evt.window_duration_ns,
                "bytes": evt.bytes_in_window,
                "packets": evt.packets_in_window,
                "rate_mbps": evt.instantaneous_rate_mbps
            }
            with self.lock:
                self.burst_events_log.append(rec)
                if len(self.burst_events_log) > 1000:
                    self.burst_events_log.pop(0)

        def _worker():
            self.bpf["burst_events"].open_perf_buffer(_perf_callback)
            while self.running and self.is_active:
                try:
                    self.bpf.perf_buffer_poll(timeout=100)
                except Exception:
                    break

        self.running = True
        self.perf_thread = threading.Thread(target=_worker, daemon=True, name="eBPF-PerfReader")
        self.perf_thread.start()
        logger.info("[eBPF] Luồng Perf Ring Buffer Microburst Reader đã sẵn sàng.")

    def attach_mininet_interfaces(self, topology_switches=None):
        """
        Quét các cổng mạng veth của Mininet, ánh xạ ifindex sang Switch DPID và gắn XDP Hook.
        """
        if not self.is_active or not self.bpf:
            return

        # 1. Tự động phát hiện các interface veth của các switch trong topology
        target_interfaces = []
        try:
            # Lấy danh sách link từ ip link
            out = subprocess.check_output("ip -o link show", shell=True, stderr=subprocess.DEVNULL).decode()
            for line in out.strip().split("\n"):
                parts = line.split(":")
                if len(parts) >= 2:
                    ifname = parts[1].strip().split("@")[0]
                    # Nhận diện các port nối switch (a1-eth, ag1-eth, c1-eth)
                    if any(ifname.startswith(pfx) for pfx in ["a", "ag", "c"]) and "-eth" in ifname:
                        target_interfaces.append(ifname)
        except Exception:
            pass

        # 2. Điền BPF Map ifindex_to_bridge_map và gắn XDP
        ifindex_map = self.bpf["ifindex_to_bridge_map"]
        fn = self.bpf.load_func("xdp_ingress_telemetry", BPF.XDP)

        attached_count = 0
        for dev in target_interfaces:
            try:
                idx = socket.if_nametoindex(dev)
                # Tính nhẩm DPID đại diện từ tên switch (ví dụ a1 -> dpid 1, ag1 -> dpid 17, c1 -> dpid 33)
                sw_name = dev.split("-")[0]
                dpid = self._convert_sw_name_to_dpid(sw_name)
                
                # Nạp vào BPF Map
                ifindex_map[ifindex_map.Key(idx)] = ifindex_map.Leaf(dpid)

                # Gắn Generic XDP Hook (XDP_FLAGS_SKB_MODE) an toàn trên veth
                if dev not in self.attached_interfaces:
                    self.bpf.attach_xdp(dev, fn, flags=BPF.XDP_FLAGS_SKB_MODE)
                    self.attached_interfaces.append(dev)
                    attached_count += 1
            except Exception as e:
                logger.debug("[eBPF] Bỏ qua interface %s: %s", dev, str(e))

        logger.info("[eBPF] Đã đính kèm thành công XDP Passive Hook vào %d giao diện mạng veth.", attached_count)

    def _convert_sw_name_to_dpid(self, sw_name):
        """Quy đổi tên switch thành dpid số nguyên tương ứng."""
        try:
            if sw_name.startswith("a") and not sw_name.startswith("ag"):
                return int(sw_name.replace("a", ""))
            elif sw_name.startswith("ag"):
                return 16 + int(sw_name.replace("ag", ""))
            elif sw_name.startswith("c"):
                return 32 + int(sw_name.replace("c", ""))
        except Exception:
            pass
        return 1

    def get_kernel_switch_stats(self, dpid_int):
        """Đọc số liệu gói tin và thời gian ngắt softirq đo trực tiếp từ Kernel của switch."""
        if not self.is_active or not self.bpf:
            return None
        try:
            sw_map = self.bpf["switch_telemetry_map"]
            k = sw_map.Key(dpid_int)
            if k in sw_map:
                val = sw_map[k]
                return {
                    "rx_bytes": val.rx_bytes,
                    "rx_packets": val.rx_packets,
                    "burst_count": val.burst_count,
                    "last_update_ns": val.last_update_ns
                }
        except Exception:
            pass
        return None

    def get_kernel_softirq_runtime_ns(self):
        """Đọc tổng thời gian ngắt mạng NET_RX softirq (nano-giây) từ BPF Array."""
        if not self.is_active or not self.bpf:
            return 0
        try:
            arr = self.bpf["softirq_metric_array"]
            val = arr[0]
            return val.value if val else 0
        except Exception:
            return 0

    def get_flow_fct_records(self):
        """
        Trích xuất danh sách luồng mạng kèm Flow Completion Time (FCT micro-giây) 
        được đo trực tiếp từ tầng Ingress XDP.
        """
        if not self.is_active or not self.bpf:
            return {}
        fct_dict = {}
        try:
            flow_map = self.bpf["flow_metrics_map"]
            for k, v in flow_map.items():
                s_ip = socket.inet_ntoa(k.src_ip.to_bytes(4, "big"))
                d_ip = socket.inet_ntoa(k.dst_ip.to_bytes(4, "big"))
                flow_key = (s_ip, d_ip, k.src_port, k.dst_port, k.protocol)
                fct_dict[flow_key] = {
                    "bytes": v.bytes,
                    "packets": v.packets,
                    "start_ktime_ns": v.start_ktime_ns,
                    "last_ktime_ns": v.last_ktime_ns,
                    "fct_us": v.fct_us,
                    "is_fin_rst": bool(v.is_fin_rst)
                }
        except Exception:
            pass
        return fct_dict

    def get_recent_microburst_events(self):
        """Lấy danh sách các đợt Microburst vừa được phát hiện qua Ring Buffer."""
        with self.lock:
            evts = list(self.burst_events_log)
            self.burst_events_log.clear()
            return evts

    def cleanup(self):
        """Gỡ bỏ an toàn toàn bộ XDP Hooks khỏi các interface veth khi dừng hệ thống."""
        self.running = False
        if not self.is_active or not self.bpf:
            return
        logger.info("[eBPF] Đang gỡ bỏ XDP Hooks khỏi các interface...")
        for dev in list(self.attached_interfaces):
            try:
                self.bpf.remove_xdp(dev, flags=BPF.XDP_FLAGS_SKB_MODE)
            except Exception:
                pass
        self.attached_interfaces.clear()
        logger.info("[eBPF] Đã hoàn tất giải phóng tài nguyên Kernel an toàn.")


# Khởi tạo singleton dùng chung
_global_ebpf_manager = None

def get_ebpf_manager():
    global _global_ebpf_manager
    if _global_ebpf_manager is None:
        _global_ebpf_manager = EBPFTelemetryManager()
    return _global_ebpf_manager
