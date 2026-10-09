#!/usr/bin/env python3
"""
Tên file: traffic_generator.py
Mô tả   : Sinh tải mạng liên tục trên môi trường DOCKER CONTAINER (Containernet):
          - Hỗ trợ đa cổng iperf3 (5201, 5202, 5203, 5204) trên mỗi host để giải quyết triệt để lỗi "server busy".
          - Sinh đan xen 80% luồng Chuột (Mice - kết hợp cả TCP ngắn 20-50KB và Ping) và 20% luồng Voi (Elephant - iperf3 tải nặng).
          - Luồng Chuột TCP ngắn tạo ra đúng đặc trưng 2 chiều (sbytes/dbytes, Ratio) cho mô hình học máy.
          - Quản lý tiến trình an toàn, tự động dọn dẹp khi bấm Ctrl + C.
"""

import subprocess
import time
import random
import re
import sys
import signal

# ==============================================================================
# CẤU HÌNH THỰC NGHIỆM
# ==============================================================================
ELEPHANT_FLOW_RATIO = 0.20   # 20% luồng Voi, 80% luồng Chuột
MIN_DELAY_BETWEEN_FLOWS = 0.2
MAX_DELAY_BETWEEN_FLOWS = 0.8
IPERF_PORTS = [5201, 5202, 5203, 5204]  # Đa cổng để tránh nghẽn server busy

RUNNING = True


def handle_sigint(sig, frame):
    """Bắt sự kiện Ctrl + C để dừng vòng lặp an toàn."""
    global RUNNING
    print("\n[!] Đang nhận tín hiệu dừng (Ctrl + C)... Vui lòng đợi dọn dẹp tiến trình.")
    RUNNING = False


signal.signal(signal.SIGINT, handle_sigint)


def discover_docker_hosts():
    """Quét và lấy địa chỉ IP thuộc mạng DCN (10.0.0.x)."""
    print("[*] Đang quét các Docker container của mạng DCN Spine-Leaf...")
    try:
        docker_ps = subprocess.check_output(
            "docker ps --format '{{.Names}}'",
            shell=True
        ).decode().strip().split("\n")
    except Exception as e:
        print(f"[!] Lỗi truy vấn Docker daemon: {e}")
        return {}

    discovered_hosts = {}
    for c_name in docker_ps:
        if c_name.startswith("mn."):
            short_name = c_name.replace("mn.", "")
            try:
                ip_out = subprocess.check_output(
                    f"docker exec {c_name} ip -4 -o addr show",
                    shell=True
                ).decode()
                match = re.search(r"inet\s+(10\.0\.0\.[0-9]+)/\d+", ip_out)
                if match:
                    ip_addr = match.group(1)
                    discovered_hosts[short_name] = {
                        "container_name": c_name,
                        "ip": ip_addr
                    }
            except Exception:
                pass

    print(f"[+] Nhận diện thành công {len(discovered_hosts)} Docker Hosts trong mạng DCN:")
    for name, info in discovered_hosts.items():
        print(f"    - Node: {name:<6} | Container: {info['container_name']:<12} | IP DCN: {info['ip']}")

    return discovered_hosts


