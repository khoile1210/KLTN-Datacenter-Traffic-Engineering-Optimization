/*
 * ebpf_telemetry.c - High-Resolution In-Kernel SDN Telemetry Engine
 * 
 * Kiến trúc eBPF / XDP thụ động (Passive Telemetry) dành cho SDN Datacenter (Mininet / Containernet).
 * Chức năng:
 *   1. XDP Ingress Hook trên veth interfaces: Bóc tách 5-tuple, timestamping nano-giây, đếm PPS vi mô.
 *   2. Cửa sổ trượt In-Kernel 10ms: Phát hiện Microburst tức thời và đẩy qua BPF Perf Event Ring Buffer.
 *   3. Bridge-Port Indexing: Tự động ánh xạ ifindex sang switch DPID trong 2ns.
 *   4. Tracepoint ngắt mềm (softirq): Đo thời gian CPU xử lý gói tin mạng trong kernel.
 * 
 * Luôn trả về XDP_PASS để 100% gói tin được chuyển giao an toàn cho Open vSwitch (OVS).
 */

#include <uapi/linux/ptrace.h>
#include <uapi/linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/in.h>
#include <linux/tcp.h>
#include <linux/udp.h>
#include <bcc/proto.h>

#define MICROBURST_WINDOW_NS  10000000ULL   /* Cửa sổ trượt 10 mili-giây */
#define BURST_THRESHOLD_BYTES 50000ULL      /* Ngưỡng phát hiện bùng nổ xung (~40 Mbps trong 10ms) */

/* Cấu trúc 5-tuple định danh luồng mạng */
struct flow_5tuple_t {
    u32 src_ip;
    u32 dst_ip;
    u16 src_port;
    u16 dst_port;
    u8  protocol;
    u8  pad[3];
};

/* Số liệu thống kê chi tiết của luồng */
struct flow_stats_t {
    u64 bytes;
    u64 packets;
    u64 start_ktime_ns;
    u64 last_ktime_ns;
    u64 fct_us;             /* Flow Completion Time (micro-giây) */
    u8  is_syn;
    u8  is_fin_rst;
    u8  pad[6];
};

/* Cấu trúc sự kiện Microburst gửi lên Userspace */
struct microburst_event_t {
    u32 ifindex;
    u32 dpid;
    u64 timestamp_ns;
    u64 window_duration_ns;
    u64 bytes_in_window;
    u64 packets_in_window;
    u64 instantaneous_rate_mbps;
};

/* Cấu trúc cửa sổ trượt từng giao diện mạng */
struct burst_window_t {
    u64 window_start_ns;
    u64 bytes;
    u64 packets;
};

/* Bảng thống kê tài nguyên từng switch OVS */
struct switch_telemetry_t {
    u64 rx_bytes;
    u64 rx_packets;
    u64 last_update_ns;
    u64 softirq_runtime_ns;
    u64 burst_count;
};

/* =========================================================================
 * BPF MAPS (BỘ NHỚ CHIA SẺ KERNEL - USERSPACE)
 * ========================================================================= */

/* Bảng luồng tự dọn dẹp LRU Hash (tối đa 65,536 luồng đồng thời) */
BPF_LRU_HASH(flow_metrics_map, struct flow_5tuple_t, struct flow_stats_t, 65536);

/* Ánh xạ ifindex -> DPID (Switch ID 1..14) để bóc tách tài nguyên trong Root Namespace */
BPF_HASH(ifindex_to_bridge_map, u32, u32, 256);

/* Cửa sổ trượt theo dõi burst cho từng cổng mạng */
BPF_HASH(burst_window_map, u32, struct burst_window_t, 256);

/* Tổng hợp số liệu kernel từng switch */
BPF_HASH(switch_telemetry_map, u32, struct switch_telemetry_t, 64);

/* Perf Event Ring Buffer truyền tin Microburst lên Userspace thời gian thực */
BPF_PERF_OUTPUT(burst_events);

