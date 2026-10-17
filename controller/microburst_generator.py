#!/usr/bin/env python3
"""
Tên file: microburst_generator.py
Mô tả   : Module sinh tải Heavy Jitter / Ephemeral Microburst độc lập (Phase 5):
          - Bơm burst ngắn (< 10 ms, 20 KB - 80 KB) bằng Python TCP Socket trực tiếp.
          - Kích hoạt cờ TCP_NODELAY = 1 và IP TOS ECT(0) = 0x02 phục vụ ECN testing.
          - Hỗ trợ 2 chế độ:
            + Random Microburst: Host ngẫu nhiên bắn burst vào một host khác.
            + Incast Congestion: Nhiều host đồng loạt bắn burst dồn về 1 host/rack mục tiêu.
          - Tự ghi nhận nhật ký Ground-Truth Client-side: results/microburst_client_ground_truth.csv.
          - Chạy độc lập với traffic_generator.py (không làm nhiễu luồng nền iperf3).
"""

import os
import sys
import time
import json
import random
import re
import socket
import subprocess
import argparse
from datetime import datetime

# Đảm bảo UTF-8
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "traffic_config.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
if not os.path.exists(RESULTS_DIR):
    RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

GROUND_TRUTH_CSV = os.path.join(RESULTS_DIR, "microburst_client_ground_truth.csv")
BURST_PORT = 9999

CSV_HEADERS = [
    "timestamp", "src_host", "src_ip", "dst_host", "dst_ip",
    "burst_bytes", "duration_ms", "rate_mbps", "mode", "ecn_tos", "is_burst"
]


