#!/usr/bin/env python3
"""
Tên file: spine_leaf_topo.py
Mô tả   : Topology Multi-tier Spine-Leaf chạy hoàn toàn trên DOCKER CONTAINERS (Containernet):
          - Đọc toàn diện cấu hình từ controller/topology_config.json
          - Quản lý tài nguyên riêng biệt (CPU Quota/Period, RAM Limit/Swap) cho từng Switch và Host
          - Tham chiếu phần cứng thực tế Facebook (Wedge 40 ToR, 6-pack Fabric, Winterfell Servers)
          - 2 Core Switches (c1, c2)
          - 4 Aggregation Switches (ag1 -> ag4)
          - 8 Access Switches (a1 -> a8) đại diện cho 8 tủ Rack (RSW / Top-of-Rack)
          - 32 Docker Hosts nội bộ (Mặc định 1 Rack = 4 Hosts: h1_1..h1_4 -> h8_1..h8_4)
          - 1 Docker Host Internet (inet)
          - Nhúng cổng nội bộ NFV Proxy (proxy-int) trên Access Leaf Switches
"""

import os
import sys
import json
import time
from mininet.net import Containernet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink

# ==============================================================================
# NẠP CẤU HÌNH TỪ TOPOLOGY_CONFIG.JSON (CÓ FALLBACK AN TOÀN)
# ==============================================================================
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "topology_config.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Cảnh báo lỗi đọc {CONFIG_FILE}: {e}. Dùng giá trị mặc định.")
    return {}


def load_ecn_settings():
    """Nạp cấu hình ECN ưu tiên từ traffic_config.json (nơi quản trị tập trung) với fallback an toàn."""
    traffic_file = os.path.join(os.path.dirname(__file__), "traffic_config.json")
    if os.path.exists(traffic_file):
        try:
            with open(traffic_file, "r", encoding="utf-8") as tf:
                tdata = json.load(tf)
                if "ecn_settings" in tdata:
                    return tdata["ecn_settings"]
        except Exception:
            pass
    ecn_raw = cfg.get("ecn", {})
    k_val = ecn_raw.get("marking_threshold_k_bytes", 30000)
    if isinstance(k_val, str) and k_val.startswith("ref:"):
        k_val = 30000
    return {
        "enabled": True,
        "marking_threshold_k_bytes": int(k_val),
        "limit_bytes": 1500000
    }


cfg = load_config()

# 1. Controller settings
ctrl_cfg = cfg.get("controller", {})
CONTROLLER_IP = ctrl_cfg.get("ip", "127.0.0.1")
CONTROLLER_PORT = int(ctrl_cfg.get("port", 6653))
OF_PROTOCOL = ctrl_cfg.get("protocol", "OpenFlow13")

# 2. Switch settings & Resources
sw_cfg = cfg.get("switches", {})
SWITCH_TYPE = sw_cfg.get("switch_type", "docker_ovs")
SW_DOCKER_IMAGE = sw_cfg.get("dimage", "dcn-ovs:latest")

NUM_CORE = sw_cfg.get("core", {}).get("count", 2)
CORE_RES = sw_cfg.get("core", {}).get("resources", {
    "cpu_quota": 100000, "cpu_period": 100000, "cpu_shares": 1024, "mem_limit": "1024m", "memswap_limit": "2048m"
})

NUM_AGG = sw_cfg.get("aggregation", {}).get("count", 4)
AGG_RES = sw_cfg.get("aggregation", {}).get("resources", {
    "cpu_quota": 100000, "cpu_period": 100000, "cpu_shares": 1024, "mem_limit": "1024m", "memswap_limit": "2048m"
})

NUM_ACCESS = sw_cfg.get("access", {}).get("count", 8)
ACCESS_RES = sw_cfg.get("access", {}).get("resources", {
    "cpu_quota": 100000, "cpu_period": 100000, "cpu_shares": 1024, "mem_limit": "1024m", "memswap_limit": "2048m"
})

