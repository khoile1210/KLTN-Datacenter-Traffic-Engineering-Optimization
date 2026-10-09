#!/usr/bin/env python3
"""
Tên file: analyze_csv_result.py
Mô tả   : Phân tích toàn diện thực nghiệm DCN Spine-Leaf:
          1. Phân loại luồng mạng: Đánh giá bộ 10 Features (dur, sbytes, dbytes, Sload, Ratio, smeansz...), tỷ lệ Voi/Chuột.
          2. Đánh giá Lộ trình TOÀN BỘ ĐƯỜNG ĐI (Full End-to-End Hop-by-Hop): Core, Aggregation, Access.
          3. Phân bố độ dài chặng (hop count).
          4. Sức khỏe tài nguyên Switch: Chiếm dụng TCAM Flow Table entries.
          5. Sức khỏe tài nguyên Host: CPU (%) và RAM (MB) của Docker container.
          6. Sức khỏe Data Plane: Thông lượng truyền/nhận và tỷ lệ Packet Loss/Drop.
Xuất ra : Các số liệu tóm tắt trên Terminal + 6 biểu đồ độ phân giải cao (.png) trong results/.
"""

import os
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Thiết lập phong cách đồ họa học thuật
sns.set_theme(style="whitegrid", font="sans-serif")
plt.rcParams.update({
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "figure.titlesize": 14
})

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)
FLOW_CSV = os.path.join(RESULTS_DIR, "traffic_flow_dataset_with_paths.csv")
HEALTH_CSV = os.path.join(RESULTS_DIR, "system_and_network_health.csv")