def exec_in_container(container_name, command, is_background=True):
    """Thực thi lệnh bên trong container qua docker exec."""
    bg_flag = "-d" if is_background else ""
    full_cmd = f"docker exec {bg_flag} {container_name} {command}"
    subprocess.Popen(full_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_iperf_servers(host_dict):
    """Khởi động iperf3 server trên nhiều cổng lắng nghe song song (5201-5204)."""
    print(f"[*] Khởi động iperf3 server đa cổng {IPERF_PORTS} trên toàn bộ container...")
    for h_name, h_info in host_dict.items():
        exec_in_container(h_info["container_name"], "killall -9 iperf3 2>/dev/null", is_background=False)
        for p in IPERF_PORTS:
            exec_in_container(h_info["container_name"], f"iperf3 -s -p {p} -B {h_info['ip']} -D")
    time.sleep(2)
    print("[+] Toàn bộ iperf3 servers đa cổng đã sẵn sàng.")


def cleanup_traffic_processes(host_dict):
    """Dọn dẹp tiến trình ping và iperf3 khi người dùng bấm Ctrl + C."""
    print("[*] Đang dọn dẹp các tiến trình client bên trong container...")
    for h_name, h_info in host_dict.items():
        exec_in_container(h_info["container_name"], "killall -9 ping iperf3 2>/dev/null", is_background=False)
    print("[+] Hoàn tất dọn dẹp. Tiến trình dừng hoàn toàn.")


def send_mice_flow(src_container, src_ip, dst_ip):
    """
    Luồng Chuột (Mice Flow):
    Đan xen 50% Ping nhỏ (ICMP) và 50% luồng TCP dung lượng nhỏ (10KB - 50KB) qua iperf3 -n
    để sinh ra đầy đủ đặc trưng 2 chiều (sbytes/dbytes, Ratio).
    """
    port = random.choice(IPERF_PORTS)
    if random.random() < 0.5:
        # Gói tin ICMP nhỏ
        pkt_bytes = random.randint(64, 256)
        exec_in_container(src_container, f"ping -c 3 -s {pkt_bytes} -i 0.2 {dst_ip}")
    else:
        # Phiên TCP truyền ngắn 20K - 50K kết thúc ngay
        burst_size = random.choice(["20K", "30K", "50K"])
        exec_in_container(src_container, f"iperf3 -c {dst_ip} -p {port} -B {src_ip} -n {burst_size}")


def send_elephant_flow(src_container, src_ip, dst_ip):
    """Luồng Voi (Elephant Flow): iperf3 TCP duy trì băng thông lớn (15M-50M) từ 5 -> 10 giây."""
    port = random.choice(IPERF_PORTS)
    duration = random.randint(5, 10)
    target_bw = random.choice(["15M", "30M", "50M"])
    exec_in_container(src_container, f"iperf3 -c {dst_ip} -p {port} -B {src_ip} -t {duration} -b {target_bw}")


def main():
    hosts = discover_docker_hosts()
    if len(hosts) < 2:
        print("[!] Không tìm thấy đủ container với IP 10.0.0.x. Kiểm tra lại topology!")
        sys.exit(1)

    start_iperf_servers(hosts)
    host_keys = list(hosts.keys())

    print("\n" + "=" * 70)
    print("[*] BẮT ĐẦU SINH TẢI LIÊN TỤC VÀO MẠNG DCN SPINE-LEAF (v2)")
    print(f"    - Tỷ lệ luồng Voi (Elephant) : {int(ELEPHANT_FLOW_RATIO * 100)}%")
    print(f"    - Tỷ lệ luồng Chuột (Mice)   : {int((1 - ELEPHANT_FLOW_RATIO) * 100)}% (TCP burst + Ping)")
    print(f"    - Cổng iperf3 đa kênh        : {IPERF_PORTS} (chống lỗi server busy)")
    print("    - Chế độ chạy                : VÔ HẠN (Dừng bằng Ctrl + C)")
    print("=" * 70 + "\n")

    start_time = time.time()
    flow_count = 0

    try:
        while RUNNING:
            src_name = random.choice(host_keys)
            dst_name = random.choice(host_keys)
            while dst_name == src_name:
                dst_name = random.choice(host_keys)

            src_container = hosts[src_name]["container_name"]
            src_ip = hosts[src_name]["ip"]
            dst_ip = hosts[dst_name]["ip"]

            flow_count += 1
            elapsed_min = (time.time() - start_time) / 60

            if random.random() < ELEPHANT_FLOW_RATIO:
                print(f"[{time.strftime('%H:%M:%S')}] [#{flow_count:,} | {elapsed_min:.1f}m] [ELEPHANT] {src_name} ({src_ip}) -> {dst_name} ({dst_ip})")
                send_elephant_flow(src_container, src_ip, dst_ip)
            else:
                send_mice_flow(src_container, src_ip, dst_ip)

            time.sleep(random.uniform(MIN_DELAY_BETWEEN_FLOWS, MAX_DELAY_BETWEEN_FLOWS))

    except Exception as e:
        print(f"\n[!] Lỗi phát sinh: {e}")

    finally:
        total_time_sec = time.time() - start_time
        print(f"\n[+] Tổng thời gian sinh tải: {total_time_sec / 60:.2f} phút.")
        print(f"[+] Tổng số luồng đã phát sinh: {flow_count:,} flows.")
        cleanup_traffic_processes(hosts)


if __name__ == "__main__":
    main()