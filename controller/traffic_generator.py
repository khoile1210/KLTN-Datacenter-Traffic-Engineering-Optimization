#!/usr/bin/env python3
"""
Tên file: traffic_generator.py
Mô tả   : Bộ sinh lưu lượng nền thống nhất cho mạng Datacenter SDN Spine-Leaf:
          - Tích hợp module toán học UnifiedCdfSampler (ACM SIGCOMM 2015).
          - Đồng nhất 100% công cụ iperf3 qua cơ chế gửi đúng S_scaled Bytes (-n).
          - Điều hướng máy đích theo phân phối 3 vùng Locality (Intra, Extra, Extra-DC).
          - Điều phối nhịp phát mở rộng (Time Dilation) dựa trên năng lực CPU máy ảo.
          - Hỗ trợ đa cổng iperf3 (5201-5204) để chống nghẽn 'server busy'.
          - Chế độ mặc định: Chạy liên tục vô hạn cho đến khi người dùng chủ động ngắt (Ctrl + C hoặc SIGTERM).
          - Hỗ trợ ngắt tức thì (Instant Interrupt) và dọn dẹp sạch sẽ 100% tiến trình iperf3 trên toàn bộ container.
"""

import subprocess
import time
import random
import re
import sys
import signal
import os
import argparse
from concurrent.futures import ThreadPoolExecutor, wait as wait_futures

# Đảm bảo UTF-8
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Nạp module UnifiedCdfSampler
try:
    from unified_sampler import UnifiedCdfSampler
except ImportError:
    from controller.unified_sampler import UnifiedCdfSampler

RUNNING = True


def handle_stop_signal(sig, frame):
    """
    Bắt sự kiện Ctrl + C (SIGINT) hoặc SIGTERM để ngắt vòng lặp an toàn và tức thì.
    Kích hoạt KeyboardInterrupt ngay lập tức để ngắt các lệnh time.sleep() không bị delay.
    """
    global RUNNING
    RUNNING = False
    raise KeyboardInterrupt


# Đăng ký bắt tín hiệu dừng chủ động
signal.signal(signal.SIGINT, handle_stop_signal)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, handle_stop_signal)


def discover_docker_hosts():
    """Quét và lấy địa chỉ IP của các container Containernet (mn.h1 -> mn.h8, mn.inet)."""
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
            # Lọc bỏ triệt để switch containers (a1..a8, ag1..ag4, c1..c2)
            if not (re.match(r"^h\d+_\d+$", short_name) or short_name == "inet"):
                continue

            try:
                ip_out = subprocess.check_output(
                    f"docker exec {c_name} ip -4 -o addr show",
                    shell=True,
                    stderr=subprocess.DEVNULL
                ).decode()
                # Chỉ lấy IP dải host DCN 10.0.0.x (loại trừ 10.255.0.x của proxy-int)
                match = re.search(r"inet\s+(10\.0\.0\.\d+)/\d+", ip_out)
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


