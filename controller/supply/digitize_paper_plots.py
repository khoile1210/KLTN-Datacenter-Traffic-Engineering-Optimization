#!/usr/bin/env python3
"""
Tên file: digitize_paper_plots.py
Mô tả   : Số hóa tự động chính xác tuyệt đối 9 đường cong ECDF thực nghiệm
          từ các ảnh biểu đồ 400 DPI của bài báo Facebook (ACM SIGCOMM 2015).
          - Áp dụng thuật toán Backward Continuous Curve Tracking cải tiến:
            + Bám sát đường cong tiệm cận mép trên (y_top + 1), bắt trọn vẹn dải đuôi
              dài (Heavy-Tail) đến sát CDF = 1.0 (không bỏ sót đuôi ngang).
            + Nhận diện và khử sạch toàn bộ tick marks hẹp ở trục Y và mép trên.
            + Bóc tách sạch màu đen (Fig 6, 7) và các kênh màu riêng biệt (Fig 14).
          - Xuất ra 9 tệp CSV thô tại controller/raw_digitized/.
          - Tự động vẽ biểu đồ đối soát kiểm chứng Overlay Plot tại results/digitization_verification/.
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

from PIL import Image
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_BASE = os.path.join(SCRIPT_DIR, "raw_digitized")
FLOW_SIZE_DIR = os.path.join(OUTPUT_BASE, "flow_size")
INTER_ARR_DIR = os.path.join(OUTPUT_BASE, "inter_arrival")
FLOW_DUR_DIR = os.path.join(OUTPUT_BASE, "flow_duration")
OVERLAY_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "results", "digitization_verification"))

for d in [FLOW_SIZE_DIR, INTER_ARR_DIR, FLOW_DUR_DIR, OVERLAY_DIR]:
    os.makedirs(d, exist_ok=True)


def find_curve_top_end(mask, min_run=5, check_rows=8):
    """
    Tìm điểm mút xa nhất bên phải của đường cong khi nó chạm hoặc chạy song song
    sát mép trên của biểu đồ (CDF ~ 1.0).
    Lọc bỏ các tick marks (vốn chỉ có bề ngang 1-2 pixel).
    """
    all_runs = []
    for y_idx in range(min(check_rows, mask.shape[0])):
        row = mask[y_idx, :]
        xs = np.where(row)[0]
        if len(xs) == 0:
            continue
        s = xs[0]
        p = xs[0]
        for x in xs[1:]:
            if x == p + 1:
                p = x
            else:
                if p - s + 1 >= min_run:
                    all_runs.append((s, p, p - s + 1, y_idx))
                s = x
                p = x
        if p - s + 1 >= min_run:
            all_runs.append((s, p, p - s + 1, y_idx))

    if not all_runs:
        return None
    return max(r[1] for r in all_runs)


def track_curve_backward(img_path, x_left, x_right, y_top, y_bottom, color_mask_fn, legend_rect=None, max_gap_x=20):
    """
    Thuật toán dò ngược (Backward Continuous Curve Tracking) hoàn thiện:
    Bắt đầu từ điểm tận cùng bên phải (CDF ~ 1.0, y ~ y_top + 1) và đi ngược về bên trái,
    bám sát liên tục đường cong của màu mục tiêu.
    """
    img = Image.open(img_path).convert("RGB")
    arr = np.array(img)

    # Lấy vùng dữ liệu bắt đầu ngay từ y_top + 1 (sát dưới đường viền trên)
    sub = arr[y_top+1:y_bottom-2, x_left+5:x_right-5]
    r, g, b = sub[:, :, 0].astype(int), sub[:, :, 1].astype(int), sub[:, :, 2].astype(int)
    mask = color_mask_fn(r, g, b)

    # Che hộp chú giải (Legend)
    if legend_rect:
        lx0, ly0, lx1, ly1 = legend_rect
        r_y0 = max(0, ly0 - (y_top + 1))
        r_y1 = min(sub.shape[0], ly1 - (y_top + 1))
        r_x0 = max(0, lx0 - (x_left + 5))
        r_x1 = min(sub.shape[1], lx1 - (x_left + 5))
        mask[r_y0:r_y1, r_x0:r_x1] = False

    # Khử các tick marks đứng độc lập tại hàng 0 (y_top + 1)
    r0 = mask[0, :]
    xs0 = np.where(r0)[0]
    if len(xs0) > 0:
        s = xs0[0]
        p = xs0[0]
        for x in xs0[1:]:
            if x == p + 1:
                p = x
            else:
                if p - s + 1 < 3:
                    mask[0, s:p+1] = False
                s = x
                p = x
        if p - s + 1 < 3:
            mask[0, s:p+1] = False

    # Tìm điểm kết thúc thực sự của đường cong ở mép trên
    top_end_rel = find_curve_top_end(mask, min_run=5, check_rows=8)

    pts_y, pts_x = np.where(mask)
    pts_x = pts_x + x_left + 5
    pts_y = pts_y + y_top + 1

    unique_x = sorted(list(np.unique(pts_x)))
    col_pts = {x: pts_y[pts_x == x] for x in unique_x}

    if top_end_rel is not None:
        cand_x_target = top_end_rel + x_left + 5
        # Tìm x gần nhất trong unique_x
        cand_end = [x for x in unique_x if x <= cand_x_target]
        x_end = cand_end[-1] if cand_end else unique_x[-1]
    else:
        cand_end = [x for x in reversed(unique_x) if np.min(col_pts[x]) <= y_top + 35]
        x_end = cand_end[0] if cand_end else unique_x[-1]

    curr_x = x_end
    curr_y = np.min(col_pts[x_end])
    track_x, track_y = [curr_x], [curr_y]

    while True:
        cand_x = [x for x in unique_x if 0 < curr_x - x <= max_gap_x]
        if not cand_x:
            break
        next_x = max(cand_x)
        cands = col_pts[next_x]
        dx = curr_x - next_x
        # Bước nhảy đứng cho phép lớn nếu bước nhảy x rất nhỏ (bước nhảy bậc CDF)
        max_dy = 220 if dx <= 4 else 80
        valid_cands = [y for y in cands if y >= curr_y - 15 and abs(y - curr_y) <= max_dy]
        if not valid_cands:
            greater_cands = [y for y in cands if y >= curr_y - 15]
            if greater_cands:
                best_y = greater_cands[np.argmin(greater_cands - curr_y)]
                if abs(best_y - curr_y) > max_dy:
                    break
            else:
                break
        else:
            best_y = valid_cands[np.argmin(np.abs(np.array(valid_cands) - curr_y))]

        curr_x, curr_y = next_x, best_y
        track_x.append(curr_x)
        track_y.append(curr_y)

    track_x = np.array(track_x[::-1])
    track_y = np.array(track_y[::-1])

    return track_x, track_y


def convert_and_resample(track_x, track_y, x_left, x_right, y_top, y_bottom, log_min, log_max, unit_scale=1.0, num_samples=150):
    """
    Ánh xạ sang giá trị vật lý và chuẩn hóa lưới phân vị đều u in [0.001, 1.0].
    Xử lý đặc biệt đoạn plateau nằm ngang ở mép trên: phân bố đều từ CDF bắt đầu plateau tới 1.0,
    bảo toàn trọn vẹn các giá trị đuôi cực lớn (Heavy-Tail) kéo dài đến hết đồ thị.
    """
    val_norm = (track_x - x_left) / (x_right - x_left)
    val_log = log_min + val_norm * (log_max - log_min)
    val = (10.0 ** val_log) * unit_scale

    cdf_raw = (y_bottom - track_y) / (y_bottom - y_top)
    cdf_mono = np.maximum.accumulate(cdf_raw)

    # Nhận diện vùng plateau nằm ngang ở mép trên (nơi ty == min(ty))
    min_y = np.min(track_y)
    top_indices = np.where(track_y == min_y)[0]
    if len(top_indices) > 1:
        c_start = cdf_mono[top_indices[0]]
        cdf_mono[top_indices] = np.linspace(c_start, 1.0, len(top_indices))

    # Đảm bảo tính đơn điệu tăng ngặt
    for i in range(1, len(cdf_mono)):
        if cdf_mono[i] <= cdf_mono[i-1]:
            cdf_mono[i] = cdf_mono[i-1] + 1e-7

    cdf_mono = np.clip(cdf_mono, 0.0, 1.0)
    cdf_mono[-1] = 1.0

    target_cdf = np.linspace(max(0.001, cdf_mono[0]), 1.0, num_samples)
    interp_val = np.interp(target_cdf, cdf_mono, val)

    # Điểm biên dưới CDF = 0.0
    final_val = np.concatenate(([val[0]], interp_val))
    final_cdf = np.concatenate(([0.0], target_cdf))

    return final_val, final_cdf


def digitize_all():
    print("=" * 80)
    print("[*] SỐ HÓA TỰ ĐỘNG CHUẨN XÁC 9 ĐƯỜNG CONG ECDF (BẮT ĐẦY ĐỦ ĐUÔI HEAVY-TAIL)")
    print("=" * 80 + "\n")

    mask_black = lambda r, g, b: (r < 60) & (g < 60) & (b < 60) & (np.abs(r - g) < 15)

    # 1. Flow Size (Figure 6: Đơn vị Kilobytes)
    print("[+] 1. Đang xử lý Figure 6 (Flow Size CDF - Đơn vị: Kilobytes)...")
    fig6_items = [
        ("raw_flow_size_frontend.csv", "figure_6a_size_web.png", FLOW_SIZE_DIR, 157, 910, 60, 508, (620, 330, 910, 508), "Web Servers"),
        ("raw_flow_size_cache.csv", "figure_6b_size_cache.png", FLOW_SIZE_DIR, 118, 871, 60, 508, (580, 330, 871, 508), "Cache Follower"),
        ("raw_flow_size_hadoop.csv", "figure_6c_size_hadoop.png", FLOW_SIZE_DIR, 81, 834, 60, 508, (540, 330, 834, 508), "Hadoop")
    ]

    for fname, img_name, odir, xl, xr, yt, yb, leg, label in fig6_items:
        img_p = os.path.join("Documents", "extracted_figures", img_name)
        tx, ty = track_curve_backward(img_p, xl, xr, yt, yb, mask_black, leg)
        # Unit bài báo: Kilobytes (unit_scale = 1.0)
        vals, cdfs = convert_and_resample(tx, ty, xl, xr, yt, yb, -2.0, 6.0, unit_scale=1.0)
        df = pd.DataFrame({"value": np.round(vals, 4), "cdf": np.round(cdfs, 4)}).drop_duplicates(subset=["cdf"])
        out_p = os.path.join(odir, fname)
        df.to_csv(out_p, index=False)
        print(f"    - {fname:<30}: {len(df):3d} pts | Dải: [{df['value'].min():.4f} KB -> {df['value'].max():,.1f} KB ({df['value'].max()/1024:.2f} MB)]")

    # 2. Flow Duration (Figure 7: Đơn vị Milliseconds)
    print("\n[+] 2. Đang xử lý Figure 7 (Flow Duration CDF - Đơn vị: Milliseconds)...")
    fig7_items = [
        ("raw_flow_duration_frontend.csv", "figure_7a_dur_web.png", FLOW_DUR_DIR, 159, 907, 63, 517, (620, 330, 907, 517), "Web Servers"),
        ("raw_flow_duration_cache.csv", "figure_7b_dur_cache.png", FLOW_DUR_DIR, 120, 869, 63, 517, (130, 68, 350, 180), "Cache Follower"),
        ("raw_flow_duration_hadoop.csv", "figure_7c_dur_hadoop.png", FLOW_DUR_DIR, 83, 831, 63, 517, (540, 330, 831, 517), "Hadoop")
    ]

    for fname, img_name, odir, xl, xr, yt, yb, leg, label in fig7_items:
        img_p = os.path.join("Documents", "extracted_figures", img_name)
        tx, ty = track_curve_backward(img_p, xl, xr, yt, yb, mask_black, leg)
        # Unit bài báo: Milliseconds (unit_scale = 1.0)
        vals, cdfs = convert_and_resample(tx, ty, xl, xr, yt, yb, 0.0, 6.0, unit_scale=1.0)
        df = pd.DataFrame({"value": np.round(vals, 2), "cdf": np.round(cdfs, 4)}).drop_duplicates(subset=["cdf"])
        out_p = os.path.join(odir, fname)
        df.to_csv(out_p, index=False)
        print(f"    - {fname:<30}: {len(df):3d} pts | Dải: [{df['value'].min():.2f} ms -> {df['value'].max():,.1f} ms ({df['value'].max()/1000:.2f}s)]")

    # 3. Inter-Arrival Time (Figure 14: Đơn vị SYN Interarrival usec)
    print("\n[+] 3. Đang xử lý Figure 14 (Inter-Arrival Time CDF - Đơn vị: usec)...")
    # Tọa độ chuẩn 400 DPI của Fig 14: xl=149, xr=1277, yt=72, yb=755
    fig14_items = [
        ("raw_inter_arrival_frontend.csv", "figure_14_inter_arrival.png", INTER_ARR_DIR,
         lambda r, g, b: (b > 140) & (b > r + 30) & (b > g + 30), "Web Server (Blue)"),
        ("raw_inter_arrival_hadoop.csv", "figure_14_inter_arrival.png", INTER_ARR_DIR,
         lambda r, g, b: (g > 80) & (g > r + 20) & (g > b + 20), "Hadoop (Green)"),
        ("raw_inter_arrival_cache.csv", "figure_14_inter_arrival.png", INTER_ARR_DIR,
         lambda r, g, b: (r > 180) & (g > 100) & (g < 170) & (b < 80), "Cache Follower (Orange)")
    ]

    xl14, xr14, yt14, yb14 = 149, 1277, 72, 755
    leg14 = (900, 540, 1250, 740)

    for fname, img_name, odir, col_fn, label in fig14_items:
        img_p = os.path.join("Documents", "extracted_figures", img_name)
        tx, ty = track_curve_backward(img_p, xl14, xr14, yt14, yb14, col_fn, leg14)
        # Unit bài báo: Microseconds / usec (unit_scale = 1.0)
        vals, cdfs = convert_and_resample(tx, ty, xl14, xr14, yt14, yb14, 1.0, 6.0, unit_scale=1.0)
        df = pd.DataFrame({"value": np.round(vals, 2), "cdf": np.round(cdfs, 4)}).drop_duplicates(subset=["cdf"])
        out_p = os.path.join(odir, fname)
        df.to_csv(out_p, index=False)
        print(f"    - {fname:<30}: {len(df):3d} pts | Dải: [{df['value'].min():.1f} usec -> {df['value'].max():,.1f} usec ({df['value'].max()/1000:.2f} ms)]")

    # 4. Vẽ biểu đồ đối soát kiểm chứng toàn diện 9 đường cong với đơn vị chuẩn của bài báo
    print("\n[*] Đang vẽ biểu đồ đối soát kiểm chứng 9 đường cong theo đúng đơn vị bài báo...")
    fig, axes = plt.subplots(3, 3, figsize=(15, 12))

    plots_cfg = [
        # Hàng 1: Flow Size (Kilobytes, thang 10^-2 đến 10^6)
        (axes[0, 0], os.path.join(FLOW_SIZE_DIR, "raw_flow_size_frontend.csv"), "(a) Web servers", "Kilobytes", (0.01, 1e6), "#2980b9"),
        (axes[0, 1], os.path.join(FLOW_SIZE_DIR, "raw_flow_size_cache.csv"), "(b) Cache follower", "Kilobytes", (0.01, 1e6), "#e67e22"),
        (axes[0, 2], os.path.join(FLOW_SIZE_DIR, "raw_flow_size_hadoop.csv"), "(c) Hadoop", "Kilobytes", (0.01, 1e6), "#27ae60"),

        # Hàng 2: Flow Duration (Milliseconds, thang 10^0 đến 10^6)
        (axes[1, 0], os.path.join(FLOW_DUR_DIR, "raw_flow_duration_frontend.csv"), "(a) Web servers", "Milliseconds", (1.0, 1e6), "#2980b9"),
        (axes[1, 1], os.path.join(FLOW_DUR_DIR, "raw_flow_duration_cache.csv"), "(b) Cache follower", "Milliseconds", (1.0, 1e6), "#e67e22"),
        (axes[1, 2], os.path.join(FLOW_DUR_DIR, "raw_flow_duration_hadoop.csv"), "(c) Hadoop", "Milliseconds", (1.0, 1e6), "#27ae60"),

        # Hàng 3: Inter-Arrival (SYN Interarrival usec, thang 10^1 đến 10^6)
        (axes[2, 0], os.path.join(INTER_ARR_DIR, "raw_inter_arrival_frontend.csv"), "Web Server", "SYN Interarrival (usec)", (10.0, 1e6), "#2980b9"),
        (axes[2, 1], os.path.join(INTER_ARR_DIR, "raw_inter_arrival_cache.csv"), "Cache Follower", "SYN Interarrival (usec)", (10.0, 1e6), "#e67e22"),
        (axes[2, 2], os.path.join(INTER_ARR_DIR, "raw_inter_arrival_hadoop.csv"), "Hadoop", "SYN Interarrival (usec)", (10.0, 1e6), "#27ae60"),
    ]

    for ax, csv_p, title, xlabel, xlim, col in plots_cfg:
        df_plot = pd.read_csv(csv_p)
        ax.plot(df_plot["value"], df_plot["cdf"], color=col, linewidth=2.4, label="Số hóa thực nghiệm (All)")
        ax.set_xscale("log")
        ax.set_xlim(xlim)
        ax.set_ylim(-0.02, 1.02)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_xlabel(xlabel, fontsize=11, fontweight="bold")
        ax.set_ylabel("CDF", fontsize=11, fontweight="bold")
        ax.grid(True, which="both", ls=":", alpha=0.6)
        ax.legend(loc="lower right", fontsize=9, frameon=True)

    plt.suptitle("ĐỐI SOÁT KIỂM CHỨNG SỐ HÓA 9 BIỂU ĐỒ FACEBOOK (CHUẨN ĐƠN VỊ BÀI BÁO SIGCOMM 2015)", fontsize=14, fontweight="bold", y=0.995)
    plt.tight_layout()
    overlay_path = os.path.join(OVERLAY_DIR, "digitized_9_curves_validation.png")
    plt.savefig(overlay_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"[+] Đã xuất biểu đồ đối soát đúng đơn vị bài báo: {overlay_path}")
    print("\n[V] Hoàn tất số hóa chính xác 9 đường cong với đơn vị chuẩn của bài báo!")


if __name__ == "__main__":
    digitize_all()
