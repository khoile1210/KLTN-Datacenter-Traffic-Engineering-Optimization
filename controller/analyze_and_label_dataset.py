#!/usr/bin/env python3
"""
Tên file: analyze_and_label_dataset.py
Mô tả   : Script Phân tích Phân vị & Chốt Ngưỡng Ground-Truth cho Classifier (Phase 7):
          - Đọc dữ liệu luồng thực nghiệm thô (results/traffic_flow_dataset_with_paths.csv).
          - Tính toán các phân vị thực nghiệm (P50, P80, P90, P95, P99) của sbytes và Sload.
          - Hiển thị bảng khuyến nghị ngưỡng phân tách Elephant Flow dựa trên nguyên lý 80/20 (Pareto).
          - Vẽ biểu đồ phân phối học thuật (Histogram, ECDF, Scatter plot với đường ngưỡng).
          - Hỗ trợ người dùng lựa chọn ngưỡng (qua interactive prompt hoặc command-line args).
          - Gán nhãn chuẩn Ground-Truth (1: Elephant, 0: Mice).
          - Xuất file kết quả sạch: results/final_labeled_flow_dataset.csv.
          - Tự động cập nhật giá trị S_threshold_bytes vào controller/traffic_config.json.
"""

import os
import sys
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Đảm bảo UTF-8
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
if not os.path.exists(RESULTS_DIR):
    RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

DEFAULT_INPUT_CSV = os.path.join(RESULTS_DIR, "traffic_flow_dataset_with_paths.csv")
DEFAULT_OUTPUT_CSV = os.path.join(RESULTS_DIR, "final_labeled_flow_dataset.csv")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "traffic_config.json")
CHART_OUTPUT_PATH = os.path.join(RESULTS_DIR, "flow_distribution_and_threshold_analysis.png")


def generate_synthetic_telemetry_if_needed(csv_path, num_samples=3000):
    """
    Tạo dữ liệu telemetry mô phỏng nếu file CSV chưa có hoặc rỗng,
    giúp người dùng kiểm thử toàn bộ pipeline Phase 7 ngay lập tức.
    """
    print(f"[*] Đang sinh tập dữ liệu mẫu ({num_samples} flows) dựa trên Unified Sampler để kiểm thử pipeline...")
    try:
        from unified_sampler import UnifiedCdfSampler
        sampler = UnifiedCdfSampler()
    except Exception:
        from controller.unified_sampler import UnifiedCdfSampler
        sampler = UnifiedCdfSampler()

    records = []
    dummy_hosts = {}
    for r in range(1, 9):
        for h in range(1, 5):
            idx = (r - 1) * 4 + h
            dummy_hosts[f"h{r}_{h}"] = f"10.0.0.{idx}"
    dummy_hosts["inet"] = "10.0.0.100"
    internal_hosts = [h for h in dummy_hosts if h != "inet"]

    for _ in range(num_samples):
        src_h = np.random.choice(internal_hosts)
        dst_h, _ = sampler.sample_destination(src_h, dummy_hosts)
        s_raw, sbytes = sampler.sample_flow_size()
        _, dur = sampler.sample_inter_arrival()
        dur = max(float(dur), 0.05) + float(sbytes) / (20.0 * 1024 * 1024 / 8.0) # Thời gian truyền tương quan

        spkts = max(int(np.ceil(sbytes / 1460)), 1)
        dpkts = max(int(np.ceil(spkts * 0.5)), 1)
        dbytes = dpkts * 60 # Gói tin TCP ACK

        sload = sbytes / dur
        dload = dbytes / dur
        smeansz = sbytes / spkts
        dmeansz = dbytes / dpkts
        ratio = sbytes / max(dbytes, 1)

        hop_count = 3 if np.random.random() < 0.3 else 5
        path_str = f"{src_h} -> a1 -> c1 -> a2 -> {dst_h}"

        records.append({
            "timestamp": "2026-10-16 12:00:00",
            "src_ip": dummy_hosts[src_h],
            "dst_ip": dummy_hosts[dst_h],
            "src_port": int(np.random.choice(sampler.iperf_ports)),
            "dst_port": int(np.random.randint(40000, 60000)),
            "protocol": 6,
            "dur": round(dur, 4),
            "sbytes": int(sbytes),
            "dbytes": int(dbytes),
            "Spkts": int(spkts),
            "Dpkts": int(dpkts),
            "Sload": round(sload, 2),
            "Dload": round(dload, 2),
            "smeansz": round(smeansz, 2),
            "dmeansz": round(dmeansz, 2),
            "Ratio": round(ratio, 2),
            "hop_count": hop_count,
            "path": path_str,
            "label": 0
        })

    df = pd.DataFrame(records)
    df.to_csv(csv_path, index=False)
    print(f"[+] Đã tạo file dữ liệu mẫu: {csv_path} ({len(df)} dòng).")
    return df


