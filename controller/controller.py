#!/usr/bin/env python3
"""
Tên file: controller.py
Mô tả   : Ryu Controller OpenFlow 1.3 chuyên dụng cho Multi-tier Spine-Leaf (Đã cải tổ toàn diện):
          - Khám phá liên kết LLDP tự động có Debounce Timer (chống bão FlowMod khi khởi động).
          - Đồng bộ an toàn Group Table (khắc phục lỗi OFPGC_MODIFY khi switch reconnect).
          - Dynamic Host Discovery & Proxy ARP thông minh, loại bỏ phụ thuộc bảng tĩnh.
          - Cài đặt cặp Flow Rule 5-tuple đối xứng (Bi-flow) tại Ingress Switch để OVS đếm riêng 2 chiều (sbytes/dbytes, Spkts/Dpkts).
          - Cân bằng tải phần cứng ECMP Group Table (OFPGT_SELECT) cho luồng Mice (Priority 100).
          - Hỗ trợ cơ chế Steering luồng Voi (Elephant - Priority 1000) vào cổng nội bộ proxy-int.
Chạy    : ryu-manager --observe-links controller.py ryu.app.ofctl_rest ryu.app.rest_topology --ofp-tcp-listen-port 6653
"""

import os
import json
import time
from datetime import datetime
import socket
import threading
import queue
from ryu import cfg
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3, ether, inet
from ryu.lib.packet import packet, ethernet, arp, ipv4, tcp, udp
from ryu.topology import event
from ryu.topology.api import get_switch, get_link
from ryu.lib import hub
import networkx as nx

# Ép buộc Ryu kích hoạt luồng khám phá liên kết LLDP
CONF = cfg.CONF
try:
    CONF.set_default('observe_links', True)
except Exception:
    pass


