#!/usr/bin/env python3
"""
Tên file: management_plane.py
Mô tả   : Tầng Quản trị (Management Plane) hoàn thiện cho Ryu OF1.3:
          - Thu thập và chuẩn hóa bộ 10 FEATURES phục vụ huấn luyện Flow Classification:
            + Nhóm 1 (Trực tiếp từ OVS): dur, sbytes, dbytes, Spkts, Dpkts
            + Nhóm 2 (Phái sinh có bảo vệ chia 0): Sload, Dload, smeansz, dmeansz, Ratio
          - Lần vết TOÀN BỘ ĐƯỜNG ĐI CỤ THỂ NHẤT (Full End-to-End Hop-by-Hop):
            Hiển thị rõ từ Host nguồn -> Switch Ingress [in->out] -> Aggregation [in->out] -> Core [in->out] -> Egress [in->out] -> Host đích.
          - Ghép cặp Luồng đối xứng (Bidirectional Flow Pairing) từ OpenFlow Flow Stats.
          - Thu thập các chỉ số sức khỏe Switch và Container không gây nghẽn chu kỳ Polling.
"""

import os
import time
import subprocess
import re
import requests
import pandas as pd
import networkx as nx
import psutil
from datetime import datetime

RYU_REST_URL = "http://127.0.0.1:8080"
RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

OUTPUT_FLOW_CSV = os.path.join(RESULTS_DIR, "traffic_flow_dataset_with_paths.csv")
OUTPUT_HEALTH_CSV = os.path.join(RESULTS_DIR, "system_and_network_health.csv")
POLL_INTERVAL_SEC = 1.0

# Ngưỡng phân loại Ground Truth cho luồng Voi (Elephant Flow)
ELEPHANT_BYTE_RATE_THRESHOLD = 1024 * 1024       # 1 MB/s (Sload > 1 MB/s)
ELEPHANT_TOTAL_BYTES_THRESHOLD = 5 * 1024 * 1024 # 5 MB (sbytes > 5 MB)

# Bộ 10 Features chuẩn theo yêu cầu + Metadata & Routing Path
FLOW_CSV_HEADERS = [
    "timestamp", "src_ip", "dst_ip", "src_port", "dst_port", "protocol",
    "dur", "sbytes", "dbytes", "Spkts", "Dpkts",
    "Sload", "Dload", "smeansz", "dmeansz", "Ratio",
    "hop_count", "path", "label"
]

