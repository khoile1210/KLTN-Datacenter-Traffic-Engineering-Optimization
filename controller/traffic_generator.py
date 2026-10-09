#!/usr/bin/env python3
"""
Tên file: traffic_generator.py
Mô tả   : Sinh tải mạng liên tục trên môi trường DOCKER CONTAINER (Containernet):
          - Chạy vòng lặp vô hạn cho tới khi bấm Ctrl + C.
          - Tự động bắt đúng dải IP DCN Spine-Leaf (10.0.0.0/24 trên card hX-eth0).
          - Khởi động iperf3 server lắng nghe đúng IP DCN.
          - Sinh đan xen 80% luồng Chuột (Mice - ping) và 20% luồng Voi (Elephant - iperf3).
          - Tự động dọn dẹp tiến trình con khi dừng chương trình.
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

# Biến cờ kiểm soát vòng lặp chính
RUNNING = True


def handle_sigint(sig, frame):
    """Bắt sự kiện Ctrl + C để dừng vòng lặp an toàn."""
    global RUNNING
    print("\n[!] Đang nhận tín hiệu dừng (Ctrl + C)... Vui lòng đợi dọn dẹp tiến trình.")
    RUNNING = False


# Đăng ký bắt tín hiệu ngắt bàn phím
signal.signal(signal.SIGINT, handle_sigint)


def discover_docker_hosts():
    """Chỉ quét và lấy địa chỉ IP thuộc mạng DCN (10.0.0.x)."""
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
                # Quét tất cả IP và CHỈ chọn IP thuộc dải 10.0.0.x
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
    """Khởi động iperf3 server lắng nghe đúng IP DCN trên toàn bộ container."""
    print("[*] Đang khởi động iperf3 server (-D) trên dải 10.0.0.x...")
    for h_name, h_info in host_dict.items():
        # Dọn sạch iperf cũ nếu có trước khi bật mới
        exec_in_container(h_info["container_name"], "killall -9 iperf3 2>/dev/null", is_background=False)
        exec_in_container(h_info["container_name"], f"iperf3 -s -B {h_info['ip']} -D")
    time.sleep(2)


def cleanup_traffic_processes(host_dict):
    """Dọn dẹp tiến trình ping và iperf3 khi người dùng bấm Ctrl + C."""
    print("[*] Đang dọn dẹp các tiến trình client bên trong container...")
    for h_name, h_info in host_dict.items():
        exec_in_container(h_info["container_name"], "killall -9 ping iperf3 2>/dev/null", is_background=False)
    print("[+] Hoàn tất dọn dẹp. Tiến trình dừng hoàn toàn.")


def send_mice_flow(src_container, src_ip, dst_ip):
    """Luồng Chuột (Mice): Ping kích thước nhỏ qua interface DCN."""
    pkt_bytes = random.randint(64, 256)
    exec_in_container(src_container, f"ping -c 4 -s {pkt_bytes} -i 0.2 {dst_ip}")


def send_elephant_flow(src_container, src_ip, dst_ip):
    """Luồng Voi (Elephant): iperf3 TCP duy trì tải lớn từ 5 -> 10 giây."""
    duration = random.randint(5, 10)
    target_bw = random.choice(["15M", "30M", "50M"])
    exec_in_container(src_container, f"iperf3 -c {dst_ip} -B {src_ip} -t {duration} -b {target_bw}")


def main():
    hosts = discover_docker_hosts()
    if len(hosts) < 2:
        print("[!] Không tìm thấy đủ container với IP 10.0.0.x. Kiểm tra lại topology!")
        sys.exit(1)

    start_iperf_servers(hosts)
    host_keys = list(hosts.keys())

    print("\n" + "=" * 70)
    print("[*] BẮT ĐẦU SINH TẢI LIÊN TỤC VÀO MẠNG DCN SPİNE-LEAF")
    print(f"    - Tỷ lệ luồng Voi (Elephant) : {int(ELEPHANT_FLOW_RATIO * 100)}%")
    print(f"    - Tỷ lệ luồng Chuột (Mice)   : {int((1 - ELEPHANT_FLOW_RATIO) * 100)}%")
    print("    - Chế độ chạy                : VÔ HẠN (Chỉ dừng khi bấm Ctrl + C)")
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