# TÓM TẮT TỔNG THỂ KẾ HOẠCH DỰ ÁN (PROJECT MASTER PLAN SUMMARY)

> **Tên đề tài:** Research on Traffic Engineering Optimization in Data Center Networks Based on Software-Defined Network and Artificial Intelligence (Nghiên cứu Tối ưu hóa Kỹ thuật Lưu lượng trong Mạng Trung tâm Dữ liệu Dựa trên Mạng Điều khiển bằng Phần mềm và Trí tuệ Nhân tạo)  
> **Phiên bản hệ thống:** v4.0 (2-Cluster Clos Fabric + OpenFlow 1.3 Multi-Table + Facebook DCN Traffic Engine + Hybrid eBPF/XDP Telemetry)  
> **Ngày cập nhật:** 2026-10-18  
> **Cố vấn Kiến trúc & Thẩm định:** Gemini 4 Argon (Senior SDN Architect, Telemetry & AI/DRL Specialist)  
> **Môi trường triển khai:** Containernet / Mininet 2.3.1+ (Ubuntu Server 22.04 LTS), Open vSwitch 2.17+ (Docker OVS), Ryu SDN Controller 4.34 (OpenFlow 1.3), Python 3.10+, eBPF/XDP (BCC/LLVM/Clang)  
> **Tài liệu nguồn tổng hợp:** [`overview_plan_origin.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/overview_plan_origin.md), [`detail_plan.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/detail_plan.md), [`UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md), [`Metrics.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/Metrics.md), [`Questions.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/Questions.md)

---

## 1. MỤC TIÊU CỐT LÕI & BÀI TOÁN NGHIÊN CỨU

Trong mạng Trung tâm Dữ liệu (Data Center Network - DCN) hiện đại, lưu lượng mạng mang tính chất lưỡng cực và phân phối đuôi dài rõ rệt (Heavy-tailed Pareto Distribution) như chứng minh thực tế tại Facebook, Google, Microsoft:
- **Luồng Chuột (Mice Flows):** Chiếm $80\% - 90\%$ tổng số lượng luồng nhưng kích thước rất nhỏ ($< 100\text{ KB}$), truyền tải các bản tin truy vấn RPC, truy vấn bộ đệm phân tán Memcached, điều khiển phân tán. Nhóm này cực kỳ nhạy cảm với độ trễ (**Latency-sensitive**) và thời gian hoàn thành luồng (**Flow Completion Time - FCT**).
- **Luồng Voi (Elephant Flows):** Chỉ chiếm $10\% - 20\%$ số lượng luồng nhưng chiếm hơn $80\%$ tổng dung lượng byte toàn mạng, sinh ra từ các tác vụ sao chép dữ liệu Hadoop/Spark, đồng bộ checkpoint mô hình AI, sao lưu cơ sở dữ liệu. Nhóm này đòi hỏi thông lượng chuyển giao lớn (**Throughput-sensitive / Goodput**).

### Bất cập của Cơ chế ECMP (Equal-Cost Multi-Path) Truyền thống
ECMP là cơ chế định tuyến mặc định trên các switch DCN phần cứng thương mại. ECMP băm tĩnh (Hash-based) 5-tuple (`src_ip`, `dst_ip`, `ip_proto`, `src_port`, `dst_port`) vào các liên kết song song cùng chi phí:
1. **Xung đột Băm (Hash Collision):** Khi hai hoặc nhiều luồng Voi ngẫu nhiên bị băm vào cùng một đường truyền (Link), liên kết đó nhanh chóng bị quá tải (Saturation).
2. **Nghẽn Hàng Đợi & Rớt Gói (Queue Overflow & Packet Drops):** Bộ đệm hàng đợi (Buffer Queue) của switch trên đường xung đột bị đầy tràn, kích hoạt cơ chế Drop-tail hoặc trễ xếp hàng nghiêm trọng.
3. **Phạt Nặng Luồng Chuột (Mice Flow Starvation):** Hàng ngàn luồng Chuột đi chung đường truyền bị kẹt sau các gói tin khổng lồ của luồng Voi, khiến độ trễ đuôi (Tail Latency $p95, p99$) và FCT của luồng Chuột tăng đột biến hàng chục lần, làm suy giảm nghiêm trọng chất lượng dịch vụ (SLA) của các ứng dụng Web/Microservices.

### Giải pháp Đề xuất của Đề tài (Mô hình Phân công 2 Tầng: Data Plane Reflex & SDN-AI Governance)
Dự án nghiên cứu và phát triển kiến trúc **Điều phối Lưu lượng Thông minh Phân Tầng**, phân định rạch ròi 2 miền thời gian xử lý:

1. **Tầng 1: Phản Xạ Tức Thời Tại Data Plane (Sub-millisecond Reflex) — Dành Cho Miceflows & Microbursts:**
   - **Bản chất vật lý của Microburst:** Một đợt Microburst ($20\text{ KB} - 80\text{ KB}$, kéo dài $< 10\text{ ms}$) chỉ mang tốc độ tức thời của Elephant nhưng tích phân dung lượng thực chất là **Miceflow**.
   - **Nghịch lý độ trễ:** Nếu xử lý Microburst theo hướng Elephant flow (chờ Packet-In, suy luận AI, tính toán GAT/PPO và gửi FlowMod mất $15\text{ ms} - 30\text{ ms}$), thì Microburst đã biến mất từ lâu và hàng đợi đã bị tràn rớt gói trước đó.
   - **Cơ chế xử lý theo hướng Miceflow:** Microburst và Miceflow được chuyển tiếp trực tiếp bằng **Hardware ECMP Group Table (`OFPGT_SELECT`, Priority 100)** trong nano-giây. Đồng thời, switch OVS kích hoạt cơ chế **ECN Marking (RFC 3168 / RFC 8257 DCTCP)** với ngưỡng $K$ cực thấp ($K = 30\text{ KB} \sim 20\text{ pkts}$, được **quản trị tập trung trong `controller/traffic_config.json` qua khối `ecn_settings`**). Khi hàng đợi vượt $K$, switch ghi đè cờ **CE (`0x03`)** lên IP ToS mà **KHÔNG RỚT GÓI (Zero-Drop)**, báo hiệu sớm cho Host tự động co giãn cửa sổ $cwnd$.
2. **Tầng 2: Điều Phối Tối Ưu SDN-AI (Closed-Loop Governance) — Dành Cho Persistent Elephant Flows:**
   - Dành riêng cho các luồng Voi bền vững có thời gian sống dài (hàng trăm mili-giây đến hàng chục giây).
   - Được phát hiện sớm ở giai đoạn đầu đời qua bộ phân loại Học máy nhẹ (**LightGBM / XGBoost** với thời gian suy luận $< 1\text{ ms}$).
   - Bị bẻ hướng chủ động bởi luật **OpenFlow Priority 1000** đẩy vào cổng nội bộ **`proxy-int` (Embedded NFV Proxy)** trên Access Switch.
   - Tại NFV Proxy, luồng Voi được phân tách thành các khối dữ liệu nhỏ **64 KB** và được phân bổ đa đường theo ma trận tỷ lệ tối ưu tính toán bởi mô hình **Graph Attention Network (GAT) + Proximal Policy Optimization (PPO)**.
   - Tại Egress Proxy, các khối dữ liệu được tái sắp xếp theo đúng số thứ tự TCP Sequence Number trước khi chuyển giao cho Host đích, bảo toàn nguyên vẹn tính toàn vẹn gói tin ($\text{Out-of-Order} = 0\%$).
3. **Mắt Thần Đo Lường In-Kernel eBPF/XDP Telemetry:**
   - Cửa sổ trượt $10\text{ ms}$ bóc tách 2 bit ToS để thống kê số gói CE (`0x03`), kiểm chứng độ hiệu quả của ECN Data Plane tại tốc độ dây mà không can thiệp dòng chuyển tiếp (`XDP_PASS`).

---

## 2. KIẾN TRÚC TỔNG THỂ 4 TẦNG (FOUR-TIER ARCHITECTURE)

Hệ thống được tổ chức phân tầng nghiêm ngặt với giao diện điều khiển chuẩn hóa:

```
========================================================================================
[ TẦNG 1: HỌC MÁY & TRÍ TUỆ NHÂN TẠO - AI / DRL PLANE ]
  ├── 1. Flow Classifier (XGBoost / LightGBM): Phân loại Voi/Chuột từ Bộ 10 Features Bi-flow
  ├── 2. GAT (Graph Attention Network): Nhúng trạng thái Topology & Telemetry thành Node Embeddings
  └── 3. PPO (Deep Reinforcement Learning): Xuất ma trận tỷ lệ phân tải đa đường (Traffic Matrix)
========================================================================================
                     ▲ (Clean Telemetry Datasets)            │ (Steering Rules & Flow Weights)
                     │                                       ▼
========================================================================================
[ TẦNG 2: QUẢN TRỊ & GIÁM SÁT VI MÔ - MANAGEMENT & TELEMETRY PLANE ]
  ├── Quản lý đồ thị topo động (NetworkX DiGraph) & Lần vết Full Hop-by-Hop Paths
  ├── Bộ thu thập 10 Features Bi-flow đối xứng + Phân vùng Locality (4 Cấp độ Facebook)
  ├── Giám sát sức khỏe Node & Link: Docker Stats Collector (Async Thread, Stale Cache)
  ├── Mô hình phân bổ tài nguyên OVS 2 Pha động (Two-Phase Dynamic Resource Attribution)
  ├── Động cơ eBPF / XDP In-Kernel Telemetry (Độ phân giải micro-giây, Microburst 10ms)
  └── Đánh giá hiệu năng mạng: Bisection BW, Jain's Fairness Index, Mice FCT, Packet Loss %
========================================================================================
                     ▲ (Ryu REST API :8080 / BPF Maps)       │ (REST Control / FlowMod)
                     │                                       ▼
========================================================================================
[ TẦNG 3: ĐIỀU KHIỂN SDN - SDN CONTROL PLANE (RYU CONTROLLER - OPENFLOW 1.3) ]
  ├── Khám phá liên kết LLDP tự động kèm Debounce Timer (2.0s) chống bão bản tin FlowMod
  ├── Dynamic Host Discovery & Proxy ARP thông minh triệt tiêu Broadcast Storm toàn mạng
  ├── Fast In-Memory Dedup with TTL 35s chống nghẽn Control Plane khi sinh tải mật độ cao
  ├── OpenFlow 1.3 Multi-Table Pipeline:
  │     + Table 0: Ingress Classification & Telemetry (Priority 150 Bi-flow, Priority 50 128B)
  │     + Table 1: Forwarding phần cứng & Cân bằng tải ECMP (OFPGT_SELECT, Priority 100)
  └── Traffic Steering (Priority 1000): Điều hướng luồng Voi vào cổng nội bộ "proxy-int"
========================================================================================
                     ▲ (OpenFlow 1.3 Protocol - TCP Port 6653)
                     ▼
========================================================================================
[ TẦNG 4: HẠ TẦNG DỮ LIỆU - DATA PLANE (2-CLUSTER CLOS FABRIC & NFV PROXY) ]
  ├── Core Tier (2 Switches: c1, c2)          <── Mô phỏng Facebook 6-pack Spine Switch (FSW)
  ├── Aggregation Tier (4 Switches: ag1..ag4) <── 2 Cụm Clos (Cluster 1: ag1,ag2; Cluster 2: ag3,ag4)
  ├── Access / ToR Tier (8 Switches: a1..a8)  <── Mô phỏng Facebook Wedge 40 ToR + Cổng "proxy-int"
  └── Edge Compute Tier (32 Hosts: h1_1..h8_4 [4 hosts/rack] + 1 Node Internet ngoài: inet)
========================================================================================
```

---

## 3. THIẾT KẾ HẠ TẦNG MẠNG 2-CLUSTER CLOS & ĐỒNG DẠNG PHẦN CỨNG (SIMILITUDE MATRIX)

Hạ tầng mạng được thiết kế bám sát thực tế kiến trúc **4-Post Cluster Design (Hình 1)** của bài báo ACM SIGCOMM 2015 từ Facebook, kết hợp phân tích thứ nguyên và **Lý thuyết Đồng dạng 4 Miền (4-Domain Similitude Analysis)** để co giãn quy mô phần cứng xuống môi trường ảo hóa Containernet:

```
                          +-------------------+   +-------------------+
                          |      Core c1      |   |      Core c2      |   (2 Core Switches - 200 Mbps)
                          +---------+---------+   +---------+---------+
                                    | \                   / |
                         +----------+--\-----------------+--+----------+
                         |              \               /              |
               [ CLUSTER 1: Frontend Web ]            [ CLUSTER 2: Backend Cache/DB ]
               +------------+------------+            +------------+------------+
               |  Agg ag1   |  Agg ag2   |            |  Agg ag3   |  Agg ag4   | (4 Aggregation Switches)
               +-----+------+-----+------+            +-----+------+-----+------+ (100 Mbps links)
                     |     X      |                         |     X      |
               +-----+-----+------+-----+             +-----+-----+------+-----+
               | a1  | a2  | a3   | a4  |             | a5  | a6  | a7   | a8  | (8 Access / ToR Switches)
               +--+--+--+--+--+---+--+--+             +--+--+--+--+--+---+--+--+
                  |     |     |      |                   |     |     |      |
               [4 Hosts/Rack: R1..R4]                 [4 Hosts/Rack: R5..R8]    (32 Hosts - 100 Mbps)
```

### 3.1. Cấu hình Băng thông & Tỷ lệ Nghẽn Thiết kế (Oversubscription Ratio)
- **Downlink tại Access (Host $\to$ ToR):** 4 hosts $\times 100\text{ Mbps} = 400\text{ Mbps}$.
- **Uplink tại Access (ToR $\to$ Aggregation):** 2 links $\times 100\text{ Mbps} = 200\text{ Mbps}$.
  $$\text{Tỷ lệ Oversubscription tại ToR} = \frac{400\text{ Mbps}}{200\text{ Mbps}} = 2:1$$
  *(Khớp hoàn hảo với tỷ lệ thiết kế $2:1$ của switch Facebook Wedge 40 ToR).*
- **Tầng Aggregation Fabric:** 4 downlinks $\times 100\text{ Mbps} = 400\text{ Mbps}$; 2 uplinks $\times 200\text{ Mbps} = 400\text{ Mbps}$ $\implies$ **Tỷ lệ $1:1$ (Non-blocking)**.
- **Tầng Core Fabric:** Mỗi Core switch chịu tải 4 links $\times 200\text{ Mbps} = 800\text{ Mbps}$ dung lượng đối xứng $\implies$ **Tỷ lệ $1:1$ (Non-blocking)**.

### 3.2. Ma trận Co giãn 4 Miền Phần cứng (Similitude Matrix)
1. **Miền Truyền dẫn ($\alpha = C_{\text{host}} / C_{\text{paper}} = 100\text{M} / 10,000\text{M} = 0.01$):**
   Hạ băng thông từ $10\text{ Gbps} \to 100\text{ Mbps}$ và co giãn kích thước luồng Voi theo $\alpha$ để **bảo toàn Thời gian hoàn thành luồng vật lý (FCT)**.
2. **Miền Tính toán CPU ($\beta_{\text{CPU}} = 1.0\text{ Core} / 16.0\text{ Cores} = 1/16 \implies D_{\text{arrival}} = 16.0$):**
   Hạ từ máy chủ $16\text{ Cores} \to 1.0\text{ Core}$ và giãn khoảng cách phát luồng gấp $16\text{ lần}$ để **bảo toàn mật độ tải tính toán trên mỗi CPU core**.
3. **Miền Bộ đệm Hàng đợi Switch ($\tau_{\text{buffer}} = 0.12\text{s}$):**
   Giới hạn hàng đợi $1000\text{ pkts}$ trên link $100\text{ Mbps}$, bảo toàn thời gian xả hàng đệm tương đương chip Broadcom Trident II $12\text{ MB}$ trên link $10\text{ Gbps}$.
4. **Miền Bộ nhớ Container (Cgroups):**
   Cấp phát trần `mem_limit = 1024m` và `memswap_limit = 2048m` cho mỗi container, đảm bảo không xảy ra hiện tượng OOM (Out of Memory).

---

## 4. KẾ HOẠCH SINH LƯU LƯỢNG THỐNG NHẤT FACEBOOK (ACM SIGCOMM 2015)

Dự án loại bỏ hoàn toàn việc tạo tải giả lập ngẫu nhiên vô căn cứ. Toàn bộ lưu lượng được sinh ra từ bộ sinh tải toán học mô phỏng bài báo _"Inside the Social Network's (Datacenter) Network"_ (ACM SIGCOMM 2015):

### 4.1. Số hóa & Hòa trộn ECDF Đa biến (Convex Combination ECDF)
- Trích xuất 9 đường cong ECDF thực nghiệm từ 3 cụm dịch vụ: **Hadoop**, **Web Frontend**, **Cache Follower** trên 3 đại lượng: *Flow Size*, *Inter-Arrival Time*, *Flow Duration*.
- Hòa trộn tổ hợp lồi theo trọng số mẫu thực nghiệm chuẩn hóa từ Bảng 3 bài báo:
  $$F_{\text{unified}}(x) = 0.428 \cdot F_{\text{Hadoop}}(x) + 0.388 \cdot F_{\text{Frontend}}(x) + 0.184 \cdot F_{\text{Cache}}(x)$$

### 4.2. Lấy mẫu Biến đổi Ngược & Hàm Co Giãn Kích Thước Liên Tục Từng Khúc
- Lấy mẫu Inverse Transform Sampling trên miền $\log_{10}$:
  $$u \sim \mathcal{U}(0, 1) \implies X = 10^{\text{Interp}(u, F_{\text{unified}}, \log_{10}(V))}$$
- Hàm Piecewise Continuous Scaling (bảo vệ cấu trúc gói tin nhỏ của luồng Chuột):
  $$S_{\text{scaled}}(s) = \begin{cases} s, & \text{khi } s \le S_{\text{threshold}} \ (\text{Luồng Chuột giữ nguyên } 100\%) \\ S_{\text{threshold}} + \alpha \cdot (s - S_{\text{threshold}}), & \text{khi } s > S_{\text{threshold}} \ (\text{Luồng Voi co giãn liên tục}) \end{cases}$$

### 4.3. Phân bổ Đích theo 4 Cấp độ Locality (Facebook Bảng 3)
Bộ sinh tải tự động nhận diện cấu hình cụm (`clusters.enabled = true`) và phân bổ chính xác:
- **Intra-Rack ($12.9\%$):** Giữa 2 host cùng tủ rack (chỉ đi qua Access switch).
- **Intra-Cluster ($57.5\%$):** Giữa 2 host khác rack nhưng cùng một Cụm (đi qua Access $\to$ Aggregation).
- **Intra-DC / Cross-Cluster ($11.9\%$):** Giữa 2 host thuộc 2 Cụm khác nhau (đi qua Access $\to$ Agg $\to$ Core $\to$ Agg $\to$ Access).
- **Extra-DC ($17.7\%$):** Trao đổi với máy chủ ngoài Internet qua node `inet` (`10.0.0.254`).
*(Tự động fallback về 3 cấp độ $7.2\% / 85.0\% / 7.8\%$ khi cấu hình flat mesh).*

### 4.4. Đa Giao thức Thực tế (Dual Protocol Realism) & Concurrency
- **18.4% Cache Traffic:** Phát qua giao thức **UDP Datagrams (MTU 1400B)**, phản ánh chính xác hành vi của Memcached trong bài báo Facebook, triệt tiêu chi phí 3-way handshake giả tạo của TCP trên các luồng siêu nhỏ ($66\text{B} - 150\text{B}$).
- **81.6% Web & Hadoop Traffic:** Phát qua giao thức **TCP Stream** với cơ chế `TCP_NODELAY = 1` và nhận 1-byte ACK.
- **Phát Tải Đa Luồng Đồng Thời:** Sử dụng `ThreadPoolExecutor` với `max_workers = 8` điều phối từ `traffic_config.json`, tạo ra sự cạnh tranh hàng đợi switch thực tế giữa các luồng.

---

## 5. KẾ HOẠCH HỌC MÁY (AI/ML) & NHÚNG NFV PROXY

### 5.1. Bộ Phân Loại Luồng Sớm (Early Flow Classifier)
- **Thuật toán:** XGBoost / LightGBM Classifier.
- **Bộ 10 Features Chuẩn Bi-flow:**
  - *5 đặc trưng đo trực tiếp:* `dur` (True FCT), `sbytes`, `dbytes`, `Spkts`, `Dpkts`.
  - *5 đặc trưng phái sinh:* $\text{Sload} = 8 \cdot sbytes / dur$, $\text{Dload} = 8 \cdot dbytes / dur$, $\text{smeansz} = sbytes / Spkts$, $\text{dmeansz} = dbytes / Dpkts$, $\text{Ratio} = sbytes / \max(dbytes, 1)$.
- **Chỉ tiêu chất lượng:** $\text{F1-Score} > 92\%$, $\text{Recall} > 95\%$, thời gian suy luận $< 1\text{ ms/luồng}$.

### 5.2. Định Tuyến Tối Ưu Đa Đường (Graph Attention Network + PPO DRL)
- **Graph Attention Network (GAT):** Nhúng đặc trưng trạng thái toàn mạng (Topology, link utilization, queue drops, available bandwidth) thành các Node Embeddings đa chiều trong thời gian $< 2\text{ ms}$.
- **Proximal Policy Optimization (PPO):** Thuật toán Học tăng cường sâu (Deep Reinforcement Learning) nhận trạng thái từ GAT, xuất ra ma trận tỷ lệ phân tải đa đường (Traffic Splitting Matrix) với mục tiêu cực đại hóa Bisection Bandwidth và cực tiểu hóa độ lệch chuẩn tải liên kết.

### 5.3. Embedded NFV Proxy (`proxy-int`)
- Switch Access nhận diện luồng Voi qua luật OpenFlow Priority 1000 và đẩy vào cổng nội bộ `proxy-int`.
- Ingress Proxy băm nhỏ luồng Voi thành các khối **64 KB** và phân bổ qua các đường uplink theo tỷ lệ của PPO.
- Egress Proxy gom các khối dữ liệu, tái lập đúng thứ tự TCP Sequence Number trước khi chuyển giao cho Host đích, đảm bảo độ toàn vẹn gói tin $100\%$ ($\text{Out-of-Order} = 0\%$).

---

## 6. HỆ THỐNG TIÊU CHÍ ĐÁNH GIÁ (METRICS) & 5 KỊCH BẢN THỰC NGHIỆM

### 6.1. Cơ sở Chọn Lọc Metric theo Bản Chất Giao Thức TCP
- **Luồng Chuột (Mice - Latency-sensitive):** Đánh giá qua **True FCT** và **Tail Latency ($p95, p99$)**. Luồng Chuột hoàn thành ngay trong pha TCP Slow Start, do đó phụ thuộc trực tiếp vào độ trễ lan truyền và thời gian xếp hàng của switch.
- **Luồng Voi (Elephant - Throughput-sensitive):** Đánh giá qua **Goodput (Mbps)**, **Bisection Bandwidth Utilization ($> 85\%$)** và **Jain's Fairness Index ($\mathcal{J} > 0.9$)**. Luồng Voi hoạt động trong pha TCP Congestion Avoidance, tận dụng toàn bộ dung lượng băng thông sẵn có.

### 6.2. 5 Kịch Bản Kiểm Chứng Toàn Diện
1. **Saturation & Noise:** Thử thách khả năng chia tải đa đường và chống đảo luồng (Anti-flapping) dưới tải $80\% - 100\%$ kèm nhiễu nền.
2. **Baseline & Data Shift:** Kiểm tra độ bền vững phân loại của mô hình ML khi tỷ lệ luồng Voi/Chuột dịch chuyển theo 3 profiles khác nhau.
3. **Link/Node Failures:** Đo thời gian hội tụ lại đồ thị khi đứt cáp và kiểm chứng cơ chế Fail-open (tự động quay về ECMP khi tắt AI, $\text{Downtime} = 0$).
4. **TCP Incast & Microburst:** Kiểm tra khả năng phát hiện và bẻ hướng luồng của eBPF/XDP trước các đợt xung đột biến dồn về một đích.
5. **Scalability Test:** Kiểm tra năng lực mở rộng quy mô đồ thị và phụ tải điều khiển Southbound.

---

## 7. LỘ TRÌNH 4 GIAI ĐOẠN LỚN CỦA ĐỀ TÀI & TIẾN ĐỘ THỰC TẾ

| Giai Đoạn | Nội Dung & Hạng Mục Cốt Lõi | Trạng Thái Thực Tế |
| :--- | :--- | :---: |
| **Giai đoạn 1** | **Xây dựng Hạ tầng Cơ sở, SDN Controller OpenFlow 1.3, Bộ Sinh tải Thống nhất Facebook, Thu thập Telemetry 6 Luồng & Kiểm định KS-Test** | **ĐÃ HOÀN THÀNH 100% (8/8 Phân đoạn)** |
| **Giai đoạn 2** | Huấn luyện mô hình Học máy: Phân loại luồng sớm (XGBoost/LightGBM) & Định tuyến đồ thị thông minh (GAT + PPO trên Gymnasium DCN Env). | **Sẵn sàng triển khai** |
| **Giai đoạn 3** | Phát triển ứng dụng Embedded NFV Proxy (cắt/ghép 64KB) và tích hợp vòng lặp điều khiển đóng thời gian thực (Closed-Loop Control) giữa Ryu – AI – Proxy. | Chuẩn bị triển khai |
| **Giai đoạn 4** | Thực nghiệm đối sánh toàn diện 5 kịch bản (ECMP truyền thống vs. Kiến trúc SDN-AI đề xuất), phân tích KPI và hoàn thiện bản thảo Luận văn. | Dự kiến |
