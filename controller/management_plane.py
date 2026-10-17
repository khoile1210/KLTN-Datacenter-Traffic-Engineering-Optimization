#!/usr/bin/env python3
"""
Tên file: management_plane.py
Mô tả   : Tầng Quản trị & Telemetry Toàn Diện (Comprehensive Management Plane) cho SDN-AI DCN:
          Phục vụ đồng thời 3 mục đích cốt lõi:
          1. THU THẬP DATA (DATASET COLLECTION CHO AI / MACHINE LEARNING):
             - Thu thập bộ 10 Features chuẩn: dur, sbytes, dbytes, Spkts, Dpkts, Sload, Dload, smeansz, dmeansz, Ratio.
             - Bổ sung đặc trưng mở rộng: pkt_rate, byte_rate, phân vùng Locality (Intra-Rack, Extra-Rack, Extra-DC).
             - Lần vết ĐƯỜNG ĐI CHI TIẾT TỪNG CHẶNG (Full End-to-End Hop-by-Hop Path) và hop_count.
             - Ghép cặp Bi-flow đối xứng và gán nhãn Ground-Truth (1: Elephant, 0: Mice).
             - Xuất file: results/traffic_flow_dataset_with_paths.csv.
          2. GIÁM SÁT HỆ THỐNG & MẠNG (REAL-TIME SYSTEM & NETWORK MONITORING):
             - Giám sát Switch OVS: CPU (%), RAM (MB), TCAM Table 0 active rules, Tx/Rx bytes, throughput (Mbps), drops, errors.
             - Giám sát Docker Host Containers: CPU (%), RAM used (MB), RAM limit (MB), RAM (%), Network Rx/Tx bytes, Network I/O (Mbps).
             - Giám sát Liên kết (Link Telemetry): Băng thông tức thời (Mbps), Capacity, Tỷ lệ sử dụng link (Utilization %), Drop delta.
             - Xuất file: results/device_resource_utilization.csv, results/system_and_network_health.csv, results/link_utilization_telemetry.csv.
          3. ĐÁNH GIÁ HIỆU NĂNG & BENCHMARK KPIS (ACADEMIC PERFORMANCE EVALUATION):
             - Tổng thông lượng toàn mạng (Total Throughput Mbps).
             - Mức độ chiếm dụng đường cắt ngang Core-Agg (Bisection Bandwidth Utilization %).
             - Tỷ lệ rớt gói toàn mạng (Overall Packet Loss Rate %).
             - Chỉ số công bằng Jain's Fairness Index trên các đường truyền song song Core-Agg.
             - Độ lệch chuẩn tải giữa các link lõi (Link Utilization Standard Deviation - thước đo cân bằng tải ECMP vs AI).
             - Thời gian hoàn thành trung bình của luồng Chuột (Mice Flow Completion Time indicator).
             - Xuất file: results/network_evaluation_kpis.csv.
"""

import os
import sys
import time
import subprocess
import re
import requests
import json
import numpy as np
import pandas as pd
import networkx as nx
import psutil
import threading
from datetime import datetime

# Tích hợp hạ tầng eBPF / XDP High-Resolution Telemetry Engine
try:
    from ebpf_loader import get_ebpf_manager
except ImportError:
    try:
        from controller.ebpf_loader import get_ebpf_manager
    except ImportError:
        get_ebpf_manager = None

# Đảm bảo UTF-8
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

RYU_REST_URL = "http://127.0.0.1:8080"
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
if not os.path.exists(RESULTS_DIR):
    RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# 1. Các tệp tin kết quả xuất ra (4 luồng chuyên biệt)
OUTPUT_FLOW_CSV = os.path.join(RESULTS_DIR, "traffic_flow_dataset_with_paths.csv")
OUTPUT_DEVICE_CSV = os.path.join(RESULTS_DIR, "device_resource_utilization.csv")
OUTPUT_HEALTH_CSV = os.path.join(RESULTS_DIR, "system_and_network_health.csv")
OUTPUT_LINK_CSV = os.path.join(RESULTS_DIR, "link_utilization_telemetry.csv")
OUTPUT_KPI_CSV = os.path.join(RESULTS_DIR, "network_evaluation_kpis.csv")

POLL_INTERVAL_SEC = 1.0

# Ngưỡng phân loại Ground Truth cho luồng Voi (Elephant Flow)
ELEPHANT_BYTE_RATE_THRESHOLD = 1024 * 1024       # 1 MB/s (Sload > 1 MB/s)
ELEPHANT_TOTAL_BYTES_THRESHOLD = 5 * 1024 * 1024 # 5 MB (sbytes > 5 MB)

# ==============================================================================
# ĐỊNH NGHĨA CẤU TRÚC TIÊU ĐỀ CSV CHO 4 BỘ METRICS
# ==============================================================================
# Bộ 1: Dataset luồng cho AI (10 Features + Hop-by-Hop + Metadata)
FLOW_CSV_HEADERS = [
    "timestamp", "src_ip", "dst_ip", "src_port", "dst_port", "protocol",
    "dur", "sbytes", "dbytes", "Spkts", "Dpkts",
    "Sload", "Dload", "smeansz", "dmeansz", "Ratio",
    "hop_count", "path", "label",
    "src_host", "dst_host", "locality", "pkt_rate", "byte_rate"
]

# Bộ 2: Giám sát tài nguyên thiết bị (Switch & Host Containers)
DEVICE_CSV_HEADERS = [
    "timestamp", "node_name", "node_type", "cpu_percent",
    "memory_usage_mb", "memory_limit_mb", "memory_percent",
    "network_rx_bytes", "network_tx_bytes", "network_rx_mbps", "network_tx_mbps",
    "packet_drop_count", "tcam_entries"
]

HEALTH_CSV_HEADERS = [
    "timestamp", "node_name", "node_type", "cpu_usage_pct", "ram_used_mb",
    "ram_limit_mb", "ram_usage_pct", "tcam_entries", "total_tx_bytes", "total_rx_bytes",
    "tx_mbps", "rx_mbps", "total_tx_dropped", "total_rx_dropped", "total_errors"
]

# Bộ 3: Giám sát & Đánh giá đường truyền liên kết (Link Telemetry for GAT/PPO)
LINK_CSV_HEADERS = [
    "timestamp", "src_node", "dst_node", "src_port", "dst_port",
    "link_type", "capacity_mbps", "tx_bytes_delta", "tx_rate_mbps",
    "utilization_pct", "tx_dropped_delta", "tx_errors_delta"
]

# Bộ 4: Chỉ số KPI đánh giá toàn mạng & Benchmark (Network KPIs)
KPI_CSV_HEADERS = [
    "timestamp", "active_flows_count", "active_elephant_flows", "active_mice_flows",
    "total_network_throughput_mbps", "bisection_utilization_pct",
    "overall_packet_loss_rate_pct", "total_network_drops",
    "jains_fairness_index", "link_util_std_dev",
    "avg_hop_count", "avg_mice_duration_sec"
]


def parse_action_helper(act):
    """Hỗ trợ bóc tách linh hoạt Action cả dạng Dict lẫn dạng String."""
    if isinstance(act, dict):
        act_type = str(act.get("type", "")).upper()
        if act_type == "OUTPUT":
            return "OUTPUT", int(act.get("port", 0))
        elif act_type == "GROUP":
            return "GROUP", int(act.get("group_id", 0))
    elif isinstance(act, str):
        if "OUTPUT:" in act:
            return "OUTPUT", int(act.split(":")[1])
        elif "GROUP:" in act:
            return "GROUP", int(act.split(":")[1])
    return None, None


def parse_size_bytes(val_str):
    """Chuyển đổi chuỗi dung lượng (12.5MiB, 1024MB, 500kB, 1.2GB) sang số Bytes."""
    if not val_str or not isinstance(val_str, str):
        return 0.0
    val_str = val_str.strip().upper()
    m = re.match(r"^([\d\.]+)\s*([A-Z]*)$", val_str)
    if not m:
        return 0.0
    try:
        num = float(m.group(1))
        unit = m.group(2)
        if "G" in unit:
            return num * 1024.0 * 1024.0 * 1024.0
        elif "M" in unit:
            return num * 1024.0 * 1024.0
        elif "K" in unit:
            return num * 1024.0
        return num
    except Exception:
        return 0.0


