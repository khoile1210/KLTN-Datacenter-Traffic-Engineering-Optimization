#!/usr/bin/env python3
"""
Tên file: unified_sampler.py
Mô tả   : Module toán học lấy mẫu ngẫu nhiên từ Hồ sơ phân phối thống nhất (Unified ECDF)
          - Đọc tham số từ controller/traffic_config.json.
          - Nghịch đảo phân phối tích lũy F^{-1}(u) trên miền Logarit.
          - Co giãn kích thước luồng liên tục (Piecewise Continuous Scaling).
          - Giãn nhịp phát (Time Dilation) dựa trên tỷ số năng lực CPU.
          - Điều hướng máy đích theo thuật toán phân phối 3 vùng Locality (Facebook Table 3).
"""

import os
import sys
import json
import random
import re

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "traffic_config.json")
DEFAULT_TOPO_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "topology_config.json")
DEFAULT_PROFILES_DIR = os.path.join(os.path.dirname(__file__), "cdf_profiles")


class UnifiedCdfSampler:
    def __init__(self, config_path=None, profiles_dir=None, topo_config_path=None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.topo_config_path = topo_config_path or DEFAULT_TOPO_CONFIG_PATH
        self.profiles_dir = profiles_dir or DEFAULT_PROFILES_DIR

        self._load_config()
        self._load_cdf_profiles()

    def _resolve_val(self, val, default_val=None):
        """Giải mã giá trị tham chiếu ref:<file>#/<path> hoặc chuyển đổi sang float."""
        if val is None:
            return default_val
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str) and val.startswith("ref:"):
            try:
                ref_part = val[4:]
                file_part, path_part = ref_part.split("#", 1)
                target_file = os.path.join(os.path.dirname(self.config_path), file_part)
                if os.path.exists(target_file):
                    with open(target_file, "r", encoding="utf-8") as tf:
                        tdata = json.load(tf)
                    keys = [k for k in path_part.split("/") if k]
                    cur = tdata
                    for k in keys:
                        cur = cur[k]
                    return float(cur)
            except Exception as e:
                print(f"[!] Lỗi giải mã tham chiếu '{val}': {e}. Dùng default: {default_val}")
        try:
            return float(val)
        except (ValueError, TypeError):
            return default_val

    def _load_config(self):
        """Nạp các tham số cấu hình mở từ traffic_config.json và giải mã tham chiếu sang topology_config.json."""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"[!] Không tìm thấy file cấu hình tại: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        # 1. Băng thông & Tỷ số scale alpha
        bw_cfg = cfg.get("bandwidth_scaling", {})
        self.c_paper = self._resolve_val(bw_cfg.get("C_paper_mbps"), default_val=10000.0)
        self.c_host = self._resolve_val(bw_cfg.get("C_host_mbps"), default_val=20.0)
        self.alpha = self.c_host / self.c_paper

        # 2. CPU & Hệ số giãn thời gian D_arrival
        cpu_cfg = cfg.get("cpu_time_dilation", {})
        self.cpu_host = self._resolve_val(cpu_cfg.get("CPU_host_cores"), default_val=1.0)
        self.cpu_paper = self._resolve_val(cpu_cfg.get("CPU_paper_cores"), default_val=16.0)
        self.d_arrival = self.cpu_paper / self.cpu_host

        # 3. Ngưỡng phân tách luồng
        th_cfg = cfg.get("flow_threshold", {})
        self.s_threshold = th_cfg.get("S_threshold_bytes", None)
        if self.s_threshold is not None:
            self.s_threshold = float(self.s_threshold)

        # 4. Tự động nhận diện cấu hình Cụm (Cluster-Aware) từ topology_config.json
        topo_path = os.path.join(os.path.dirname(self.config_path), "topology_config.json")
        self.clusters_cfg = {}
        self.is_clustered = False
        if os.path.exists(topo_path):
            try:
                with open(topo_path, "r", encoding="utf-8") as tf:
                    tdata = json.load(tf)
                    self.clusters_cfg = tdata.get("clusters", {})
                    self.is_clustered = self.clusters_cfg.get("enabled", False)
            except Exception:
                pass

        # 5. Tỷ lệ phân bổ vùng Locality (Facebook SIGCOMM 2015 Bảng 3)
        loc_cfg = cfg.get("destination_locality", {})
        if self.is_clustered and "clustered" in loc_cfg:
            c_loc = loc_cfg.get("clustered", {})
            self.r_intra_rack = float(c_loc.get("r_intra_rack", 0.129))
            self.r_intra_cluster = float(c_loc.get("r_intra_cluster", 0.575))
            self.r_intra_dc = float(c_loc.get("r_intra_dc", 0.119))
            self.r_extra_dc = float(c_loc.get("r_extra_dc", 0.177))
            tot_r = self.r_intra_rack + self.r_intra_cluster + self.r_intra_dc + self.r_extra_dc
            self.r_intra_rack /= tot_r
            self.r_intra_cluster /= tot_r
            self.r_intra_dc /= tot_r
            self.r_extra_dc /= tot_r
        else:
            f_loc = loc_cfg.get("flat", loc_cfg)
            self.r_intra_rack = float(f_loc.get("r_intra_rack", 0.072))
            self.r_extra_rack = float(f_loc.get("r_extra_rack", 0.850))
            self.r_extra_dc = float(f_loc.get("r_extra_dc", 0.078))
            tot_r = self.r_intra_rack + self.r_extra_rack + self.r_extra_dc
            self.r_intra_rack /= tot_r
            self.r_extra_rack /= tot_r
            self.r_extra_dc /= tot_r

        # 6. Quản trị đa luồng đồng thời & Giao thức Cache UDP
        conc_cfg = cfg.get("concurrency", {})
        self.max_workers = int(self._resolve_val(conc_cfg.get("max_workers"), default_val=32))
        self.min_burst_ratio = float(conc_cfg.get("min_burst_ratio", 0.25))
        self.max_burst_ratio = float(conc_cfg.get("max_burst_ratio", 1.0))
        self.udp_ratio = float(cfg.get("cache_protocol", {}).get("udp_ratio", 0.184))

        # 7. Cấu hình mạng
        net_cfg = cfg.get("network_runtime", {})
        self.iperf_ports = net_cfg.get("iperf_ports", [5201, 5202, 5203, 5204])
        self.min_sleep_sec = float(net_cfg.get("min_sleep_sec", 0.01))

    def _load_cdf_profiles(self):
        """Nạp 3 file CSV hồ sơ phân phối thống nhất và chuẩn bị mảng nội suy nhanh."""
        fs_path = os.path.join(self.profiles_dir, "cdf_flow_size_unified.csv")
        ia_path = os.path.join(self.profiles_dir, "cdf_inter_arrival_unified.csv")
        fd_path = os.path.join(self.profiles_dir, "cdf_flow_duration_unified.csv")

        for p in [fs_path, ia_path, fd_path]:
            if not os.path.exists(p):
                raise FileNotFoundError(f"[!] Thiếu file hồ sơ phân phối ECDF: {p}. Hãy chạy controller/supply/blend_cdfs.py trước!")

        self.df_flow_size = pd.read_csv(fs_path)
        self.df_inter_arrival = pd.read_csv(ia_path)
        self.df_duration = pd.read_csv(fd_path)

        # Mảng cho nội suy nhanh (u_grid, log_values)
        self.u_fs = self.df_flow_size["cdf"].values
        self.log_v_fs = np.log10(np.maximum(self.df_flow_size["value"].values, 1.0))

        self.u_ia = self.df_inter_arrival["cdf"].values
        self.log_v_ia = np.log10(np.maximum(self.df_inter_arrival["value"].values, 1e-9))

        self.u_fd = self.df_duration["cdf"].values
        self.log_v_fd = np.log10(np.maximum(self.df_duration["value"].values, 1e-6))

    def scale_flow_size(self, s_paper):
        """Co giãn phi tuyến kích thước luồng theo mô hình Piecewise Continuous Scaling."""
        if self.s_threshold is not None and self.s_threshold > 0:
            if s_paper <= self.s_threshold:
                s_scaled = s_paper
            else:
                s_scaled = self.s_threshold + (s_paper - self.s_threshold) * self.alpha
        else:
            s_scaled = s_paper
        return max(int(round(s_scaled)), 64)

    def sample_flow_size(self):
        """
        Lấy mẫu kích thước luồng (Bytes):
        1. Nghịch đảo lấy mẫu trên log-scale: u ~ Uniform(0, 1) -> s_paper (Bytes)
        2. Co giãn phi tuyến chống nghịch đảo qua scale_flow_size()
        """
        u = random.uniform(0.001, 0.999)
        log_s = np.interp(u, self.u_fs, self.log_v_fs)
        s_paper = 10.0 ** log_s
        s_scaled = self.scale_flow_size(s_paper)
        return int(round(s_paper)), s_scaled

    def sample_inter_arrival(self):
        """
        Lấy mẫu khoảng thời gian chờ giữa 2 luồng liên tiếp (Giây):
        1. u ~ Uniform(0, 1) -> dt_paper
        2. Dãn nhịp phát: dt_scaled = dt_paper * D_arrival
        """
        u = random.uniform(0.001, 0.999)
        log_dt = np.interp(u, self.u_ia, self.log_v_ia)
        dt_paper = 10.0 ** log_dt

        dt_scaled = dt_paper * self.d_arrival
        dt_scaled = max(dt_scaled, self.min_sleep_sec)
        return dt_paper, dt_scaled

    def sample_flow_duration(self):
        """Lấy mẫu thời lượng lý thuyết (Giây) phục vụ đối soát và kiểm chứng."""
        u = random.uniform(0.001, 0.999)
        log_dur = np.interp(u, self.u_fd, self.log_v_fd)
        dur_paper = 10.0 ** log_dur
        return dur_paper

    def sample_protocol(self):
        """
        Lấy mẫu giao thức truyền dẫn:
        - 18.4% luồng thuộc phân vùng Cache (Memcached) sử dụng UDP Datagram (Bảng 3 Facebook).
        - 81.6% luồng còn lại sử dụng chuẩn kết nối TCP.
        """
        return "udp" if random.random() < self.udp_ratio else "tcp"

    def sample_destination(self, src_host_name, all_hosts_dict):
        """
        Lựa chọn máy đích theo phân phối Locality:
        - Nếu có Cụm (Cluster-Aware): Phân bổ 4 cấp theo Bảng 3 bài báo Facebook:
          + 12.9% Intra-Rack (cùng rack ToR)
          + 57.5% Intra-Cluster (khác rack, cùng Cụm CSW)
          + 11.9% Intra-DC (khác Cụm, xuyên Fat Cat Core)
          + 17.7% Extra-DC (Internet inet host)
        - Nếu không có Cụm (Flat Mesh fallback):
          + 7.2% Intra-Rack
          + 85.0% Extra-Rack
          + 7.8% Extra-DC
        """
        internal_hosts = [h for h in all_hosts_dict.keys() if h != "inet"]
        inet_host = "inet" if "inet" in all_hosts_dict else None

        def get_rack_num(h_name):
            if "_" in h_name:
                try:
                    return int(h_name.split("_")[0].replace("h", ""))
                except Exception:
                    return 1
            try:
                n = int(re.sub(r"\D", "", h_name))
                return (n - 1) // 4 + 1
            except Exception:
                return 1

        def get_cluster_name(r_num):
            if not self.is_clustered:
                return "default"
            for cl_key in ["cluster_1", "cluster_2"]:
                cl_info = self.clusters_cfg.get(cl_key, {})
                racks = cl_info.get("racks", [])
                access_switches = cl_info.get("access_switches", [])
                if r_num in racks or f"a{r_num}" in access_switches:
                    return cl_key
            return "cluster_1" if r_num <= 4 else "cluster_2"

        src_rack = get_rack_num(src_host_name)
        src_cluster = get_cluster_name(src_rack)

        intra_rack_cand = []
        intra_cluster_cand = []
        intra_dc_cand = []

        for h in internal_hosts:
            if h == src_host_name:
                continue
            h_rack = get_rack_num(h)
            h_cluster = get_cluster_name(h_rack)
            if h_rack == src_rack:
                intra_rack_cand.append(h)
            elif h_cluster == src_cluster:
                intra_cluster_cand.append(h)
            else:
                intra_dc_cand.append(h)

        other_internal = [h for h in internal_hosts if h != src_host_name]
        u = random.random()

        if self.is_clustered:
            # === PHÂN BỔ 4 CẤP ĐỘ CLUSTER-AWARE ===
            th_intra_rack = self.r_intra_rack
            th_intra_cluster = th_intra_rack + self.r_intra_cluster
            th_intra_dc = th_intra_cluster + self.r_intra_dc

            if u <= th_intra_rack:
                dst = random.choice(intra_rack_cand) if intra_rack_cand else (random.choice(other_internal) if other_internal else src_host_name)
                zone = "Intra-Rack"
            elif u <= th_intra_cluster:
                dst = random.choice(intra_cluster_cand) if intra_cluster_cand else (random.choice(intra_dc_cand) if intra_dc_cand else (random.choice(other_internal) if other_internal else src_host_name))
                zone = "Intra-Cluster"
            elif u <= th_intra_dc or not inet_host:
                dst = random.choice(intra_dc_cand) if intra_dc_cand else (random.choice(other_internal) if other_internal else src_host_name)
                zone = "Intra-DC"
            else:
                dst = inet_host
                zone = "Extra-DC"
        else:
            # === PHÂN BỔ 3 CẤP ĐỘ FALLBACK FLAT MESH ===
            extra_rack_cand = [h for h in internal_hosts if h != src_host_name and get_rack_num(h) != src_rack]
            th_intra = self.r_intra_rack
            th_extra = th_intra + self.r_extra_rack

            if u <= th_intra:
                dst = random.choice(intra_rack_cand) if intra_rack_cand else (random.choice(other_internal) if other_internal else src_host_name)
                zone = "Intra-Rack"
            elif u <= th_extra or not inet_host:
                dst = random.choice(extra_rack_cand) if extra_rack_cand else (random.choice(other_internal) if other_internal else src_host_name)
                zone = "Extra-Rack"
            else:
                dst = inet_host
                zone = "Extra-DC"

        return dst, zone