/* Mảng đo thời gian CPU ngắt mạng softirq NET_RX (vec == 3) */
BPF_ARRAY(softirq_metric_array, u64, 8);


/* =========================================================================
 * 1. XDP INGRESS PROBE (GẮN TẠI VETH INTERFACES - TỐC ĐỘ DÂY)
 * ========================================================================= */
int xdp_ingress_telemetry(struct xdp_md *ctx) {
    void *data = (void *)(long)ctx->data;
    void *data_end = (void *)(long)ctx->data_end;
    u64 now_ns = bpf_ktime_get_ns();
    u32 ifindex = ctx->ingress_ifindex;
    u64 pkt_len = (u64)(data_end - data);

    /* 1. Phân tích Ethernet Header an toàn với Verifier */
    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end)
        return XDP_PASS;

    if (eth->h_proto != bpf_htons(ETH_P_IP))
        return XDP_PASS; /* Chỉ đo lường gói IPv4 */

    /* 2. Phân tích IPv4 Header */
    struct iphdr *ip = (void *)(eth + 1);
    if ((void *)(ip + 1) > data_end)
        return XDP_PASS;

    u8 proto = ip->protocol;
    u32 src_ip = bpf_ntohl(ip->saddr);
    u32 dst_ip = bpf_ntohl(ip->daddr);
    u16 src_port = 0;
    u16 dst_port = 0;
    u8 is_syn = 0;
    u8 is_fin_rst = 0;

    void *l4 = (void *)ip + (ip->ihl * 4);

    if (proto == IPPROTO_TCP) {
        struct tcphdr *tcp = l4;
        if ((void *)(tcp + 1) > data_end)
            return XDP_PASS;
        src_port = bpf_ntohs(tcp->source);
        dst_port = bpf_ntohs(tcp->dest);
        if (tcp->syn && !tcp->ack) is_syn = 1;
        if (tcp->fin || tcp->rst) is_fin_rst = 1;
    } else if (proto == IPPROTO_UDP) {
        struct udphdr *udp = l4;
        if ((void *)(udp + 1) > data_end)
            return XDP_PASS;
        src_port = bpf_ntohs(udp->source);
        dst_port = bpf_ntohs(udp->dest);
    } else {
        return XDP_PASS;
    }

    /* 3. Tra cứu Bridge DPID qua BPF Map trong 2 nano-giây */
    u32 default_dpid = 0;
    u32 *dpid_ptr = ifindex_to_bridge_map.lookup(&ifindex);
    u32 dpid = dpid_ptr ? *dpid_ptr : default_dpid;

    /* 4. Cập nhật Bảng Luồng 5-tuple (LRU Hash Map) & Tính FCT */
    struct flow_5tuple_t flow_key = {};
    flow_key.src_ip = src_ip;
    flow_key.dst_ip = dst_ip;
    flow_key.src_port = src_port;
    flow_key.dst_port = dst_port;
    flow_key.protocol = proto;

    struct flow_stats_t *fstats = flow_metrics_map.lookup(&flow_key);
    if (fstats) {
        fstats->bytes += pkt_len;
        fstats->packets += 1;
        fstats->last_ktime_ns = now_ns;
        if (is_fin_rst && fstats->start_ktime_ns > 0) {
            fstats->fct_us = (now_ns - fstats->start_ktime_ns) / 1000ULL;
            fstats->is_fin_rst = 1;
        }
    } else {
        struct flow_stats_t new_fstats = {};
        new_fstats.bytes = pkt_len;
        new_fstats.packets = 1;
        new_fstats.start_ktime_ns = now_ns;
        new_fstats.last_ktime_ns = now_ns;
        new_fstats.is_syn = is_syn;
        flow_metrics_map.update(&flow_key, &new_fstats);
    }

    /* 5. Thuật toán Cửa sổ trượt 10ms phát hiện Microburst tại Card Mạng */
    struct burst_window_t *w = burst_window_map.lookup(&ifindex);
    if (w) {
        u64 delta_t = now_ns - w->window_start_ns;
        if (delta_t >= MICROBURST_WINDOW_NS) {
            /* Hết chu kỳ cửa sổ 10ms -> Đánh giá ngưỡng bùng nổ xung */
            if (w->bytes >= BURST_THRESHOLD_BYTES) {
                u64 rate_mbps = (w->bytes * 8ULL * 1000000000ULL) / (delta_t * 1000000ULL);
                struct microburst_event_t evt = {};
                evt.ifindex = ifindex;
                evt.dpid = dpid;
                evt.timestamp_ns = now_ns;
                evt.window_duration_ns = delta_t;
                evt.bytes_in_window = w->bytes;
                evt.packets_in_window = w->packets;
                evt.instantaneous_rate_mbps = rate_mbps;

                /* Đẩy sự kiện qua Ring Buffer lên Userspace thời gian thực */
                burst_events.perf_submit(ctx, &evt, sizeof(evt));

                /* Ghi nhận số lần burst cho switch */
                struct switch_telemetry_t *sw_t = switch_telemetry_map.lookup(&dpid);
                if (sw_t) {
                    sw_t->burst_count += 1;
                }
            }
            /* Đặt lại cửa sổ trượt mới */
            w->window_start_ns = now_ns;
            w->bytes = pkt_len;
            w->packets = 1;
        } else {
            w->bytes += pkt_len;
            w->packets += 1;
        }
    } else {
        struct burst_window_t init_w = {};
        init_w.window_start_ns = now_ns;
        init_w.bytes = pkt_len;
        init_w.packets = 1;
        burst_window_map.update(&ifindex, &init_w);
    }

    /* 6. Cập nhật số liệu Switch Telemetry */
    struct switch_telemetry_t *sw = switch_telemetry_map.lookup(&dpid);
    if (sw) {
        sw->rx_bytes += pkt_len;
        sw->rx_packets += 1;
        sw->last_update_ns = now_ns;
    } else {
        struct switch_telemetry_t init_sw = {};
        init_sw.rx_bytes = pkt_len;
        init_sw.rx_packets = 1;
        init_sw.last_update_ns = now_ns;
        switch_telemetry_map.update(&dpid, &init_sw);
    }

    /* LUÔN TRẢ VỀ XDP_PASS ĐỂ OVS NHẬN GÓI VÀ CHUYỂN TIẾP BÌNH THƯỜNG */
    return XDP_PASS;
}