class DockerStatsCollectorThread(threading.Thread):
    """
    Luồng nền chuyên trách thu thập số liệu Docker Containers (CPU, RAM, Net I/O).
    Chạy bất đồng bộ để vòng lặp chính của Management Plane không bị nghẽn (zero block),
    ngăn ngừa triệt để lỗi TimeoutExpired khi hệ thống có 33 containers hoạt động dưới tải cao.
    Có cơ chế Stale Cache Retention lưu giữ snapshot mới nhất khi có lỗi tạm thời.
    """
    def __init__(self, poll_interval=2.0, timeout=8.0):
        super().__init__(daemon=True)
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.lock = threading.Lock()
        self.running = True
        self.cached_container_stats = {}
        self.last_update_time = 0.0

    def run(self):
        while self.running:
            try:
                cmd = "docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}'"
                output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=self.timeout).decode()
                parsed = {}
                for line in output.strip().split("\n"):
                    if not line or "\t" not in line:
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 5:
                        raw_name = parts[0].strip()
                        c_name = raw_name.replace("mn.", "") if raw_name.startswith("mn.") else raw_name
                        cpu_raw = parts[1].replace("%", "").strip()
                        try:
                            cpu_pct = float(cpu_raw) if cpu_raw else 0.0
                        except ValueError:
                            cpu_pct = 0.0

                        # Phân tích RAM: used / limit
                        mem_parts = parts[2].split("/")
                        mem_used_bytes = parse_size_bytes(mem_parts[0]) if len(mem_parts) > 0 else 0.0
                        mem_limit_bytes = parse_size_bytes(mem_parts[1]) if len(mem_parts) > 1 else 1024.0 * 1024 * 1024
                        mem_used_mb = mem_used_bytes / (1024.0 * 1024.0)
                        mem_limit_mb = mem_limit_bytes / (1024.0 * 1024.0)

                        mem_pct_raw = parts[3].replace("%", "").strip()
                        try:
                            mem_pct = float(mem_pct_raw) if mem_pct_raw else (mem_used_mb / max(mem_limit_mb, 1.0) * 100.0)
                        except ValueError:
                            mem_pct = 0.0

                        # Phân tích Network I/O: rx / tx
                        net_parts = parts[4].split("/")
                        net_rx_bytes = parse_size_bytes(net_parts[0]) if len(net_parts) > 0 else 0.0
                        net_tx_bytes = parse_size_bytes(net_parts[1]) if len(net_parts) > 1 else 0.0

                        parsed[c_name] = {
                            "cpu_pct": cpu_pct,
                            "mem_used_mb": mem_used_mb,
                            "mem_limit_mb": mem_limit_mb,
                            "mem_pct": mem_pct,
                            "net_rx_bytes": net_rx_bytes,
                            "net_tx_bytes": net_tx_bytes
                        }
                if parsed:
                    with self.lock:
                        self.cached_container_stats.update(parsed)
                        self.last_update_time = time.time()
            except Exception:
                # Giữ nguyên Stale Cache khi gặp Timeout hoặc Docker Daemon bận
                pass
            time.sleep(self.poll_interval)

    def get_stats(self):
        with self.lock:
            return dict(self.cached_container_stats)

    def stop(self):
        self.running = False


