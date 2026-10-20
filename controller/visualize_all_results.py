#!/usr/bin/env python3
"""
Tên file: visualize_all_results.py
Mô tả   : Sinh toàn bộ hệ thống biểu đồ trực quan hóa dữ liệu thực nghiệm chuẩn học thuật:
          1. 01_traffic_flows_characteristics.png (Flow Size ECDF, Duration, Locality, Hop count)
          2. 02_device_resource_utilization.png (Two-Phase Resource Attribution: RAM, TCAM, CPU switches & hosts)
          3. 03_link_utilization_telemetry.png (Link Utilization by Tier, Top Links, Link TX throughput)
          4. 04_network_evaluation_kpis.png (Active flows time series, Throughput, Jain's fairness index)
          5. 05_microburst_ground_truth.png (Microburst duration, bytes, rate distribution)
          Tất cả biểu đồ và báo cáo tóm tắt được lưu vào thư mục timestamp: results/<YYYY-MM-DD_HH-MM>/
"""

import os
import sys
import json
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Thiết lập UTF-8
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import argparse

parser = argparse.ArgumentParser(description="SDN DCN Academic Results Visualizer")
parser.add_argument("-o", "--output-dir", default=None, help="Thư mục lưu biểu đồ kết quả")
cli_args, _ = parser.parse_known_args()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(BASE_DIR, "results")

if cli_args.output_dir:
    TARGET_DIR = cli_args.output_dir
else:
    subdirs = [
        os.path.join(RESULTS_DIR, d) for d in os.listdir(RESULTS_DIR)
        if os.path.isdir(os.path.join(RESULTS_DIR, d)) and not d.startswith('.')
        and d not in ('Excel', 'digitization_verification')
    ]
    if subdirs:
        subdirs.sort(key=os.path.getmtime, reverse=True)
        TARGET_DIR = subdirs[0]
    else:
        NOW_STR = datetime.now().strftime("%Y-%m-%d_%H-%M")
        TARGET_DIR = os.path.join(RESULTS_DIR, NOW_STR)

os.makedirs(TARGET_DIR, exist_ok=True)

# Cấu hình Seaborn & Matplotlib
sns.set_theme(style="whitegrid", font="sans-serif")
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
plt.rcParams['axes.edgecolor'] = '#bdc3c7'
plt.rcParams['axes.linewidth'] = 0.8


def resolve_csv_path(filename):
    """Tìm file CSV trong TARGET_DIR, RESULTS_DIR hoặc trong thư mục snapshot mới nhất."""
    target_path = os.path.join(TARGET_DIR, filename)
    if os.path.exists(target_path):
        return target_path
    direct_path = os.path.join(RESULTS_DIR, filename)
    if os.path.exists(direct_path):
        return direct_path
    # Tìm trong thư mục con mới nhất
    subdirs = [
        os.path.join(RESULTS_DIR, d) for d in os.listdir(RESULTS_DIR)
        if os.path.isdir(os.path.join(RESULTS_DIR, d)) and not d.startswith('.')
        and d not in ('Excel', 'digitization_verification')
    ]
    if subdirs:
        subdirs.sort(key=os.path.getmtime, reverse=True)
        for s in subdirs:
            candidate = os.path.join(s, filename)
            if os.path.exists(candidate):
                return candidate
    return direct_path