if __name__ == "__main__":
    print("[*] Kiểm thử độc lập module UnifiedCdfSampler (Kiến trúc 4 Hosts/Rack)...")
    sampler = UnifiedCdfSampler()

    print(f" [+] Cấu hình: C_host={sampler.c_host} Mbps | C_paper={sampler.c_paper} Mbps | alpha={sampler.alpha:.5f}")
    print(f" [+] Dãn nhịp phát: CPU_host={sampler.cpu_host} | CPU_paper={sampler.cpu_paper} | D_arrival={sampler.d_arrival:.2f}x")
    if sampler.is_clustered:
        print(f" [+] Phân bổ Locality (4 cấp Cụm): Intra-Rack={sampler.r_intra_rack*100:.1f}%, Intra-Cluster={sampler.r_intra_cluster*100:.1f}%, Intra-DC={sampler.r_intra_dc*100:.1f}%, Internet={sampler.r_extra_dc*100:.1f}%\n")
    else:
        print(f" [+] Phân bổ Locality (3 cấp Phẳng): Intra-Rack={sampler.r_intra_rack*100:.1f}%, Extra-Rack={sampler.r_extra_rack*100:.1f}%, Internet={sampler.r_extra_dc*100:.1f}%\n")

    # Mô phỏng 8 Racks x 4 Hosts = 32 Hosts nội bộ + 1 node Internet
    dummy_hosts = {}
    for r in range(1, 9):
        for h in range(1, 5):
            idx = (r - 1) * 4 + h
            dummy_hosts[f"h{r}_{h}"] = {"ip": f"10.0.0.{idx}"}
    dummy_hosts["inet"] = {"ip": "10.0.0.100"}

    print(f"[*] Khởi tạo mock 32 Hosts ({len(dummy_hosts)} nodes tổng cộng). Lấy mẫu ngẫu nhiên 10 luồng:")
    sample_srcs = ["h1_1", "h1_2", "h2_1", "h3_4", "h8_2"]
    for i in range(1, 11):
        src = random.choice(sample_srcs)
        s_raw, s_scaled = sampler.sample_flow_size()
        dt_raw, dt_scaled = sampler.sample_inter_arrival()
        dst, zone = sampler.sample_destination(src, dummy_hosts)
        port = random.choice(sampler.iperf_ports)

        print(f"  #{i:02d}: [{zone:<10}] {src} -> {dst} | Size: {s_raw:,.0f} B (scaled: {s_scaled:,.0f} B) | Wait: {dt_scaled*1000:.2f} ms | Port: {port}")

    print("\n[V] Kiểm thử thành công! Module đã sẵn sàng tích hợp vào traffic_generator.py.")