def calculate_percentiles(series):
    """Tính toán bảng phân vị chi tiết cho 1 thuộc tính."""
    vals = series.dropna().values
    percentiles = [25, 50, 75, 80, 85, 90, 95, 98, 99]
    res = {
        "min": float(np.min(vals)),
        "max": float(np.max(vals)),
        "mean": float(np.mean(vals)),
        "std": float(np.std(vals))
    }
    for p in percentiles:
        res[f"P{p}"] = float(np.percentile(vals, p))
    return res


def plot_distribution_and_thresholds(df, sbytes_th, sload_th, output_img):
    """
    Vẽ tổ hợp 4 biểu đồ phân tích phân phối học thuật:
    1. Histogram & KDE của sbytes (thang Log10)
    2. ECDF thực nghiệm của sbytes với các vạch phân vị
    3. Histogram & KDE của Sload (thang Log10)
    4. Scatter plot (sbytes vs Sload) với ranh giới phân tách Elephant/Mice Flow.
    """
    sns.set_theme(style="whitegrid", font="sans-serif")
    fig, axes = plt.subplots(2, 2, figsize=(15, 12))

    sbytes_vals = df["sbytes"].values
    sload_vals = df["Sload"].values

    log_sbytes = np.log10(np.maximum(sbytes_vals, 1))
    log_sload = np.log10(np.maximum(sload_vals, 1))

    p80_sb = np.percentile(sbytes_vals, 80)
    p90_sb = np.percentile(sbytes_vals, 90)
    p95_sb = np.percentile(sbytes_vals, 95)

    p80_sl = np.percentile(sload_vals, 80)
    p90_sl = np.percentile(sload_vals, 90)
    p95_sl = np.percentile(sload_vals, 95)

    # 1. Histogram sbytes
    ax1 = axes[0, 0]
    sns.histplot(log_sbytes, kde=True, ax=ax1, color="#2980b9", bins=35)
    ax1.axvline(np.log10(sbytes_th), color="red", linestyle="--", linewidth=2, label=f"Ngưỡng chọn ({sbytes_th/1024:.1f} KB)")
    ax1.set_title("Phân bố Kích thước Luồng Chiều đi (sbytes)", fontsize=13, fontweight="bold")
    ax1.set_xlabel("log10(sbytes [Bytes])", fontsize=11)
    ax1.set_ylabel("Tần suất (Count)", fontsize=11)
    ax1.legend(loc="upper right")

    # 2. ECDF sbytes
    ax2 = axes[0, 1]
    sorted_sb = np.sort(sbytes_vals)
    ecdf_sb = np.arange(1, len(sorted_sb) + 1) / len(sorted_sb)
    ax2.plot(sorted_sb, ecdf_sb, color="#27ae60", linewidth=2.5, label="ECDF Thực nghiệm")
    ax2.axvline(p90_sb, color="purple", linestyle=":", label=f"P90 = {p90_sb/1024:.1f} KB")
    ax2.axvline(sbytes_th, color="red", linestyle="--", label=f"Ngưỡng = {sbytes_th/1024:.1f} KB")
    ax2.set_xscale("log")
    ax2.set_title("Hàm Phân Phối Tích Lũy (ECDF) của sbytes", fontsize=13, fontweight="bold")
    ax2.set_xlabel("sbytes [Bytes] (Thang Log)", fontsize=11)
    ax2.set_ylabel("Xác suất tích lũy F(x)", fontsize=11)
    ax2.legend(loc="lower right")

    # 3. Histogram Sload
    ax3 = axes[1, 0]
    sns.histplot(log_sload, kde=True, ax=ax3, color="#d35400", bins=35)
    ax3.axvline(np.log10(sload_th), color="red", linestyle="--", linewidth=2, label=f"Ngưỡng chọn ({sload_th/1024:.1f} KB/s)")
    ax3.set_title("Phân bố Tốc độ Truyền Chiều đi (Sload)", fontsize=13, fontweight="bold")
    ax3.set_xlabel("log10(Sload [Bytes/s])", fontsize=11)
    ax3.set_ylabel("Tần suất (Count)", fontsize=11)
    ax3.legend(loc="upper right")

    # 4. Scatter Plot: sbytes vs Sload với màu nhãn phân loại
    ax4 = axes[1, 1]
    is_ele = (df["sbytes"] >= sbytes_th) | (df["Sload"] >= sload_th)
    ax4.scatter(df.loc[~is_ele, "sbytes"], df.loc[~is_ele, "Sload"],
                c="#3498db", alpha=0.5, s=20, label=f"Mice Flow ({sum(~is_ele):,})")
    ax4.scatter(df.loc[is_ele, "sbytes"], df.loc[is_ele, "Sload"],
                c="#e74c3c", alpha=0.8, s=35, marker="^", label=f"Elephant Flow ({sum(is_ele):,})")
    ax4.axvline(sbytes_th, color="red", linestyle="--", alpha=0.7)
    ax4.axhline(sload_th, color="red", linestyle="--", alpha=0.7)
    ax4.set_xscale("log")
    ax4.set_yscale("log")
    ax4.set_title("Không gian Đặc trưng (sbytes vs Sload) & Ranh giới Phân loại", fontsize=13, fontweight="bold")
    ax4.set_xlabel("sbytes [Bytes] (Thang Log)", fontsize=11)
    ax4.set_ylabel("Sload [Bytes/s] (Thang Log)", fontsize=11)
    ax4.legend(loc="upper left")

    plt.suptitle("PHÂN TÍCH PHÂN VỊ VÀ XÁC ĐỊNH NGƯỠNG GROUND-TRUTH (DCN TELEMETRY)", fontsize=16, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_img, dpi=300)
    plt.close()
    print(f"[+] Đã xuất biểu đồ phân tích phân vị: {output_img}")


