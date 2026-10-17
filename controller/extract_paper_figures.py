#!/usr/bin/env python3
"""
Tên file: extract_paper_figures.py
Mô tả   : Trích xuất các biểu đồ ECDF thực nghiệm từ file PDF bài báo Facebook
          (ACM SIGCOMM 2015: Inside the Social Network's Datacenter Network)
          ở độ phân giải siêu nét (400 DPI) phục vụ số hóa dữ liệu.
"""

import os
import sys
import pymupdf

PDF_PATH = os.path.join("Documents", "Inside the Social Network’s (Datacenter) Network.pdf")
OUTPUT_DIRS = [
    os.path.join("Documents", "extracted_figures"),
    os.path.join("controller", "extracted_figures")
]

# Danh sách cấu hình trích xuất (Page 1-indexed, Tên file, BBox toạ độ: x0, y0, x1, y1)
CROPS = [
    # Page 8: Figure 6 (Flow Size Distribution)
    (8, "figure_6_flow_size_all.png", pymupdf.Rect(48, 48, 560, 188)),
    (8, "figure_6a_size_web.png", pymupdf.Rect(48, 48, 222, 172)),
    (8, "figure_6b_size_cache.png", pymupdf.Rect(218, 48, 392, 172)),
    (8, "figure_6c_size_hadoop.png", pymupdf.Rect(388, 48, 560, 172)),

    # Page 8: Figure 7 (Flow Duration Distribution)
    (8, "figure_7_flow_duration_all.png", pymupdf.Rect(48, 190, 560, 330)),
    (8, "figure_7a_dur_web.png", pymupdf.Rect(48, 190, 222, 314)),
    (8, "figure_7b_dur_cache.png", pymupdf.Rect(218, 190, 392, 314)),
    (8, "figure_7c_dur_hadoop.png", pymupdf.Rect(388, 190, 560, 314)),

    # Page 10: Figure 10 (Heavy-hitter stability)
    (10, "figure_10_heavy_hitter_stability.png", pymupdf.Rect(48, 48, 560, 196)),

    # Page 11: Figure 11 (Heavy-hitter intersection)
    (11, "figure_11_heavy_hitter_intersection.png", pymupdf.Rect(48, 230, 300, 418)),

    # Page 12: Figure 12 (Packet Size) & Figure 14 (Flow Inter-arrival)
    (12, "figure_12_packet_size.png", pymupdf.Rect(48, 48, 300, 220)),
    (12, "figure_14_inter_arrival.png", pymupdf.Rect(310, 48, 560, 220))
]


def extract_figures():
    if not os.path.exists(PDF_PATH):
        print(f"[!] Không tìm thấy tệp PDF tại: {PDF_PATH}")
        sys.exit(1)

    for d in OUTPUT_DIRS:
        os.makedirs(d, exist_ok=True)

    doc = pymupdf.open(PDF_PATH)
    dpi = 400
    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)

    print(f"[*] Đang trích xuất {len(CROPS)} biểu đồ ở độ phân giải {dpi} DPI từ PDF...")

    for page_no, filename, rect in CROPS:
        page = doc[page_no - 1]
        pix = page.get_pixmap(matrix=mat, clip=rect)
        for d in OUTPUT_DIRS:
            save_path = os.path.join(d, filename)
            pix.save(save_path)
        print(f" [+] Đã xuất: {filename:<38} ({pix.width}x{pix.height}px)")

    print(f"\n[V] Hoàn tất! Ảnh đã được lưu đồng bộ vào: {OUTPUT_DIRS[0]} và {OUTPUT_DIRS[1]}")


if __name__ == "__main__":
    extract_figures()
