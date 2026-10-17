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
            except Exception:
                pass

        self.host_db = {}
        for r in range(1, num_access + 1):
            for h in range(1, hosts_per_rack + 1):
                host_num = (r - 1) * hosts_per_rack + h
                self.host_db[f"10.0.0.{host_num}"] = {
                    "mac": f"00:00:00:00:{r:02x}:{h:02x}",
                    "dpid": r,
                    "port": num_agg + h
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
        self.installed_biflows = set()    # Lưu tập hợp (dpid, src_ip, dst_ip, src_port, dst_port, proto)

        # Quản lý Debounce Timer chống bão FlowMod khi LLDP phát hiện link dồn dập
        self.topology_debounce_timer = None
        self.DEBOUNCE_INTERVAL = 2.0  # Chờ 2 giây sau link cuối cùng mới tính toán toàn mạng

        # Lưu ánh xạ cổng nội bộ proxy-int của từng switch
        self.proxy_ports = {}

        self.logger.info("[+] Multi-Tier Spine-Leaf Controller (Cải tổ v2) đã khởi động thành công.")

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
        self.installed_biflows = {item for item in self.installed_biflows if item[0] != dpid}

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

        # 2. Table 0 - Priority 50: Bắt luồng mới từ cổng cắm Host (Access Switch)
        # Chỉ sao chép tối đa 128 bytes header lên Controller (chống nghẽn control plane)
        # và NGAY LẬP TỨC chuyển tiếp sang Table 1 để xử lý forwarding, không làm trễ hay mất gói
        host_ports = [info["port"] for ip, info in self.host_db.items() if info["dpid"] == dpid]
        for hp in host_ports:
            m_hp = parser.OFPMatch(in_port=hp, eth_type=ether.ETH_TYPE_IP)
            inst_hp = [
                parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, 128)]),
                parser.OFPInstructionGotoTable(1)
            ]
            self.add_flow(datapath, priority=50, match=m_hp, actions=[], instructions=inst_hp, table_id=0)

        # 3. Table 0 - Priority 0: Mặc định Table 0 -> Chuyển tiếp sang Table 1
        self.add_flow(datapath, priority=0, match=parser.OFPMatch(), actions=[], instructions=[parser.OFPInstructionGotoTable(1)], table_id=0)

        # 4. Table 1 - Priority 0: Table-Miss Table 1 -> Gửi lên Controller (LLDP link discovery, v.v.)
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

    def add_flow(self, datapath, priority, match, actions, instructions=None, idle_timeout=0, hard_timeout=0, table_id=0):
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
            hard_timeout=hard_timeout
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
                m_hp = parser.OFPMatch(in_port=in_port, eth_type=ether.ETH_TYPE_IP)
                inst_hp = [
                    parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, 128)]),
                    parser.OFPInstructionGotoTable(1)
                ]
                self.add_flow(datapath, priority=50, match=m_hp, actions=[], instructions=inst_hp, table_id=0)

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

        # 3.2. Xử lý gói tin IPv4: Cài đặt 5-tuple Bi-flow đối xứng trên cả Ingress và Egress Switch
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
                # FAST IN-MEMORY DEDUP: Kiểm tra xem cặp 5-tuple đã được cài đặt chưa
                biflow_signature = tuple(sorted([(src_ip, src_port), (dst_ip, dst_port)])) + (proto,)
                if biflow_signature in self.installed_biflows:
                    return
                self.installed_biflows.add(biflow_signature)

                # Đảm bảo đã có ECMP group cho dst_ip
                if (dpid, self.group_id_map.get(dst_ip, 0)) not in self.installed_groups:
                    self.install_ecmp_for_single_host(dst_ip)

                # Cài đặt cặp Flow Rule 5-tuple đối xứng tại Table 0 trên CẢ Ingress và Egress Switch
                self.install_symmetric_biflow(datapath, dpid, src_ip, dst_ip, src_port, dst_port, proto)

            # Do Table 0 Priority 50 đã có Instruction GotoTable(1), các gói tin bình thường đã được chuyển tiếp
            # trực tiếp trong datapath sang Table 1 mà không cần controller PacketOut (tránh trùng lặp).
            # Chỉ trường hợp gói tin đến từ Table-Miss Table 1 (gói lạ) mới cần chuyển tiếp qua PacketOut.
            if getattr(msg, 'table_id', 0) == 1 and dst_ip in self.host_db:
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

                actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
                out = datapath.ofproto_parser.OFPPacketOut(
                    datapath=datapath,
                    buffer_id=msg.buffer_id,
                    in_port=in_port,
                    actions=actions,
                    data=msg.data
                )
                datapath.send_msg(out)

    def install_symmetric_biflow(self, ingress_dp, ingress_dpid, src_ip, dst_ip, src_port, dst_port, proto):
        """Cài đặt cặp luật 5-tuple đối xứng tại Table 0 trên CẢ Ingress Switch và Egress Switch để OVS đếm riêng 2 chiều."""
        target_switches = [(ingress_dpid, ingress_dp)]

        egress_dpid = self.host_db.get(dst_ip, {}).get("dpid")
        if egress_dpid and egress_dpid != ingress_dpid and egress_dpid in self.datapaths:
            target_switches.append((egress_dpid, self.datapaths[egress_dpid]))

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

            # Cài đặt với Priority=150 (cao hơn Priority=50 và Priority=0 của Table 0) và idle_timeout=30s
            self.add_flow(dp, priority=150, match=m_fwd, actions=[], instructions=fwd_inst, idle_timeout=30, table_id=0)
            self.add_flow(dp, priority=150, match=m_bwd, actions=[], instructions=bwd_inst, idle_timeout=30, table_id=0)

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