def update_traffic_config(sbytes_th, config_path=CONFIG_PATH):
    """Cập nhật giá trị S_threshold_bytes vào tệp traffic_config.json."""
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("flow_threshold", {})["S_threshold_bytes"] = int(sbytes_th)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            print(f"[+] Đã cập nhật S_threshold_bytes = {int(sbytes_th):,} Bytes ({int(sbytes_th)/1024:.1f} KB) vào {config_path}!")
        except Exception as e:
            print(f"[!] Không thể ghi đè traffic_config.json: {e}")


def main():
    parser = argparse.ArgumentParser(description="SDN DCN Data-Driven Threshold Analysis & Labeling (Phase 7)")
    parser.add_argument("--input", default=DEFAULT_INPUT_CSV, help="File telemetry đầu vào (.csv)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_CSV, help="File dataset đã gán nhãn đầu ra (.csv)")
    parser.add_argument("--sbytes-thresh", type=float, default=None, help="Ngưỡng dung lượng sbytes (Bytes). Nếu không truyền, dùng P90.")
    parser.add_argument("--sload-thresh", type=float, default=None, help="Ngưỡng tốc độ Sload (Bytes/s). Nếu không truyền, dùng P90.")
    parser.add_argument("--percentile", choices=["P80", "P90", "P95", "P99"], default="P90", help="Mốc phân vị tự động chọn nếu không chỉ định ngưỡng cụ thể (mặc định: P90)")
    parser.add_argument("--non-interactive", action="store_true", help="Chạy tự động không dừng hỏi người dùng")
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print(" GIAI ĐOẠN 7: PHÂN TÍCH PHÂN VỊ HẬU KỲ & CHỐT NGƯỠNG GROUND-TRUTH")
    print("=" * 80)

    # 1. Đọc dữ liệu
    if not os.path.exists(args.input) or os.path.getsize(args.input) < 100:
        print(f"[!] File telemetry {args.input} không tồn tại hoặc rỗng.")
        df = generate_synthetic_telemetry_if_needed(args.input)
    else:
        df = pd.read_csv(args.input)

    # Chuẩn hóa cột
    if "Sload" not in df.columns and "byte_rate" in df.columns:
        df["Sload"] = df["byte_rate"]
    if "sbytes" not in df.columns and "bytes" in df.columns:
        df["sbytes"] = df["bytes"]

    total_flows = len(df)
    print(f"[*] Tổng số bản ghi telemetry nạp vào: {total_flows:,} Bi-Flows.")

    # 2. Phân tích phân vị
    p_sb = calculate_percentiles(df["sbytes"])
    p_sl = calculate_percentiles(df["Sload"])

    print("\n" + "-" * 80)
    print(" BẢNG PHÂN TÍCH PHÂN VỊ THỰC NGHIỆM (EMPIRICAL PERCENTILE SUMMARY)")
    print("-" * 80)
    print(f"{'Chỉ Số':<12} | {'sbytes (Dung lượng chiều đi)':<30} | {'Sload (Tốc độ chiều đi)':<30}")
    print("-" * 80)
    print(f"{'Min':<12} | {p_sb['min']:>15,.0f} B ({p_sb['min']/1024:>8.2f} KB)   | {p_sl['min']:>15,.0f} B/s ({p_sl['min']/1024:>8.2f} KB/s)")
    print(f"{'P50 (Median)':<12} | {p_sb['P50']:>15,.0f} B ({p_sb['P50']/1024:>8.2f} KB)   | {p_sl['P50']:>15,.0f} B/s ({p_sl['P50']/1024:>8.2f} KB/s)")
    print(f"{'P80 (Top 20%)':<12} | {p_sb['P80']:>15,.0f} B ({p_sb['P80']/1024:>8.2f} KB)   | {p_sl['P80']:>15,.0f} B/s ({p_sl['P80']/1024:>8.2f} KB/s)")
    print(f"{'P90 (Top 10%)':<12} | {p_sb['P90']:>15,.0f} B ({p_sb['P90']/1024:>8.2f} KB)   | {p_sl['P90']:>15,.0f} B/s ({p_sl['P90']/1024:>8.2f} KB/s)")
    print(f"{'P95 (Top 5%)':<12} | {p_sb['P95']:>15,.0f} B ({p_sb['P95']/1024:>8.2f} KB)   | {p_sl['P95']:>15,.0f} B/s ({p_sl['P95']/1024:>8.2f} KB/s)")
    print(f"{'P99 (Top 1%)':<12} | {p_sb['P99']:>15,.0f} B ({p_sb['P99']/1024:>8.2f} KB)   | {p_sl['P99']:>15,.0f} B/s ({p_sl['P99']/1024:>8.2f} KB/s)")
    print(f"{'Max':<12} | {p_sb['max']:>15,.0f} B ({p_sb['max']/1024:>8.2f} KB)   | {p_sl['max']:>15,.0f} B/s ({p_sl['max']/1024:>8.2f} KB/s)")
    print("-" * 80)

    # 3. Đề xuất ngưỡng
    rec_sb = p_sb[args.percentile]
    rec_sl = p_sl[args.percentile]

    chosen_sb = args.sbytes_thresh if args.sbytes_thresh is not None else rec_sb
    chosen_sl = args.sload_thresh if args.sload_thresh is not None else rec_sl

    print(f"\n[💡] KHUYẾN NGHỊ HỌC THUẬT (Dựa trên Nguyên lý Pareto & Facebook SIGCOMM 2015):")
    print(f"    - Mốc phân vị khuyến nghị: {args.percentile} (Chiếm ~10% số luồng nhưng chiếm đa số lưu lượng)")
    print(f"    - Ngưỡng dung lượng đề xuất (sbytes) : {rec_sb:,.0f} Bytes ({rec_sb/1024:.1f} KB)")
    print(f"    - Ngưỡng tốc độ đề xuất (Sload)     : {rec_sl:,.0f} Bytes/s ({rec_sl/1024:.1f} KB/s)")

    # 4. Tương tác với người dùng (nếu có stdin tty và không bật non-interactive)
    if not args.non_interactive and sys.stdin.isatty():
        print("\n" + "=" * 80)
        print("🔔 ĐIỂM DỪNG QUYẾT ĐỊNH CỦA NGƯỜI DÙNG (USER DECISION PROMPT)")
        print("   Bạn có muốn chấp nhận ngưỡng đề xuất này không?")
        print(f"   [1] Chấp nhận mốc P90: sbytes >= {p_sb['P90']/1024:.1f} KB  hoặc  Sload >= {p_sl['P90']/1024:.1f} KB/s")
        print(f"   [2] Chấp nhận mốc P95: sbytes >= {p_sb['P95']/1024:.1f} KB  hoặc  Sload >= {p_sl['P95']/1024:.1f} KB/s")
        print(f"   [3] Chấp nhận mốc P80: sbytes >= {p_sb['P80']/1024:.1f} KB  hoặc  Sload >= {p_sl['P80']/1024:.1f} KB/s")
        print(f"   [4] Nhập ngưỡng tùy chỉnh thủ công")
        print("=" * 80)
        try:
            choice = input("Nhập lựa chọn của bạn [1/2/3/4] (Mặc định: 1): ").strip()
            if choice == "2":
                chosen_sb = p_sb["P95"]
                chosen_sl = p_sl["P95"]
            elif choice == "3":
                chosen_sb = p_sb["P80"]
                chosen_sl = p_sl["P80"]
            elif choice == "4":
                sb_inp = input(f"Nhập ngưỡng sbytes (Bytes, hiện tại: {chosen_sb:.0f}): ").strip()
                if sb_inp:
                    chosen_sb = float(sb_inp)
                sl_inp = input(f"Nhập ngưỡng Sload (Bytes/s, hiện tại: {chosen_sl:.0f}): ").strip()
                if sl_inp:
                    chosen_sl = float(sl_inp)
        except Exception:
            pass

    print(f"\n[+] ĐÃ CHỐT NGƯỠNG GROUND-TRUTH:")
    print(f"    - sbytes_threshold : {chosen_sb:,.0f} Bytes ({chosen_sb/1024:.1f} KB)")
    print(f"    - Sload_threshold  : {chosen_sl:,.0f} Bytes/s ({chosen_sl/1024:.1f} KB/s)")

    # 5. Gán nhãn Ground-Truth chuẩn
    is_elephant = (df["sbytes"] >= chosen_sb) | (df["Sload"] >= chosen_sl)
    df["label"] = is_elephant.astype(int)

    ele_count = sum(df["label"] == 1)
    mice_count = sum(df["label"] == 0)

    print("\n" + "-" * 80)
    print(" KẾT QUẢ GÁN NHÃN DATASET GROUND-TRUTH")
    print("-" * 80)
    print(f"[*] Luồng Chuột (Mice - Label 0)   : {mice_count:,} flows ({mice_count/total_flows*100:.2f}%)")
    print(f"[*] Luồng Voi (Elephant - Label 1) : {ele_count:,} flows ({ele_count/total_flows*100:.2f}%)")
    print("-" * 80)

    # 6. Xuất dataset đã gán nhãn
    df.to_csv(args.output, index=False)
    print(f"\n[V] Đã xuất tập dữ liệu gán nhãn hoàn chỉnh: {args.output}")

    # 7. Vẽ đồ thị phân tích
    plot_distribution_and_thresholds(df, chosen_sb, chosen_sl, CHART_OUTPUT_PATH)

    # 8. Cập nhật vào config
    update_traffic_config(chosen_sb, CONFIG_PATH)

    print("\n" + "=" * 80)
    print(" HOÀN TẤT GIAI ĐOẠN 7! SẴN SÀNG CHO HUẤN LUYỆN MACHINE LEARNING.")
    print("=" * 80)


if __name__ == "__main__":
    main()