def exec_in_container(container_name, command, is_background=True, wait_timeout=None):
    """
    Thực thi lệnh bên trong container qua docker exec.
    - Nếu is_background=True: Chạy ngầm trong container (-d) không chặn luồng chính.
    - Nếu is_background=False: Đợi lệnh thực thi xong để đảm bảo tính tuần tự.
    """
    bg_flag = "-d" if is_background else ""
    full_cmd = f"docker exec {bg_flag} {container_name} {command}"
    if is_background:
        return subprocess.Popen(full_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            return subprocess.run(full_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=wait_timeout)
        except Exception:
            return None


ENGINE_PATH = os.path.join(os.path.dirname(__file__), "dcn_flow_engine.py")


def start_flow_servers(host_dict, iperf_ports):
    """
    Khởi động DCN Flow Engine Server đa luồng trên toàn bộ các container:
    1. Dọn dẹp sạch tiến trình cũ (cả dcn_flow_engine.py và iperf3) trên toàn bộ host đồng thời.
    2. Sao chép dcn_flow_engine.py vào /tmp/ của từng container.
    3. Bật độc quyền daemon Flow Server siêu nhẹ (tránh xung đột cướp cổng TCP/UDP với iperf3 -s).
    """
    ports_str = ",".join(map(str, iperf_ports))
    print(f"[*] Phổ biến DCN Flow Engine và khởi động server đa cổng [{ports_str}] trên {len(host_dict)} containers...")
    procs = []
    for h_name, h_info in host_dict.items():
        c_name = h_info['container_name']
        # Dọn dẹp sạch tiến trình cũ (đặc biệt diệt iperf3 -s để không chiếm cổng của dcn_flow_engine)
        cmd_clean = f"docker exec {c_name} killall -9 iperf3 2>/dev/null; docker exec {c_name} pkill -f dcn_flow_engine.py 2>/dev/null"
        procs.append(subprocess.Popen(cmd_clean, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

        # Sao chép dcn_flow_engine.py vào container nếu có
        if os.path.exists(ENGINE_PATH):
            subprocess.run(f"docker cp \"{ENGINE_PATH}\" {c_name}:/tmp/dcn_flow_engine.py", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for p in procs:
        try:
            p.wait(timeout=2)
        except Exception:
            pass

    for h_name, h_info in host_dict.items():
        c_name = h_info["container_name"]
        # Khởi chạy độc quyền Flow Server chính (TCP + UDP) trên các cổng 5201-5204
        exec_in_container(c_name, f"python3 /tmp/dcn_flow_engine.py --server -p {ports_str}", is_background=True)

    time.sleep(1.5)
    print(f"[+] Toàn bộ Flow Servers ({len(host_dict)} hosts x {len(iperf_ports)} ports) đã sẵn sàng.")


def cleanup_traffic_processes(host_dict):
    """
    Dọn dẹp triệt để 100% các tiến trình sinh tải (Flow Engine và iperf3) bên trong container:
    Thực thi song song trên toàn bộ 33 container và chờ hoàn tất (.wait())
    trước khi thoát, đảm bảo không còn tiến trình rác chạy ngầm bắn trộm traffic.
    """
    print("\n[*] Đang dọn dẹp triệt để các tiến trình sinh tải trên toàn bộ container...")
    procs = []
    for h_name, h_info in host_dict.items():
        c_name = h_info['container_name']
        cmd = f"docker exec {c_name} pkill -f dcn_flow_engine.py 2>/dev/null; docker exec {c_name} killall -9 iperf3 2>/dev/null"
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(p)

    for p in procs:
        try:
            p.wait(timeout=3)
        except Exception:
            pass
    print("[+] Hoàn tất dọn dẹp. Mọi tiến trình sinh tải đã được giải phóng an toàn.")


def parse_duration_arg(val):
    """Hỗ trợ linh hoạt cả số giây (3600, 3600s), số phút (60m) lẫn số giờ (1h, 1.5h)."""
    if val is None:
        return None
    val_str = str(val).strip().lower()
    try:
        if val_str.endswith("h"):
            return float(val_str[:-1]) * 3600.0
        elif val_str.endswith("m"):
            return float(val_str[:-1]) * 60.0
        elif val_str.endswith("s"):
            return float(val_str[:-1])
        return float(val_str)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Định dạng thời gian không hợp lệ: '{val}'. Ví dụ hợp lệ: 3600, 1h, 60m, 1800s.")


def parse_arguments():
    """Hỗ trợ tùy chọn dòng lệnh linh hoạt nếu muốn giới hạn thời gian/số luồng."""
    parser = argparse.ArgumentParser(
        description="Unified DCN Traffic Generator (Facebook SIGCOMM 2015 Workload)"
    )
    parser.add_argument(
        "--duration", type=parse_duration_arg, default=None,
        help="Thời gian sinh tải tối đa (hỗ trợ số giây như 3600, hoặc chuỗi thời gian như 1h, 60m). Mặc định: None (chạy liên tục vô hạn cho tới khi người dùng chủ động ngắt bằng Ctrl + C)"
    )
    parser.add_argument(
        "--flows", type=int, default=None,
        help="Số lượng luồng tối đa cần phát. Mặc định: None (chạy liên tục vô hạn cho tới khi người dùng chủ động ngắt bằng Ctrl + C)"
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Đường dẫn file cấu hình traffic_config.json"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    hosts = discover_docker_hosts()
    if len(hosts) < 2:
        print("[!] Không tìm thấy đủ container với IP mạng 10.x.x.x. Hãy khởi động spine_leaf_topo.py trước!")
        sys.exit(1)

    sampler = UnifiedCdfSampler(config_path=args.config)
    start_flow_servers(hosts, sampler.iperf_ports)

    # Danh sách các host nội bộ tham gia phát sinh luồng
    internal_hosts = [h for h in hosts.keys() if h != "inet"]

    mode_desc = "VÔ HẠN (Chỉ dừng khi người dùng chủ động bấm Ctrl + C)"
    if args.duration:
        hours = args.duration / 3600.0
        mins = args.duration / 60.0
        if hours >= 1.0:
            time_str = f"{hours:.2f} giờ ({args.duration:,.0f} giây)"
        else:
            time_str = f"{mins:.2f} phút ({args.duration:,.0f} giây)"
        mode_desc = f"HẸN GIỜ: {time_str} (Tự động dừng hoặc bấm Ctrl + C để ngắt sớm)"
    elif args.flows:
        mode_desc = f"Giới hạn số luồng: {args.flows:,} luồng (hoặc bấm Ctrl + C để dừng sớm)"

    print("\n" + "=" * 80)
    print("[*] BẮT ĐẦU SINH TẢI DATACENTER THỐNG NHẤT (UNIFIED DCN WORKLOAD - v4)")
    print(f"    - Băng thông cấu hình : {sampler.c_host} Mbps (Hệ số scale alpha = {sampler.alpha:.5f})")
    print(f"    - Giãn nhịp phát      : {sampler.d_arrival:.1f}x (Bảo toàn độ tải CPU máy chủ ảo)")
    # Tính toán động min_burst và max_burst dựa trên tổng số host nội bộ thực tế
    num_internal = len(internal_hosts)
    min_burst = max(1, int(round(num_internal * sampler.min_burst_ratio)))
    max_burst = max(min_burst, int(round(num_internal * sampler.max_burst_ratio)))
    # Hệ số đệm an toàn 2x (Headroom Factor) hấp thụ hoàn toàn các luồng voi gối đầu giữa các đợt phát
    worker_count = max(sampler.max_workers, num_internal) * 2

    if sampler.is_clustered:
        print(f"    - Phân bổ 4 cấp Cụm   : Intra-Rack={sampler.r_intra_rack*100:.1f}%, Intra-Cluster={sampler.r_intra_cluster*100:.1f}%, Intra-DC={sampler.r_intra_dc*100:.1f}%, Internet={sampler.r_extra_dc*100:.1f}%")
    else:
        print(f"    - Phân bổ 3 vùng phẳng: Intra={sampler.r_intra_rack*100:.1f}%, Extra={sampler.r_extra_rack*100:.1f}%, Internet={sampler.r_extra_dc*100:.1f}%")
    print(f"    - Bơm tải đa luồng   : ThreadPoolExecutor (max_workers={worker_count} [Hệ số gối đầu 2x cho {num_internal} hosts])")
    print(f"    - Bùng nổ Incast/Coflow: {min_burst} - {max_burst} hosts/đợt ({sampler.min_burst_ratio*100:.1f}% - {sampler.max_burst_ratio*100:.1f}% tổng số {num_internal} hosts)")
    print(f"    - Giao thức phân vùng : {sampler.udp_ratio*100:.1f}% UDP Cache (Memcached), {(1.0-sampler.udp_ratio)*100:.1f}% TCP")
    print(f"    - Cổng đa kênh        : {sampler.iperf_ports} (Chống nghẽn server busy)")
    print(f"    - Chế độ hoạt động    : {mode_desc}")
    print("=" * 80 + "\n")

    start_time = time.time()
    flow_count = 0
    burst_count = 0
    zone_stats = {}
    executor = ThreadPoolExecutor(max_workers=worker_count)

    def send_single_flow(src_cname, src_ip, dst_ip, port, s_bytes, protocol):
        flow_cmd = f"python3 /tmp/dcn_flow_engine.py --client -d {dst_ip} -p {port} -b {s_bytes} -B {src_ip} --proto {protocol}"
        exec_in_container(src_cname, flow_cmd, is_background=False, wait_timeout=20)

    try:
        while RUNNING:
            if args.duration and (time.time() - start_time) >= args.duration:
                print(f"\n[*] Đã đạt giới hạn thời gian chạy ({args.duration}s). Tự động dừng sinh tải.")
                break
            if args.flows and flow_count >= args.flows:
                print(f"\n[*] Đã phát đủ {args.flows:,} luồng. Tự động dừng sinh tải.")
                break

            # 1. Tính toán ngẫu nhiên kích thước đợt bùng nổ (Incast burst size)
            burst_size = random.randint(min_burst, max_burst)
            if args.flows and (flow_count + burst_size) > args.flows:
                burst_size = max(1, args.flows - flow_count)

            # 2. Chọn ngẫu nhiên burst_size host nguồn phân biệt trong internal_hosts
            sampled_srcs = random.sample(internal_hosts, burst_size)

            # 3. Lấy mẫu khoảng thời gian chờ (Giây) từ ECDF Inter-Arrival cho cả đợt
            dt_raw, dt_scaled = sampler.sample_inter_arrival()
            burst_count += 1
            elapsed_min = (time.time() - start_time) / 60

            # 4. Phát đồng loạt toàn bộ luồng trong đợt qua ThreadPoolExecutor (Có đồng bộ Backpressure)
            burst_details = []
            burst_futures = []
            for src_name in sampled_srcs:
                src_info = hosts[src_name]

                # Lấy mẫu đích theo phân phối Locality (tự thích ứng 4 cấp hoặc 3 cấp)
                dst_name, zone = sampler.sample_destination(src_name, hosts)
                dst_info = hosts[dst_name]
                zone_stats[zone] = zone_stats.get(zone, 0) + 1

                # Lấy mẫu kích thước luồng (Bytes) từ ECDF Facebook
                s_raw, s_scaled = sampler.sample_flow_size()

                # Lấy mẫu giao thức (UDP cho Cache 18.4%, TCP cho các luồng còn lại)
                proto = sampler.sample_protocol()

                # Chọn cổng ngẫu nhiên trong danh sách đa cổng
                port = random.choice(sampler.iperf_ports)

                flow_count += 1
                fut = executor.submit(send_single_flow, src_info["container_name"], src_info["ip"], dst_info["ip"], port, s_scaled, proto)
                burst_futures.append(fut)
                burst_details.append((src_name, dst_name, proto, s_scaled, zone))

            # Chờ đợt bùng nổ hoàn tất (hoặc tối đa 5s) để chống nghẽn hàng đợi dockerd
            if burst_futures:
                wait_futures(burst_futures, timeout=5.0)

            # Giãn nhịp giữa các đợt theo kích thước burst_size để bảo toàn tốc độ đến trung bình ECDF
            burst_sleep = max(dt_scaled * burst_size, 0.5)

            # Hiển thị thông tin đợt bùng nổ định kỳ hoặc khi có luồng voi lớn (Chuẩn SSoT S_threshold_bytes)
            eleph_thresh = sampler.s_threshold if (sampler.s_threshold and sampler.s_threshold > 0) else 65536
            has_elephant = any(s >= eleph_thresh for _, _, _, s, _ in burst_details)
            if burst_count % 5 == 0 or has_elephant or burst_size == max_burst:
                eleph_str = " [CÓ LUỒNG VOI]" if has_elephant else ""
                print(f"[{time.strftime('%H:%M:%S')}] [Burst #{burst_count:,} | {elapsed_min:.1f}m] Bắn đồng thời {burst_size}/{num_internal} hosts ({burst_size/num_internal*100:.1f}%) | Tổng: {flow_count:,} luồng | Sleep: {burst_sleep*1000:.0f}ms{eleph_str}")

            # 5. Nghỉ đúng khoảng thời gian giãn nhịp ECDF của cả đợt
            time.sleep(burst_sleep)

    except KeyboardInterrupt:
        print("\n[!] Đã nhận tín hiệu ngắt chủ động từ người dùng (Ctrl + C). Đang tiến hành dừng...")
    except Exception as e:
        print(f"\n[!] Lỗi phát sinh trong quá trình sinh tải: {e}")
    finally:
        try:
            executor.shutdown(wait=False)
        except Exception:
            pass
        total_time_sec = time.time() - start_time
        print("\n" + "=" * 80)
        print("[*] TỔNG KẾT TIẾN TRÌNH SINH TẢI:")
        print(f"    - Thời gian chạy thực tế : {total_time_sec / 60:.2f} phút ({total_time_sec:.1f} giây)")
        print(f"    - Tổng số đợt bùng nổ    : {burst_count:,} đợt")
        print(f"    - Tổng số luồng đã phát  : {flow_count:,} luồng")
        if flow_count > 0:
            print("    - Tỷ lệ các vùng phân bổ :")
            for z, cnt in sorted(zone_stats.items()):
                print(f"      + {z:<14}: {cnt:,} luồng ({cnt/flow_count*100:.1f}%)")
        print("=" * 80)
        cleanup_traffic_processes(hosts)


if __name__ == "__main__":
    main()