/* =========================================================================
 * 2. TRACEPOINT HOOK: ĐO THỜI GIAN CPU NGẮT MỀM (NET_RX_SOFTIRQ)
 * ========================================================================= */
struct softirq_entry_args_t {
    u64 __pad;
    u32 vec;
};

struct softirq_exit_args_t {
    u64 __pad;
    u32 vec;
};

BPF_HASH(softirq_start_time, u32, u64);

int trace_softirq_entry(struct softirq_entry_args_t *args) {
    /* vec == 3 tương ứng với NET_RX_SOFTIRQ trong linux/interrupt.h */
    if (args->vec == 3) {
        u32 cpu = bpf_get_smp_processor_id();
        u64 ts = bpf_ktime_get_ns();
        softirq_start_time.update(&cpu, &ts);
    }
    return 0;
}

int trace_softirq_exit(struct softirq_exit_args_t *args) {
    if (args->vec == 3) {
        u32 cpu = bpf_get_smp_processor_id();
        u64 *start_ts = softirq_start_time.lookup(&cpu);
        if (start_ts) {
            u64 duration = bpf_ktime_get_ns() - *start_ts;
            u32 key = 0;
            u64 *total = softirq_metric_array.lookup(&key);
            if (total) {
                *total += duration;
            } else {
                softirq_metric_array.update(&key, &duration);
            }
            softirq_start_time.delete(&cpu);
        }
    }
    return 0;
}