# 3. Links settings
links_cfg = cfg.get("links", {})
bw_cfg = links_cfg.get("bandwidth_mbps", {})
BW_CORE_INET = bw_cfg.get("core_inet", 100)
BW_CORE_AGG = bw_cfg.get("core_agg", 100)
BW_AGG_ACC = bw_cfg.get("agg_access", 50)
BW_HOST_ACC = bw_cfg.get("access_host", 20.0)
LINK_DELAY = links_cfg.get("delay", "1ms")
MAX_QUEUE = links_cfg.get("max_queue_size_packets", 1000)

# 4. Host settings & Resources
hosts_cfg = cfg.get("hosts", {})
DOCKER_IMAGE = hosts_cfg.get("dimage", "dcn-host:latest")
HOSTS_PER_RACK = int(hosts_cfg.get("hosts_per_rack", 4))
NUM_HOSTS = int(hosts_cfg.get("total_hosts", NUM_ACCESS * HOSTS_PER_RACK))
IP_PREFIX = hosts_cfg.get("ip_prefix", "10.0.0.")
SUBNET_MASK = hosts_cfg.get("subnet_mask", "/24")
HOST_RES = hosts_cfg.get("resources", {
    "cpu_quota": 100000, "cpu_period": 100000, "cpu_shares": 1024, "mem_limit": "1024m", "memswap_limit": "2048m"
})

INET_NODE = hosts_cfg.get("inet_node", {
    "name": "inet",
    "ip": "10.0.0.254/24",
    "mac": "00:00:00:00:00:99",
    "default_gw_dev": "inet-eth0",
    "resources": {
        "cpu_quota": 100000, "cpu_period": 100000, "cpu_shares": 1024, "mem_limit": "1024m", "memswap_limit": "2048m"
    }
})
INET_RES = INET_NODE.get("resources", HOST_RES)

# 5. NFV Proxy settings
proxy_cfg = cfg.get("nfv_proxy", {})
ENABLE_PROXY_INT = proxy_cfg.get("enable", True)
PROXY_PORT_NAME = proxy_cfg.get("port_name", "proxy-int")
PROXY_SUBNET_PREFIX = proxy_cfg.get("subnet_prefix", "10.255.0.")
PROXY_SUBNET_MASK = proxy_cfg.get("subnet_mask", "/24")