class ComprehensiveManagementPlane:
    def __init__(self, rest_url=RYU_REST_URL):
        self.rest_url = rest_url
        self.flow_csv = OUTPUT_FLOW_CSV
        self.device_csv = OUTPUT_DEVICE_CSV
        self.health_csv = OUTPUT_HEALTH_CSV
        self.link_csv = OUTPUT_LINK_CSV
        self.kpi_csv = OUTPUT_KPI_CSV

        self.topo_graph = nx.DiGraph()

        # Nạp cấu hình từ topology_config.json
        self._load_topology_config()

        # Bộ nhớ đệm phục vụ tính đạo hàm delta (thông lượng Mbps và drop rate)
        self.last_port_stats = {}  # (dpid, port) -> (time, tx_bytes, rx_bytes, tx_pkts, rx_pkts, tx_dropped, errors)
        self.last_host_stats = {}  # host_name -> (time, rx_bytes, tx_bytes)
        self.last_time = time.time()

        self.flow_cache = {}
        self.flow_tracker = {}  # pair_id -> {'first_seen', 'last_active', 'bytes', 'pkts', 'committed'}
        self.group_bucket_cache = {}

        # Khởi tạo CPU tracking
        psutil.cpu_percent(interval=None)

        # Khởi tạo các file CSV nếu chưa tồn tại
        self._init_csv_files()

        # Khởi tạo và kích hoạt Background Collector cho Docker stats (Zero-timeout, Non-blocking)
        self.docker_collector = DockerStatsCollectorThread(poll_interval=2.0, timeout=8.0)
        self.docker_collector.start()

        # Khởi tạo hạ tầng eBPF / XDP High-Resolution Telemetry Engine (Tự động thích ứng Fallback 3 Tầng)
        self.ebpf_manager = get_ebpf_manager() if get_ebpf_manager else None
        if self.ebpf_manager and self.ebpf_manager.is_active:
            try:
                self.ebpf_manager.attach_mininet_interfaces()
            except Exception:
                pass

    def _load_topology_config(self):
        """Nạp các thông số hạ tầng phần cứng và băng thông mở từ topology_config.json."""
        config_path = os.path.join(os.path.dirname(__file__), "topology_config.json")
        self.num_access = 8
        self.num_agg = 4
        self.num_core = 2
        self.hosts_per_rack = 4
        self.inet_ip = "10.0.0.100"

        # Băng thông các tầng (Mbps)
        self.bw_core_inet = 100.0
        self.bw_core_agg = 100.0
        self.bw_agg_access = 50.0
        self.bw_access_host = 20.0

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                    sw_cfg = cfg_data.get("switches", {})
                    self.num_access = int(sw_cfg.get("access", {}).get("count", 8))
                    self.num_agg = int(sw_cfg.get("aggregation", {}).get("count", 4))
                    self.num_core = int(sw_cfg.get("core", {}).get("count", 2))

                    hosts_cfg = cfg_data.get("hosts", {})
                    self.hosts_per_rack = int(hosts_cfg.get("hosts_per_rack", 4))
                    raw_inet = hosts_cfg.get("inet_node", {}).get("ip", "10.0.0.100/24")
                    self.inet_ip = raw_inet.split("/")[0]

                    bw_cfg = cfg_data.get("links", {}).get("bandwidth_mbps", {})
                    self.bw_core_inet = float(bw_cfg.get("core_inet", 100.0))
                    self.bw_core_agg = float(bw_cfg.get("core_agg", 100.0))
                    self.bw_agg_access = float(bw_cfg.get("agg_access", 50.0))
                    self.bw_access_host = float(bw_cfg.get("access_host", 20.0))
            except Exception as e:
                print(f"[!] Cảnh báo nạp cấu hình: {e}. Sử dụng cấu hình mặc định.")

        # Xây dựng danh bạ ánh xạ IP -> Switch DPID và Port cắm (1 rack = hosts_per_rack)
        self.host_switch_map = {}
        self.host_port_map = {}
        for r in range(1, self.num_access + 1):
            for h in range(1, self.hosts_per_rack + 1):
                idx = (r - 1) * self.hosts_per_rack + h
                ip = f"10.0.0.{idx}"
                self.host_switch_map[ip] = r
                self.host_port_map[ip] = self.num_agg + h

        # Node inet ngoài DCN cắm vào Core Switch (c1 DPID 33, Port 1)
        self.host_switch_map[self.inet_ip] = 33
        self.host_port_map[self.inet_ip] = 1

    def _init_csv_files(self):
        """Khởi tạo toàn bộ 5 tệp tin CSV với header chuẩn nếu chưa tồn tại."""
        files_headers = [
            (self.flow_csv, FLOW_CSV_HEADERS, "Dataset luồng (10 Features + Hop-by-Hop)"),
            (self.device_csv, DEVICE_CSV_HEADERS, "Giám sát tài nguyên thiết bị (CPU/RAM/Net IO)"),
            (self.health_csv, HEALTH_CSV_HEADERS, "Sức khỏe hệ thống và switch OVS"),
            (self.link_csv, LINK_CSV_HEADERS, "Giám sát & Đánh giá băng thông liên kết (Link Telemetry)"),
            (self.kpi_csv, KPI_CSV_HEADERS, "Chỉ số KPI đánh giá toàn mạng (Benchmark KPIs)")
        ]
        for path, headers, desc in files_headers:
            if not os.path.exists(path):
                pd.DataFrame(columns=headers).to_csv(path, index=False)
                print(f"[+] Khởi tạo file {desc}: {path}")

    def format_dpid_name(self, dpid):
        """Định dạng số DPID sang tên switch trực quan (a1..a8, ag1..ag4, c1..c2)."""
        if 1 <= dpid <= self.num_access:
            return f"a{dpid}"
        elif 17 <= dpid <= 16 + self.num_agg:
            return f"ag{dpid - 16}"
        elif dpid in [33, 0x21]:
            return "c1"
        elif dpid in [34, 0x22]:
            return "c2"
        elif dpid >= 33:
            return f"c{dpid - 32}"
        return f"s{dpid}"

    def ip_to_host_name(self, ip):
        """Chuyển đổi địa chỉ IP sang định dạng tên host chuẩn h{rack}_{host} hoặc inet."""
        if ip == self.inet_ip:
            return "inet"
        m = re.search(r"10\.0\.0\.(\d+)", ip)
        if m:
            host_idx = int(m.group(1))
            r = (host_idx - 1) // self.hosts_per_rack + 1
            h = (host_idx - 1) % self.hosts_per_rack + 1
            return f"h{r}_{h}"
        return ip

    def get_link_type_and_capacity(self, src_name, dst_name):
        """Xác định loại liên kết và dung lượng băng thông thiết kế (Capacity Mbps)."""
        s, d = str(src_name).lower(), str(dst_name).lower()
        if (s.startswith("c") and d.startswith("ag")) or (s.startswith("ag") and d.startswith("c")):
            return "Core-Agg", self.bw_core_agg
        elif (s.startswith("c") and "inet" in d) or ("inet" in s and d.startswith("c")):
            return "Core-Inet", self.bw_core_inet
        elif (s.startswith("ag") and s.startswith("a")) or (s.startswith("ag") and d.startswith("a")) or (s.startswith("a") and d.startswith("ag")):
            return "Agg-Access", self.bw_agg_access
        elif (s.startswith("a") and "h" in d) or ("h" in s and d.startswith("a")):
            return "Access-Host", self.bw_access_host
        return "Internal-Fabric", self.bw_agg_access

    def get_active_switches(self):
        """Lấy danh sách các Switch đang kết nối tới Ryu Controller."""
        try:
            resp = requests.get(f"{self.rest_url}/stats/switches", timeout=0.8)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    def update_topology_graph(self):
        """Cập nhật đồ thị liên kết topo chi tiết cả out_port và in_port giữa các switch."""
        try:
            resp = requests.get(f"{self.rest_url}/v1.0/topology/links", timeout=0.8)
            if resp.status_code == 200:
                self.topo_graph.clear()
                for link in resp.json():
                    src_dpid = int(link["src"]["dpid"], 16)
                    dst_dpid = int(link["dst"]["dpid"], 16)
                    src_port = int(link["src"]["port_no"])
                    dst_port = int(link["dst"]["port_no"])
                    self.topo_graph.add_edge(src_dpid, dst_dpid, out_port=src_port, in_port=dst_port)
                    self.topo_graph.add_edge(dst_dpid, src_dpid, out_port=dst_port, in_port=src_port)
        except Exception:
            pass

    def get_group_desc(self, dpid):
        try:
            resp = requests.get(f"{self.rest_url}/stats/groupdesc/{dpid}", timeout=0.8)
            if resp.status_code == 200:
                return resp.json().get(str(dpid), [])
        except Exception:
            pass
        return []

    def get_group_stats(self, dpid):
        try:
            resp = requests.get(f"{self.rest_url}/stats/group/{dpid}", timeout=0.8)
            if resp.status_code == 200:
                return resp.json().get(str(dpid), [])
        except Exception:
            pass
        return []

    def determine_active_out_port(self, dpid, group_id):
        """Giải mã cổng vật lý đang chuyển gói trong bảng nhóm ECMP."""
        group_desc_list = self.get_group_desc(dpid)
        group_stats_list = self.get_group_stats(dpid)

        bucket_ports = []
        for g_desc in group_desc_list:
            if g_desc.get("group_id") == group_id:
                for b in g_desc.get("buckets", []):
                    for act in b.get("actions", []):
                        a_type, a_val = parse_action_helper(act)
                        if a_type == "OUTPUT":
                            bucket_ports.append(a_val)
                break

        if not bucket_ports:
            return None

        chosen_port = bucket_ports[0]
        max_delta = -1

        for g_stat in group_stats_list:
            if g_stat.get("group_id") == group_id:
                for idx, b_stat in enumerate(g_stat.get("bucket_stats", [])):
                    if idx >= len(bucket_ports):
                        break
                    port = bucket_ports[idx]
                    cur_b = b_stat.get("byte_count", 0)
                    cache_key = (dpid, group_id, idx)
                    last_b = self.group_bucket_cache.get(cache_key, cur_b)
                    delta = cur_b - last_b
                    self.group_bucket_cache[cache_key] = cur_b

                    if delta > max_delta and delta > 0:
                        max_delta = delta
                        chosen_port = port
                break

        return chosen_port

    def trace_full_path(self, src_ip, dst_ip, switch_flows_map):
        """
        Dò vết TOÀN BỘ ĐƯỜNG ĐI CHI TIẾT NHẤT (Full End-to-End Hop-by-Hop):
        h_src -> a_src[in:X->out:Y] -> ag_src[in:X->out:Y] -> [c_core[in:X->out:Y] ->] ag_dst[in:X->out:Y] -> a_dst[in:X->out:Y] -> h_dst
        """
        src_name = self.ip_to_host_name(src_ip)
        dst_name = self.ip_to_host_name(dst_ip)

        ingress_dpid = self.host_switch_map.get(src_ip)
        egress_dpid = self.host_switch_map.get(dst_ip)

        if not ingress_dpid or not egress_dpid:
            return 0, f"{src_name} -> Unknown Route -> {dst_name}"

        # Trường hợp 1: Hai host cắm trên cùng một Switch (Intra-Rack)
        if ingress_dpid == egress_dpid:
            sw_name = self.format_dpid_name(ingress_dpid)
            in_p = self.host_port_map.get(src_ip, 5)
            out_p = self.host_port_map.get(dst_ip, 5)
            return 1, f"{src_name} -> {sw_name}[in:{in_p}->out:{out_p}] -> {dst_name}"

        # Trường hợp 2: Lộ trình đa chặng qua Spine-Leaf
        current_dpid = ingress_dpid
        hop_segments = []
        visited = set()
        prev_out_port = None
        current_in_port = self.host_port_map.get(src_ip, 5)

        while current_dpid != egress_dpid and len(hop_segments) < 8:
            visited.add(current_dpid)
            out_port = None
            flows = switch_flows_map.get(current_dpid, [])

            # 1. Tìm action cổng ra trên switch hiện tại
            for f in flows:
                match = f.get("match", {})
                if match.get("ipv4_dst") == dst_ip or match.get("nw_dst") == dst_ip:
                    for inst in f.get("instructions", []):
                        for act in inst.get("actions", []):
                            a_type, a_val = parse_action_helper(act)
                            if a_type == "GROUP":
                                out_port = self.determine_active_out_port(current_dpid, a_val)
                            elif a_type == "OUTPUT":
                                out_port = a_val
                    if out_port:
                        break

            # Fallback nếu OVS chưa có group stats: dùng shortest path từ topo graph
            if not out_port:
                if self.topo_graph.has_node(current_dpid) and self.topo_graph.has_node(egress_dpid):
                    try:
                        sp = nx.shortest_path(self.topo_graph, source=current_dpid, target=egress_dpid)
                        if len(sp) > 1:
                            out_port = self.topo_graph[current_dpid][sp[1]]["out_port"]
                    except Exception:
                        break
                else:
                    break

            sw_name = self.format_dpid_name(current_dpid)
            hop_segments.append(f"{sw_name}[in:{current_in_port}->out:{out_port}]")

            # 2. Xác định Switch kế tiếp và cổng nhận (in_port) của nó
            next_dpid = None
            next_in_port = None

            if self.topo_graph.has_node(current_dpid):
                for neighbor in self.topo_graph.neighbors(current_dpid):
                    if neighbor not in visited:
                        edge = self.topo_graph.get_edge_data(current_dpid, neighbor)
                        if edge and edge.get("out_port") == out_port:
                            next_dpid = neighbor
                            next_in_port = edge.get("in_port")
                            break

            if not next_dpid:
                try:
                    sp = nx.shortest_path(self.topo_graph, source=current_dpid, target=egress_dpid)
                    if len(sp) > 1:
                        next_dpid = sp[1]
                        edge = self.topo_graph.get_edge_data(current_dpid, next_dpid)
                        if edge:
                            next_in_port = edge.get("in_port")
                except Exception:
                    break

            current_dpid = next_dpid
            current_in_port = next_in_port or 1

        # Chặng cuối cùng: Egress Switch chuyển tiếp ra Host đích
        egress_sw_name = self.format_dpid_name(egress_dpid)
        final_out_port = self.host_port_map.get(dst_ip, 5)
        hop_segments.append(f"{egress_sw_name}[in:{current_in_port}->out:{final_out_port}]")

        full_path_str = f"{src_name} -> " + " -> ".join(hop_segments) + f" -> {dst_name}"
        return len(hop_segments), full_path_str

    def extract_biflow_stats(self, switch_flows_map):
        """
        Ghép cặp Luồng đối xứng (Bidirectional Flow Pairing) từ các Flow Rules 5-tuple
        được Controller cài đặt trên các Access Switch:
        - Bóc tách đầy đủ cả chuẩn OpenFlow 1.3 và Ryu REST API cũ (tp_src/tp_dst, nw_proto).
        - Triển khai Flow State Machine & True FCT: chỉ tính FCT thực tế thay vì tuổi thọ rule.
        - Single Commit: Chỉ xuất bản ghi luồng đã hoàn thành 1 lần duy nhất, chống nhân bản luồng lặp lại.
        """
        raw_flows = {}

        for dpid, flows in switch_flows_map.items():
            for f in flows:
                m = f.get("match", {})
                s_ip = m.get("ipv4_src") or m.get("nw_src")
                d_ip = m.get("ipv4_dst") or m.get("nw_dst")
                proto = int(m.get("ip_proto") or m.get("nw_proto") or 0)
                s_pt = int(m.get("tcp_src") or m.get("udp_src") or m.get("tp_src") or 0)
                d_pt = int(m.get("tcp_dst") or m.get("udp_dst") or m.get("tp_dst") or 0)

                if s_ip and d_ip and s_ip.startswith("10.") and d_ip.startswith("10."):
                    dur_ovs = float(f.get("duration_sec", 0)) + float(f.get("duration_nsec", 0)) / 1e9
                    pkts = int(f.get("packet_count", 0))
                    bytes_ = int(f.get("byte_count", 0))

                    direction_key = (s_ip, d_ip, s_pt, d_pt, proto)
                    if direction_key not in raw_flows or bytes_ > raw_flows[direction_key]["bytes"]:
                        raw_flows[direction_key] = {
                            "dur_ovs": dur_ovs,
                            "pkts": pkts,
                            "bytes": bytes_,
                            "dpid": dpid
                        }

        now_ts = time.time()
        processed_pairs = set()
        active_pairs = set()
        paired_records = []

        for (s_ip, d_ip, s_pt, d_pt, proto), fwd_info in raw_flows.items():
            bwd_key = (d_ip, s_ip, d_pt, s_pt, proto)
            pair_id = tuple(sorted([(s_ip, s_pt), (d_ip, d_pt)])) + (proto,)
            active_pairs.add(pair_id)

            if pair_id in processed_pairs:
                continue
            processed_pairs.add(pair_id)

            bwd_info = raw_flows.get(bwd_key, {"dur_ovs": 0.0, "pkts": 0, "bytes": 0})

            if fwd_info["bytes"] >= bwd_info["bytes"]:
                src_ip, dst_ip = s_ip, d_ip
                src_port, dst_port = s_pt, d_pt
                sbytes = fwd_info["bytes"]
                dbytes = bwd_info["bytes"]
                Spkts = fwd_info["pkts"]
                Dpkts = bwd_info["pkts"]
            else:
                src_ip, dst_ip = d_ip, s_ip
                src_port, dst_port = d_pt, s_pt
                sbytes = bwd_info["bytes"]
                dbytes = fwd_info["bytes"]
                Spkts = bwd_info["pkts"]
                Dpkts = fwd_info["pkts"]

            tot_bytes = sbytes + dbytes
            tot_pkts = Spkts + Dpkts
            if tot_bytes == 0:
                continue

            # 1. Flow State Machine: Theo dõi vòng đời luồng và chống nhân bản luồng lặp
            tracker = self.flow_tracker.get(pair_id)
            if not tracker:
                # Luồng mới xuất hiện lần đầu trong OVS
                tracker = {
                    "first_seen": now_ts,
                    "last_active": now_ts,
                    "bytes": tot_bytes,
                    "pkts": tot_pkts,
                    "committed": False
                }
                self.flow_tracker[pair_id] = tracker
            else:
                # Luồng đã có trong cache: nếu bytes tăng thì cập nhật last_active
                if tot_bytes > tracker["bytes"]:
                    tracker["last_active"] = now_ts
                    tracker["bytes"] = tot_bytes
                    tracker["pkts"] = tot_pkts
                    tracker["committed"] = False

            # 2. Tính toán True FCT (Flow Completion Time) chuẩn xác
            ebpf_fct = None
            if self.ebpf_manager and self.ebpf_manager.is_active:
                f_metrics = self.ebpf_manager.get_flow_metrics()
                for (es_ip, ed_ip, es_pt, ed_pt, e_proto), m_val in f_metrics.items():
                    if sorted([(es_ip, es_pt), (ed_ip, ed_pt)]) == sorted([(src_ip, src_port), (dst_ip, dst_port)]):
                        if m_val.get("fct_us", 0) > 0:
                            ebpf_fct = m_val["fct_us"] / 1e6
                            break

            if ebpf_fct is not None and ebpf_fct > 0:
                true_dur = round(ebpf_fct, 4)
            elif tracker["last_active"] > tracker["first_seen"]:
                true_dur = round(tracker["last_active"] - tracker["first_seen"], 4)
            else:
                # Luồng Mice hoàn tất trong 1 chu kỳ polling:
                # Thời gian truyền vật lý trên đường link Access (20 Mbps) + RTT
                c_mbps = self.bw_access_host
                phy_time = (tot_bytes * 8.0) / (c_mbps * 1e6) + 0.002
                true_dur = max(round(phy_time, 4), 0.001)

            # 3. SINGLE COMMIT: Chỉ xuất bản ghi luồng 1 lần duy nhất khi hoàn tất
            # Không ghi lặp lại khi số bytes đứng im suốt 30 giây idle_timeout của OVS!
            if not tracker["committed"]:
                tracker["committed"] = True
                paired_records.append({
                    "src_ip": src_ip,
                    "dst_ip": dst_ip,
                    "src_port": src_port,
                    "dst_port": dst_port,
                    "protocol": proto,
                    "dur": true_dur,
                    "sbytes": sbytes,
                    "dbytes": dbytes,
                    "Spkts": Spkts,
                    "Dpkts": Dpkts
                })

        # Dọn dẹp các luồng đã bị OVS xóa sau khi hết timeout
        stale_keys = [k for k in self.flow_tracker.keys() if k not in active_pairs]
        for k in stale_keys:
            del self.flow_tracker[k]

        return paired_records

    # ==========================================================================
    # 2. GIÁM SÁT TÀI NGUYÊN THIẾT BỊ (SWITCH & HOST TELEMETRY)
    # ==========================================================================
    def collect_device_telemetry(self, active_dpids, now_str, dt):
        """
        Thu thập toàn diện tài nguyên Host Containers và Switch OVS:
        CPU %, RAM used (MB), RAM limit (MB), RAM %, Network Rx/Tx bytes, Network I/O (Mbps), Drop count.
        """
        device_records = []
        health_records = []
        port_stats_by_dpid = {}

        # 1. Thu thập số liệu các Docker Containers từ Background Worker Thread (Zero-Latency, No-Timeout)
        try:
            container_stats = self.docker_collector.get_stats()
            for c_name, c_data in container_stats.items():
                cpu_pct = c_data["cpu_pct"]
                mem_used_mb = c_data["mem_used_mb"]
                mem_limit_mb = c_data["mem_limit_mb"]
                mem_pct = c_data["mem_pct"]
                net_rx_bytes = c_data["net_rx_bytes"]
                net_tx_bytes = c_data["net_tx_bytes"]

                # Tính tốc độ truyền tức thời (Mbps)
                prev_host = self.last_host_stats.get(c_name, (time.time() - dt, net_rx_bytes, net_tx_bytes))
                delta_rx = max(net_rx_bytes - prev_host[1], 0.0)
                delta_tx = max(net_tx_bytes - prev_host[2], 0.0)
                rx_mbps = round((delta_rx * 8.0) / (dt * 1e6), 3)
                tx_mbps = round((delta_tx * 8.0) / (dt * 1e6), 3)
                self.last_host_stats[c_name] = (time.time(), net_rx_bytes, net_tx_bytes)

                is_switch_container = c_name.startswith("a") or c_name.startswith("ag") or c_name.startswith("c")
                node_type = "Switch (OVS)" if is_switch_container else "Host (Container)"

                dev_rec = {
                    "timestamp": now_str,
                    "node_name": c_name,
                    "node_type": node_type,
                    "cpu_percent": round(cpu_pct, 2),
                    "memory_usage_mb": round(mem_used_mb, 2),
                    "memory_limit_mb": round(mem_limit_mb, 2),
                    "memory_percent": round(mem_pct, 2),
                    "network_rx_bytes": int(net_rx_bytes),
                    "network_tx_bytes": int(net_tx_bytes),
                    "network_rx_mbps": rx_mbps,
                    "network_tx_mbps": tx_mbps,
                    "packet_drop_count": 0,
                    "tcam_entries": "-"
                }
                device_records.append(dev_rec)

                hlth_rec = {
                    "timestamp": now_str,
                    "node_name": c_name,
                    "node_type": node_type,
                    "cpu_usage_pct": round(cpu_pct, 2),
                    "ram_used_mb": round(mem_used_mb, 2),
                    "ram_limit_mb": round(mem_limit_mb, 2),
                    "ram_usage_pct": round(mem_pct, 2),
                    "tcam_entries": "-",
                    "total_tx_bytes": int(net_tx_bytes),
                    "total_rx_bytes": int(net_rx_bytes),
                    "tx_mbps": tx_mbps,
                    "rx_mbps": rx_mbps,
                    "total_tx_dropped": 0,
                    "total_rx_dropped": 0,
                    "total_errors": 0
                }
                health_records.append(hlth_rec)
        except Exception:
            pass

        # 2. Thu thập Telemetry Switch OVS từ Ryu REST API theo Dynamic Resource Attribution Model
        ovs_cpu = 0.0
        ovs_ram_mb = 0.0
        for proc in psutil.process_iter(['name', 'cpu_percent', 'memory_info']):
            try:
                if 'ovs-vswitchd' in proc.info['name']:
                    ovs_cpu += proc.cpu_percent(interval=None)
                    ovs_ram_mb += proc.info['memory_info'].rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # PHA 1: Thu thập số liệu mạng & bảng luồng của toàn bộ active switches
        sw_metrics = {}
        for dpid in active_dpids:
            sw_name = self.format_dpid_name(dpid)
            tcam_count = 0
            tx_bytes, rx_bytes = 0, 0
            tx_pkts, rx_pkts = 0, 0
            tx_dropped, rx_dropped, errors = 0, 0, 0
            port_stats_by_dpid[dpid] = {}

            # Đọc tổng số flow rules trên TOÀN BỘ các bảng (Table 0 + Table 1)
            try:
                t_resp = requests.get(f"{self.rest_url}/stats/table/{dpid}", timeout=0.8)
                if t_resp.status_code == 200:
                    tcam_count = sum(t.get("active_count", 0) for t in t_resp.json().get(str(dpid), []))
            except Exception:
                pass

            # Đọc port statistics
            try:
                p_resp = requests.get(f"{self.rest_url}/stats/port/{dpid}", timeout=0.8)
                if p_resp.status_code == 200:
                    for ps in p_resp.json().get(str(dpid), []):
                        p_raw = ps.get("port_no")
                        if str(p_raw).upper() == "LOCAL":
                            continue
                        try:
                            port_no = int(p_raw)
                            if port_no >= 0xFFFFFF00:
                                continue
                        except (ValueError, TypeError):
                            continue

                        p_tx_b = int(ps.get("tx_bytes", 0))
                        p_rx_b = int(ps.get("rx_bytes", 0))
                        p_tx_p = int(ps.get("tx_packets", 0))
                        p_rx_p = int(ps.get("rx_packets", 0))
                        p_tx_d = int(ps.get("tx_dropped", 0))
                        p_rx_d = int(ps.get("rx_dropped", 0))
                        p_err = int(ps.get("tx_errors", 0)) + int(ps.get("rx_errors", 0))

                        tx_bytes += p_tx_b
                        rx_bytes += p_rx_b
                        tx_pkts += p_tx_p
                        rx_pkts += p_rx_p
                        tx_dropped += p_tx_d
                        rx_dropped += p_rx_d
                        errors += p_err

                        port_stats_by_dpid[dpid][port_no] = {
                            "tx_bytes": p_tx_b, "rx_bytes": p_rx_b,
                            "tx_packets": p_tx_p, "rx_packets": p_rx_p,
                            "tx_dropped": p_tx_d, "rx_dropped": p_rx_d,
                            "errors": p_err
                        }
            except Exception:
                pass

            # Tính delta throughput & delta packets cho switch
            prev_sw_port = self.last_port_stats.get((dpid, "TOTAL"), (time.time() - dt, tx_bytes, rx_bytes, tx_pkts, rx_pkts, tx_dropped, errors))
            sw_delta_tx_b = max(tx_bytes - prev_sw_port[1], 0)
            sw_delta_rx_b = max(rx_bytes - prev_sw_port[2], 0)
            sw_delta_tx_p = max(tx_pkts - prev_sw_port[3], 0)
            sw_delta_rx_p = max(rx_pkts - prev_sw_port[4], 0)
            sw_tx_mbps = round((sw_delta_tx_b * 8.0) / (dt * 1e6), 3)
            sw_rx_mbps = round((sw_delta_rx_b * 8.0) / (dt * 1e6), 3)

            # Đo đạc PPS: Tận dụng số liệu vi mô từ eBPF Kernel nếu sẵn sàng, nếu không dùng delta OpenFlow
            pps = round((sw_delta_tx_p + sw_delta_rx_p) / dt, 2)
            if self.ebpf_manager and self.ebpf_manager.is_active:
                try:
                    dpid_int = int(str(dpid).lstrip("0") or "0", 16) if isinstance(dpid, str) else int(dpid)
                    k_stats = self.ebpf_manager.get_kernel_switch_stats(dpid_int)
                    if k_stats and k_stats.get("rx_packets", 0) > 0:
                        k_pkts = k_stats["rx_packets"]
                        prev_k = self.last_port_stats.get((dpid, "KERNEL_PKTS"), (time.time() - dt, k_pkts))
                        delta_k_pkts = max(k_pkts - prev_k[1], 0)
                        pps = round(delta_k_pkts / dt, 2)
                        self.last_port_stats[(dpid, "KERNEL_PKTS")] = (time.time(), k_pkts)
                except Exception:
                    pass
            self.last_port_stats[(dpid, "TOTAL")] = (time.time(), tx_bytes, rx_bytes, tx_pkts, rx_pkts, tx_dropped, errors)

            sw_metrics[dpid] = {
                "sw_name": sw_name,
                "tcam_count": tcam_count,
                "pps": pps,
                "tx_bytes": tx_bytes,
                "rx_bytes": rx_bytes,
                "sw_tx_mbps": sw_tx_mbps,
                "sw_rx_mbps": sw_rx_mbps,
                "tx_dropped": tx_dropped,
                "rx_dropped": rx_dropped,
                "errors": errors
            }

        # PHA 2: Tính toán trọng số phân bổ tài nguyên động (Dynamic Attribution Model)
        num_switches = max(len(active_dpids), 1)
        w_base = 0.10 / num_switches
        w_dynamic_budget = 0.90

        total_pps = sum(m["pps"] for m in sw_metrics.values())
        total_rules = sum(m["tcam_count"] for m in sw_metrics.values())

        w_cpu_map = {}
        w_ram_map = {}

        for dpid, m in sw_metrics.items():
            # 1. Trọng số động CPU (ưu tiên PPS 70%, Rules 30%)
            if total_pps > 0 and total_rules > 0:
                cpu_dyn = 0.70 * (m["pps"] / total_pps) + 0.30 * (m["tcam_count"] / total_rules)
            elif total_rules > 0:
                cpu_dyn = m["tcam_count"] / total_rules
            elif total_pps > 0:
                cpu_dyn = m["pps"] / total_pps
            else:
                cpu_dyn = 1.0 / num_switches

            # 2. Trọng số động RAM (ưu tiên Rules 80%, PPS 20%)
            if total_pps > 0 and total_rules > 0:
                ram_dyn = 0.80 * (m["tcam_count"] / total_rules) + 0.20 * (m["pps"] / total_pps)
            elif total_rules > 0:
                ram_dyn = m["tcam_count"] / total_rules
            elif total_pps > 0:
                ram_dyn = m["pps"] / total_pps
            else:
                ram_dyn = 1.0 / num_switches

            w_cpu_map[dpid] = w_base + w_dynamic_budget * cpu_dyn
            w_ram_map[dpid] = w_base + w_dynamic_budget * ram_dyn

        # Chuẩn hóa hậu kiểm (Post-normalization) bảo toàn chính xác 100% tổng tài nguyên OVS
        sum_w_cpu = sum(w_cpu_map.values())
        if sum_w_cpu > 0:
            w_cpu_map = {d: w / sum_w_cpu for d, w in w_cpu_map.items()}
        sum_w_ram = sum(w_ram_map.values())
        if sum_w_ram > 0:
            w_ram_map = {d: w / sum_w_ram for d, w in w_ram_map.items()}

        # Ghi nhận số liệu vào device_records và health_records
        for dpid, m in sw_metrics.items():
            sw_name = m["sw_name"]
            tcam_count = m["tcam_count"]
            tx_bytes = m["tx_bytes"]
            rx_bytes = m["rx_bytes"]
            sw_tx_mbps = m["sw_tx_mbps"]
            sw_rx_mbps = m["sw_rx_mbps"]
            tx_dropped = m["tx_dropped"]
            rx_dropped = m["rx_dropped"]
            errors = m["errors"]

            per_switch_cpu = round(ovs_cpu * w_cpu_map.get(dpid, 1.0 / num_switches), 2)
            per_switch_ram = round(ovs_ram_mb * w_ram_map.get(dpid, 1.0 / num_switches), 2)

            existing_dev = [r for r in device_records if r["node_name"] == sw_name]
            if existing_dev:
                existing_dev[0]["tcam_entries"] = tcam_count
                existing_dev[0]["packet_drop_count"] = tx_dropped + rx_dropped
                existing_dev[0]["cpu_percent"] = per_switch_cpu
                existing_dev[0]["memory_usage_mb"] = per_switch_ram
                existing_dev[0]["memory_percent"] = round((per_switch_ram / 1024.0) * 100.0, 2)
            else:
                device_records.append({
                    "timestamp": now_str,
                    "node_name": sw_name,
                    "node_type": "Switch (OVS)",
                    "cpu_percent": per_switch_cpu,
                    "memory_usage_mb": per_switch_ram,
                    "memory_limit_mb": 1024.0,
                    "memory_percent": round((per_switch_ram / 1024.0) * 100.0, 2),
                    "network_rx_bytes": rx_bytes,
                    "network_tx_bytes": tx_bytes,
                    "network_rx_mbps": sw_rx_mbps,
                    "network_tx_mbps": sw_tx_mbps,
                    "packet_drop_count": tx_dropped + rx_dropped,
                    "tcam_entries": tcam_count
                })

            existing_hlth = [r for r in health_records if r["node_name"] == sw_name]
            if existing_hlth:
                existing_hlth[0]["tcam_entries"] = tcam_count
                existing_hlth[0]["cpu_usage_pct"] = per_switch_cpu
                existing_hlth[0]["ram_used_mb"] = per_switch_ram
                existing_hlth[0]["ram_usage_pct"] = round((per_switch_ram / 1024.0) * 100.0, 2)
            else:
                health_records.append({
                    "timestamp": now_str,
                    "node_name": sw_name,
                    "node_type": "Switch (OVS)",
                    "cpu_usage_pct": per_switch_cpu,
                    "ram_used_mb": per_switch_ram,
                    "ram_limit_mb": 1024.0,
                    "ram_usage_pct": round((per_switch_ram / 1024.0) * 100.0, 2),
                    "tcam_entries": tcam_count,
                    "total_tx_bytes": tx_bytes,
                    "total_rx_bytes": rx_bytes,
                    "tx_mbps": sw_tx_mbps,
                    "rx_mbps": sw_rx_mbps,
                    "total_tx_dropped": tx_dropped,
                    "total_rx_dropped": rx_dropped,
                    "total_errors": errors
                })

        return device_records, health_records, port_stats_by_dpid

    # ==========================================================================
    # 3. GIÁM SÁT LIÊN KẾT MẠNG (LINK TELEMETRY CHO GAT / PPO & NGHẼN MẠNG)
    # ==========================================================================
    def collect_link_telemetry(self, active_dpids, port_stats_by_dpid, now_str, dt):
        """
        Thu thập telemetry chi tiết cho từng đường link (Inter-switch & Access-Host):
        Throughput (Mbps), Capacity (Mbps), Utilization %, Drop delta, Error delta.
        """
        link_records = []

        # 1. Các liên kết Switch <-> Switch từ Topology Graph
        for u, v, data in self.topo_graph.edges(data=True):
            src_name = self.format_dpid_name(u)
            dst_name = self.format_dpid_name(v)
            src_port = data.get("out_port", 1)
            dst_port = data.get("in_port", 1)

            link_type, capacity = self.get_link_type_and_capacity(src_name, dst_name)

            # Lấy thống kê cổng xuất tại src_dpid
            p_stat = port_stats_by_dpid.get(u, {}).get(src_port, {})
            cur_tx_bytes = p_stat.get("tx_bytes", 0)
            cur_tx_drop = p_stat.get("tx_dropped", 0)
            cur_err = p_stat.get("errors", 0)

            cache_key = (u, src_port)
            prev_stat = self.last_port_stats.get(cache_key, (time.time() - dt, cur_tx_bytes, 0, 0, 0, cur_tx_drop, cur_err))
            delta_bytes = max(cur_tx_bytes - prev_stat[1], 0)
            delta_drop = max(cur_tx_drop - prev_stat[5], 0)
            delta_err = max(cur_err - prev_stat[6], 0)

            tx_rate_mbps = round((delta_bytes * 8.0) / (dt * 1e6), 3)
            util_pct = round(min((tx_rate_mbps / max(capacity, 1.0)) * 100.0, 100.0), 2)

            self.last_port_stats[cache_key] = (time.time(), cur_tx_bytes, 0, 0, 0, cur_tx_drop, cur_err)

            link_records.append({
                "timestamp": now_str,
                "src_node": src_name,
                "dst_node": dst_name,
                "src_port": src_port,
                "dst_port": dst_port,
                "link_type": link_type,
                "capacity_mbps": capacity,
                "tx_bytes_delta": delta_bytes,
                "tx_rate_mbps": tx_rate_mbps,
                "utilization_pct": util_pct,
                "tx_dropped_delta": delta_drop,
                "tx_errors_delta": delta_err
            })

        # 2. Các liên kết Downlink từ Access Switch xuống Hosts
        for ip, sw_dpid in self.host_switch_map.items():
            if sw_dpid not in active_dpids:
                continue
            sw_name = self.format_dpid_name(sw_dpid)
            host_name = self.ip_to_host_name(ip)
            port_no = self.host_port_map.get(ip, 5)
            link_type = "Core-Inet" if host_name == "inet" else "Access-Host"
            capacity = self.bw_core_inet if host_name == "inet" else self.bw_access_host

            p_stat = port_stats_by_dpid.get(sw_dpid, {}).get(port_no, {})
            cur_tx_bytes = p_stat.get("tx_bytes", 0)
            cur_tx_drop = p_stat.get("tx_dropped", 0)
            cur_err = p_stat.get("errors", 0)

            cache_key = (sw_dpid, port_no)
            prev_stat = self.last_port_stats.get(cache_key, (time.time() - dt, cur_tx_bytes, 0, 0, 0, cur_tx_drop, cur_err))
            delta_bytes = max(cur_tx_bytes - prev_stat[1], 0)
            delta_drop = max(cur_tx_drop - prev_stat[5], 0)
            delta_err = max(cur_err - prev_stat[6], 0)

            tx_rate_mbps = round((delta_bytes * 8.0) / (dt * 1e6), 3)
            util_pct = round(min((tx_rate_mbps / max(capacity, 1.0)) * 100.0, 100.0), 2)
            self.last_port_stats[cache_key] = (time.time(), cur_tx_bytes, 0, 0, 0, cur_tx_drop, cur_err)

            link_records.append({
                "timestamp": now_str,
                "src_node": sw_name,
                "dst_node": host_name,
                "src_port": port_no,
                "dst_port": 1,
                "link_type": link_type,
                "capacity_mbps": capacity,
                "tx_bytes_delta": delta_bytes,
                "tx_rate_mbps": tx_rate_mbps,
                "utilization_pct": util_pct,
                "tx_dropped_delta": delta_drop,
                "tx_errors_delta": delta_err
            })

        return link_records

    # ==========================================================================
    # 4. THU THẬP BỘ ĐẶC TRƯNG LUỒNG (10 FEATURES CHO AI CLASSIFIER)
    # ==========================================================================
    def collect_flow_dataset(self, active_dpids, switch_flows_map, now_str):
        """
        Thu thập bộ 10 Features và thông tin lần vết Hop-by-Hop phục vụ huấn luyện Machine Learning.
        """
        paired_flows = self.extract_biflow_stats(switch_flows_map)
        flow_records = []
        eps = 1e-6

        for f in paired_flows:
            src_ip = f["src_ip"]
            dst_ip = f["dst_ip"]
            src_port = f["src_port"]
            dst_port = f["dst_port"]
            proto = f["protocol"]

            dur = f["dur"]
            sbytes = f["sbytes"]
            dbytes = f["dbytes"]
            Spkts = f["Spkts"]
            Dpkts = f["Dpkts"]

            if sbytes == 0 and dbytes == 0:
                continue

            # Tính toán 10 đặc trưng
            Sload = sbytes / max(dur, eps)
            Dload = dbytes / max(dur, eps)
            smeansz = sbytes / max(Spkts, 1)
            dmeansz = dbytes / max(Dpkts, 1)
            Ratio = sbytes / (dbytes + eps)

            # Đặc trưng mở rộng
            pkt_rate = (Spkts + Dpkts) / max(dur, eps)
            byte_rate = (sbytes + dbytes) / max(dur, eps)

            # Lần vết toàn bộ lộ trình cụ thể Hop-by-Hop
            hop_count, path_str = self.trace_full_path(src_ip, dst_ip, switch_flows_map)

            # Xác định phân vùng phụ tải Locality
            src_name = self.ip_to_host_name(src_ip)
            dst_name = self.ip_to_host_name(dst_ip)
            if src_ip == self.inet_ip or dst_ip == self.inet_ip:
                locality = "Extra-DC"
            elif self.host_switch_map.get(src_ip) == self.host_switch_map.get(dst_ip):
                locality = "Intra-Rack"
            else:
                locality = "Extra-Rack"

            # Gán nhãn Ground Truth (1: Elephant, 0: Mice)
            is_elephant = 1 if (
                Sload > ELEPHANT_BYTE_RATE_THRESHOLD or
                sbytes > ELEPHANT_TOTAL_BYTES_THRESHOLD
            ) else 0

            flow_records.append({
                "timestamp": now_str,
                "src_ip": src_ip,
                "dst_ip": dst_ip,
                "src_port": src_port,
                "dst_port": dst_port,
                "protocol": proto,
                "dur": round(dur, 4),
                "sbytes": sbytes,
                "dbytes": dbytes,
                "Spkts": Spkts,
                "Dpkts": Dpkts,
                "Sload": round(Sload, 2),
                "Dload": round(Dload, 2),
                "smeansz": round(smeansz, 2),
                "dmeansz": round(dmeansz, 2),
                "Ratio": round(Ratio, 4),
                "hop_count": hop_count,
                "path": path_str,
                "label": is_elephant,
                "src_host": src_name,
                "dst_host": dst_name,
                "locality": locality,
                "pkt_rate": round(pkt_rate, 2),
                "byte_rate": round(byte_rate, 2)
            })

        return flow_records

    # ==========================================================================
    # 5. TÍNH TOÁN CÁC CHỈ SỐ KPI ĐÁNH GIÁ HIỆU NĂNG & BENCHMARK
    # ==========================================================================
    def compute_and_save_kpis(self, flow_records, link_records, health_records, now_str):
        """
        Tính toán các chỉ số đánh giá toàn mạng:
        Throughput, Bisection Bandwidth, Packet Loss Rate %, Jain's Fairness Index, Mice FCT.
        """
        active_flows_count = len(flow_records)
        active_elephant = sum(1 for f in flow_records if f["label"] == 1)
        active_mice = active_flows_count - active_elephant

        # 1. Tổng thông lượng mạng (Mbps): Tổng thông lượng chuyển giao tại các chặng biên xuống host
        host_links = [l for l in link_records if l["link_type"] in ["Access-Host", "Core-Inet"]]
        if host_links:
            total_throughput = round(sum(l["tx_rate_mbps"] for l in host_links), 2)
        else:
            total_throughput = round(sum(f["Sload"] * 8.0 / 1e6 for f in flow_records), 2)

        # 2. Mức độ chiếm dụng đường cắt ngang (Core-Agg bisection links)
        core_agg_links = [l for l in link_records if l["link_type"] == "Core-Agg"]
        if core_agg_links:
            core_agg_utils = [l["utilization_pct"] for l in core_agg_links]
            bisection_util = round(float(np.mean(core_agg_utils)), 2)

            # 3. Chỉ số công bằng Jain's Fairness Index trên các liên kết trục Core-Agg
            # J = (sum(u_i))^2 / (n * sum(u_i^2))
            sum_u = sum(core_agg_utils)
            sum_u_sq = sum(u ** 2 for u in core_agg_utils)
            n_links = len(core_agg_utils)
            if sum_u_sq > 0 and n_links > 0:
                jains_idx = round(float((sum_u ** 2) / (n_links * sum_u_sq)), 4)
            else:
                jains_idx = 1.0  # Hoàn toàn công bằng khi mạng đang rỗi

            link_std = round(float(np.std(core_agg_utils)), 2)
        else:
            bisection_util = 0.0
            jains_idx = 1.0
            link_std = 0.0

        # 4. Tỷ lệ rớt gói toàn mạng (Overall Packet Loss Rate %)
        total_drops = sum(l.get("tx_dropped_delta", 0) for l in link_records)
        total_bytes_sent = sum(l.get("tx_bytes_delta", 0) for l in link_records)
        estimated_packets = int(total_bytes_sent / 1000.0) if total_bytes_sent > 0 else 0
        if (estimated_packets + total_drops) > 0:
            loss_rate_pct = round((total_drops / float(estimated_packets + total_drops)) * 100.0, 3)
        else:
            loss_rate_pct = 0.0

        # 5. Số chặng trung bình & Thời gian hoàn thành luồng chuột (Mice FCT indicator)
        avg_hop = round(float(np.mean([f["hop_count"] for f in flow_records])), 2) if flow_records else 0.0
        mice_durs = [f["dur"] for f in flow_records if f["label"] == 0]
        avg_mice_dur = round(float(np.mean(mice_durs)), 4) if mice_durs else 0.0

        kpi_rec = {
            "timestamp": now_str,
            "active_flows_count": active_flows_count,
            "active_elephant_flows": active_elephant,
            "active_mice_flows": active_mice,
            "total_network_throughput_mbps": total_throughput,
            "bisection_utilization_pct": bisection_util,
            "overall_packet_loss_rate_pct": loss_rate_pct,
            "total_network_drops": total_drops,
            "jains_fairness_index": jains_idx,
            "link_util_std_dev": link_std,
            "avg_hop_count": avg_hop,
            "avg_mice_duration_sec": avg_mice_dur
        }
        return kpi_rec

    def _print_dashboard(self, now_str, flow_records, device_records, link_records, kpi_record):
        """In dashboard trạng thái định kỳ ra màn hình Terminal 3 một cách trực quan."""
        time_str = now_str.split(" ")[1] if " " in now_str else now_str
        n_flows = len(flow_records)
        n_eleph = kpi_record.get("active_elephant_flows", 0) if kpi_record else 0
        n_mice = kpi_record.get("active_mice_flows", 0) if kpi_record else 0
        n_nodes = len(device_records)
        thru = kpi_record.get("total_network_throughput_mbps", 0.0) if kpi_record else 0.0
        core_util = kpi_record.get("bisection_utilization_pct", 0.0) if kpi_record else 0.0
        jains = kpi_record.get("jains_fairness_index", 1.0) if kpi_record else 1.0
        drops = kpi_record.get("total_network_drops", 0) if kpi_record else 0

        print(f"[{time_str}] [Telemetry Poller] Flows: {n_flows:3d} (Voi: {n_eleph:2d}, Chuột: {n_mice:2d}) | Throughput: {thru:6.2f} Mbps | Core-Agg: {core_util:5.1f}% (Jain's: {jains:.3f}) | Nodes: {n_nodes:2d} | Drops: {drops}")

    # ==========================================================================
    # 6. VÒNG LẶP CHÍNH THU THẬP VÀ GHI DỮ LIỆU ĐỒNG THỜI
    # ==========================================================================
    def collect_and_save_all(self):
        cur_time = time.time()
        dt = max(cur_time - self.last_time, 0.001)
        self.last_time = cur_time
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        active_dpids = self.get_active_switches()

        # 1. Thu thập Telemetry Thiết bị (Host Containers & Switches)
        device_records, health_records, port_stats_by_dpid = self.collect_device_telemetry(active_dpids, now_str, dt)
        if device_records:
            pd.DataFrame(device_records).to_csv(self.device_csv, mode="a", header=False, index=False)
        if health_records:
            pd.DataFrame(health_records).to_csv(self.health_csv, mode="a", header=False, index=False)

        if not active_dpids:
            return

        # 2. Cập nhật đồ thị liên kết topo
        self.update_topology_graph()

        # 3. Thu thập Telemetry Liên kết (Throughput, Utilization %, Drops)
        link_records = self.collect_link_telemetry(active_dpids, port_stats_by_dpid, now_str, dt)
        if link_records:
            pd.DataFrame(link_records).to_csv(self.link_csv, mode="a", header=False, index=False)

        # 4. Đọc Flow Table của tất cả các Switch & Ghép cặp Bi-flow
        switch_flows_map = {}
        for dpid in active_dpids:
            try:
                resp = requests.get(f"{self.rest_url}/stats/flow/{dpid}", timeout=0.8)
                if resp.status_code == 200:
                    switch_flows_map[dpid] = resp.json().get(str(dpid), [])
            except Exception:
                switch_flows_map[dpid] = []

        flow_records = self.collect_flow_dataset(active_dpids, switch_flows_map, now_str)
        if flow_records:
            pd.DataFrame(flow_records).to_csv(self.flow_csv, mode="a", header=False, index=False)

        # 5. Tính toán và lưu trữ các chỉ số KPI Đánh giá Toàn mạng (Evaluation Benchmarks)
        kpi_record = self.compute_and_save_kpis(flow_records, link_records, health_records, now_str)
        if kpi_record:
            pd.DataFrame([kpi_record]).to_csv(self.kpi_csv, mode="a", header=False, index=False)

        # 6. In Dashboard trạng thái thời gian thực ra màn hình
        self._print_dashboard(now_str, flow_records, device_records, link_records, kpi_record)