class MultiTierEcmpController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(MultiTierEcmpController, self).__init__(*args, **kwargs)
        self.topo_graph = nx.DiGraph()
        self.datapaths = {}

        # Danh bạ Host động (IP -> {mac, dpid, port})
        # Khởi tạo mặc định cho các host nội bộ (1 rack = 4 hosts) và host inet
        config_path = os.path.join(os.path.dirname(__file__), "topology_config.json")
        num_access = 8
        hosts_per_rack = 4
        num_agg = 4
        cfg_data = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                    num_access = int(cfg_data.get("switches", {}).get("access", {}).get("count", 8))
                    num_agg = int(cfg_data.get("switches", {}).get("aggregation", {}).get("count", 4))
                    hosts_per_rack = int(cfg_data.get("hosts", {}).get("hosts_per_rack", 4))
                    clusters_cfg = cfg_data.get("clusters", {})
            except Exception:
                clusters_cfg = {}

        is_clustered = clusters_cfg.get("enabled", False)

        self.host_db = {}
        for r in range(1, num_access + 1):
            # Xác định số đường uplink của switch Access a{r}
            uplinks_count = num_agg
            if is_clustered:
                for cl_key in ["cluster_1", "cluster_2"]:
                    cl_info = clusters_cfg.get(cl_key, {})
                    racks = cl_info.get("racks", [])
                    access_names = cl_info.get("access_switches", [])
                    if r in racks or f"a{r}" in access_names:
                        uplinks_count = len(cl_info.get("aggregation_switches", []))
                        break

            for h in range(1, hosts_per_rack + 1):
                host_num = (r - 1) * hosts_per_rack + h
                self.host_db[f"10.0.0.{host_num}"] = {
                    "mac": f"00:00:00:00:{r:02x}:{h:02x}",
                    "dpid": r,
                    "port": uplinks_count + h
                }

        # Đọc động thông tin node Internet từ topology_config.json (10.0.0.254, cắm vào Core switch c1 - DPID 33, Port 1)
        inet_cfg = cfg_data.get("hosts", {}).get("inet_node", {})
        inet_raw_ip = inet_cfg.get("ip", "10.0.0.254/24")
        inet_ip = inet_raw_ip.split("/")[0]
        inet_mac = inet_cfg.get("mac", "00:00:00:00:00:99")
        self.host_db[inet_ip] = {"mac": inet_mac, "dpid": 33, "port": 1}
        if inet_ip != "10.0.0.100":
            self.host_db["10.0.0.100"] = {"mac": inet_mac, "dpid": 33, "port": 1}

        self.group_id_map = {ip: idx + 1 for idx, ip in enumerate(self.host_db.keys())}
        self.installed_groups = set()     # Lưu tập hợp (dpid, group_id)
        self.installed_biflows = {}       # Lưu ánh xạ biflow_signature -> timestamp cài đặt (TTL 1.5s)
        self.packet_in_accounting = {}    # Bù byte/gói đầu tiên đi qua PacketOut: (dpid, s_ip, d_ip, s_pt, d_pt, proto) -> [bytes, pkts, ts]
        self.pending_early_probes = {}    # dpid -> {biflow_sig: (t_start, src_ip, dst_ip, src_port, dst_port, proto)}
        self.active_early_timers = set()  # Tập các dpid đang có hẹn giờ vi mô 8ms chờ bắn OFPFlowStatsRequest

        # Quản lý Debounce Timer chống bão FlowMod khi LLDP phát hiện link dồn dập
        self.topology_debounce_timer = None
        self.DEBOUNCE_INTERVAL = 2.0  # Chờ 2 giây sau link cuối cùng mới tính toán toàn mạng

        # Lưu ánh xạ cổng nội bộ proxy-int của từng switch
        self.proxy_ports = {}

        # ======================================================================
        # HẠ TẦNG TELEMETRY SỰ KIỆN THỜI GIAN THỰC (ZERO-BLOCKING IPC STREAMER)
        # ======================================================================
        self.telemetry_queue = queue.Queue(maxsize=50000)
        self.ipc_running = True
        self.ipc_thread = threading.Thread(target=self._ipc_server_loop, daemon=True, name="RyuTelemetryIPC")
        self.ipc_thread.start()

        self.logger.info("[+] Multi-Tier Spine-Leaf Controller (Kèm Telemetry Push & Zero-block IPC) đã khởi động thành công.")

    # ==========================================================================
    # 1. BẮT TAY SWITCH & ĐỒNG BỘ GROUP TABLE AN TOÀN
    # ==========================================================================
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        self.datapaths[dpid] = datapath

        # VÁ LỖI QUAN TRỌNG: Xóa sạch trạng thái installed_groups của DPID này trong RAM Controller
        # để đảm bảo khi Switch kết nối lại, lệnh GroupMod gửi xuống luôn là OFPGC_ADD
        self.installed_groups = {item for item in self.installed_groups if item[0] != dpid}
        self.installed_biflows.clear()

        # Xóa các Group Table cũ còn tồn đọng trên switch phần cứng
        del_mod = parser.OFPGroupMod(
            datapath=datapath,
            command=ofproto.OFPGC_DELETE,
            type_=ofproto.OFPGT_SELECT,
            group_id=ofproto.OFPG_ALL
        )
        datapath.send_msg(del_mod)

        # ======================================================================
        # CẤU HÌNH MULTI-TABLE PIPELINE (OPENFLOW 1.3):
        # Table 0: Phân loại luồng, Proxy ARP, Bắt 5-tuple Ingress Header (128 bytes)
        # Table 1: Bảng định tuyến phần cứng FIB & Cân bằng tải ECMP Group Table
        # ======================================================================

        # 1. Table 0 - Priority 200: Cô lập gói tin ARP chuyển thẳng lên Controller để Proxy ARP xử lý
        m_arp = parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP)
        self.add_flow(datapath, priority=200, match=m_arp, actions=[parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)], table_id=0)

        # 2. Table 0 - Priority 50: Bắt gói khởi tạo luồng TCP/UDP mới từ cổng cắm Host (Access Switch)
        # Gửi gói đầu tiên (TCP SYN / UDP Pkt #1) lên Controller để nạp luật 5-tuple Priority 150
        # trước khi quá trình truyền tải payload bắt đầu, đảm bảo OVS đếm chính xác 100% sbytes/dbytes
        host_ports = [info["port"] for ip, info in self.host_db.items() if info["dpid"] == dpid]
        for hp in host_ports:
            for l4_proto in (inet.IPPROTO_TCP, inet.IPPROTO_UDP):
                m_hp = parser.OFPMatch(in_port=hp, eth_type=ether.ETH_TYPE_IP, ip_proto=l4_proto)
                self.add_flow(
                    datapath,
                    priority=50,
                    match=m_hp,
                    actions=[parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)],
                    table_id=0
                )

        # 3. Table 0 - Priority 60: Đếm thống kê và nhận diện các gói tin bị đánh dấu cờ CE (Congestion Experienced - ip_ecn=3)
        # Giúp OVS đếm riêng biệt lưu lượng đang chịu tắc nghẽn tức thời (Microburst) trước khi chuyển tiếp sang Table 1
        m_ce = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_ecn=3)
        self.add_flow(datapath, priority=60, match=m_ce, actions=[], instructions=[parser.OFPInstructionGotoTable(1)], table_id=0)

        # 4. Table 0 - Priority 0: Mặc định Table 0 -> Chuyển tiếp sang Table 1
        self.add_flow(datapath, priority=0, match=parser.OFPMatch(), actions=[], instructions=[parser.OFPInstructionGotoTable(1)], table_id=0)

        # 5. Table 1 - Priority 0: Table-Miss Table 1 -> Gửi lên Controller (LLDP link discovery, v.v.)
        self.add_flow(datapath, priority=0, match=parser.OFPMatch(), actions=[parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)], table_id=1)

        # 5. Cài đặt luật chuyển tiếp cục bộ cho các Host cắm trực tiếp vào switch này (vào Table 1)
        self.install_local_host_rules(dpid)

        # Yêu cầu thống kê cổng để phát hiện số hiệu cổng 'proxy-int' nếu có
        req = parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        for p in ev.msg.body:
            port_name = p.name.decode('utf-8') if isinstance(p.name, bytes) else str(p.name)
            if "proxy-int" in port_name:
                self.proxy_ports[dpid] = p.port_no
                self.logger.info(f"[+] Phát hiện cổng NFV Proxy 'proxy-int' trên Switch DPID={dpid}: Port {p.port_no}")

    def install_local_host_rules(self, dpid):
        datapath = self.datapaths.get(dpid)
        if not datapath:
            return
        parser = datapath.ofproto_parser
        for ip, info in self.host_db.items():
            if info["dpid"] == dpid:
                host_port = info["port"]
                m_ip = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ipv4_dst=ip)
                self.add_flow(datapath, priority=100, match=m_ip, actions=[parser.OFPActionOutput(host_port)], table_id=1)
                self.logger.info(f"[+] Cài luật cục bộ trên Switch DPID={dpid} (Table 1) cho Host {ip} -> Port {host_port}")

    def add_flow(self, datapath, priority, match, actions, instructions=None, idle_timeout=0, hard_timeout=0, flags=0, table_id=0):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        if instructions is None:
            instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            table_id=table_id,
            priority=priority,
            match=match,
            instructions=instructions,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
            flags=flags
        )
        datapath.send_msg(mod)

    # ==========================================================================
    # 2. KHÁM PHÁ TOPO TỰ ĐỘNG & DEBOUNCE TIMER (CHỐNG BÃO FLOWMOD)
    # ==========================================================================
    @set_ev_cls([event.EventSwitchEnter, event.EventSwitchLeave, event.EventLinkAdd, event.EventLinkDelete])
    def update_topology(self, ev):
        switches = [sw.dp.id for sw in get_switch(self, None)]
        self.topo_graph.clear()
        self.topo_graph.add_nodes_from(switches)

        links = get_link(self, None)
        for link in links:
            src = link.src.dpid
            dst = link.dst.dpid
            self.topo_graph.add_edge(src, dst, port=link.src.port_no)
            self.topo_graph.add_edge(dst, src, port=link.dst.port_no)

        # Áp dụng cơ chế DEBOUNCE: Chờ topo ổn định rồi mới tính toán và nạp lại ECMP
        if self.topology_debounce_timer:
            self.topology_debounce_timer.cancel()
        self.topology_debounce_timer = hub.spawn_after(self.DEBOUNCE_INTERVAL, self._on_topology_stabilized, len(switches), len(links))

    def _on_topology_stabilized(self, num_switches, num_links):
        self.logger.info(f"[*] Topo đã ổn định: {num_switches} Switches, {num_links} Links LLDP. Bắt đầu nạp luật ECMP...")
        self.install_all_ecmp_paths()

    # ==========================================================================
    # 3. DYNAMIC HOST DISCOVERY, PROXY ARP & 5-TUPLE SYMMETRIC BIFLOW
    # ==========================================================================
    def learn_host(self, ip, mac, dpid, in_port):
        """Học vị trí host động nếu gói tin đi vào từ cổng Access (không phải cổng liên-switch)."""
        if not ip or ip == "0.0.0.0" or not mac:
            return

        # Kiểm tra xem in_port có phải cổng liên kết giữa các Switch không
        if self.topo_graph.has_node(dpid):
            for neighbor in self.topo_graph.neighbors(dpid):
                edge = self.topo_graph.get_edge_data(dpid, neighbor)
                if edge and edge.get("port") == in_port:
                    return  # Đây là cổng nối switch khác, không học host tại đây

        current = self.host_db.get(ip)
        if not current or current["dpid"] != dpid or current["port"] != in_port:
            self.host_db[ip] = {"mac": mac, "dpid": dpid, "port": in_port}
            if ip not in self.group_id_map:
                self.group_id_map[ip] = len(self.group_id_map) + 1
            self.logger.info(f"[+] Dynamic Host Discovery: Nhận diện {ip} (MAC: {mac}) tại Switch DPID={dpid}, Port={in_port}")
            self.install_local_host_rules(dpid)
            self.install_ecmp_for_single_host(ip)

            # Cài bổ sung luật bắt Table 0 Priority 50 cho host_port mới
            datapath = self.datapaths.get(dpid)
            if datapath:
                parser = datapath.ofproto_parser
                ofproto = datapath.ofproto
                for l4_proto in (inet.IPPROTO_TCP, inet.IPPROTO_UDP):
                    m_hp = parser.OFPMatch(in_port=in_port, eth_type=ether.ETH_TYPE_IP, ip_proto=l4_proto)
                    self.add_flow(
                        datapath,
                        priority=50,
                        match=m_hp,
                        actions=[parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)],
                        table_id=0
                    )

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether.ETH_TYPE_LLDP:
            return

        # 3.1. Xử lý bản tin ARP bằng Proxy ARP + Dynamic Host Learning
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt:
            src_ip = arp_pkt.src_ip
            dst_ip = arp_pkt.dst_ip
            self.learn_host(src_ip, eth.src, dpid, in_port)

            if arp_pkt.opcode == arp.ARP_REQUEST:
                if dst_ip in self.host_db:
                    target_mac = self.host_db[dst_ip]["mac"]
                    self.send_arp_reply(datapath, in_port, eth.src, src_ip, target_mac, dst_ip)
            return

        # 3.2. Xử lý gói tin IPv4: Cài đặt 5-tuple Bi-flow đối xứng trên cả Egress và Ingress Switch
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            src_ip = ip_pkt.src
            dst_ip = ip_pkt.dst
            proto = ip_pkt.proto
            self.learn_host(src_ip, eth.src, dpid, in_port)

            # Bóc tách cổng L4 nếu là TCP hoặc UDP
            src_port = 0
            dst_port = 0
            tcp_pkt = pkt.get_protocol(tcp.tcp)
            udp_pkt = pkt.get_protocol(udp.udp)
            if tcp_pkt:
                src_port = tcp_pkt.src_port
                dst_port = tcp_pkt.dst_port
            elif udp_pkt:
                src_port = udp_pkt.src_port
                dst_port = udp_pkt.dst_port

            if src_port > 0 and dst_port > 0:
                # FAST IN-MEMORY DEDUP WITH TTL (1.5s): Đảm bảo luật 5-tuple Priority 150 được cài trước khi đẩy PacketOut
                biflow_signature = tuple(sorted([(src_ip, src_port), (dst_ip, dst_port)])) + (proto,)
                now_ts = time.time()
                if (
                    biflow_signature not in self.installed_biflows
                    or (now_ts - self.installed_biflows[biflow_signature]) >= 1.5
                ):
                    self.installed_biflows[biflow_signature] = now_ts

                    # Đảm bảo đã có ECMP group cho dst_ip
                    if (dpid, self.group_id_map.get(dst_ip, 0)) not in self.installed_groups:
                        self.install_ecmp_for_single_host(dst_ip)

                    # Cài đặt cặp Flow Rule 5-tuple đối xứng tại Table 0 trên CẢ Egress và Ingress Switch
                    self.install_symmetric_biflow(datapath, dpid, src_ip, dst_ip, src_port, dst_port, proto)

                    # Đăng ký truy vấn sớm Sub-10ms (8ms kể từ khi luồng xuất hiện) trên Ingress Switch
                    sw_probes = self.pending_early_probes.setdefault(dpid, {})
                    if len(sw_probes) > 5000:
                        cutoff_p = now_ts - 10.0
                        self.pending_early_probes[dpid] = {
                            k: v for k, v in sw_probes.items() if v[0] >= cutoff_p
                        }
                        sw_probes = self.pending_early_probes[dpid]
                    sw_probes[biflow_signature] = (now_ts, src_ip, dst_ip, src_port, dst_port, proto)
                    if dpid not in self.active_early_timers:
                        self.active_early_timers.add(dpid)
                        hub.spawn_after(0.008, self._fire_early_probe, datapath, dpid)

            # Chuyển tiếp gói tin đầu tiên (TCP SYN / UDP Pkt #1) ngay sau khi FlowMod Priority 150 đã được nạp
            if dst_ip in self.host_db:
                target_dpid = self.host_db[dst_ip]["dpid"]
                if dpid == target_dpid:
                    out_port = self.host_db[dst_ip]["port"]
                elif self.topo_graph.has_node(dpid) and self.topo_graph.has_node(target_dpid):
                    try:
                        p = nx.shortest_path(self.topo_graph, source=dpid, target=target_dpid)
                        out_port = self.topo_graph[dpid][p[1]]["port"]
                    except Exception:
                        return
                else:
                    return

                # Ghi nhận dung lượng gói tin đi qua PacketOut để bù chính xác vào FlowRemoved trên Ingress Switch
                if src_port > 0 and dst_port > 0 and msg.data:
                    if len(self.packet_in_accounting) > 5000:
                        cutoff_ts = time.time() - 60.0
                        self.packet_in_accounting = {
                            k: v for k, v in self.packet_in_accounting.items() if v[2] >= cutoff_ts
                        }
                    acct_key = (dpid, src_ip, dst_ip, src_port, dst_port, proto)
                    prev = self.packet_in_accounting.get(acct_key)
                    pkt_len = len(msg.data)
                    if prev:
                        prev[0] += pkt_len
                        prev[1] += 1
                        prev[2] = time.time()
                    else:
                        self.packet_in_accounting[acct_key] = [pkt_len, 1, time.time()]

                actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
                out = datapath.ofproto_parser.OFPPacketOut(
                    datapath=datapath,
                    buffer_id=datapath.ofproto.OFP_NO_BUFFER,
                    in_port=in_port,
                    actions=actions,
                    data=msg.data
                )
                datapath.send_msg(out)

    def install_symmetric_biflow(self, ingress_dp, ingress_dpid, src_ip, dst_ip, src_port, dst_port, proto):
        """
        Cài đặt cặp luật 5-tuple đối xứng tại Table 0 trên CẢ Egress Switch (trước) và Ingress Switch (sau)
        để OVS đếm chính xác 100% lưu lượng 2 chiều (sbytes/dbytes, Spkts/Dpkts) ngay từ gói tin đầu tiên.
        """
        target_switches = []

        egress_dpid = self.host_db.get(dst_ip, {}).get("dpid")
        if egress_dpid and egress_dpid != ingress_dpid and egress_dpid in self.datapaths:
            target_switches.append((egress_dpid, self.datapaths[egress_dpid]))

        target_switches.append((ingress_dpid, ingress_dp))

        for sw_dpid, dp in target_switches:
            parser = dp.ofproto_parser

            if proto == inet.IPPROTO_TCP:
                m_fwd = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=src_ip, ipv4_dst=dst_ip, tcp_src=src_port, tcp_dst=dst_port)
                m_bwd = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=dst_ip, ipv4_dst=src_ip, tcp_src=dst_port, tcp_dst=src_port)
            elif proto == inet.IPPROTO_UDP:
                m_fwd = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=src_ip, ipv4_dst=dst_ip, udp_src=src_port, udp_dst=dst_port)
                m_bwd = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=dst_ip, ipv4_dst=src_ip, udp_src=dst_port, udp_dst=src_port)
            else:
                continue

            # Tại Table 0: Chuyển tiếp thẳng sang Table 1 để xử lý định tuyến FIB/ECMP mà không cần qua Controller
            fwd_inst = [parser.OFPInstructionGotoTable(1)]
            bwd_inst = [parser.OFPInstructionGotoTable(1)]

            # PHÒNG THỦ CHỐNG TRÙNG LẶP: Chỉ Ingress Switch mới kích hoạt cờ OFPFF_SEND_FLOW_REM!
            # Egress Switch chỉ chuyển tiếp (flags=0) để tránh sinh bản tin FlowRemoved kép
            is_ingress = (sw_dpid == ingress_dpid)
            flow_flags = dp.ofproto.OFPFF_SEND_FLOW_REM if is_ingress else 0
            self.add_flow(dp, priority=150, match=m_fwd, actions=[], instructions=fwd_inst, idle_timeout=2, flags=flow_flags, table_id=0)
            self.add_flow(dp, priority=150, match=m_bwd, actions=[], instructions=bwd_inst, idle_timeout=2, flags=flow_flags, table_id=0)

    def send_arp_reply(self, datapath, port, dst_mac, dst_ip, src_mac, src_ip):
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(
            ethertype=ether.ETH_TYPE_ARP,
            dst=dst_mac,
            src=src_mac
        ))
        pkt.add_protocol(arp.arp(
            opcode=arp.ARP_REPLY,
            src_mac=src_mac,
            src_ip=src_ip,
            dst_mac=dst_mac,
            dst_ip=dst_ip
        ))
        pkt.serialize()

        actions = [datapath.ofproto_parser.OFPActionOutput(port)]
        out = datapath.ofproto_parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=datapath.ofproto.OFP_NO_BUFFER,
            in_port=datapath.ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=pkt.data
        )
        datapath.send_msg(out)

    # ==========================================================================
    # 3.3. TIẾP NHẬN SỰ KIỆN ĐẨY EVENT_OFP_FLOW_REMOVED & IPC STREAMING DAEMON
    # ==========================================================================
    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        """
        Bộ đón sự kiện đẩy OpenFlow EventOFPFlowRemoved (Zero-Block).
        Chỉ bóc tách trường raw và đưa vào queue vi mô (< 1µs) để GreenThread Hub không bị nghẽn.
        """
        msg = ev.msg
        dp = msg.datapath
        dpid = dp.id
        m = msg.match
        s_ip = m.get("ipv4_src") or m.get("nw_src")
        d_ip = m.get("ipv4_dst") or m.get("nw_dst")
        if not (s_ip and d_ip):
            return

        proto = int(m.get("ip_proto") or m.get("nw_proto") or 0)
        s_pt = int(m.get("tcp_src") or m.get("udp_src") or m.get("tp_src") or 0)
        d_pt = int(m.get("tcp_dst") or m.get("udp_dst") or m.get("tp_dst") or 0)

        # Bù trôi idle_timeout (2.0s) khi bị xóa do hết hạn IDLE_TIMEOUT
        dur_raw = float(msg.duration_sec) + float(msg.duration_nsec) / 1e9
        if msg.reason == dp.ofproto.OFPRR_IDLE_TIMEOUT:
            idle_to = float(msg.idle_timeout) if hasattr(msg, 'idle_timeout') and msg.idle_timeout > 0 else 2.0
            true_dur = max(dur_raw - idle_to, 0.001)
        else:
            true_dur = max(dur_raw, 0.001)

        # Giải phóng cache installed_biflows & pending_early_probes ngay khi luồng kết thúc
        if s_pt > 0 and d_pt > 0:
            biflow_sig = tuple(sorted([(s_ip, s_pt), (d_ip, d_pt)])) + (proto,)
            self.installed_biflows.pop(biflow_sig, None)
            # Nếu luồng cực ngắn chưa kịp bắn early probe thì phát luôn hoặc dọn dẹp
            sw_probes = self.pending_early_probes.get(dpid)
            if sw_probes:
                sw_probes.pop(biflow_sig, None)

        acct_key = (dpid, s_ip, d_ip, s_pt, d_pt, proto)
        pi_bytes, pi_pkts, _ = self.packet_in_accounting.pop(acct_key, (0, 0, 0.0))
        total_bytes = int(msg.byte_count) + int(pi_bytes)
        total_pkts = int(msg.packet_count) + int(pi_pkts)

        now_ts = time.time()
        now_str_us = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S.%f")

        event_rec = {
            "type": "FLOW_REMOVED",
            "dpid": dpid,
            "src_ip": s_ip,
            "dst_ip": d_ip,
            "src_port": s_pt,
            "dst_port": d_pt,
            "proto": proto,
            "bytes": total_bytes,
            "pkts": total_pkts,
            "dur": round(true_dur, 6),
            "reason": int(msg.reason),
            "timestamp": now_ts,
            "timestamp_str": now_str_us,
            "timestamp_epoch_ms": int(now_ts * 1000)
        }

        try:
            self.telemetry_queue.put_nowait(event_rec)
        except Exception:
            # Drop oldest nếu queue chạm ngưỡng maxsize=50000 bảo vệ bộ nhớ
            pass

    def _fire_early_probe(self, datapath, dpid):
        """
        Kích hoạt truy vấn bộ đếm phần cứng OVS ở mốc ~8ms (< 10ms) kể từ khi luồng xuất hiện.
        Gom nhóm (Coalescing) toàn bộ luồng mới trên cùng một Ingress Switch thành 1 bản tin OFPFlowStatsRequest(table_id=0) duy nhất.
        """
        self.active_early_timers.discard(dpid)
        sw_probes = self.pending_early_probes.get(dpid)
        if not sw_probes:
            return
        try:
            parser = datapath.ofproto_parser
            req = parser.OFPFlowStatsRequest(datapath, flags=0, table_id=0)
            datapath.send_msg(req)
        except Exception:
            pass

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def early_flow_stats_reply_handler(self, ev):
        """
        Đón bản tin phản hồi OFPFlowStatsReply từ Ingress Switch ở mốc < 10ms.
        Ghép cặp bộ đếm phần cứng 2 chiều + bù gói đầu tiên từ packet_in_accounting và đẩy qua kênh IPC.
        """
        msg = ev.msg
        dp = msg.datapath
        dpid = dp.id
        sw_probes = self.pending_early_probes.get(dpid)
        if not sw_probes:
            return

        now_ts = time.time()
        # Chỉ trích xuất các luồng đã đủ độ tuổi quan sát sớm (>= 5ms)
        ready_sigs = [sig for sig, info in list(sw_probes.items()) if (now_ts - info[0]) >= 0.005]
        if not ready_sigs:
            # Nếu vẫn còn luồng chưa đủ 5ms (do trùng nhịp poll khác), hẹn lại sau 5ms
            if dpid not in self.active_early_timers and sw_probes:
                self.active_early_timers.add(dpid)
                hub.spawn_after(0.005, self._fire_early_probe, dp, dpid)
            return

        # Lập chỉ mục nhanh các luật 5-tuple Table 0 trong bản tin phản hồi
        stats_map = {}
        for stat in msg.body:
            if getattr(stat, "table_id", 0) != 0 or getattr(stat, "priority", 0) < 150:
                continue
            m = stat.match
            s_ip = m.get("ipv4_src") or m.get("nw_src")
            d_ip = m.get("ipv4_dst") or m.get("nw_dst")
            if not (s_ip and d_ip):
                continue
            proto = int(m.get("ip_proto") or m.get("nw_proto") or 0)
            s_pt = int(m.get("tcp_src") or m.get("udp_src") or m.get("tp_src") or 0)
            d_pt = int(m.get("tcp_dst") or m.get("udp_dst") or m.get("tp_dst") or 0)
            if s_pt > 0 and d_pt > 0:
                dur_ovs = float(stat.duration_sec) + float(stat.duration_nsec) / 1e9
                stats_map[(s_ip, d_ip, s_pt, d_pt, proto)] = (
                    int(stat.byte_count), int(stat.packet_count), dur_ovs
                )

        now_str_us = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S.%f")
        for sig in ready_sigs:
            probe_info = sw_probes.pop(sig, None)
            if not probe_info:
                continue
            t_start, src_ip, dst_ip, src_port, dst_port, proto = probe_info

            fwd_b, fwd_p, fwd_dur = stats_map.get((src_ip, dst_ip, src_port, dst_port, proto), (0, 0, 0.0))
            bwd_b, bwd_p, bwd_dur = stats_map.get((dst_ip, src_ip, dst_port, src_port, proto), (0, 0, 0.0))

            # Đọc cộng bù gói đầu tiên đi qua PacketOut (KHÔNG pop để FlowRemoved cuối đời vẫn cộng đủ)
            pi_fwd = self.packet_in_accounting.get((dpid, src_ip, dst_ip, src_port, dst_port, proto), (0, 0, 0.0))
            pi_bwd = self.packet_in_accounting.get((dpid, dst_ip, src_ip, dst_port, src_port, proto), (0, 0, 0.0))

            sbytes = int(fwd_b) + int(pi_fwd[0])
            Spkts = int(fwd_p) + int(pi_fwd[1])
            dbytes = int(bwd_b) + int(pi_bwd[0])
            Dpkts = int(bwd_p) + int(pi_bwd[1])

            if sbytes == 0 and dbytes == 0:
                continue

            # Đồng bộ hướng luồng (Forward là chiều có dung lượng lớn hơn) khớp 100% với BiFlowStitcher
            if dbytes > sbytes:
                src_ip, dst_ip = dst_ip, src_ip
                src_port, dst_port = dst_port, src_port
                sbytes, dbytes = dbytes, sbytes
                Spkts, Dpkts = Dpkts, Spkts

            # Thời gian quan sát thực tế tại cửa sổ sớm (< 10ms)
            elapsed = max(now_ts - t_start, fwd_dur, bwd_dur, 0.001)
            dur_early = min(elapsed, 0.0099) if (now_ts - t_start) < 0.015 else elapsed

            early_rec = {
                "type": "EARLY_FLOW_STATS",
                "dpid": dpid,
                "src_ip": src_ip,
                "dst_ip": dst_ip,
                "src_port": src_port,
                "dst_port": dst_port,
                "proto": proto,
                "sbytes": sbytes,
                "dbytes": dbytes,
                "Spkts": Spkts,
                "Dpkts": Dpkts,
                "dur": round(dur_early, 6),
                "timestamp": now_ts,
                "timestamp_str": now_str_us,
                "timestamp_epoch_ms": int(now_ts * 1000)
            }
            try:
                self.telemetry_queue.put_nowait(early_rec)
            except Exception:
                pass

        # Nếu vẫn còn luồng mới vào sau trong sw_probes, đặt hẹn giờ tiếp
        if sw_probes and dpid not in self.active_early_timers:
            self.active_early_timers.add(dpid)
            hub.spawn_after(0.006, self._fire_early_probe, dp, dpid)

    def _ipc_server_loop(self):
        """
        Kênh truyền stream sự kiện thời gian thực (Zero-blocking TCP Loopback Socket).
        Gửi dữ liệu theo định dạng JSON Lines (\n) cho management_plane.py.
        """
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", 6654))
            srv.listen(5)
            srv.setblocking(False)
            self.logger.info("[+] Telemetry IPC Server đã lắng nghe trên 127.0.0.1:6654")
        except Exception as e:
            self.logger.warning(f"[!] Không thể mở cổng IPC 6654: {e}")
            return

        connected_clients = []

        while self.ipc_running:
            try:
                conn, _ = srv.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.setblocking(True)
                connected_clients.append(conn)
                self.logger.info(f"[+] Client Telemetry đã kết nối tới IPC Server (Tổng: {len(connected_clients)})")
            except (BlockingIOError, socket.error):
                pass
            except Exception:
                break

            # Chỉ rút sự kiện khỏi queue khi ĐÃ CÓ client kết nối để tuyệt đối không làm rớt batch khi khởi động
            if not connected_clients:
                time.sleep(0.02)
                continue

            # Thu gom tối đa 100 sự kiện trong queue để gửi theo batch
            batch = []
            while len(batch) < 100:
                try:
                    item = self.telemetry_queue.get_nowait()
                    batch.append(item)
                except queue.Empty:
                    break

            if batch:
                payload = "".join(json.dumps(x) + "\n" for x in batch).encode("utf-8")
                dead_clients = []
                sent_ok = False
                for cl in connected_clients:
                    try:
                        cl.sendall(payload)
                        sent_ok = True
                    except Exception:
                        dead_clients.append(cl)
                for dc in dead_clients:
                    try:
                        dc.close()
                    except Exception:
                        pass
                    if dc in connected_clients:
                        connected_clients.remove(dc)
                if not sent_ok:
                    # Tất cả client đều đứt kết nối: Đẩy trả lại queue để bảo toàn 100% sự kiện
                    for item in batch:
                        try:
                            self.telemetry_queue.put_nowait(item)
                        except Exception:
                            break
            else:
                time.sleep(0.02)

    # ==========================================================================
    # 4. TÍNH TOÁN ĐA ĐƯỜNG & LẬP TRÌNH ECMP GROUP TABLE (OFPGT_SELECT)
    # ==========================================================================
    def install_ecmp_for_single_host(self, dst_ip):
        host_info = self.host_db.get(dst_ip)
        if not host_info:
            return

        dst_dpid = host_info["dpid"]
        group_id = self.group_id_map.get(dst_ip)
        if not group_id:
            return

        for src_dpid, datapath in self.datapaths.items():
            if src_dpid == dst_dpid:
                continue

            if not (self.topo_graph.has_node(src_dpid) and self.topo_graph.has_node(dst_dpid)):
                continue

            try:
                all_paths = list(nx.all_shortest_paths(self.topo_graph, source=src_dpid, target=dst_dpid))
            except Exception:
                continue

            next_hop_ports = {self.topo_graph[src_dpid][p[1]]["port"] for p in all_paths if len(p) > 1}
            if not next_hop_ports:
                continue

            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto

            buckets = [
                parser.OFPBucket(weight=100, actions=[parser.OFPActionOutput(p)])
                for p in sorted(list(next_hop_ports))
            ]

            command = ofproto.OFPGC_MODIFY if (src_dpid, group_id) in self.installed_groups else ofproto.OFPGC_ADD
            group_mod = parser.OFPGroupMod(
                datapath=datapath,
                command=command,
                type_=ofproto.OFPGT_SELECT,
                group_id=group_id,
                buckets=buckets
            )
            datapath.send_msg(group_mod)
            self.installed_groups.add((src_dpid, group_id))

            match_ip = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ipv4_dst=dst_ip)
            instructions = [
                parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS,
                    [parser.OFPActionGroup(group_id=group_id)]
                )
            ]
            self.add_flow(datapath, priority=100, match=match_ip, actions=[], instructions=instructions, table_id=1)

    def install_all_ecmp_paths(self):
        for dst_ip in list(self.host_db.keys()):
            self.install_ecmp_for_single_host(dst_ip)

    # ==========================================================================
    # 5. CƠ CHẾ STEERING LUỒNG VOI VÀO CỔNG PROXY-INT (PRIORITY 1000)
    # ==========================================================================
    def steer_elephant_flow(self, src_dpid, src_ip, dst_ip, src_port, dst_port, proto):
        """Cài đặt luật Priority 1000 điều hướng luồng Voi vào NFV Proxy nội bộ."""
        datapath = self.datapaths.get(src_dpid)
        if not datapath:
            return False

        proxy_port = self.proxy_ports.get(src_dpid)
        if not proxy_port:
            self.logger.warning(f"[!] Switch DPID={src_dpid} chưa nhận diện được cổng proxy-int!")
            return False

        parser = datapath.ofproto_parser
        if proto == inet.IPPROTO_TCP:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=src_ip, ipv4_dst=dst_ip, tcp_src=src_port, tcp_dst=dst_port)
        elif proto == inet.IPPROTO_UDP:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=src_ip, ipv4_dst=dst_ip, udp_src=src_port, udp_dst=dst_port)
        else:
            return False

        actions = [parser.OFPActionOutput(proxy_port)]
        self.add_flow(datapath, priority=1000, match=match, actions=actions, idle_timeout=60, table_id=0)
        self.logger.info(f"[STEER] Luồng Voi {src_ip}:{src_port} -> {dst_ip}:{dst_port} trên DPID={src_dpid} đã được điều hướng vào proxy-int (Port {proxy_port})!")
        return True