HEALTH_CSV_HEADERS = [
    "timestamp", "node_name", "node_type", "cpu_usage_pct", "ram_used_mb",
    "tcam_entries", "total_tx_bytes", "total_rx_bytes", "total_tx_dropped",
    "total_rx_dropped", "total_errors"
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


class EnhancedManagementPlane:
    def __init__(self, rest_url, flow_csv, health_csv):
        self.rest_url = rest_url
        self.flow_csv = flow_csv
        self.health_csv = health_csv
        self.topo_graph = nx.DiGraph()

        # Ánh xạ tĩnh ban đầu giữa IP Host và Switch gắn trực tiếp (được cập nhật động nếu cần)
        self.host_switch_map = {f"10.0.0.{i}": i for i in range(1, 9)}
        self.host_switch_map["10.0.0.100"] = 33

        self.flow_cache = {}
        self.group_bucket_cache = {}

        psutil.cpu_percent(interval=None)
        self._init_csv_files()

    def _init_csv_files(self):
        if not os.path.exists(self.flow_csv):
            pd.DataFrame(columns=FLOW_CSV_HEADERS).to_csv(self.flow_csv, index=False)
            print(f"[+] Khởi tạo file Dataset luồng (10 Features): {self.flow_csv}")

        if not os.path.exists(self.health_csv):
            pd.DataFrame(columns=HEALTH_CSV_HEADERS).to_csv(self.health_csv, index=False)
            print(f"[+] Khởi tạo file Sức khỏe hệ thống: {self.health_csv}")

    def get_active_switches(self):
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
                    # Lưu rõ cổng xuất và cổng nhập giữa 2 switch kề nhau
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

    def format_dpid_name(self, dpid):
        if 1 <= dpid <= 8:
            return f"a{dpid}"
        elif 17 <= dpid <= 20:
            return f"ag{dpid - 16}"
        elif dpid in [33, 0x21]:
            return "c1"
        elif dpid in [34, 0x22]:
            return "c2"
        return f"s{dpid}"

    def ip_to_host_name(self, ip):
        m = re.search(r"10\.0\.0\.(\d+)", ip)
        if m:
            host_idx = int(m.group(1))
            if host_idx == 100:
                return "inet"
            return f"h{host_idx}"
        return ip

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

        # Trường hợp 1: Hai host cắm trên cùng một Switch
        if ingress_dpid == egress_dpid:
            sw_name = self.format_dpid_name(ingress_dpid)
            in_p = 5
            out_p = 1 if dst_ip == "10.0.0.100" else 5
            return 1, f"{src_name} -> {sw_name}[in:{in_p}->out:{out_p}] -> {dst_name}"

        # Trường hợp 2: Lộ trình đa chặng qua Spine-Leaf
        current_dpid = ingress_dpid
        hop_segments = []
        visited = set()
        prev_out_port = None
        current_in_port = 5  # Host cắm ở Port 5 trên Access Switch (hoặc Port 1 trên Core nếu inet)
        if src_ip == "10.0.0.100":
            current_in_port = 1

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
        final_out_port = 1 if dst_ip == "10.0.0.100" else 5
        hop_segments.append(f"{egress_sw_name}[in:{current_in_port}->out:{final_out_port}]")

        full_path_str = f"{src_name} -> " + " -> ".join(hop_segments) + f" -> {dst_name}"
        return len(hop_segments), full_path_str

    def extract_biflow_stats(self, switch_flows_map):
        """
        Ghép cặp Luồng đối xứng (Bidirectional Flow Pairing) từ các Flow Rules 5-tuple
        được Controller cài đặt trên các Access Switch.
        """
        raw_flows = {}

        # Quét các flow rules trên tất cả các switch
        for dpid, flows in switch_flows_map.items():
            for f in flows:
                m = f.get("match", {})
                s_ip = m.get("ipv4_src") or m.get("nw_src")
                d_ip = m.get("ipv4_dst") or m.get("nw_dst")
                proto = m.get("ip_proto", 0)
                s_pt = m.get("tcp_src") or m.get("udp_src", 0)
                d_pt = m.get("tcp_dst") or m.get("udp_dst", 0)

                if s_ip and d_ip and s_ip.startswith("10.0.0.") and d_ip.startswith("10.0.0."):
                    dur = float(f.get("duration_sec", 0)) + float(f.get("duration_nsec", 0)) / 1e9
                    pkts = int(f.get("packet_count", 0))
                    bytes_ = int(f.get("byte_count", 0))

                    direction_key = (s_ip, d_ip, s_pt, d_pt, proto)
                    # Lưu flow có byte lớn nhất (tránh trùng lặp qua nhiều switch)
                    if direction_key not in raw_flows or bytes_ > raw_flows[direction_key]["bytes"]:
                        raw_flows[direction_key] = {
                            "dur": dur,
                            "pkts": pkts,
                            "bytes": bytes_,
                            "dpid": dpid
                        }

        # Ghép cặp hai chiều Forward (s -> d) và Backward (d -> s)
        processed_pairs = set()
        paired_records = []

        for (s_ip, d_ip, s_pt, d_pt, proto), fwd_info in raw_flows.items():
            bwd_key = (d_ip, s_ip, d_pt, s_pt, proto)
            pair_id = tuple(sorted([(s_ip, s_pt), (d_ip, d_pt)])) + (proto,)

            if pair_id in processed_pairs:
                continue
            processed_pairs.add(pair_id)

            bwd_info = raw_flows.get(bwd_key, {"dur": 0.0, "pkts": 0, "bytes": 0})

            # Xác định chiều đi (Forward: bên phát nhiều byte hơn hoặc bên gửi yêu cầu)
            if fwd_info["bytes"] >= bwd_info["bytes"]:
                src_ip, dst_ip = s_ip, d_ip
                src_port, dst_port = s_pt, d_pt
                dur = max(fwd_info["dur"], bwd_info["dur"], 0.001)
                sbytes = fwd_info["bytes"]
                dbytes = bwd_info["bytes"]
                Spkts = fwd_info["pkts"]
                Dpkts = bwd_info["pkts"]
            else:
                src_ip, dst_ip = d_ip, s_ip
                src_port, dst_port = d_pt, s_pt
                dur = max(bwd_info["dur"], fwd_info["dur"], 0.001)
                sbytes = bwd_info["bytes"]
                dbytes = fwd_info["bytes"]
                Spkts = bwd_info["pkts"]
                Dpkts = fwd_info["pkts"]

            paired_records.append({
                "src_ip": src_ip,
                "dst_ip": dst_ip,
                "src_port": src_port,
                "dst_port": dst_port,
                "protocol": proto,
                "dur": dur,
                "sbytes": sbytes,
                "dbytes": dbytes,
                "Spkts": Spkts,
                "Dpkts": Dpkts
            })

        return paired_records

    def collect_health_metrics(self, active_dpids):
        """Thu thập chỉ số CPU, RAM, TCAM và lỗi cổng mạng của toàn bộ Nút."""
        health_records = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Đọc CPU/RAM Docker Container
        try:
            cmd = "docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}'"
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode()

            for line in output.strip().split("\n"):
                if not line or not line.startswith("mn."):
                    continue
                parts = line.split(",")
                if len(parts) >= 3:
                    c_name = parts[0].replace("mn.", "")
                    cpu_raw = parts[1].replace("%", "").strip()
                    cpu_pct = float(cpu_raw) if cpu_raw else 0.0

                    mem_part = parts[2].split("/")[0].strip()
                    mem_mb = 0.0
                    if "GiB" in mem_part or "GB" in mem_part:
                        mem_mb = float(mem_part.replace("GiB", "").replace("GB", "").strip()) * 1024
                    elif "MiB" in mem_part or "MB" in mem_part:
                        mem_mb = float(mem_part.replace("MiB", "").replace("MB", "").strip())
                    elif "KiB" in mem_part or "kB" in mem_part:
                        mem_mb = float(mem_part.replace("KiB", "").replace("kB", "").strip()) / 1024

                    health_records.append({
                        "timestamp": now_str,
                        "node_name": c_name,
                        "node_type": "Host (Container)",
                        "cpu_usage_pct": round(cpu_pct, 2),
                        "ram_used_mb": round(mem_mb, 2),
                        "tcam_entries": "-",
                        "total_tx_bytes": "-",
                        "total_rx_bytes": "-",
                        "total_tx_dropped": 0,
                        "total_rx_dropped": 0,
                        "total_errors": 0
                    })
        except Exception:
            pass

        # 2. Đọc CPU/RAM/TCAM Switch OVS
        ovs_cpu = 0.0
        ovs_ram_mb = 0.0
        for proc in psutil.process_iter(['name', 'cpu_percent', 'memory_info']):
            try:
                if 'ovs-vswitchd' in proc.info['name']:
                    ovs_cpu += proc.cpu_percent(interval=None)
                    ovs_ram_mb += proc.info['memory_info'].rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        num_switches = max(len(active_dpids), 1)
        per_switch_cpu = round(ovs_cpu / num_switches, 2)
        per_switch_ram = round(ovs_ram_mb / num_switches, 2)

        for dpid in active_dpids:
            tcam_count = 0
            tx_bytes = 0
            rx_bytes = 0
            tx_dropped = 0
            rx_dropped = 0
            errors = 0

            # Đọc TCAM entries
            try:
                t_resp = requests.get(f"{self.rest_url}/stats/table/{dpid}", timeout=0.8)
                if t_resp.status_code == 200:
                    for t in t_resp.json().get(str(dpid), []):
                        if t.get("table_id") == 0:
                            tcam_count = t.get("active_count", 0)
                            break
            except Exception:
                pass

            # Đọc Tx/Rx và Drop từ cổng Switch
            try:
                p_resp = requests.get(f"{self.rest_url}/stats/port/{dpid}", timeout=0.8)
                if p_resp.status_code == 200:
                    for ps in p_resp.json().get(str(dpid), []):
                        p_raw = ps.get("port_no")
                        if str(p_raw).upper() == "LOCAL":
                            continue
                        try:
                            if int(p_raw) >= 0xFFFFFF00:
                                continue
                        except (ValueError, TypeError):
                            continue

                        tx_bytes += int(ps.get("tx_bytes", 0))
                        rx_bytes += int(ps.get("rx_bytes", 0))
                        tx_dropped += int(ps.get("tx_dropped", 0))
                        rx_dropped += int(ps.get("rx_dropped", 0))
                        errors += int(ps.get("tx_errors", 0)) + int(ps.get("rx_errors", 0))
            except Exception:
                pass

            health_records.append({
                "timestamp": now_str,
                "node_name": self.format_dpid_name(dpid),
                "node_type": "Switch (OVS)",
                "cpu_usage_pct": per_switch_cpu,
                "ram_used_mb": per_switch_ram,
                "tcam_entries": tcam_count,
                "total_tx_bytes": tx_bytes,
                "total_rx_bytes": rx_bytes,
                "total_tx_dropped": tx_dropped,
                "total_rx_dropped": rx_dropped,
                "total_errors": errors
            })

        return health_records

    def collect_and_save_all(self):
        active_dpids = self.get_active_switches()

        # Thu thập sức khỏe hệ thống
        health_records = self.collect_health_metrics(active_dpids)
        if health_records:
            pd.DataFrame(health_records).to_csv(self.health_csv, mode="a", header=False, index=False)

        if not active_dpids:
            return

        self.update_topology_graph()

        # Đọc Flow Table của tất cả các Switch
        switch_flows_map = {}
        for dpid in active_dpids:
            try:
                resp = requests.get(f"{self.rest_url}/stats/flow/{dpid}", timeout=0.8)
                if resp.status_code == 200:
                    switch_flows_map[dpid] = resp.json().get(str(dpid), [])
            except Exception:
                switch_flows_map[dpid] = []

        # Ghép cặp luồng 5-tuple đối xứng
        paired_flows = self.extract_biflow_stats(switch_flows_map)
        flow_records = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

            # ==================================================================
            # TÍNH TOÁN BỘ ĐẶC TRƯNG PHÁI SINH (NHÓM 2) CÓ BẢO VỆ CHIA CHO 0
            # ==================================================================
            eps = 1e-6
            Sload = sbytes / max(dur, eps)
            Dload = dbytes / max(dur, eps)
            smeansz = sbytes / max(Spkts, 1)
            dmeansz = dbytes / max(Dpkts, 1)
            Ratio = sbytes / (dbytes + eps)

            # Dò vết toàn bộ lộ trình cụ thể Hop-by-Hop
            hop_count, path_str = self.trace_full_path(src_ip, dst_ip, switch_flows_map)

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
                "label": is_elephant
            })

        if flow_records:
            pd.DataFrame(flow_records).to_csv(self.flow_csv, mode="a", header=False, index=False)

        print(f"[{time.strftime('%H:%M:%S')}] Đã ghi: {len(flow_records)} Bi-Flows (10 Features + Full Path) | {len(health_records)} Health Nodes.")


def main():
    collector = EnhancedManagementPlane(RYU_REST_URL, OUTPUT_FLOW_CSV, OUTPUT_HEALTH_CSV)
    print(f"[*] Management Plane v2 đang chạy (10 Features + Full Hop-by-Hop Paths). Chu kỳ: {POLL_INTERVAL_SEC}s...")
    try:
        while True:
            collector.collect_and_save_all()
            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("\n[+] Đã dừng tầng Management Plane.")


if __name__ == "__main__":
    main()