#!/usr/bin/env python3
"""
Tên file: launch_architecture_viewer.py
Mô tả   : Trình khởi chạy giao diện Đồ họa Tương tác SDN Architecture Explorer.
          Tự động đồng bộ sơ đồ kiến trúc mới nhất từ mã nguồn AST và mở ngay
          trên trình duyệt mặc định (Chrome / Edge / Firefox) với đầy đủ tính năng:
          - Phóng to / Thu nhỏ vô cực (Zoom In / Zoom Out) mượt mà bằng con lăn chuột
          - Kéo rê toàn cảnh (Pan Canvas)
          - Bảng điều khiển chi tiết Node Inspector & Pipeline Trace
          - Bộ lọc 6 phân hệ và Tìm kiếm tức thì theo thời gian thực
Chạy    : python launch_architecture_viewer.py [--server] [--port 8055]
"""

import os
import sys
import subprocess
import webbrowser
import http.server
import socketserver
import threading
import argparse

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
MAPPER_SCRIPT = os.path.join(PROJECT_ROOT, ".antigravity", "skills", "code-architecture-mapper", "scripts", "map_code_architecture.py")
HTML_PATH = os.path.join(PROJECT_ROOT, ".Project Plans", "ARCHITECTURE_EXPLORER.html")

def print_banner():
    banner = r"""
========================================================================================
   ____ ____  _   _   _  ___     _____ _   _     ___  ____  ____  _     ___  ____  _____ ____  
  / ___|  _ \| \ | | | |/ / |   |_   _| \ | |   / _ \|  _ \|  _ \| |   / _ \|  _ \| ____|  _ \ 
  \___ \ | | |  \| | | ' /| |     | | |  \| |  | | | | |_) | |_) | |  | | | | |_) |  _| | |_) |
   ___) | |_| | |\  | | . \| |___  | | | |\  |  | |_| |  __/|  __/| |__| |_| |  _ <| |___|  _ < 
  |____/|____/|_| \_| |_|\_\_____| |_| |_| \_|   \___/|_|   |_|   |_____\___/|_| \_\_____|_| \_\
========================================================================================
    🌐 TRÌNH XEM KIẾN TRÚC MẠNG TƯƠNG TÁC ĐỒ HỌA CAO CẤP (SDN DCN - KLTN)
========================================================================================
  [+] Hướng dẫn Điều khiển UI/UX trên Canvas:
      • 🖱️  Kéo chuột trái       : Di chuyển vùng nhìn toàn cảnh (Pan Canvas).
      • 🔍  Cuộn con lăn chuột   : Phóng to / Thu nhỏ mượt mà tại trỏ chuột (0.15x - 4.0x).
      • 🎯  Click vào Node       : Mở Node Inspector & Highlight luồng liên thông (Pipeline Trace).
      • ⛶  Nút [⛶] góc dưới     : Tự động thu phóng vừa khít màn hình (Fit to Screen).
      • 🔍  Ô tìm kiếm trên cùng : Tìm nhanh module (ví dụ gõ: ecn, ebpf, sampler, kstest...).
      • 🏷️  Bộ lọc phân tầng     : Bật/tắt hiển thị Control Plane, Data Plane, Telemetry, AI/DRL...
========================================================================================
"""
    print(banner)

def sync_architecture():
    """Chạy map_code_architecture.py để đảm bảo dữ liệu luôn mới nhất."""
    print("[*] Đang phân tích mã nguồn AST và đồng bộ đồ thị kiến trúc...")
    if not os.path.exists(MAPPER_SCRIPT):
        print(f"[!] Không tìm thấy script phân tích tại: {MAPPER_SCRIPT}")
        return False
    
    res = subprocess.run([sys.executable, MAPPER_SCRIPT], cwd=PROJECT_ROOT)
    if res.returncode == 0:
        print("[✔] Đồng bộ hoàn tất! Dữ liệu kiến trúc đã cập nhật 100% chính xác.")
        return True
    else:
        print("[!] Có lỗi trong quá trình phân tích mã nguồn.")
        return False

def main():
    parser = argparse.ArgumentParser(description="Khởi chạy SDN Architecture Explorer")
    parser.add_argument("--server", action="store_true", help="Chạy qua local HTTP server thay vì mở trực tiếp file://")
    parser.add_argument("--port", type=int, default=8055, help="Cổng HTTP Server (mặc định 8055)")
    args = parser.parse_args()

    print_banner()

    # Bước 1: Đồng bộ đồ thị
    sync_architecture()

    if not os.path.exists(HTML_PATH):
        print(f"[!] Lỗi: Không tìm thấy tệp giao diện tại: {HTML_PATH}")
        return

    # Bước 2: Mở trình duyệt
    if args.server:
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass # Tắt bớt log HTTP để màn hình sạch sẽ

        os.chdir(PROJECT_ROOT)
        server_url = f"http://localhost:{args.port}/.Project%20Plans/ARCHITECTURE_EXPLORER.html"
        print(f"[+] Đang khởi chạy Local Web Server tại: http://localhost:{args.port}/")
        print(f"[+] Mở giao diện: {server_url}")

        def run_server():
            with socketserver.TCPServer(("", args.port), QuietHandler) as httpd:
                httpd.serve_forever()

        t = threading.Thread(target=run_server, daemon=True)
        t.start()

        webbrowser.open(server_url)
        print("[i] Nhấn Ctrl+C để dừng server khi hoàn tất xem.")
        try:
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            print("\n[+] Đã đóng server.")
    else:
        file_url = f"file:///{HTML_PATH.replace(os.sep, '/')}"
        print(f"[+] Đang mở trực tiếp giao diện đồ họa trên trình duyệt: {file_url}")
        webbrowser.open(file_url)
        print("[✔] Đã mở thành công! Bạn có thể thoải mái phóng to, thu nhỏ và đối soát chi tiết.")

if __name__ == "__main__":
    main()