def print_section(title):
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def analyze_flow_dataset(flow_file):
    if not os.path.exists(flow_file):
        print(f"[!] Không tìm thấy file {flow_file}")
        return

    print_section("1. PHÂN TÍCH DATASET TELEMETRY LUỒNG MẠNG (10 FEATURES + FULL PATH)")
    df = pd.read_csv(flow_file)

    # Chuẩn hóa trường tốc độ: hỗ trợ cả Sload (mới) và byte_rate (cũ)
    rate_col = "Sload" if "Sload" in df.columns else "byte_rate"
    pkt_col = "Spkts" if "Spkts" in df.columns else "packet_count"
    meansz_col = "smeansz" if "smeansz" in df.columns else "avg_packet_size"

    df = df.dropna(subset=[rate_col, "label"])
    df["label"] = df["label"].astype(int)

    total_records = len(df)
    mice_df = df[df["label"] == 0]
    elephant_df = df[df["label"] == 1]

    mice_count = len(mice_df)
    elephant_count = len(elephant_df)

    print(f"[*] Tổng số mẫu Bi-Flow thu thập được : {total_records:,}")
    print(f"[*] Luồng Chuột (Mice - Label 0)      : {mice_count:,} ({mice_count/total_records*100:.2f}%)")
    print(f"[*] Luồng Voi (Elephant - Label 1)    : {elephant_count:,} ({elephant_count/total_records*100:.2f}%)")

    # Thống kê phân bố băng thông chiều đi (Sload)
    print(f"\n[+] Tốc độ truyền chiều đi ({rate_col}):")
    print(f"    - Luồng Chuột TB   : {mice_df[rate_col].mean() / 1024:.2f} KB/s (Max: {mice_df[rate_col].max() / 1024:.2f} KB/s)")
    print(f"    - Luồng Voi TB     : {elephant_df[rate_col].mean() / (1024*1024):.2f} MB/s (Max: {elephant_df[rate_col].max() / (1024*1024):.2f} MB/s)")

    # Thống kê kích thước gói tin (smeansz)
    if meansz_col in df.columns:
        print(f"\n[+] Kích thước gói tin trung bình chiều đi ({meansz_col}):")
        print(f"    - Luồng Chuột      : {mice_df[meansz_col].mean():.2f} Bytes")
        print(f"    - Luồng Voi        : {elephant_df[meansz_col].mean():.2f} Bytes (Tiệm cận MTU)")

    # Thống kê Tỷ lệ chênh lệch hai chiều (Ratio = sbytes / dbytes)
    if "Ratio" in df.columns:
        print("\n[+] Tỉ lệ chênh lệch dung lượng hai chiều (Ratio = sbytes / dbytes):")
        print(f"    - Luồng Chuột TB   : {mice_df['Ratio'].mean():.2f} (Cân bằng hai chiều)")
        print(f"    - Luồng Voi TB     : {elephant_df['Ratio'].mean():.2f} (Độ bất đối xứng rất lớn - chỉ có ACK về)")

    # --------------------------------------------------------------------------
    # BIỂU ĐỒ 1: PHÂN BỐ TỐC ĐỘ TRUYỀN (BOXPLOT LOG-SCALE)
    # --------------------------------------------------------------------------
    plt.figure(figsize=(7, 5))
    ax = sns.boxplot(
        x="label", y=rate_col, data=df,
        palette=["#3498db", "#e74c3c"],
        showmeans=True,
        meanprops={"marker": "o", "markerfacecolor": "yellow", "markeredgecolor": "black"}
    )
    plt.yscale("log")
    plt.xticks([0, 1], ["Luồng Chuột (Mice)\n[Label 0]", "Luồng Voi (Elephant)\n[Label 1]"])
    plt.ylabel(f"Tốc độ truyền ({rate_col} - Bytes/s - Thang Log)")
    plt.title("Phân bố Tốc độ Truyền giữa Luồng Voi và Luồng Chuột")
    plt.tight_layout()
    chart1_path = os.path.join(RESULTS_DIR, "chart1_byte_rate_distribution.png")
    plt.savefig(chart1_path, dpi=300)
    print(f"\n[+] Đã xuất biểu đồ: {chart1_path}")

    # --------------------------------------------------------------------------
    # BIỂU ĐỒ 2: ĐÁNH GIÁ LỘ TRÌNH ĐA TẦNG (CORE, AGGREGATION, ACCESS)
    # --------------------------------------------------------------------------
    # Bóc tách sự xuất hiện của các switch trong chuỗi path chi tiết
    sw_counts = {}
    for sw in ["c1", "c2", "ag1", "ag2", "ag3", "ag4"]:
        sw_counts[sw] = 0

    for p in df["path"].dropna():
        for sw in sw_counts.keys():
            if sw in p:
                sw_counts[sw] += 1

    total_routed = sum(sw_counts.values())
    print("\n[+] Phân bổ lưu lượng qua các Switch Tầng Core & Aggregation:")
    for sw, cnt in sw_counts.items():
        pct = (cnt / total_routed * 100) if total_routed > 0 else 0
        tier = "Core" if sw.startswith("c") else "Aggregation"
        print(f"    - Switch {sw:<5} ({tier:<11}): {cnt:,} luồng ({pct:.2f}%)")

    plt.figure(figsize=(9, 5))
    colors = ["#e67e22" if sw.startswith("c") else "#2ecc71" for sw in sw_counts.keys()]
    bars = plt.bar(sw_counts.keys(), sw_counts.values(), color=colors, edgecolor="black", alpha=0.85)
    plt.ylabel("Số lượng luồng định tuyến qua")
    plt.xlabel("Switch Phân Tầng (Cam: Core Switch | Xanh: Aggregation Switch)")
    plt.title("Phân Bổ Lộ Trình Luồng Qua Các Switch Tầng Core và Aggregation")
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2.0, yval + (total_routed * 0.01), f"{yval:,}", ha='center', va='bottom')
    plt.tight_layout()
    chart2_path = os.path.join(RESULTS_DIR, "chart2_ecmp_load_balance.png")
    plt.savefig(chart2_path, dpi=300)
    print(f"[+] Đã xuất biểu đồ: {chart2_path}")

    # --------------------------------------------------------------------------
    # BIỂU ĐỒ 3: PHÂN BỐ ĐỘ DÀI CHẶNG (HOP COUNT DISTRIBUTION)
    # --------------------------------------------------------------------------
    plt.figure(figsize=(7, 5))
    sns.countplot(x="hop_count", data=df, palette="Blues_d", edgecolor="black")
    plt.xlabel("Số lượng chặng Switch (Hop Count)")
    plt.ylabel("Số lượng luồng ghi nhận")
    plt.title("Phân bố Số lượng Chặng mạng (Hop Count) của các Luồng")
    plt.tight_layout()
    chart3_path = os.path.join(RESULTS_DIR, "chart3_hop_count_distribution.png")
    plt.savefig(chart3_path, dpi=300)
    print(f"[+] Đã xuất biểu đồ: {chart3_path}")


