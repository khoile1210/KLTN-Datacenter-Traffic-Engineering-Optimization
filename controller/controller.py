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
        # Khởi tạo mặc định cho 8 host nội bộ và host inet làm điểm xuất phát
        self.host_db = {
            f"10.0.0.{i}": {"mac": f"00:00:00:00:00:0{i}", "dpid": i, "port": 5}
            for i in range(1, 9)
        }
        self.host_db["10.0.0.100"] = {"mac": "00:00:00:00:00:99", "dpid": 33, "port": 1}

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

        # Cài luật Table-Miss chuyển gói lạ lên Controller (Priority 0)
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, priority=0, match=match, actions=actions)

        # Xóa các Group Table cũ còn tồn đọng trên switch phần cứng
        del_mod = parser.OFPGroupMod(
            datapath=datapath,
            command=ofproto.OFPGC_DELETE,
            type_=ofproto.OFPGT_SELECT,
            group_id=ofproto.OFPG_ALL
        )
        datapath.send_msg(del_mod)

        # Cài đặt ngay luật chuyển tiếp cục bộ cho các Host cắm trực tiếp vào switch này
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
                self.add_flow(datapath, priority=100, match=m_ip, actions=[parser.OFPActionOutput(host_port)])
                m_arp = parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP, arp_tpa=ip)
                self.add_flow(datapath, priority=100, match=m_arp, actions=[parser.OFPActionOutput(host_port)])
                self.logger.info(f"[+] Cài luật cục bộ trên Switch DPID={dpid} cho Host {ip} -> Port {host_port}")

    def add_flow(self, datapath, priority, match, actions, instructions=None, idle_timeout=0, hard_timeout=0):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        if instructions is None:
            instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
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

        # 3.2. Xử lý gói tin IPv4: On-demand routing + Cài đặt 5-tuple Bi-flow
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            src_ip = ip_pkt.src
            dst_ip = ip_pkt.dst
            proto = ip_pkt.proto
            self.learn_host(src_ip, eth.src, dpid, in_port)

            if dst_ip in self.host_db:
                # Đảm bảo đã có ECMP group cho dst_ip
                if (dpid, self.group_id_map.get(dst_ip, 0)) not in self.installed_groups:
                    self.install_ecmp_for_single_host(dst_ip)

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

                # Cài đặt cặp Flow Rule 5-tuple đối xứng (Bi-flow) tại Ingress Access Switch
                if src_port > 0 and dst_port > 0:
                    self.install_symmetric_biflow(datapath, dpid, in_port, src_ip, dst_ip, src_port, dst_port, proto)

                # Đẩy gói tin đầu tiên đi tiếp an toàn bằng Packet-Out
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

    def install_symmetric_biflow(self, datapath, dpid, in_port, src_ip, dst_ip, src_port, dst_port, proto):
        """Cài đặt cặp luật 5-tuple đối xứng tại Ingress Switch để OVS đếm riêng chiều đi và chiều về."""
        biflow_key = (dpid, src_ip, dst_ip, src_port, dst_port, proto)
        if biflow_key in self.installed_biflows:
            return

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        group_id = self.group_id_map.get(dst_ip)
        if not group_id:
            return

        # 1. Forward Rule (Chiều đi: src -> dst): Đẩy vào ECMP Group (hoặc output host nếu cùng switch)
        target_dpid = self.host_db.get(dst_ip, {}).get("dpid")
        if dpid == target_dpid:
            fwd_actions = [parser.OFPActionOutput(self.host_db[dst_ip]["port"])]
            fwd_inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, fwd_actions)]
        else:
            fwd_inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, [parser.OFPActionGroup(group_id)])]

        # 2. Backward Rule (Chiều về: dst -> src): Đẩy ra cổng cắm host nguồn
        bwd_actions = [parser.OFPActionOutput(in_port)]
        bwd_inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, bwd_actions)]

        # Tạo match chi tiết theo TCP hoặc UDP
        if proto == inet.IPPROTO_TCP:
            m_fwd = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=src_ip, ipv4_dst=dst_ip, tcp_src=src_port, tcp_dst=dst_port)
            m_bwd = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=dst_ip, ipv4_dst=src_ip, tcp_src=dst_port, tcp_dst=src_port)
        elif proto == inet.IPPROTO_UDP:
            m_fwd = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=src_ip, ipv4_dst=dst_ip, udp_src=src_port, udp_dst=dst_port)
            m_bwd = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=proto, ipv4_src=dst_ip, ipv4_dst=src_ip, udp_src=dst_port, udp_dst=src_port)
        else:
            return

        # Cài đặt với Priority=150 (ưu tiên hơn luật ECMP mặc định Priority=100) và idle_timeout=30s
        self.add_flow(datapath, priority=150, match=m_fwd, actions=[], instructions=fwd_inst, idle_timeout=30)
        self.add_flow(datapath, priority=150, match=m_bwd, actions=[], instructions=bwd_inst, idle_timeout=30)
        self.installed_biflows.add(biflow_key)

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
            self.add_flow(datapath, priority=100, match=match_ip, actions=[], instructions=instructions)

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
        self.add_flow(datapath, priority=1000, match=match, actions=actions, idle_timeout=60)
        self.logger.info(f"[STEER] Luồng Voi {src_ip}:{src_port} -> {dst_ip}:{dst_port} trên DPID={src_dpid} đã được điều hướng vào proxy-int (Port {proxy_port})!")
        return True