#!/usr/bin/env python3
"""
Tên file: blend_cdfs.py
Mô tả   : Hòa trộn toán học 9 file phân phối thực nghiệm từ Facebook (SIGCOMM 2015)
          thành 3 hồ sơ phân phối ECDF thống nhất (Unified Datacenter Workload)
          theo phương pháp tổ hợp lồi trên miền Logarit (Log-scale Convex Combination):
          - Trọng số chuẩn hóa từ Table 3:
              w_hadoop = 0.428 (42.8%)
              w_frontend = 0.388 (38.8%)
              w_cache = 0.184 (18.4%)
          - Xuất ra 3 file CSV hồ sơ tại: controller/cdf_profiles/
          - Vẽ đồ thị trực quan hóa quá trình hòa trộn.
"""

import os
import sys
import tempfile

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

mpl_temp = os.path.join(tempfile.gettempdir(), "mpl_cache")
os.makedirs(mpl_temp, exist_ok=True)
os.environ["MPLCONFIGDIR"] = mpl_temp

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_BASE = os.path.join(SCRIPT_DIR, "raw_digitized")
if not os.path.exists(RAW_BASE):
    RAW_BASE = os.path.join("controller", "supply", "raw_digitized")

PROFILES_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "cdf_profiles"))
RESULTS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "results", "digitization_verification"))