def analyze_health_dataset(health_file):
    if not os.path.exists(health_file):
        print(f"[!] Không tìm thấy file {health_file}")
        return

    print_section("2. PHÂN TÍCH SỨC KHỎE HẠ TẦNG PHẦN CỨNG & DATA PLANE")
    df = pd.read_csv(health_file)

    # 2.1. ĐÁNH GIÁ SWITCH: TCAM & DATA PLANE
    sw_df = df[df["node_type"] == "Switch (OVS)"].copy()
    if not sw_df.empty:
        sw_df["tcam_entries"] = pd.to_numeric(sw_df["tcam_entries"], errors="coerce")
        sw_df["total_tx_bytes"] = pd.to_numeric(sw_df["total_tx_bytes"], errors="coerce")
        sw_df["total_rx_bytes"] = pd.to_numeric(sw_df["total_rx_bytes"], errors="coerce")
        sw_df["total_tx_dropped"] = pd.to_numeric(sw_df["total_tx_dropped"], errors="coerce")
        sw_df["total_errors"] = pd.to_numeric(sw_df["total_errors"], errors="coerce")

        max_tcam = sw_df.groupby("node_name")["tcam_entries"].max()
        max_tx = sw_df.groupby("node_name")["total_tx_bytes"].max() / (1024 * 1024)

        print("[+] Dung lượng bộ nhớ Flow Table / TCAM trên các Switch (Entries):")
        print(f"    - Trung bình: {max_tcam.mean():.1f} entries")
        print(f"    - Cao nhất  : {max_tcam.max()} entries (Ngưỡng an toàn < 500)")
        print(f"    - Thấp nhất : {max_tcam.min()} entries")

        print("\n[+] Thống kê chất lượng truyền tải Data Plane:")
        print(f"    - Tổng gói tin bị rớt (Packet Drops) : {sw_df['total_tx_dropped'].sum()}")
        print(f"    - Tổng gói tin bị lỗi (CRC/Errors)   : {sw_df['total_errors'].sum()}")

        # BIỂU ĐỒ 4: TCAM OCCUPANCY
        plt.figure(figsize=(11, 5))
        switch_order = ["c1", "c2", "ag1", "ag2", "ag3", "ag4"] + [f"a{i}" for i in range(1, 9)]
        ordered_tcam = max_tcam.reindex(switch_order).dropna()

        bars = plt.bar(ordered_tcam.index, ordered_tcam.values, color="#8e44ad", edgecolor="black", alpha=0.85)
        plt.axhline(y=500, color="red", linestyle="--", linewidth=1.5, label="Ngưỡng an toàn TCAM (500 entries)")
        plt.ylabel("Số lượng Flow Entries")
        plt.xlabel("Danh sách Switch (Core -> Aggregation -> Access)")
        plt.title("Mức độ Chiếm dụng Bộ nhớ TCAM / Flow Table trên 14 Switch OVS")
        plt.ylim(0, max(ordered_tcam.max() * 1.5, 30))
        plt.legend(loc="upper right")
        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2.0, yval + 1, f"{int(yval)}", ha='center', va='bottom')
        plt.tight_layout()
        chart4_path = os.path.join(RESULTS_DIR, "chart4_switch_tcam_occupancy.png")
        plt.savefig(chart4_path, dpi=300)
        print(f"\n[+] Đã xuất biểu đồ: {chart4_path}")

        # BIỂU ĐỒ 5: TỔNG LƯU LƯỢNG TRUYỀN TẢI
        plt.figure(figsize=(11, 5))
        ordered_tx = max_tx.reindex(switch_order).dropna()
        plt.bar(ordered_tx.index, ordered_tx.values, color="#d35400", edgecolor="black", alpha=0.85)
        plt.ylabel("Tổng dung lượng truyền tải (MB)")
        plt.xlabel("Danh sách Switch")
        plt.title("Tổng Lưu lượng Vận chuyển qua Cổng của các Switch (Data Plane Throughput)")
        plt.tight_layout()
        chart5_path = os.path.join(RESULTS_DIR, "chart5_switch_traffic_volume.png")
        plt.savefig(chart5_path, dpi=300)
        print(f"[+] Đã xuất biểu đồ: {chart5_path}")

    # 2.2. ĐÁNH GIÁ HOST DOCKER
    host_df = df[df["node_type"] == "Host (Container)"].copy()
    if not host_df.empty:
        host_df["cpu_usage_pct"] = pd.to_numeric(host_df["cpu_usage_pct"], errors="coerce")
        host_df["ram_used_mb"] = pd.to_numeric(host_df["ram_used_mb"], errors="coerce")

        avg_cpu = host_df.groupby("node_name")["cpu_usage_pct"].mean()
        max_cpu = host_df.groupby("node_name")["cpu_usage_pct"].max()
        max_ram = host_df.groupby("node_name")["ram_used_mb"].max()

        print("\n[+] Sức khỏe phần cứng Docker Host Containers:")
        print(f"    - CPU Trung bình toàn mạng : {avg_cpu.mean():.2f}%")
        print(f"    - RAM Dùng cao nhất        : {max_ram.max():.2f} MB")

        fig, ax1 = plt.subplots(figsize=(10, 5))
        hosts_order = [f"h{i}" for i in range(1, 9)] + ["inet"]
        ordered_ram = max_ram.reindex(hosts_order).dropna()
        ordered_cpu = avg_cpu.reindex(hosts_order).dropna()

        x = np.arange(len(ordered_ram))
        width = 0.35

        rects1 = ax1.bar(x - width/2, ordered_ram.values, width, label="RAM tối đa (MB)", color="#16a085", edgecolor="black")
        ax1.set_ylabel("RAM sử dụng (MB)", color="#16a085")
        ax1.set_xlabel("Docker Host Containers")
        ax1.set_ylim(0, max(ordered_ram.max() * 1.5, 20))

        ax2 = ax1.twinx()
        rects2 = ax2.bar(x + width/2, ordered_cpu.values, width, label="CPU trung bình (%)", color="#f39c12", edgecolor="black")
        ax2.set_ylabel("CPU trung bình (%)", color="#f39c12")
        ax2.set_ylim(0, max(ordered_cpu.max() * 1.5, 20))

        plt.xticks(x, ordered_ram.index)
        plt.title("Mức độ Chiếm dụng Tài nguyên (RAM & CPU) của các Docker Container")
        plt.tight_layout()
        chart6_path = os.path.join(RESULTS_DIR, "chart6_host_resource_usage.png")
        plt.savefig(chart6_path, dpi=300)
        print(f"[+] Đã xuất biểu đồ: {chart6_path}")


def main():
    analyze_flow_dataset(FLOW_CSV)
    analyze_health_dataset(HEALTH_CSV)
    print_section("HOÀN TẤT QUÁ TRÌNH PHÂN TÍCH!")
    print(f"[*] Toàn bộ biểu đồ chất lượng cao đã được lưu vào thư mục '{RESULTS_DIR}/'.")


if __name__ == "__main__":
    main()