def load_config(config_path=DEFAULT_CONFIG_PATH):
    """Nạp tham số cấu hình microburst từ traffic_config.json."""
    defaults = {
        "burst_size_min_bytes": 20480,   # 20 KB
        "burst_size_max_bytes": 81920,   # 80 KB
        "target_duration_ms_max": 10.0,
        "p_burst": 0.02
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                mb_cfg = cfg.get("microburst_settings", {})
                defaults.update(mb_cfg)
        except Exception as e:
            print(f"[!] Cảnh báo nạp file cấu hình: {e}. Sử dụng cấu hình mặc định.")
    return defaults


def init_ground_truth_csv(csv_path=GROUND_TRUTH_CSV):
    """Khởi tạo file CSV ghi nhận nhật ký Ground-Truth client-side."""
    if not os.path.exists(csv_path):
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(",".join(CSV_HEADERS) + "\n")
        print(f"[+] Khởi tạo file Ground-Truth Microburst: {csv_path}")


def log_ground_truth_record(record, csv_path=GROUND_TRUTH_CSV):
    """Ghi 1 bản ghi vào file CSV."""
    line = [
        str(record.get("timestamp", "")),
        str(record.get("src_host", "")),
        str(record.get("src_ip", "")),
        str(record.get("dst_host", "")),
        str(record.get("dst_ip", "")),
        str(record.get("burst_bytes", 0)),
        f"{record.get('duration_ms', 0.0):.3f}",
        f"{record.get('rate_mbps', 0.0):.2f}",
        str(record.get("mode", "")),
        str(record.get("ecn_tos", "0x02")),
        str(record.get("is_burst", True))
    ]
    with open(csv_path, "a", encoding="utf-8") as f:
        f.write(",".join(line) + "\n")


def discover_docker_hosts():
    """Quét và nhận diện container mn.h1 -> mn.h8, mn.inet."""
    print("[*] Đang quét Docker container trong topo Spine-Leaf...")
    try:
        docker_ps = subprocess.check_output(
            "docker ps --format '{{.Names}}'",
            shell=True
        ).decode().strip().split("\n")
    except Exception as e:
        print(f"[!] Không thể kết nối Docker daemon: {e}")
        return {}

    discovered_hosts = {}
    for c_name in docker_ps:
        c_name = c_name.strip()
        if c_name.startswith("mn."):
            short_name = c_name.replace("mn.", "")
            try:
                ip_out = subprocess.check_output(
                    f"docker exec {c_name} ip -4 -o addr show",
                    shell=True
                ).decode()
                match = re.search(r"inet\s+(10\.\d+\.\d+\.\d+)/\d+", ip_out)
                if match:
                    discovered_hosts[short_name] = {
                        "container_name": c_name,
                        "ip": match.group(1)
                    }
            except Exception:
                pass

    return discovered_hosts


def start_receiver_servers(hosts_dict, port=BURST_PORT):
    """Khởi chạy Microburst TCP Server nhẹ trên các container để tiếp nhận burst."""
    print(f"[*] Khởi động Microburst receiver daemon trên cổng TCP {port}...")

    server_script = f"""import socket, threading, sys

def handle(c):
    try:
        while c.recv(65536):
            pass
    except Exception:
        pass
    finally:
        c.close()

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', {port}))
s.listen(64)
while True:
    try:
        conn, _ = s.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()
    except Exception:
        sys.exit(0)
"""

    for h_name, h_info in hosts_dict.items():
        c_name = h_info["container_name"]
        # Diệt tiến trình cũ lắng nghe cổng này nếu có
        subprocess.call(["docker", "exec", "-d", c_name, "pkill", "-f", f"0.0.0.0.*{port}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Khởi chạy daemon mới với mã Python đa dòng hợp lệ
        subprocess.call(["docker", "exec", "-d", c_name, "python3", "-c", server_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(1.0)
    print(f"[+] Microburst receivers đã sẵn sàng trên toàn bộ {len(hosts_dict)} containers.")


def send_single_burst(src_container, src_ip, dst_ip, burst_bytes, port=BURST_PORT):
    """
    Thực thi mã phát burst từ bên trong container nguồn qua docker exec.
    Sử dụng socket TCP_NODELAY + IP_TOS 0x02 (ECT(0)) và đo thời gian chính xác (ms).
    """
    client_script = f"""import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
try:
    s.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0x02)
except Exception:
    pass
t0 = time.perf_counter()
s.connect(('{dst_ip}', {port}))
s.sendall(b'M' * {burst_bytes})
s.shutdown(socket.SHUT_WR)
t1 = time.perf_counter()
s.close()
dur_ms = (t1 - t0) * 1000.0
print(f'{{dur_ms:.4f}}')
"""
    cmd = ["docker", "exec", src_container, "python3", "-c", client_script]
    try:
        output = subprocess.check_output(cmd, timeout=5.0).decode().strip()
        dur_ms = float(output)
        return dur_ms
    except Exception:
        # Nếu lỗi hoặc timeout
        return None


def run_random_burst(hosts_dict, burst_min, burst_max):
    """Phát 1 burst ngẫu nhiên từ 1 host tới 1 host khác."""
    internal_hosts = [h for h in hosts_dict.keys() if h != "inet"]
    if len(internal_hosts) < 2:
        return None

    src_name = random.choice(internal_hosts)
    candidates = [h for h in internal_hosts if h != src_name]
    dst_name = random.choice(candidates)

    src_info = hosts_dict[src_name]
    dst_info = hosts_dict[dst_name]

    burst_bytes = int(random.uniform(burst_min, burst_max))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    dur_ms = send_single_burst(
        src_info["container_name"],
        src_info["ip"],
        dst_info["ip"],
        burst_bytes,
        BURST_PORT
    )

    if dur_ms is not None:
        rate_mbps = (burst_bytes * 8.0) / (dur_ms * 1000.0) if dur_ms > 0 else 0.0
        record = {
            "timestamp": now_str,
            "src_host": src_name,
            "src_ip": src_info["ip"],
            "dst_host": dst_name,
            "dst_ip": dst_info["ip"],
            "burst_bytes": burst_bytes,
            "duration_ms": dur_ms,
            "rate_mbps": rate_mbps,
            "mode": "Random",
            "ecn_tos": "0x02 (ECT-0)",
            "is_burst": True
        }
        log_ground_truth_record(record)
        return record
    return None


def run_incast_burst(hosts_dict, target_host_name, burst_min, burst_max):
    """
    Phát đợt Incast Microburst: Toàn bộ các host còn lại đồng loạt bắn burst
    vào target_host để kiểm thử tràn hàng đợi switch và ECN Congestion Experienced.
    """
    if target_host_name not in hosts_dict:
        # Fallback tự động chọn host nội bộ đầu tiên nếu target chỉ định không tồn tại
        candidates = [h for h in hosts_dict.keys() if h != "inet"]
        if candidates:
            target_host_name = candidates[0]
            print(f"[!] Target host chỉ định không tồn tại. Tự động chuyển mục tiêu về '{target_host_name}'.")
        else:
            print(f"[!] Target host {target_host_name} không tồn tại và không có host nội bộ khả dụng.")
            return []

    dst_info = hosts_dict[target_host_name]
    senders = [h for h in hosts_dict.keys() if h != target_host_name and h != "inet"]

    print(f"\n[!] BẮT ĐẦU INCAST MICROBURST -> Mục tiêu: {target_host_name} ({dst_info['ip']}) từ {len(senders)} hosts!")
    records = []

    # Bắn đồng thời qua subprocess đa luồng
    procs = []
    burst_plan = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    for src_name in senders:
        src_info = hosts_dict[src_name]
        burst_bytes = int(random.uniform(burst_min, burst_max))
        client_script = f"""import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
try:
    s.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0x02)
except Exception:
    pass
t0 = time.perf_counter()
s.connect(('{dst_info['ip']}', {BURST_PORT}))
s.sendall(b'I' * {burst_bytes})
s.shutdown(socket.SHUT_WR)
t1 = time.perf_counter()
s.close()
dur_ms = (t1 - t0) * 1000.0
print(f'{{dur_ms:.4f}}')
"""
        cmd = ["docker", "exec", src_info['container_name'], "python3", "-c", client_script]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        procs.append((src_name, src_info, burst_bytes, p))

    for src_name, src_info, burst_bytes, p in procs:
        try:
            stdout, stderr = p.communicate(timeout=5.0)
            dur_ms = float(stdout.decode().strip())
            rate_mbps = (burst_bytes * 8.0) / (dur_ms * 1000.0) if dur_ms > 0 else 0.0
            rec = {
                "timestamp": now_str,
                "src_host": src_name,
                "src_ip": src_info["ip"],
                "dst_host": target_host_name,
                "dst_ip": dst_info["ip"],
                "burst_bytes": burst_bytes,
                "duration_ms": dur_ms,
                "rate_mbps": rate_mbps,
                "mode": "Incast",
                "ecn_tos": "0x02 (ECT-0)",
                "is_burst": True
            }
            log_ground_truth_record(rec)
            records.append(rec)
            print(f"    - Incast sender {src_name} ({src_info['ip']}): {burst_bytes/1024:.1f} KB in {dur_ms:.2f} ms ({rate_mbps:.1f} Mbps)")
        except Exception as e:
            print(f"    - Incast sender {src_name} lỗi: {e}")

    return records


def run_dry_run_simulation(config):
    """Chế độ mô phỏng kiểm thử độc lập (Dry-Run) khi chưa khởi động Containernet."""
    print("\n" + "=" * 78)
    print("[*] CHẾ ĐỘ KIỂM THỬ ĐỘC LẬP (DRY-RUN / SIMULATION MODE)")
    print(f"    - Cấu hình burst size: {config['burst_size_min_bytes']/1024:.1f} KB -> {config['burst_size_max_bytes']/1024:.1f} KB")
    print(f"    - Mục tiêu thời lượng: < {config['target_duration_ms_max']} ms")
    print(f"    - Tùy chọn ECN TOS   : 0x02 (ECT-0)")
    print(f"    - Ghi nhận file      : {GROUND_TRUTH_CSV}")
    print("=" * 78 + "\n")

    init_ground_truth_csv()
    dummy_hosts = {}
    for r in range(1, 9):
        for h in range(1, 5):
            idx = (r - 1) * 4 + h
            dummy_hosts[f"h{r}_{h}"] = f"10.0.0.{idx}"

    all_keys = list(dummy_hosts.keys())
    print("[*] Đang sinh 10 mẫu Microburst giả lập (Kiến trúc 32 Hosts) để kiểm tra cơ chế ghi log...")
    for i in range(1, 11):
        src_name = random.choice(all_keys)
        dst_name = random.choice([h for h in all_keys if h != src_name])
        burst_bytes = int(random.uniform(config['burst_size_min_bytes'], config['burst_size_max_bytes']))
        # Giả lập thời gian truyền ở line-rate 20 - 100 Mbps:
        # Ở 100 Mbps: 50 KB / 12.5 MB/s = ~4 ms
        dur_ms = round(random.uniform(1.8, 6.2), 3)
        rate_mbps = (burst_bytes * 8.0) / (dur_ms * 1000.0)

        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "src_host": src_name,
            "src_ip": dummy_hosts[src_name],
            "dst_host": dst_name,
            "dst_ip": dummy_hosts[dst_name],
            "burst_bytes": burst_bytes,
            "duration_ms": dur_ms,
            "rate_mbps": rate_mbps,
            "mode": "DryRun-Random",
            "ecn_tos": "0x02 (ECT-0)",
            "is_burst": True
        }
        log_ground_truth_record(record)
        print(f"  #{i:02d}: [{record['mode']}] {src_name} ({record['src_ip']}) -> {dst_name} ({record['dst_ip']}) | {burst_bytes/1024:.1f} KB | {dur_ms} ms | Rate: {rate_mbps:.1f} Mbps")

    print(f"\n[V] Kiểm thử Dry-run hoàn tất! Đã ghi nhận 10 bản ghi vào {GROUND_TRUTH_CSV}.")


def parse_duration_arg(val):
    """Hỗ trợ linh hoạt cả số giây (10, 10s, 2.5), số phút (60m, 0.5m) lẫn số giờ (1h, 1.5h)."""
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
        raise argparse.ArgumentTypeError(f"Định dạng thời gian không hợp lệ: '{val}'. Ví dụ: 10s, 30s, 2.5, 60m, 1h, 3600.")


def cleanup_receiver_servers(hosts_dict, port=BURST_PORT):
    """Giải phóng các daemon receiver cổng port trên tất cả container."""
    print("\n[*] Đang giải phóng các daemon receiver cổng TCP 9999...")
    for h_name, h_info in hosts_dict.items():
        c_name = h_info["container_name"]
        subprocess.call(["docker", "exec", "-d", c_name, "pkill", "-f", f"0.0.0.0.*{port}"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("[+] Toàn bộ tiến trình receiver đã được giải phóng an toàn.")


def main():
    parser = argparse.ArgumentParser(description="SDN DCN Heavy Jitter / Microburst Generator (Phase 5)")
    parser.add_argument("--mode", choices=["random", "incast", "dry-run"], default="random",
                        help="Chế độ bắn burst: random (ngẫu nhiên), incast (dồn về 1 host), hoặc dry-run (mô phỏng)")
    parser.add_argument("--target", default="h1_1", help="Host mục tiêu khi chạy chế độ incast (mặc định: h1_1)")
    parser.add_argument("--duration", type=parse_duration_arg, default=None,
                        help="Thời gian tiêm jitter tối đa (hỗ trợ số giây như 3600 hoặc chuỗi 1h, 60m).")
    parser.add_argument("--count", type=int, default=None,
                        help="Số lượng đợt burst cần phát. Mặc định: 20 nếu không truyền --duration.")
    parser.add_argument("--interval", type=parse_duration_arg, default=None,
                        help="Khoảng cách chu kỳ cố định giữa các đợt burst (hỗ trợ số giây như 2.0, 10s, 0.5m. Mặc định: 2.0s nếu không truyền min/max).")
    parser.add_argument("--mininterval", "--min-interval", type=parse_duration_arg, default=None,
                        help="Khoảng thời gian ngẫu nhiên tối thiểu giữa các đợt burst (ví dụ: 10s, 5, 0.5m).")
    parser.add_argument("--maxinterval", "--max-interval", type=parse_duration_arg, default=None,
                        help="Khoảng thời gian ngẫu nhiên tối đa giữa các đợt burst (ví dụ: 30s, 15, 1m).")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Đường dẫn file cấu hình traffic_config.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    burst_min = cfg["burst_size_min_bytes"]
    burst_max = cfg["burst_size_max_bytes"]

    # Xử lý tham số chu kỳ (Interval): Hỗ trợ cả cố định và khoảng ngẫu nhiên Uniform
    if args.mininterval is not None or args.maxinterval is not None:
        if args.mininterval is not None and args.maxinterval is not None:
            min_interval = float(args.mininterval)
            max_interval = float(args.maxinterval)
            if min_interval > max_interval:
                min_interval, max_interval = max_interval, min_interval
        elif args.mininterval is not None:
            min_interval = float(args.mininterval)
            base_ref = float(args.interval) if args.interval is not None else 2.0
            max_interval = max(min_interval, base_ref)
        else:
            max_interval = float(args.maxinterval)
            base_ref = float(args.interval) if args.interval is not None else 2.0
            min_interval = min(base_ref, max_interval)
    elif args.interval is not None:
        min_interval = max_interval = float(args.interval)
    else:
        min_interval = max_interval = 2.0

    if min_interval == max_interval:
        interval_desc = f"{min_interval:.1f} giây (Cố định)"
    else:
        interval_desc = f"{min_interval:.1f}s -> {max_interval:.1f}s (Ngẫu nhiên Uniform)"

    if args.mode == "dry-run":
        run_dry_run_simulation(cfg)
        return

    hosts = discover_docker_hosts()
    if len(hosts) < 2:
        print("[!] Không tìm thấy Docker container mạng DCN đang chạy.")
        print("[!] Tự động chuyển sang chế độ '--mode dry-run' để kiểm thử tính năng...")
        run_dry_run_simulation(cfg)
        return

    init_ground_truth_csv()
    start_receiver_servers(hosts, BURST_PORT)

    # Nếu không cấu hình duration và count, mặc định count = 20
    if args.duration is None and args.count is None:
        args.count = 20

    if args.duration:
        hours = args.duration / 3600.0
        mins = args.duration / 60.0
        time_desc = f"{hours:.2f} giờ ({args.duration:,.0f}s)" if hours >= 1.0 else f"{mins:.2f} phút ({args.duration:,.0f}s)"
        mode_info = f"HẸN GIỜ: {time_desc} (Tự động dừng hoặc bấm Ctrl + C để ngắt sớm)"
    else:
        mode_info = f"Giới hạn: {args.count} đợt burst (hoặc bấm Ctrl + C để ngắt sớm)"

    print("\n" + "=" * 78)
    print(f"[*] BẮT ĐẦU BƠM HEAVY JITTER / MICROBURST (Chế độ: {args.mode.upper()})")
    print(f"    - Kích thước burst : {burst_min/1024:.1f} KB -> {burst_max/1024:.1f} KB")
    print(f"    - Quy mô thực thi  : {mode_info}")
    print(f"    - Chu kỳ kích hoạt : {interval_desc}")
    print(f"    - Nhãn IP TOS      : 0x02 (ECT-0 for DCTCP/ECN)")
    print(f"    - Tệp nhật ký GT   : {GROUND_TRUTH_CSV}")
    print("=" * 78 + "\n")

    start_time = time.time()
    burst_idx = 0
    total_bytes = 0

    try:
        while True:
            # Kiểm tra hết giờ nếu có cấu hình --duration
            if args.duration and (time.time() - start_time) >= args.duration:
                print(f"\n[*] Đã đạt thời gian hẹn giờ ({args.duration:,.0f}s). Kết thúc tiêm Heavy Jitter.")
                break

            # Kiểm tra hết số lượt nếu có cấu hình --count
            if args.count and burst_idx >= args.count:
                print(f"\n[*] Đã phát đủ {args.count} đợt burst. Kết thúc tiêm Heavy Jitter.")
                break

            # Tính toán thời gian nghỉ ngẫu nhiên hoặc cố định trước lượt kế tiếp
            if min_interval == max_interval:
                sleep_sec = min_interval
            else:
                sleep_sec = round(random.uniform(min_interval, max_interval), 2)

            burst_idx += 1
            if args.mode == "random":
                rec = run_random_burst(hosts, burst_min, burst_max)
                if rec:
                    total_bytes += rec["burst_bytes"]
                    print(f"[{time.strftime('%H:%M:%S')}] Burst #{burst_idx:03d}: {rec['src_host']} -> {rec['dst_host']} | {rec['burst_bytes']/1024:.1f} KB | {rec['duration_ms']:.2f} ms | {rec['rate_mbps']:.1f} Mbps | Nghỉ tiếp: {sleep_sec:.2f}s")
            elif args.mode == "incast":
                recs = run_incast_burst(hosts, args.target, burst_min, burst_max)
                for r in recs:
                    total_bytes += r.get("burst_bytes", 0)
                print(f"[{time.strftime('%H:%M:%S')}] Incast #{burst_idx:03d} tới {args.target} hoàn tất ({len(recs)} senders) | Nghỉ tiếp: {sleep_sec:.2f}s")

            time.sleep(sleep_sec)

    except KeyboardInterrupt:
        print("\n[!] Đã nhận tín hiệu ngắt (Ctrl + C). Đang dừng tiêm microburst...")
    finally:
        total_time_sec = time.time() - start_time
        print("\n" + "=" * 78)
        print("[*] TỔNG KẾT TIÊM HEAVY JITTER / MICROBURST:")
        print(f"    - Thời gian chạy thực tế : {total_time_sec / 60:.2f} phút ({total_time_sec:.1f} giây)")
        print(f"    - Tổng số đợt đã tiêm    : {burst_idx} đợt")
        print(f"    - Tổng dung lượng burst  : {total_bytes / 1024 / 1024:.2f} MB")
        print(f"    - Tệp nhật ký GT         : {GROUND_TRUTH_CSV}")
        print("=" * 78)
        cleanup_receiver_servers(hosts, BURST_PORT)


if __name__ == "__main__":
    main()