os.makedirs(PROFILES_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# Trọng số chuẩn hóa đại diện từ Table 3 Facebook (tổng = 1.0)
W_HADOOP = 0.428
W_FRONTEND = 0.388
W_CACHE = 0.184
NUM_POINTS = 1000


def blend_single_metric(hadoop_csv, frontend_csv, cache_csv, out_csv, is_log_val=True, output_scale=1.0):
    """
    Hòa trộn 3 phân phối thành 1 phân phối thống nhất trên lưới phân vị u in [0.001, 0.999].
    Áp dụng output_scale để chuyển đổi sang đơn vị chuẩn hệ thống (Bytes cho size, Giây cho time).
    """
    df_h = pd.read_csv(hadoop_csv)
    df_f = pd.read_csv(frontend_csv)
    df_c = pd.read_csv(cache_csv)

    # Lưới phân vị chuẩn
    u_grid = np.linspace(0.001, 0.999, NUM_POINTS)

    # Hàm nghịch đảo F^{-1}(u) cho từng dịch vụ:
    # Với is_log_val=True, nội suy trên không gian log10 để bảo toàn bản chất heavy-tail
    def get_inverse(df):
        vals = df["value"].values
        cdfs = df["cdf"].values
        # Đảm bảo tăng ngặt cdfs
        u_cdfs, u_idx = np.unique(cdfs, return_index=True)
        u_vals = vals[u_idx]

        if is_log_val:
            log_v = np.log10(np.maximum(u_vals, 1e-9))
            interp_log = np.interp(u_grid, u_cdfs, log_v)
            return 10.0 ** interp_log
        else:
            return np.interp(u_grid, u_cdfs, u_vals)

    v_h = get_inverse(df_h)
    v_f = get_inverse(df_f)
    v_c = get_inverse(df_c)

    # Tổ hợp lồi có trọng số:
    # s_unified(u) = 10^( w_h * log10(s_h) + w_f * log10(s_f) + w_c * log10(s_c) )
    if is_log_val:
        log_unified = (
            W_HADOOP * np.log10(np.maximum(v_h, 1e-9)) +
            W_FRONTEND * np.log10(np.maximum(v_f, 1e-9)) +
            W_CACHE * np.log10(np.maximum(v_c, 1e-9))
        )
        val_unified = 10.0 ** log_unified
    else:
        val_unified = W_HADOOP * v_h + W_FRONTEND * v_f + W_CACHE * v_c

    # Đảm bảo tăng ngặt đơn điệu
    val_unified = np.sort(val_unified)

    # Chuyển đổi sang đơn vị runtime (Bytes, Giây)
    val_output = val_unified * output_scale

    df_unified = pd.DataFrame({
        "value": np.round(val_output, 6),
        "cdf": np.round(u_grid, 4)
    })
    df_unified.to_csv(out_csv, index=False)

    return df_h, df_f, df_c, df_unified


def blend_all():
    print("=" * 80)
    print("[*] HÒA TRỘN PHÂN PHỐI ECDF THỐNG NHẤT (UNIFIED DATACENTER WORKLOAD)")
    print(f"    - Trọng số chuẩn hóa: Hadoop={W_HADOOP*100:.1f}%, Frontend={W_FRONTEND*100:.1f}%, Cache={W_CACHE*100:.1f}%")
    print("=" * 80 + "\n")

    # 1. Flow Size Unified (Input KB -> Output Bytes)
    print("[+] 1. Hòa trộn Flow Size ECDF (Từ Kilobytes -> Bytes)...")
    h_fs = os.path.join(RAW_BASE, "flow_size", "raw_flow_size_hadoop.csv")
    f_fs = os.path.join(RAW_BASE, "flow_size", "raw_flow_size_frontend.csv")
    c_fs = os.path.join(RAW_BASE, "flow_size", "raw_flow_size_cache.csv")
    out_fs = os.path.join(PROFILES_DIR, "cdf_flow_size_unified.csv")
    h_df_fs, f_df_fs, c_df_fs, u_df_fs = blend_single_metric(h_fs, f_fs, c_fs, out_fs, is_log_val=True, output_scale=1024.0)
    p50_fs = u_df_fs.iloc[len(u_df_fs)//2]["value"]
    p90_fs = u_df_fs.iloc[int(len(u_df_fs)*0.9)]["value"]
    print(f"    -> Đã xuất: {out_fs}")
    print(f"       Dải Bytes: [{u_df_fs['value'].min():,.0f} B -> {u_df_fs['value'].max():,.0f} B ({u_df_fs['value'].max()/(1024*1024):.2f} MB)] | P50 = {p50_fs:,.0f} B | P90 = {p90_fs:,.0f} B")

    # 2. Flow Inter-Arrival Time Unified (Input usec -> Output Seconds)
    print("\n[+] 2. Hòa trộn Flow Inter-Arrival Time ECDF (Từ usec -> Giây)...")
    h_ia = os.path.join(RAW_BASE, "inter_arrival", "raw_inter_arrival_hadoop.csv")
    f_ia = os.path.join(RAW_BASE, "inter_arrival", "raw_inter_arrival_frontend.csv")
    c_ia = os.path.join(RAW_BASE, "inter_arrival", "raw_inter_arrival_cache.csv")
    out_ia = os.path.join(PROFILES_DIR, "cdf_inter_arrival_unified.csv")
    h_df_ia, f_df_ia, c_df_ia, u_df_ia = blend_single_metric(h_ia, f_ia, c_ia, out_ia, is_log_val=True, output_scale=1e-6)
    p50_ia = u_df_ia.iloc[len(u_df_ia)//2]["value"]
    p90_ia = u_df_ia.iloc[int(len(u_df_ia)*0.9)]["value"]
    print(f"    -> Đã xuất: {out_ia}")
    print(f"       Dải Khoảng Cách: [{u_df_ia['value'].min()*1e6:.1f} us -> {u_df_ia['value'].max():.3f}s] | P50 = {p50_ia*1e6:.1f} us | P90 = {p90_ia*1e3:.2f} ms")

    # 3. Flow Duration Unified (Input ms -> Output Seconds)
    print("\n[+] 3. Hòa trộn Flow Duration ECDF (Từ ms -> Giây)...")
    h_fd = os.path.join(RAW_BASE, "flow_duration", "raw_flow_duration_hadoop.csv")
    f_fd = os.path.join(RAW_BASE, "flow_duration", "raw_flow_duration_frontend.csv")
    c_fd = os.path.join(RAW_BASE, "flow_duration", "raw_flow_duration_cache.csv")
    out_fd = os.path.join(PROFILES_DIR, "cdf_flow_duration_unified.csv")
    h_df_fd, f_df_fd, c_df_fd, u_df_fd = blend_single_metric(h_fd, f_fd, c_fd, out_fd, is_log_val=True, output_scale=1e-3)
    p50_fd = u_df_fd.iloc[len(u_df_fd)//2]["value"]
    p90_fd = u_df_fd.iloc[int(len(u_df_fd)*0.9)]["value"]
    print(f"    -> Đã xuất: {out_fd}")
    print(f"       Dải Thời Lượng: [{u_df_fd['value'].min():.4f}s -> {u_df_fd['value'].max():.1f}s] | P50 = {p50_fd:.4f}s | P90 = {p90_fd:.2f}s")

    # 4. Xuất biểu đồ trực quan hóa chuẩn đơn vị bài báo
    plot_blended_cdfs(
        (h_df_fs, f_df_fs, c_df_fs, u_df_fs),
        (h_df_ia, f_df_ia, c_df_ia, u_df_ia),
        (h_df_fd, f_df_fd, c_df_fd, u_df_fd)
    )

    print("\n" + "=" * 80)
    print(f"[V] HOÀN TẤT XUẤT SẮC CẢ 3 HỒ SƠ PHÂN PHỐI THỐNG NHẤT TẠI: {PROFILES_DIR}")
    print("=" * 80)


def plot_blended_cdfs(fs_tuple, ia_tuple, fd_tuple):
    plt.figure(figsize=(16, 5))

    # 1. Flow Size (Kilobytes)
    plt.subplot(1, 3, 1)
    h_df, f_df, c_df, u_df = fs_tuple
    plt.plot(h_df["value"], h_df["cdf"], "--", color="#27ae60", alpha=0.8, label="Hadoop (42.8%)")
    plt.plot(f_df["value"], f_df["cdf"], "--", color="#2980b9", alpha=0.8, label="Frontend (38.8%)")
    plt.plot(c_df["value"], c_df["cdf"], "--", color="#e67e22", alpha=0.8, label="Cache (18.4%)")
    plt.plot(u_df["value"] / 1024.0, u_df["cdf"], "-", color="black", linewidth=2.5, label="UNIFIED ECDF")
    plt.xscale("log")
    plt.xlim(0.01, 1e6)
    plt.ylim(-0.02, 1.02)
    plt.xlabel("Flow Size (Kilobytes)", fontsize=11, fontweight="bold")
    plt.ylabel("CDF", fontsize=11, fontweight="bold")
    plt.title("Unified Flow Size ECDF", fontsize=12, fontweight="bold")
    plt.grid(True, which="both", linestyle=":", alpha=0.6)
    plt.legend(loc="lower right")

    # 2. Inter-Arrival Time (SYN Interarrival usec)
    plt.subplot(1, 3, 2)
    h_df, f_df, c_df, u_df = ia_tuple
    plt.plot(h_df["value"], h_df["cdf"], "--", color="#27ae60", alpha=0.8, label="Hadoop (42.8%)")
    plt.plot(f_df["value"], f_df["cdf"], "--", color="#2980b9", alpha=0.8, label="Web Server (38.8%)")
    plt.plot(c_df["value"], c_df["cdf"], "--", color="#e67e22", alpha=0.8, label="Cache (18.4%)")
    plt.plot(u_df["value"] * 1e6, u_df["cdf"], "-", color="black", linewidth=2.5, label="UNIFIED ECDF")
    plt.xscale("log")
    plt.xlim(10, 1e6)
    plt.ylim(-0.02, 1.02)
    plt.xlabel("SYN Interarrival (usec)", fontsize=11, fontweight="bold")
    plt.ylabel("CDF", fontsize=11, fontweight="bold")
    plt.title("Unified Inter-Arrival ECDF", fontsize=12, fontweight="bold")
    plt.grid(True, which="both", linestyle=":", alpha=0.6)
    plt.legend(loc="lower right")

    # 3. Flow Duration (Milliseconds)
    plt.subplot(1, 3, 3)
    h_df, f_df, c_df, u_df = fd_tuple
    plt.plot(h_df["value"], h_df["cdf"], "--", color="#27ae60", alpha=0.8, label="Hadoop (42.8%)")
    plt.plot(f_df["value"], f_df["cdf"], "--", color="#2980b9", alpha=0.8, label="Frontend (38.8%)")
    plt.plot(c_df["value"], c_df["cdf"], "--", color="#e67e22", alpha=0.8, label="Cache (18.4%)")
    plt.plot(u_df["value"] * 1000.0, u_df["cdf"], "-", color="black", linewidth=2.5, label="UNIFIED ECDF")
    plt.xscale("log")
    plt.xlim(1.0, 1e6)
    plt.ylim(-0.02, 1.02)
    plt.xlabel("Duration (Milliseconds)", fontsize=11, fontweight="bold")
    plt.ylabel("CDF", fontsize=11, fontweight="bold")
    plt.title("Unified Flow Duration ECDF", fontsize=12, fontweight="bold")
    plt.grid(True, which="both", linestyle=":", alpha=0.6)
    plt.legend(loc="lower right")

    plt.tight_layout()
    chart_path = os.path.join(RESULTS_DIR, "blended_unified_cdfs.png")
    plt.savefig(chart_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"\n[+] Đã lưu biểu đồ đối soát hòa trộn chuẩn đơn vị bài báo: {chart_path}")


if __name__ == "__main__":
    blend_all()


if __name__ == "__main__":
    blend_all()
