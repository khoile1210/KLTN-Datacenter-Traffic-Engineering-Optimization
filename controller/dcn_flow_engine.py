#!/usr/bin/env python3
"""
Tên file: dcn_flow_engine.py
Mô tả   : Công cụ sinh và tiếp nhận luồng TCP chính xác cấp độ byte cho DCN Containernet:
          - Chế độ --server: Multi-threaded TCP Sink Server nhận luồng không giới hạn kết nối đồng thời.
          - Chế độ --client: Tạo kết nối TCP duy nhất, gửi chính xác N bytes dữ liệu (zero control overhead).
          - Khắc phục hoàn toàn lỗi phân mảnh khối (block quantization 128KB) và lỗi 327B của iperf3.
"""

import sys
import os
import socket
import time
import argparse
import threading

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

CHUNK_SIZE = 16384  # 16 KB chunks


def run_server(ports_str):
    ports = [int(p.strip()) for p in ports_str.split(",") if p.strip()]
    
    def serve_port(p):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        srv.bind(("0.0.0.0", p))
        srv.listen(256)
        
        while True:
            try:
                conn, _ = srv.accept()
                threading.Thread(target=handle_incoming, args=(conn,), daemon=True).start()
            except Exception:
                break
                
    def handle_incoming(conn):
        try:
            total_rcv = 0
            while True:
                data = conn.recv(CHUNK_SIZE)
                if not data:
                    break
                total_rcv += len(data)
            # Gửi 1-byte ACK xác nhận đã nhận trọn vẹn luồng trước khi đóng
            try:
                conn.sendall(b"K")
            except Exception:
                pass
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    threads = []
    for p in ports:
        t = threading.Thread(target=serve_port, args=(p,), daemon=True)
        t.start()
        threads.append(t)
        
    print(f"[+] DCN Flow Server đã khởi động trên các cổng {ports}")
    for t in threads:
        t.join()


def run_client(dst_ip, dst_port, total_bytes, bind_ip=None):
    total_bytes = int(total_bytes)
    if total_bytes <= 0:
        return
        
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
    if bind_ip:
        try:
            s.bind((bind_ip, 0))
        except Exception:
            pass
            
    try:
        s.connect((dst_ip, int(dst_port)))
        
        dummy_chunk = b"X" * min(CHUNK_SIZE, total_bytes)
        rem = total_bytes
        
        while rem > 0:
            send_size = min(len(dummy_chunk), rem)
            s.sendall(dummy_chunk[:send_size])
            rem -= send_size
            
        # Thông báo đóng chiều gửi để server gửi ACK
        s.shutdown(socket.SHUT_WR)
        
        # Đợi ACK xác nhận
        try:
            s.settimeout(2.0)
            s.recv(1)
        except Exception:
            pass
    except Exception as e:
        pass
    finally:
        try:
            s.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="DCN Precise Byte Flow Engine")
    parser.add_argument("--server", action="store_true", help="Chạy chế độ Server")
    parser.add_argument("--client", action="store_true", help="Chạy chế độ Client")
    parser.add_argument("-p", "--ports", default="5201,5202,5203,5204", help="Cổng server")
    parser.add_argument("-d", "--dest", default=None, help="Địa chỉ IP đích")
    parser.add_argument("-b", "--bytes", type=int, default=1024, help="Kích thước luồng cần truyền (Bytes)")
    parser.add_argument("-B", "--bind", default=None, help="Địa chỉ IP nguồn bind")
    
    args = parser.parse_args()
    
    if args.server:
        run_server(args.ports)
    elif args.client:
        if not args.dest:
            print("[!] Thiếu tham số --dest cho client!")
            sys.exit(1)
        port = int(args.ports.split(",")[0])
        run_client(args.dest, port, args.bytes, bind_ip=args.bind)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
