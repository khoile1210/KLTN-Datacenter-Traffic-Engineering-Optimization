#!/usr/bin/env python3
"""
Tên file: controller.py
Mô tả   : Ryu Controller OpenFlow 1.3 chuyên dụng cho Multi-tier Spine-Leaf:
          - Tự động kích hoạt LLDP link discovery (observe_links = True).
          - Proxy ARP thông minh, chống Broadcast Storm.
          - Cài đặt luật Host cục bộ ngay khi Switch kết nối.
          - Cài đặt ECMP Group Table (OFPGT_SELECT) chia tải phần cứng.
          - Hỗ trợ On-demand Routing: Tự tính đường và nạp flow ngay khi có gói tin IP đầu tiên.
Chạy    : ryu-manager --observe-links controller.py ryu.app.ofctl_rest ryu.app.rest_topology --ofp-tcp-listen-port 6653
"""

from ryu import cfg
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3, ether
from ryu.lib.packet import packet, ethernet, arp, ipv4
from ryu.topology import event
from ryu.topology.api import get_switch, get_link
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

        # Danh bạ IP -> MAC và cổng cắm trực tiếp trên Switch Access/Core
        # a1->h1, a2->h2, ..., a8->h8 (Host luôn ở Port 5 trên Access Switch)
        self.host_db = {
            f"10.0.0.{i}": {"mac": f"00:00:00:00:00:0{i}", "dpid": i, "port": 5}
            for i in range(1, 9)
        }
        # inet gắn vào Core switch c1 (DPID 0x21 = 33) qua Port 1
        self.host_db["10.0.0.100"] = {"mac": "00:00:00:00:00:99", "dpid": 33, "port": 1}

        self.group_id_map = {ip: idx + 1 for idx, ip in enumerate(self.host_db.keys())}
        self.installed_groups = set()

        self.logger.info("[+] Dynamic Spine-Leaf Controller đã khởi động.")

    # ==========================================================================
    # 1. BẮT TAY SWITCH & CÀI ĐẶT LUẬT CỤC BỘ (LOCAL HOST RULES)
    # ==========================================================================
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        self.datapaths[dpid] = datapath

        # Cài luật Table-Miss chuyển gói lạ lên Controller (Priority 0)
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, priority=0, match=match, actions=actions)

        # Xóa các Group Table cũ còn tồn đọng
        del_mod = parser.OFPGroupMod(
            datapath=datapath,
            command=ofproto.OFPGC_DELETE,
            type_=ofproto.OFPGT_SELECT,
            group_id=ofproto.OFPG_ALL
        )
        datapath.send_msg(del_mod)

        # Cài đặt ngay luật chuyển tiếp cục bộ cho các Host cắm trực tiếp vào switch này
        for ip, info in self.host_db.items():
            if info["dpid"] == dpid:
                host_port = info["port"]
                # Match IPv4
                m_ip = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ipv4_dst=ip)
                self.add_flow(datapath, priority=100, match=m_ip, actions=[parser.OFPActionOutput(host_port)])
                # Match ARP
                m_arp = parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP, arp_tpa=ip)
                self.add_flow(datapath, priority=100, match=m_arp, actions=[parser.OFPActionOutput(host_port)])
                self.logger.info(f"[+] Cài luật cục bộ trên Switch DPID={dpid} cho Host {ip} ra Port {host_port}")

    def add_flow(self, datapath, priority, match, actions, instructions=None):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        if instructions is None:
            instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions
        )
        datapath.send_msg(mod)

    # ==========================================================================
    # 2. KHÁM PHÁ LIÊN KẾT LIÊN TẦNG (LLDP) & CẬP NHẬT ĐỒ THỊ
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

        self.logger.info(f"[*] Topo cập nhật: {len(switches)} Switches, {len(links)} Links LLDP.")
        # Nạp lại ECMP mỗi khi có liên kết mới xuất hiện
        self.install_all_ecmp_paths()

    # ==========================================================================
    # 3. PROXY ARP & ON-DEMAND ROUTING (XỬ LÝ GÓI TIN LẠ)
    # ==========================================================================
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

        # 3.1. Xử lý bản tin ARP Request bằng Proxy ARP
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt and arp_pkt.opcode == arp.ARP_REQUEST:
            dst_ip = arp_pkt.dst_ip
            src_ip = arp_pkt.src_ip

            if dst_ip in self.host_db:
                target_mac = self.host_db[dst_ip]["mac"]
                self.send_arp_reply(datapath, in_port, eth.src, src_ip, target_mac, dst_ip)
            return

        # 3.2. Xử lý gói tin IPv4 chưa kịp có Flow Rule (On-Demand Flow Setup)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            dst_ip = ip_pkt.dst
            if dst_ip in self.host_db:
                # Cài đặt ngay ECMP cho IP này trên toàn mạng
                self.install_ecmp_for_single_host(dst_ip)
                # Đẩy gói tin này ra đường đi hợp lệ thay vì hủy bỏ
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
        group_id = self.group_id_map[dst_ip]

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
        for dst_ip in self.host_db.keys():
            self.install_ecmp_for_single_host(dst_ip)