def main():
    collector = ComprehensiveManagementPlane(RYU_REST_URL)
    print("\n" + "=" * 80)
    print("[*] TẦNG QUẢN TRỊ & TELEMETRY TOÀN DIỆN (COMPREHENSIVE MANAGEMENT PLANE - v3)")
    print(f"    - Cổng Ryu REST API : {RYU_REST_URL}")
    print(f"    - Chu kỳ Polling    : {POLL_INTERVAL_SEC} giây")
    print(f"    - 1. Dataset AI     : {collector.flow_csv} (10 Features + Hop-by-Hop + Locality)")
    print(f"    - 2. Giám sát Node  : {collector.device_csv} (CPU %, RAM MB, Net IO)")
    print(f"    - 3. Giám sát Link  : {collector.link_csv} (Throughput Mbps, Utilization %, Drops)")
    print(f"    - 4. Benchmark KPIs : {collector.kpi_csv} (Total Throughput, Jain's Fairness, Loss %)")
    ebpf_status = collector.ebpf_manager.active_tier if collector.ebpf_manager else "Disabled (No eBPF module)"
    print(f"    - 5. eBPF Engine    : {ebpf_status}")
    print("=" * 80 + "\n")

    try:
        while True:
            collector.collect_and_save_all()
            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        if collector.ebpf_manager:
            collector.ebpf_manager.cleanup()
        if hasattr(collector, 'docker_collector'):
            collector.docker_collector.stop()
        print("\n[+] Đã dừng tầng Management Plane và giải phóng eBPF/Docker threads an toàn.")


if __name__ == "__main__":
    main()