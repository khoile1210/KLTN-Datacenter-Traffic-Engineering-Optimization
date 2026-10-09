#!/usr/bin/env python3
"""
Tên file: management_plane.py
Mô tả   : Tầng Quản trị hoàn thiện cho Ryu OF1.3:
          - Bóc tách Action cả dạng Dict và String (Chuẩn OpenFlow 1.3 REST).
          - Ghép chuỗi lộ trình Hop-by-Hop đầy đủ xuyên suốt các tầng Access - Aggregation - Core.
          - Đọc chính xác dung lượng cổng mạng (Tx/Rx Bytes).
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

ELEPHANT_BYTE_RATE_THRESHOLD = 1024 * 1024       # 1 MB/s
ELEPHANT_TOTAL_BYTES_THRESHOLD = 5 * 1024 * 1024 # 5 MB

FLOW_CSV_HEADERS = [
    "timestamp", "src_ip", "dst_ip", "src_port", "dst_port", "protocol",
    "duration_sec", "packet_count", "byte_count", "byte_rate", "packet_rate",
    "avg_packet_size", "hop_count", "path", "label"
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

        self.host_switch_map = {f"10.0.0.{i}": i for i in range(1, 9)}
        self.host_switch_map["10.0.0.100"] = 33

        self.flow_cache = {}
        self.group_bucket_cache = {}

        psutil.cpu_percent(interval=None)
        self._init_csv_files()

    def _init_csv_files(self):
        if not os.path.exists(self.flow_csv):
            pd.DataFrame(columns=FLOW_CSV_HEADERS).to_csv(self.flow_csv, index=False)
            print(f"[+] Khởi tạo file Dataset luồng: {self.flow_csv}")

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
        try:
            resp = requests.get(f"{self.rest_url}/v1.0/topology/links", timeout=0.8)
            if resp.status_code == 200:
                self.topo_graph.clear()
                for link in resp.json():
                    src_dpid = int(link["src"]["dpid"], 16)
                    dst_dpid = int(link["dst"]["dpid"], 16)
                    src_port = int(link["src"]["port_no"])
                    dst_port = int(link["dst"]["port_no"])
                    self.topo_graph.add_edge(src_dpid, dst_dpid, out_port=src_port)
                    self.topo_graph.add_edge(dst_dpid, src_dpid, out_port=dst_port)
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

    def discover_active_connections(self):
        active_conns = []
        try:
            docker_ps = subprocess.check_output(
                "docker ps --format '{{.Names}}'",
                shell=True, stderr=subprocess.DEVNULL
            ).decode().strip().split("\n")
        except Exception:
            return []

        for c_name in docker_ps:
            if not c_name.startswith("mn."):
                continue
            try:
                out = subprocess.check_output(
                    f"docker exec {c_name} ss -tuna",
                    shell=True, stderr=subprocess.DEVNULL
                ).decode().strip().split("\n")

                for line in out[1:]:
                    parts = line.split()
                    if len(parts) >= 5:
                        proto = 6 if "tcp" in parts[0].lower() else 17
                        local_addr = parts[4]
                        peer_addr = parts[5] if len(parts) > 5 else ""

                        m_src = re.search(r"(10\.0\.0\.\d+):(\d+)", local_addr)
                        m_dst = re.search(r"(10\.0\.0\.\d+):(\d+)", peer_addr)

                        if m_src and m_dst:
                            s_ip = m_src.group(1)
                            s_pt = int(m_src.group(2))
                            d_ip = m_dst.group(1)
                            d_pt = int(m_dst.group(2))

                            if s_ip != d_ip:
                                active_conns.append({
                                    "src_ip": s_ip,
                                    "dst_ip": d_ip,
                                    "src_port": s_pt,
                                    "dst_port": d_pt,
                                    "protocol": proto
                                })
            except Exception:
                pass

        return active_conns

    def determine_active_out_port(self, dpid, group_id):
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

    def trace_flow_route(self, src_ip, dst_ip, switch_flows_map):
        ingress_dpid = self.host_switch_map.get(src_ip)
        egress_dpid = self.host_switch_map.get(dst_ip)

        if not ingress_dpid or not egress_dpid:
            return 0, "Unknown Route"

        if ingress_dpid == egress_dpid:
            return 1, f"{self.format_dpid_name(ingress_dpid)}(p:5)"

        current_dpid = ingress_dpid
        path_segments = []
        visited = set()

        while current_dpid != egress_dpid and len(path_segments) < 8:
            visited.add(current_dpid)
            out_port = None
            flows = switch_flows_map.get(current_dpid, [])

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

            # Fallback tính qua đồ thị LLDP nếu OVS chưa kịp phản hồi
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
            path_segments.append(f"{sw_name}(p:{out_port})")

            # Tìm Switch tiếp theo nối với out_port
            next_dpid = None
            if self.topo_graph.has_node(current_dpid):
                for neighbor in self.topo_graph.neighbors(current_dpid):
                    if neighbor not in visited:
                        edge = self.topo_graph.get_edge_data(current_dpid, neighbor)
                        if edge and edge.get("out_port") == out_port:
                            next_dpid = neighbor
                            break

            if not next_dpid:
                try:
                    sp = nx.shortest_path(self.topo_graph, source=current_dpid, target=egress_dpid)
                    if len(sp) > 1:
                        next_dpid = sp[1]
                except Exception:
                    break

            current_dpid = next_dpid

        egress_sw_name = self.format_dpid_name(egress_dpid)
        path_segments.append(f"{egress_sw_name}(p:5)")
        return len(path_segments), " -> ".join(path_segments)

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

    def collect_health_metrics(self, active_dpids):
        health_records = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Đọc CPU/RAM Host Docker
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

        # Đọc CPU/RAM/TCAM Switch OVS
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

            # Đọc TCAM
            try:
                t_resp = requests.get(f"{self.rest_url}/stats/table/{dpid}", timeout=0.8)
                if t_resp.status_code == 200:
                    for t in t_resp.json().get(str(dpid), []):
                        if t.get("table_id") == 0:
                            tcam_count = t.get("active_count", 0)
                            break
            except Exception:
                pass

            # Đọc Tx/Rx và Drop từ cổng Switch (Xử lý an toàn chuỗi LOCAL)
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
        now = time.time()
        active_dpids = self.get_active_switches()

        health_records = self.collect_health_metrics(active_dpids)
        if health_records:
            pd.DataFrame(health_records).to_csv(self.health_csv, mode="a", header=False, index=False)

        if not active_dpids:
            return

        self.update_topology_graph()
        switch_flows_map = {}
        for dpid in active_dpids:
            try:
                resp = requests.get(f"{self.rest_url}/stats/flow/{dpid}", timeout=0.8)
                if resp.status_code == 200:
                    switch_flows_map[dpid] = resp.json().get(str(dpid), [])
            except Exception:
                switch_flows_map[dpid] = []

        active_conns = self.discover_active_connections()
        flow_records = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for conn in active_conns:
            s_ip = conn["src_ip"]
            d_ip = conn["dst_ip"]
            s_port = conn["src_port"]
            d_port = conn["dst_port"]
            proto = conn["protocol"]

            ingress_dpid = self.host_switch_map.get(s_ip)
            byte_count = 0
            packet_count = 0
            duration_sec = 1.0

            if ingress_dpid and ingress_dpid in switch_flows_map:
                for f in switch_flows_map[ingress_dpid]:
                    m = f.get("match", {})
                    if m.get("ipv4_dst") == d_ip or m.get("nw_dst") == d_ip:
                        byte_count = int(f.get("byte_count", 0))
                        packet_count = int(f.get("packet_count", 0))
                        duration_sec = max(float(f.get("duration_sec", 1.0)), 0.1)
                        break

            cache_key = (s_ip, d_ip, d_port, proto)
            if cache_key in self.flow_cache:
                last_b, last_p, last_t = self.flow_cache[cache_key]
                delta_t = max(now - last_t, 1e-4)
                byte_rate = max(0.0, (byte_count - last_b) / delta_t)
                packet_rate = max(0.0, (packet_count - last_p) / delta_t)
            else:
                byte_rate = byte_count / duration_sec
                packet_rate = packet_count / duration_sec

            self.flow_cache[cache_key] = (byte_count, packet_count, now)
            avg_packet_size = (byte_count / packet_count) if packet_count > 0 else 0.0

            hop_count, path_str = self.trace_flow_route(s_ip, d_ip, switch_flows_map)

            is_elephant = 1 if (
                byte_rate > ELEPHANT_BYTE_RATE_THRESHOLD or
                byte_count > ELEPHANT_TOTAL_BYTES_THRESHOLD
            ) else 0

            flow_records.append({
                "timestamp": now_str,
                "src_ip": s_ip,
                "dst_ip": d_ip,
                "src_port": s_port,
                "dst_port": d_port,
                "protocol": proto,
                "duration_sec": round(duration_sec, 4),
                "packet_count": packet_count,
                "byte_count": byte_count,
                "byte_rate": round(byte_rate, 4),
                "packet_rate": round(packet_rate, 4),
                "avg_packet_size": round(avg_packet_size, 2),
                "hop_count": hop_count,
                "path": path_str,
                "label": is_elephant
            })

        if flow_records:
            pd.DataFrame(flow_records).to_csv(self.flow_csv, mode="a", header=False, index=False)

        print(f"[{time.strftime('%H:%M:%S')}] Đã ghi: {len(flow_records)} Flows (Path Traced) | {len(health_records)} Health Nodes.")


def main():
    collector = EnhancedManagementPlane(RYU_REST_URL, OUTPUT_FLOW_CSV, OUTPUT_HEALTH_CSV)
    print(f"[*] Management Plane đang chạy (Hop-by-Hop Paths + Tx/Rx Port Stats). Chu kỳ: {POLL_INTERVAL_SEC}s...")
    try:
        while True:
            collector.collect_and_save_all()
            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("\n[+] Đã dừng tầng Management Plane.")


if __name__ == "__main__":
    main()