def build_docker_dcn():
    # Tắt autoStaticArp để Ryu Controller tự học vị trí qua ARP tự nhiên
    net = Containernet(
        controller=RemoteController,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=False
    )

    info("\n" + "=" * 80 + "\n")
    info("[*] KHỞI TẠO TOPOLOGY SPINE-LEAF DOCKER DCN (CONTAINERNET)\n")
    info(f"    - Controller        : {CONTROLLER_IP}:{CONTROLLER_PORT} ({OF_PROTOCOL})\n")
    info(f"    - Mô hình Switch    : {SWITCH_TYPE} (Core: {NUM_CORE}, Agg: {NUM_AGG}, Access: {NUM_ACCESS})\n")
    info(f"    - Tài nguyên Switch : CPU Limit={ACCESS_RES.get('cpus', 1.0)} Core ({ACCESS_RES.get('cpu_quota', 100000)}us), RAM Limit={ACCESS_RES.get('mem_limit', '1024m')}\n")
    info(f"    - Tài nguyên Host   : CPU Limit={HOST_RES.get('cpus', 1.0)} Core ({HOST_RES.get('cpu_quota', 100000)}us), RAM Limit={HOST_RES.get('mem_limit', '1024m')}\n")
    info(f"    - Phân bố Host      : {NUM_ACCESS} Racks x {HOSTS_PER_RACK} Hosts = {NUM_HOSTS} Hosts nội bộ + 1 Inet Node\n")
    info(f"    - Băng thông phân tầng: Host={BW_HOST_ACC}M | Agg-Access={BW_AGG_ACC}M | Core-Agg={BW_CORE_AGG}M | Inet={BW_CORE_INET}M\n")
    info("=" * 80 + "\n\n")

    info(f"[*] Bước 1: Khởi tạo Ryu Remote Controller ({CONTROLLER_IP}:{CONTROLLER_PORT})...\n")
    c0 = net.addController(
        name="c0",
        controller=RemoteController,
        ip=CONTROLLER_IP,
        port=CONTROLLER_PORT
    )

    info("[*] Bước 2: Khởi tạo các Switch theo 3 phân tầng Spine-Leaf...\n")
    # Core Switches (c1, c2, ...)
    core_switches = []
    for i in range(1, NUM_CORE + 1):
        dpid_hex = f"000000000000002{i}"
        sw = net.addSwitch(f"c{i}", dpid=dpid_hex, protocols=OF_PROTOCOL)
        core_switches.append(sw)

    # Aggregation Switches (ag1 -> ag4, ...)
    agg_switches = []
    for i in range(1, NUM_AGG + 1):
        dpid_hex = f"000000000000001{i}"
        sw = net.addSwitch(f"ag{i}", dpid=dpid_hex, protocols=OF_PROTOCOL)
        agg_switches.append(sw)

    # Access Switches (a1 -> a8, ...)
    access_switches = []
    for i in range(1, NUM_ACCESS + 1):
        dpid_hex = f"000000000000000{i}"
        sw = net.addSwitch(f"a{i}", dpid=dpid_hex, protocols=OF_PROTOCOL)
        access_switches.append(sw)

    info(f"[*] Bước 3: Khởi tạo {NUM_HOSTS} Docker Hosts nội bộ ({HOSTS_PER_RACK} hosts/rack) và node Internet với tài nguyên riêng biệt...\n")
    hosts = {}
    for r in range(1, NUM_ACCESS + 1):
        for h in range(1, HOSTS_PER_RACK + 1):
            h_name = f"h{r}_{h}"
            host_idx = (r - 1) * HOSTS_PER_RACK + h
            hosts[h_name] = net.addDocker(
                h_name,
                ip=f"{IP_PREFIX}{host_idx}{SUBNET_MASK}",
                mac=f"00:00:00:00:{r:02x}:{h:02x}",
                dimage=DOCKER_IMAGE,
                cpu_quota=HOST_RES.get("cpu_quota", 100000),
                cpu_period=HOST_RES.get("cpu_period", 100000),
                cpu_shares=HOST_RES.get("cpu_shares", 1024),
                mem_limit=HOST_RES.get("mem_limit", "1024m"),
                memswap_limit=HOST_RES.get("memswap_limit", "2048m")
            )

    # Node Internet ngoài DCN với tài nguyên độc lập
    inet_host = net.addDocker(
        INET_NODE["name"],
        ip=INET_NODE["ip"],
        mac=INET_NODE["mac"],
        dimage=DOCKER_IMAGE,
        cpu_quota=INET_RES.get("cpu_quota", 100000),
        cpu_period=INET_RES.get("cpu_period", 100000),
        cpu_shares=INET_RES.get("cpu_shares", 1024),
        mem_limit=INET_RES.get("mem_limit", "1024m"),
        memswap_limit=INET_RES.get("memswap_limit", "2048m")
    )

    info(f"[*] Bước 4: Thiết lập liên kết tầng kề (Full-Mesh | Host Link: {BW_HOST_ACC} Mbps)...\n")
    # Internet nối vào toàn bộ Core Switches
    for c_sw in core_switches:
        net.addLink(c_sw, inet_host, bw=BW_CORE_INET, delay=LINK_DELAY, max_queue_size=MAX_QUEUE)

    # Core <-> Aggregation (Toàn bộ Aggregation nối lên Core Switches)
    for ag_sw in agg_switches:
        for c_sw in core_switches:
            net.addLink(c_sw, ag_sw, bw=BW_CORE_AGG, delay=LINK_DELAY, max_queue_size=MAX_QUEUE)

    # Aggregation <-> Access: Tự động nhận diện cấu hình Cụm (Cluster-Aware)
    clusters_cfg = cfg.get("clusters", {})
    is_clustered = clusters_cfg.get("enabled", False)

    if is_clustered:
        info("[*] Cấu hình Cụm (Cluster-Aware): Thiết lập liên kết theo 2 Cụm Facebook (Hình 1)...\n")
        sw_name_map = {sw.name: sw for sw in (agg_switches + access_switches)}
        for cl_key in ["cluster_1", "cluster_2"]:
            cl_info = clusters_cfg.get(cl_key, {})
            cl_aggs = [sw_name_map[name] for name in cl_info.get("aggregation_switches", []) if name in sw_name_map]
            cl_access = [sw_name_map[name] for name in cl_info.get("access_switches", []) if name in sw_name_map]
            for a_sw in cl_access:
                for ag_sw in cl_aggs:
                    net.addLink(ag_sw, a_sw, bw=BW_AGG_ACC, delay=LINK_DELAY, max_queue_size=MAX_QUEUE)
    else:
        info("[*] Cấu hình Phẳng (Flat Mesh): Thiết lập liên kết Full-Mesh giữa toàn bộ Access và Aggregation...\n")
        for a_sw in access_switches:
            for ag_sw in agg_switches:
                net.addLink(ag_sw, a_sw, bw=BW_AGG_ACC, delay=LINK_DELAY, max_queue_size=MAX_QUEUE)

    # Access <-> Docker Hosts (Mỗi Rack có HOSTS_PER_RACK hosts cắm vào switch Access a{r} tương ứng)
    for r_idx, a_sw in enumerate(access_switches):
        r = r_idx + 1
        for h in range(1, HOSTS_PER_RACK + 1):
            h_name = f"h{r}_{h}"
            net.addLink(a_sw, hosts[h_name], bw=BW_HOST_ACC, delay=LINK_DELAY, max_queue_size=MAX_QUEUE)

    info("[*] Bước 5: Khởi động mạng và các switch OVS...\n")
    net.build()
    c0.start()
    for sw in core_switches + agg_switches + access_switches:
        sw.start([c0])

    # Thiết lập default route cho container Internet
    inet_gw_dev = INET_NODE.get("default_gw_dev", "inet-eth0")
    inet_host.cmd(f"ip route add default dev {inet_gw_dev}")

    # Bước 5.1: Thiết lập cổng nội bộ NFV Proxy (proxy-int) trên Access Leaf Switches
    if ENABLE_PROXY_INT:
        info("[*] Bước 5.1: Thiết lập cổng nội bộ NFV Proxy trên Access Leaf Switches...\n")
        for i, a_sw in enumerate(access_switches):
            sw_name = a_sw.name
            proxy_ip = f"{PROXY_SUBNET_PREFIX}{i+1}{PROXY_SUBNET_MASK}"
            a_sw.cmd(f"ovs-vsctl add-port {sw_name} {PROXY_PORT_NAME} -- set Interface {PROXY_PORT_NAME} type=internal")
            a_sw.cmd(f"ip addr add {proxy_ip} dev {PROXY_PORT_NAME}")
            a_sw.cmd(f"ip link set dev {PROXY_PORT_NAME} up")
            info(f"    - Switch {sw_name}: Cổng '{PROXY_PORT_NAME}' sẵn sàng (IP: {proxy_ip})\n")

    # Bước 5.2: Kích hoạt ECN (Explicit Congestion Notification) & Ngưỡng đánh dấu K
    ecn_cfg = load_ecn_settings()
    if ecn_cfg.get("enabled", True):
        k_bytes = int(ecn_cfg.get("marking_threshold_k_bytes", 30000))
        info(f"[*] Bước 5.2: Kích hoạt ECN trên Hosts (tcp_ecn=1) và cấu hình RED/ECN (K={k_bytes} B) quản trị từ traffic_config.json...\n")
        for h_name, h_obj in hosts.items():
            h_obj.cmd("sysctl -w net.ipv4.tcp_ecn=1")
        inet_host.cmd("sysctl -w net.ipv4.tcp_ecn=1")

        for sw in access_switches + agg_switches:
            for intf in sw.intfList():
                if intf.name != "lo" and PROXY_PORT_NAME not in intf.name:
                    sw.cmd(f"tc qdisc add dev {intf.name} parent 5:1 handle 10: red limit 1500000 min {k_bytes} max {k_bytes + 5000} avpkt 1500 burst 25 ecn probability 1.0 2>/dev/null || true")

    info("[+] Đang đợi 2s để Ryu Controller quét cấu trúc liên kết qua LLDP...\n")
    time.sleep(2)

    info("[+] Topology DCN chạy Docker Container với tài nguyên cô lập đã sẵn sàng!\n")
    CLI(net)

    info("[*] Đang dừng hạ tầng mạng Mininet...\n")
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    build_docker_dcn()