def plot_traffic_flows():
    # Ưu tiên completed_flows_dataset.csv, fallback sang traffic_flow_dataset_with_paths.csv
    csv_path = resolve_csv_path("completed_flows_dataset.csv")
    if not os.path.exists(csv_path):
        csv_path = resolve_csv_path("traffic_flow_dataset_with_paths.csv")
    if not os.path.exists(csv_path):
        print(f"[!] Bỏ qua traffic flows vì không thấy: {csv_path}")
        return

    print("[*] Đang vẽ 01_traffic_flows_characteristics.png...")
    df = pd.read_csv(csv_path)
    total_records = len(df)

    # Thích ứng tự động: nếu có cờ is_completed thì lọc trực tiếp, ngược lại fallback group-by 5-tuple
    if "is_completed" in df.columns and (df["is_completed"] == 1).any():
        df_completed = df[df["is_completed"] == 1].copy()
    else:
        flow_key_cols = ['src_ip', 'dst_ip', 'src_port', 'dst_port', 'protocol']
        if all(col in df.columns for col in flow_key_cols):
            df_completed = df.sort_values(['sbytes', 'dur']).groupby(flow_key_cols, as_index=False).last()
        else:
            df_completed = df
    num_completed = len(df_completed)

    # Tìm tệp viễn trắc thô (traffic_flow_dataset_with_paths.csv) để vẽ đường nét đứt mờ đối sánh (nếu có)
    trace_path = resolve_csv_path("traffic_flow_dataset_with_paths.csv")
    if os.path.exists(trace_path) and os.path.abspath(trace_path) != os.path.abspath(csv_path):
        try:
            df_trace = pd.read_csv(trace_path)
            sbytes_all = df_trace["sbytes"].dropna().values
            total_records = len(df_trace)
        except Exception:
            sbytes_all = df["sbytes"].dropna().values
    else:
        sbytes_all = df["sbytes"].dropna().values

    fig, axes = plt.subplots(2, 2, figsize=(14, 11))

    # 1. ECDF Flow Size (Dual-View: Completed Flows vs All Telemetry Records)
    ax1 = axes[0, 0]
    sbytes_comp = df_completed["sbytes"].dropna().values
    sort_sbytes_comp = np.sort(sbytes_comp)
    ecdf_comp = np.arange(1, len(sort_sbytes_comp) + 1) / len(sort_sbytes_comp)
    ax1.plot(sort_sbytes_comp, ecdf_comp, color="#1f77b4", linewidth=2.4, label=f"Luồng hoàn tất (N={len(sort_sbytes_comp):,})")

    if total_records > num_completed:
        sort_sbytes_all = np.sort(sbytes_all)
        ecdf_all = np.arange(1, len(sort_sbytes_all) + 1) / len(sort_sbytes_all)
        ax1.plot(sort_sbytes_all, ecdf_all, color="#95a5a6", linestyle="-.", linewidth=1.5, alpha=0.6,
                 label=f"Tất cả bản ghi viễn trắc (N={len(sort_sbytes_all):,})")

    # Kiểm tra cấu hình ngưỡng: Chỉ vẽ đường dóng khi người dùng đã chủ động chốt ngưỡng cụ thể
    cfg_path = os.path.join(os.path.dirname(__file__), "traffic_config.json")
    s_th = None
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as cf:
                s_th = json.load(cf).get("flow_threshold", {}).get("S_threshold_bytes")
        except Exception:
            pass
    if s_th and s_th > 0:
        ax1.axvline(x=s_th, color="#d62728", linestyle="--", linewidth=1.8, label=f"Ngưỡng Elephant ({s_th/1024:.1f} KB)")

    ax1.set_xscale("log")
    ax1.set_title("Hàm phân phối tích lũy (ECDF) Kích thước luồng", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Flow Size - sbytes (Bytes) [Thang Log]", fontsize=10)
    ax1.set_ylabel("F(x) - Tỷ lệ tích lũy", fontsize=10)
    ax1.legend(loc="lower right", frameon=True)
    ax1.grid(True, which="both", ls=":", alpha=0.6)

    # 2. Duration Distribution (Completed Flows True FCT)
    ax2 = axes[0, 1]
    dur = df_completed["dur"].dropna()
    sns.histplot(dur, bins=40, kde=True, ax=ax2, color="#2ca02c", edgecolor="#1b661b")
    med_dur = dur.median()
    p90_dur = dur.quantile(0.9)
    ax2.axvline(x=med_dur, color="#e67e22", linestyle="--", linewidth=1.8, label=f"Median P50 = {med_dur:.3f}s")
    ax2.axvline(x=p90_dur, color="#9b59b6", linestyle=":", linewidth=1.8, label=f"P90 = {p90_dur:.3f}s")
    ax2.set_title(f"Phân phối Thời lượng luồng hoàn tất (True FCT, N={num_completed:,})", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Duration / FCT (Giây)", fontsize=10)
    ax2.set_ylabel("Số lượng luồng", fontsize=10)
    ax2.legend(loc="upper right", frameon=True)
    ax2.grid(True, ls=":", alpha=0.6)

    # 3. Locality Breakdown (30k Luồng Hoàn tất)
    ax3 = axes[1, 0]
    locality_counts = df_completed["locality"].value_counts()
    colors = ["#2ecc71", "#3498db", "#e67e22", "#9b59b6", "#e74c3c"]
    wedges, texts, autotexts = ax3.pie(
        locality_counts.values,
        labels=locality_counts.index,
        autopct="%1.2f%%",
        startangle=140,
        colors=colors[:len(locality_counts)],
        explode=[0.04] * len(locality_counts),
        textprops=dict(fontweight="bold")
    )
    for at in autotexts:
        at.set_color("white")
    ax3.set_title(f"Phân bố Không gian Luồng (N={num_completed:,} Luồng Hoàn tất)", fontsize=11, fontweight="bold")

    # 4. Hop Count Distribution (30k Luồng Hoàn tất)
    ax4 = axes[1, 1]
    hop_counts = df_completed["hop_count"].value_counts().sort_index()
    x_labels = [f"{int(h)} Hop" if h == 1 else f"{int(h)} Hops" for h in hop_counts.index]
    bar_colors = sns.color_palette("Blues_r", len(hop_counts))
    bars = ax4.bar(x_labels, hop_counts.values, color=bar_colors, width=0.45, edgecolor="#333")
    for bar in bars:
        h = bar.get_height()
        ax4.text(bar.get_x() + bar.get_width()/2., h + len(df_completed)*0.01, f"{h:,}\n({h/len(df_completed)*100:.1f}%)",
                 ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax4.set_ylim(0, max(hop_counts.values) * 1.15 if len(hop_counts) > 0 else 10)
    ax4.set_title(f"Phân phối Số chặng Switch (N={num_completed:,} Luồng Hoàn tất)", fontsize=11, fontweight="bold")
    ax4.set_ylabel("Số lượng luồng", fontsize=10)
    ax4.grid(True, axis="y", ls=":", alpha=0.6)

    plt.suptitle("ĐẶC TRƯNG LƯU LƯỢNG MẠNG (TRAFFIC FLOWS CHARACTERISTICS)", fontsize=14, fontweight="bold", y=0.99)
    plt.tight_layout()
    out_file = os.path.join(TARGET_DIR, "01_traffic_flows_characteristics.png")
    plt.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  [+] Đã lưu: {out_file}")


def plot_device_resources():
    csv_path = resolve_csv_path("device_resource_utilization.csv")
    if not os.path.exists(csv_path):
        print(f"[!] Bỏ qua device resources vì không thấy: {csv_path}")
        return
    
    print("[*] Đang vẽ 02_device_resource_utilization.png...")
    df = pd.read_csv(csv_path)
    for col in ['cpu_percent', 'memory_usage_mb', 'tcam_entries']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    switches = df[df['node_type'].str.contains('Switch', na=False)].copy()
    hosts = df[df['node_type'].str.contains('Host', na=False)].copy()
    
    # Định nghĩa Switch Tier
    def get_switch_tier(name):
        if name.startswith('a') and not name.startswith('ag'):
            return 'Access (a1-a8)'
        elif name.startswith('ag'):
            return 'Aggregation (ag1-ag4)'
        elif name.startswith('c'):
            return 'Core (c1-c2)'
        return 'Other'
    
    switches['tier'] = switches['node_name'].apply(get_switch_tier)
    
    topo_cfg_path = os.path.join(os.path.dirname(__file__), "topology_config.json")
    tcam_cap = 1000
    if os.path.exists(topo_cfg_path):
        try:
            with open(topo_cfg_path, "r", encoding="utf-8") as tf:
                tcam_cap = json.load(tf).get("switches", {}).get("tcam_capacity_rules", 1000)
        except Exception:
            pass

    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    
    # 1. Switch RAM by Tier
    ax1 = axes[0, 0]
    sns.boxplot(data=switches, x='tier', y='memory_usage_mb', hue='tier', legend=False, palette=['#3498db', '#f39c12', '#9b59b6'], ax=ax1)
    ax1.set_title("RAM Sử Dụng theo Tầng Switch (Two-Phase Attribution)", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Phân tầng Switch", fontsize=10)
    ax1.set_ylabel("RAM sử dụng (MB)", fontsize=10)
    ax1.grid(True, ls=":", alpha=0.6)
    
    # 2. TCAM Entries & Usage (%) by Switch
    ax2 = axes[0, 1]
    tcam_avg = switches.groupby('node_name')['tcam_entries'].mean().reset_index()
    tcam_avg['tcam_pct'] = (tcam_avg['tcam_entries'] / tcam_cap) * 100.0
    # Sắp xếp theo Access, Agg, Core
    order = [f'a{i}' for i in range(1, 9)] + [f'ag{i}' for i in range(1, 5)] + ['c1', 'c2']
    tcam_avg['order'] = tcam_avg['node_name'].map(lambda x: order.index(x) if x in order else 99)
    tcam_avg = tcam_avg.sort_values('order')
    
    bar_colors = ['#3498db']*8 + ['#f39c12']*4 + ['#9b59b6']*2
    bars = ax2.bar(tcam_avg['node_name'], tcam_avg['tcam_entries'], color=bar_colors, edgecolor="#333", width=0.6)
    for bar, pct in zip(bars, tcam_avg['tcam_pct']):
        h = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., h + 1.5, f"{int(h)}\n({pct:.1f}%)", 
                 ha="center", va="bottom", fontsize=8, fontweight="bold")
    ax2.set_ylim(0, max(tcam_avg['tcam_entries'].max() * 1.35, 60))
    ax2.set_title(f"Tài nguyên TCAM Switch & Tỷ lệ Sử dụng % (Dung lượng: {tcam_cap:,} Rules)", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Tên Switch (Xanh: Access, Cam: Aggregation, Tím: Core)", fontsize=10)
    ax2.set_ylabel("Số lượng Flow Entries (và % TCAM)", fontsize=10)
    ax2.tick_params(axis='x', rotation=45)
    ax2.grid(True, axis="y", ls=":", alpha=0.6)
    
    # 3. Switch CPU Boxplot by Tier
    ax3 = axes[1, 0]
    sns.barplot(data=switches, x='tier', y='cpu_percent', hue='tier', legend=False, palette=['#3498db', '#f39c12', '#9b59b6'], ax=ax3, errorbar=None)
    ax3.set_title("CPU Trung bình (%) theo Tầng Switch", fontsize=11, fontweight="bold")
    ax3.set_xlabel("Phân tầng Switch", fontsize=10)
    ax3.set_ylabel("CPU (%)", fontsize=10)
    ax3.grid(True, ls=":", alpha=0.6)
    
    # 4. Host Resource Profile (CPU & RAM)
    ax4 = axes[1, 1]
    host_summary = hosts.groupby('node_name')[['cpu_percent', 'memory_usage_mb']].mean()
    ax4.scatter(host_summary['memory_usage_mb'], host_summary['cpu_percent'], color='#2ecc71', s=80, edgecolors='#27ae60', alpha=0.8)
    for node, row in host_summary.iterrows():
        if row['cpu_percent'] > 45 or row['memory_usage_mb'] > 12:
            ax4.annotate(node, (row['memory_usage_mb'], row['cpu_percent']), fontsize=8, alpha=0.9)
    ax4.set_title("Tương quan CPU (%) vs RAM (MB) của 33 Host Container", fontsize=11, fontweight="bold")
    ax4.set_xlabel("RAM trung bình (MB)", fontsize=10)
    ax4.set_ylabel("CPU trung bình (%)", fontsize=10)
    ax4.grid(True, ls=":", alpha=0.6)
    
    plt.suptitle("GIÁM SÁT TÀI NGUYÊN THIẾT BỊ & SWITCH OVS (DEVICE TELEMETRY)", fontsize=14, fontweight="bold", y=0.99)
    plt.tight_layout()
    out_file = os.path.join(TARGET_DIR, "02_device_resource_utilization.png")
    plt.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  [+] Đã lưu: {out_file}")


def plot_link_utilization():
    csv_path = resolve_csv_path("link_utilization_telemetry.csv")
    if not os.path.exists(csv_path):
        print(f"[!] Bỏ qua link utilization vì không thấy: {csv_path}")
        return
        
    print("[*] Đang vẽ 03_link_utilization_telemetry.png...")
    df = pd.read_csv(csv_path)
    for col in ['tx_rate_mbps', 'utilization_pct']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    
    # 1. Utilization by Link Type (Lọc các mẫu hoạt động > 0% để thấy rõ phân bố tải thực tế, tránh bẹp hộp do mẫu rỗi)
    ax1 = axes[0]
    df_active = df[df['utilization_pct'] > 0].copy()
    if not df_active.empty:
        sns.boxplot(data=df_active, x='link_type', y='utilization_pct', hue='link_type', legend=False, palette='Set2', ax=ax1, showfliers=True)
        ax1.set_title("Phân phối Mức tải Liên kết Khi Hoạt động (Tải > 0%)", fontsize=11, fontweight="bold")
    else:
        sns.boxplot(data=df, x='link_type', y='utilization_pct', hue='link_type', legend=False, palette='Set2', ax=ax1)
        ax1.set_title("Phân phối Mức tải Liên kết (%) theo Loại Đường truyền", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Loại đường truyền", fontsize=10)
    ax1.set_ylabel("Mức tải - Utilization (%)", fontsize=10)
    ax1.grid(True, ls=":", alpha=0.6)
    
    # 2. Top 12 Highest Utilized Links
    ax2 = axes[1]
    df['link_pair'] = df['src_node'] + " -> " + df['dst_node']
    top_links = df.groupby('link_pair')['utilization_pct'].max().sort_values(ascending=False).head(12)
    bars = ax2.barh(top_links.index[::-1], top_links.values[::-1], color='#e74c3c', edgecolor='#333', height=0.65)
    for bar in bars:
        w = bar.get_width()
        ax2.text(w + 0.1, bar.get_y() + bar.get_height()/2., f"{w:.2f}%", va='center', fontsize=9, fontweight='bold')
    ax2.set_xlim(0, max(top_links.values) * 1.18)
    ax2.set_title("Top 12 Liên kết có Tải Đỉnh Cao Nhất (Peak Utilization)", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Mức tải đỉnh (%)", fontsize=10)
    ax2.grid(True, axis="x", ls=":", alpha=0.6)
    
    plt.suptitle("VIỄN TRẮC ĐƯỜNG TRUYỀN & HIỆU SUẤT LIÊN KẾT (LINK TELEMETRY)", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_file = os.path.join(TARGET_DIR, "03_link_utilization_telemetry.png")
    plt.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  [+] Đã lưu: {out_file}")


def plot_network_kpis():
    csv_path = resolve_csv_path("network_evaluation_kpis.csv")
    if not os.path.exists(csv_path):
        print(f"[!] Bỏ qua KPI vì không thấy: {csv_path}")
        return
        
    print("[*] Đang vẽ 04_network_evaluation_kpis.png...")
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    # Lấy trục thời gian tính bằng phút từ bắt đầu
    df['time_min'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds() / 60.0
    
    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    
    # 1. Active Flows
    ax1 = axes[0, 0]
    ax1.plot(df['time_min'], df['active_flows_count'], label='Tổng số luồng đồng thời', color='#3498db', linewidth=1.5)
    ax1.plot(df['time_min'], df['active_elephant_flows'], label='Luồng Elephant (>=64KB)', color='#e74c3c', linewidth=2.0)
    ax1.set_title("Số lượng Luồng Hoạt động Đồng thời theo Thời gian", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Thời gian chạy thực nghiệm (Phút)", fontsize=10)
    ax1.set_ylabel("Số lượng luồng (Flows)", fontsize=10)
    ax1.legend(loc='upper right', frameon=True)
    ax1.grid(True, ls=":", alpha=0.6)
    
    # 2. Total Throughput
    ax2 = axes[0, 1]
    ax2.plot(df['time_min'], df['total_network_throughput_mbps'], color='#27ae60', linewidth=1.8, label='Thông lượng thực tế')
    ax2.fill_between(df['time_min'], 0, df['total_network_throughput_mbps'], color='#2ecc71', alpha=0.25)
    ax2.set_title("Tổng Thông Lượng Mạng Toàn Cục (Throughput Mbps)", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Thời gian chạy thực nghiệm (Phút)", fontsize=10)
    ax2.set_ylabel("Băng thông (Mbps)", fontsize=10)
    ax2.legend(loc='upper right', frameon=True)
    ax2.grid(True, ls=":", alpha=0.6)
    
    # 3. Jain's Fairness Index
    ax3 = axes[1, 0]
    ax3.plot(df['time_min'], df['jains_fairness_index'], color='#9b59b6', linewidth=1.6, label="Chỉ số Jain's Fairness")
    ax3.axhline(y=1.0, color='#7f8c8d', linestyle='--', label='Công bằng tuyệt đối (1.0)')
    ax3.set_ylim(-0.05, 1.1)
    ax3.set_title("Chỉ Số Công Bằng Băng Thông (Jain's Fairness Index)", fontsize=11, fontweight="bold")
    ax3.set_xlabel("Thời gian chạy thực nghiệm (Phút)", fontsize=10)
    ax3.set_ylabel("Chỉ số công bằng (0.0 - 1.0)", fontsize=10)
    ax3.legend(loc='lower right', frameon=True)
    ax3.grid(True, ls=":", alpha=0.6)
    
    # 4. Mice FCT Duration over time
    ax4 = axes[1, 1]
    ax4.plot(df['time_min'], df['avg_mice_duration_sec'], color='#f39c12', linewidth=1.6, label='FCT luồng Mice TB')
    ax4.set_title("Thời Gian Hoàn Thành Luồng Mice (FCT Duration)", fontsize=11, fontweight="bold")
    ax4.set_xlabel("Thời gian chạy thực nghiệm (Phút)", fontsize=10)
    ax4.set_ylabel("Thời gian truyền (Giây)", fontsize=10)
    ax4.legend(loc='upper right', frameon=True)
    ax4.grid(True, ls=":", alpha=0.6)
    
    plt.suptitle("CHỈ SỐ HIỆU NĂNG MẠNG TOÀN CỤC (GLOBAL NETWORK KPIS)", fontsize=14, fontweight="bold", y=0.99)
    plt.tight_layout()
    out_file = os.path.join(TARGET_DIR, "04_network_evaluation_kpis.png")
    plt.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  [+] Đã lưu: {out_file}")


def plot_microbursts():
    csv_path = resolve_csv_path("microburst_client_ground_truth.csv")
    if not os.path.exists(csv_path):
        print(f"[!] Bỏ qua microburst vì không thấy: {csv_path}")
        return
        
    print("[*] Đang vẽ 05_microburst_ground_truth.png...")
    df = pd.read_csv(csv_path)
    for col in ['burst_bytes', 'duration_ms', 'rate_mbps']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    
    # 1. Burst Rate Distribution
    ax1 = axes[0]
    sns.histplot(df['rate_mbps'], bins=20, kde=True, color='#e74c3c', ax=ax1)
    ax1.axvline(df['rate_mbps'].median(), color='#c0392b', linestyle='--', label=f"Trung vị: {df['rate_mbps'].median():.1f} Mbps")
    ax1.set_title("Tốc Độ Truyền Xung Tức Thời (Mbps)", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Rate (Mbps)", fontsize=10)
    ax1.set_ylabel("Số lượng xung (Bursts)", fontsize=10)
    ax1.legend(frameon=True)
    ax1.grid(True, ls=":", alpha=0.6)
    
    # 2. Duration vs Bytes
    ax2 = axes[1]
    ax2.scatter(df['duration_ms'], df['burst_bytes'] / 1024.0, color='#3498db', s=60, edgecolors='#2980b9', alpha=0.7)
    ax2.set_title("Thời Lượng Xung (ms) vs Dung Lượng (KB)", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Duration (ms)", fontsize=10)
    ax2.set_ylabel("Dung lượng xung (KB)", fontsize=10)
    ax2.grid(True, ls=":", alpha=0.6)
    
    # 3. Source Host distribution
    ax3 = axes[2]
    src_counts = df['src_host'].value_counts().head(8)
    bars = ax3.bar(src_counts.index, src_counts.values, color='#9b59b6', edgecolor='#333', width=0.55)
    for b in bars:
        ax3.text(b.get_x() + b.get_width()/2., b.get_height() + 0.3, str(int(b.get_height())), ha='center', fontsize=9, fontweight='bold')
    ax3.set_title("Top Nguồn Phát Xung Microburst (Hosts)", fontsize=11, fontweight="bold")
    ax3.set_xlabel("Host phát", fontsize=10)
    ax3.set_ylabel("Số lần phát xung", fontsize=10)
    ax3.tick_params(axis='x', rotation=45)
    ax3.grid(True, axis="y", ls=":", alpha=0.6)
    
    plt.suptitle("ĐẶC TÍNH XUNG BÙNG NỔ (MICROBURST CLIENT GROUND TRUTH)", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_file = os.path.join(TARGET_DIR, "05_microburst_ground_truth.png")
    plt.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  [+] Đã lưu: {out_file}")


def create_summary_report():
    report_file = os.path.join(TARGET_DIR, "SUMMARY_REPORT.md")
    content = f"""# BÁO CÁO TRỰC QUAN HÓA & ĐỐI SOÁT DỮ LIỆU THỰC NGHIỆM SDN DCN
**Thời điểm tạo:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Thư mục lưu:** `{TARGET_DIR}`

---

### Danh mục Biểu đồ Trực quan hóa

1. **`01_traffic_flows_characteristics.png`**:
   - Phân phối ECDF Kích thước luồng (Flow Size) với ngưỡng Elephant 64KB.
   - Histogram thời lượng luồng (Duration / FCT).
   - Biểu đồ tròn phân bố không gian mạng 4 phân vùng chuẩn Facebook (Locality: Intra-Cluster, Extra-DC, Intra-DC, Intra-Rack).
   - Biểu đồ cột phân bố số chặng (Hop Count: 1-Hop ToR vs 3-Hops Spine-Leaf).

2. **`02_device_resource_utilization.png`**:
   - So sánh RAM giữa các phân tầng Switch OVS (Access ~34MB vs Agg ~20MB vs Core ~18MB).
   - Phân bố số lượng luật bảng TCAM trên từng Switch (Access phản ánh các luồng 5-tuple).
   - Mức tiêu thụ CPU (%) của các tầng Switch.
   - Biểu đồ phân tán tương quan CPU (%) vs RAM (MB) của 33 Host Containers.

3. **`03_link_utilization_telemetry.png`**:
   - Mức tải phần trăm liên kết theo từng phân lớp đường truyền (Access-Host, Agg-Access, Core-Agg, Core-Inet).
   - Top 12 đường truyền có mức tải đỉnh (Peak Utilization) cao nhất trong mạng.

4. **`04_network_evaluation_kpis.png`**:
   - Diễn biến theo thời gian của số lượng luồng đồng thời (Total, Mice, Elephant).
   - Tổng thông lượng mạng toàn cục (Throughput Mbps).
   - Chỉ số công bằng Jain's Fairness Index và độ lệch chuẩn tải đường truyền.
   - Thời gian hoàn thành luồng Mice (FCT Duration).

5. **`05_microburst_ground_truth.png`**:
   - Phân phối tốc độ truyền xung tức thời (đỉnh lên tới 117.2 Mbps).
   - Tương quan giữa thời lượng xung (ms) và dung lượng phát (KB).
   - Tần suất phát xung trên các Host nguồn.

6. **`chart_facebook_workload_validation.png` & `ks_test_results.txt`**:
   - Biểu đồ đối soát chồng hình (Overlay Plot) 2 đường cong thực nghiệm vs lý thuyết Facebook (ACM SIGCOMM 2015).
   - Kết quả kiểm định thống kê 2 mẫu Kolmogorov-Smirnov (KS-Test).
"""
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  [+] Đã xuất báo cáo tóm tắt: {report_file}")


def main():
    print("=" * 80)
    print(f" KHỞI TẠO TIẾN TRÌNH TRỰC QUAN HÓA TOÀN DIỆN DỮ LIỆU SDN DCN")
    print(f" Thư mục đích: {TARGET_DIR}")
    print("=" * 80)
    
    plot_traffic_flows()
    plot_device_resources()
    plot_link_utilization()
    plot_network_kpis()
    plot_microbursts()

    # Chạy kiểm định thống kê học thuật KS-Test và lưu biểu đồ vào TARGET_DIR
    kstest_script = os.path.join(os.path.dirname(__file__), "validate_workload_kstest.py")
    if os.path.exists(kstest_script):
        import subprocess
        print("[*] Đang thực thi validate_workload_kstest.py...")
        subprocess.run([sys.executable, kstest_script, "-o", TARGET_DIR])

    create_summary_report()
    
    print("\n[V] Hoàn tất toàn bộ biểu đồ trực quan hóa dữ liệu thực nghiệm!")
    print(f"[*] Đường dẫn thư mục: {TARGET_DIR}\n")
    return TARGET_DIR


if __name__ == "__main__":
    main()
