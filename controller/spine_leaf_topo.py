#!/usr/bin/env python3
"""
Tên file: spine_leaf_topo.py
Mô tả   : Topology Multi-tier Spine-Leaf chạy hoàn toàn trên DOCKER CONTAINERS (Containernet):
          - 2 Core Switches (c1, c2)
          - 4 Aggregation Switches (ag1 -> ag4)
          - 8 Access Switches (a1 -> a8)
          - 8 Docker Hosts nội bộ (h1 -> h8) dùng dimage="dcn-host:latest"
          - 1 Docker Host Internet (inet) dùng dimage="dcn-host:latest"
"""

import time
from mininet.net import Containernet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink

# ==============================================================================
# CẤU HÌNH CONTROLLER VÀ THÔNG SỐ LIÊN KẾT
# ==============================================================================
CONTROLLER_IP = "127.0.0.1"
CONTROLLER_PORT = 6653
OF_PROTOCOL = "OpenFlow13"
DOCKER_IMAGE = "dcn-host:latest"  # Image Docker đã build ở Bước 1

BW_CORE_INET = 100
BW_CORE_AGG = 100
BW_AGG_ACC = 50
BW_HOST_ACC = 20
LINK_DELAY = "1ms"


def build_docker_dcn():
    # Tắt autoStaticArp để Ryu Controller tự học vị trí qua ARP tự nhiên
    net = Containernet(
        controller=RemoteController,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=False
    )

    info("[*] Bước 1: Khởi tạo Ryu Remote Controller...\n")
    c0 = net.addController(
        name="c0",
        controller=RemoteController,
        ip=CONTROLLER_IP,
        port=CONTROLLER_PORT
    )

    info("[*] Bước 2: Khởi tạo các Switch theo 3 phân tầng...\n")
    # 2 Core Switches
    c1 = net.addSwitch("c1", dpid="0000000000000021", protocols=OF_PROTOCOL)
    c2 = net.addSwitch("c2", dpid="0000000000000022", protocols=OF_PROTOCOL)
    core_switches = [c1, c2]

    # 4 Aggregation Switches
    agg_switches = []
    for i in range(1, 5):
        sw = net.addSwitch(f"ag{i}", dpid=f"000000000000001{i}", protocols=OF_PROTOCOL)
        agg_switches.append(sw)

    # 8 Access Switches
    access_switches = []
    for i in range(1, 9):
        sw = net.addSwitch(f"a{i}", dpid=f"000000000000000{i}", protocols=OF_PROTOCOL)
        access_switches.append(sw)

    info("[*] Bước 3: Khởi tạo 8 Docker Hosts nội bộ và 1 Docker Host Internet...\n")
    # Khởi tạo 8 Docker container đóng vai trò Hosts nội bộ
    hosts = {}
    for i in range(1, 9):
        h_name = f"h{i}"
        hosts[h_name] = net.addDocker(
            h_name,
            ip=f"10.0.0.{i}/24",
            mac=f"00:00:00:00:00:0{i}",
            dimage=DOCKER_IMAGE
        )

    # Khởi tạo 1 Docker container đóng vai trò Internet
    inet_host = net.addDocker(
        "inet",
        ip="10.0.0.100/24",
        mac="00:00:00:00:00:99",
        dimage=DOCKER_IMAGE
    )

    info("[*] Bước 4: Thiết lập liên kết tầng kề (Full-Mesh)...\n")
    # Internet nối vào cả 2 Core Switches
    net.addLink(c1, inet_host, bw=BW_CORE_INET, delay=LINK_DELAY)
    net.addLink(c2, inet_host, bw=BW_CORE_INET, delay=LINK_DELAY)

    # Core <-> Aggregation (Full-mesh giữa 2 Core và 4 Aggregation)
    for ag_sw in agg_switches:
        for c_sw in core_switches:
            net.addLink(c_sw, ag_sw, bw=BW_CORE_AGG, delay=LINK_DELAY)

    # Aggregation <-> Access (Mỗi Access nối lên cả 4 Aggregation)
    for a_sw in access_switches:
        for ag_sw in agg_switches:
            net.addLink(ag_sw, a_sw, bw=BW_AGG_ACC, delay=LINK_DELAY)

    # Access <-> Docker Hosts (Mỗi Host cắm vào 1 Switch Access tương ứng)
    for i in range(8):
        net.addLink(access_switches[i], hosts[f"h{i+1}"], bw=BW_HOST_ACC)

    info("[*] Bước 5: Khởi động mạng và các switch OVS...\n")
    net.build()
    c0.start()
    for sw in core_switches + agg_switches + access_switches:
        sw.start([c0])

    # Thiết lập default route cho container Internet
    inet_host.cmd("ip route add default dev inet-eth0")

    info("[+] Đang đợi 2s để Ryu Controller quét cấu trúc liên kết qua LLDP...\n")
    time.sleep(2)

    info("[+] Topology DCN chạy Docker Container đã sẵn sàng!\n")
    CLI(net)

    info("[*] Đang dừng hạ tầng mạng Mininet...\n")
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    build_docker_dcn()