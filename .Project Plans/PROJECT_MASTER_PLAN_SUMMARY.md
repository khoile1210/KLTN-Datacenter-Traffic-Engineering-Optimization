# TÓM TẮT TỔNG THỂ KẾ HOẠCH DỰ ÁN (PROJECT MASTER PLAN SUMMARY)

> **Tên đề tài:** Research on Traffic Engineering Optimization in Data Center Networks Based on Software-Defined Network and Artificial Intelligence (Nghiên cứu Tối ưu hóa Kỹ thuật Lưu lượng trong Mạng Trung tâm Dữ liệu Dựa trên Mạng Điều khiển bằng Phần mềm và Trí tuệ Nhân tạo)  
> **Ngày tổng hợp:** 2026-10-17  
> **Môi trường triển khai:** Containernet / Mininet (Ubuntu Server 22.04 LTS), Open vSwitch (Docker OVS), Ryu SDN Controller (OpenFlow 1.3), Python 3.10+, eBPF/XDP  
> **Tài liệu nguồn tổng hợp:** [`overview_plan_origin.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/overview_plan_origin.md), [`detail_plan.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/detail_plan.md), [`UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md), [`Metrics.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/Metrics.md), [`Questions.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/Questions.md)

---

## 1. MỤC TIÊU CỐT LÕI & BÀI TOÁN NGHIÊN CỨU

Trong mạng Trung tâm Dữ liệu (Data Center Network - DCN) hiện đại, lưu lượng mạng mang tính chất lưỡng cực rõ rệt (Heavy-tailed Pareto Distribution):
- **Luồng Chuột (Mice Flows):** Chiếm $80\% - 90\%$ tổng số lượng luồng nhưng kích thước rất nhỏ ($< 100\text{ KB}$), cực kỳ nhạy cảm với độ trễ (**Latency-sensitive**) và thời gian hoàn thành luồng (**Flow Completion Time - FCT**).
- **Luồng Voi (Elephant Flows):** Chỉ chiếm $10\% - 20\%$ số lượng luồng nhưng chiếm hơn $80\%$ tổng dung lượng byte toàn mạng, đòi hỏi thông lượng lớn (**Throughput-sensitive / Goodput**).

**Hạn chế của ECMP (Equal-Cost Multi-Path) truyền thống:**
ECMP băm tĩnh theo 5-tuple mà không nhận biết trạng thái tắc nghẽn đường truyền và kích thước luồng. Khi hai hay nhiều luồng Voi bị băm trùng vào một liên kết (Hash Collision), chúng làm tràn bộ đệm switch, gây rớt gói và kéo tăng đột biến độ trễ đuôi (Tail Latency / FCT) của hàng ngàn luồng Chuột đi chung đường.

**Giải pháp Đề xuất của Đề tài (SDN + AI + NFV Proxy):**
Xây dựng kiến trúc **Điều phối Lưu lượng Thông minh 4 Tầng** kết hợp:
1. **Luồng Chuột (Mice Flows):** Tiếp tục đi qua cơ chế băm phần cứng **ECMP Group Table (`OFPGT_SELECT`, Priority 100)** ngay tại Switch để đảm bảo độ trễ chuyển mạch bằng không (zero controller delay).
2. **Luồng Voi (Elephant Flows):** Được phát hiện sớm bằng mô hình Học máy (**XGBoost / LightGBM**), sau đó bị đánh chặn bởi luật **OpenFlow Priority 1000** đẩy vào cổng nội bộ **`proxy-int` (Embedded NFV Proxy)**. Tại đây, luồng Voi được cắt thành các khối **64 KB** và phân bổ đa đường theo ma trận tỷ lệ tối ưu tính toán bởi **Graph Attention Network (GAT) + Proximal Policy Optimization (PPO)**, sau đó tái hợp thứ tự TCP tại Egress Proxy trước khi giao cho Host đích.

---

## 2. KIẾN TRÚC TỔNG THỂ 4 TẦNG (FOUR-TIER ARCHITECTURE)

```
========================================================================================
[ TẦNG 1: HỌC MÁY - AI / ML PLANE ]
  ├── 1. Flow Classifier (XGBoost / LightGBM): Phân loại Voi/Chuột từ Bộ 10 Features Bi-Flow
  ├── 2. GAT (Graph Attention Network): Nén đặc trưng Topology & Link Telemetry thành Node Embeddings
  └── 3. PPO (Deep Reinforcement Learning): Xuất ma trận tỷ lệ phân tải đa đường (Traffic Matrix)
========================================================================================
                     ▲ (Datasets & Real-time State)          │ (Action Steering & Weights)
                     │                                       ▼
========================================================================================
[ TẦNG 2: QUẢN TRỊ & GIÁM SÁT - MANAGEMENT & TELEMETRY PLANE ]
  ├── Quản lý đồ thị mạng động (NetworkX DiGraph) & Lần vết Full Hop-by-Hop Paths
  ├── Thu thập Bộ 10 Features Bi-Flow đối xứng + Phân vùng Locality (Intra-Rack, Extra-Rack, Extra-DC)
  ├── Giám sát sức khỏe Node & Link (Non-blocking Docker Stats + Dynamic Resource Attribution)
  ├── Động cơ eBPF / XDP In-Kernel Telemetry (Độ phân giải micro-giây, cửa sổ trượt Microburst 10ms)
  └── Tính toán các chỉ số học thuật (Bisection BW, Jain's Fairness Index, Mice FCT, Packet Loss %)
========================================================================================
                     ▲ (REST API :8080 / BPF Maps)           │ (REST Control Commands)
                     │                                       ▼
========================================================================================
[ TẦNG 3: ĐIỀU KHIỂN - SDN CONTROL PLANE (RYU CONTROLLER - OPENFLOW 1.3) ]
  ├── Khám phá liên kết LLDP tự động kèm Debounce Timer (2.0s) chống bão bản tin FlowMod
  ├── Dynamic Host Discovery & Proxy ARP thông minh triệt tiêu Broadcast Storm
  ├── OpenFlow 1.3 Multi-Table Pipeline:
  │     + Table 0: Phân loại luồng 5-tuple Bi-flow (Priority 150) & Bắt luồng mới (Priority 50)
  │     + Table 1: Định tuyến đích IPv4 qua ECMP Group Table (OFPGT_SELECT, Priority 100)
  └── Traffic Steering (Priority 1000): Bẻ hướng luồng Voi vào cổng nội bộ "proxy-int"
========================================================================================
                     ▲ (OpenFlow 1.3 - TCP 6653)
                     ▼
========================================================================================
[ TẦNG 4: DỮ LIỆU - DATA PLANE (CONTAINERNET SPINE-LEAF & EMBEDDED NFV PROXY) ]
  ├── Core Tier (2 Switches: c1, c2)          <── Mô phỏng Facebook 6-pack Fabric Switch (FSW)
  ├── Aggregation Tier (4 Switches: ag1..ag4) <── Mô phỏng Facebook 6-pack Cluster Switch (CSW)
  ├── Access / ToR Tier (8 Switches: a1..a8)  <── Mô phỏng Facebook Wedge 40 RSW + Cổng "proxy-int"
  └── Edge Compute Tier (32 Hosts: h1_1..h8_4 [4 hosts/rack] + 1 External Node: inet)
========================================================================================
```

---

## 3. THIẾT KẾ HẠ TẦNG MẠNG & ĐỒNG DẠNG PHẦN CỨNG (SIMILITUDE MATRIX)

Kế hoạch thiết kế hạ tầng dựa trên thông số phần cứng thực tế của trung tâm dữ liệu Facebook giai đoạn 2014–2016 (Altoona, Prineville, Forest City) và áp dụng **Lý thuyết Đồng dạng 4 Miền Chức năng (4-Domain Similitude)** để co giãn xuống môi trường ảo hóa Containernet:

1. **Cấu trúc Topology Spine-Leaf:**
   - **8 Access Switches (`a1..a8`):** Đóng vai trò Top-of-Rack (ToR), mỗi rack quản lý **4 Docker Hosts** (`h1_1..h8_4`, tổng 32 hosts nội bộ dải `10.0.0.1/24` – `10.0.0.32/24`).
   - **4 Aggregation Switches (`ag1..ag4`):** Kết nối full-mesh với Access và Core.
   - **2 Core Spine Switches (`c1, c2`):** Kết nối trục chính và cắm ra node Internet ngoài DCN (`inet` – `10.0.0.254/24`).
   - **Băng thông phân tầng:** Host–Access = $20\text{ Mbps}$, Access–Agg = $50\text{ Mbps}$ (Oversubscription $2.5:1$), Agg–Core = $100\text{ Mbps}$, Core–Inet = $100\text{ Mbps}$.
2. **Ma trận Co giãn 4 Miền Phần cứng:**
   - **Miền Truyền dẫn ($\alpha = 1/500 = 0.002$):** Hạ băng thông từ $10\text{ Gbps} \to 20\text{ Mbps}$ và thu nhỏ phần đuôi của luồng Voi theo tỷ lệ $\alpha$ để **bảo toàn Thời gian hoàn thành luồng (FCT)**.
   - **Miền Tính toán CPU ($\beta_{\text{CPU}} = 1/16$, $D_{\text{arrival}} = 16.0$):** Hạ từ máy chủ Xeon $16\text{ Cores} \to 1.0\text{ Core}$ (`cpu_quota = 100,000us`) và giãn khoảng cách phát luồng gấp $16\text{ lần}$ để **bảo toàn mật độ tải công việc trên mỗi CPU Core**.
   - **Miền Hàng đợi Switch ($\tau_{\text{buffer}} \approx 9.6 - 10\text{ ms}$):** Giới hạn hàng đợi $1000\text{ pkts}$ trên link $20\text{ Mbps}$, tương đương chính xác thời gian xả bộ đệm SmartBuffer $12\text{ MB}$ của chip Broadcom Trident II trên link $10\text{ Gbps}$.
   - **Miền Bộ nhớ RAM:** Cấp phát trần `mem_limit = 1024m` ($1\text{ GB}$) và `memswap_limit = 2048m` cho mỗi container, chống tràn bộ nhớ (OOM).

---

## 4. KẾ HOẠCH SINH LƯU LƯỢNG THỐNG NHẤT FACEBOOK (ACM SIGCOMM 2015)

Thay vì tạo tải ngẫu nhiên thiếu căn cứ, dự án xây dựng bộ sinh tải tái hiện chính xác bài báo _"Inside the Social Network's (Datacenter) Network"_ (Facebook, ACM SIGCOMM 2015):

1. **Số hóa & Hòa trộn Phân phối Đa biến:**
   - Số hóa 9 đường cong ECDF thực nghiệm từ bài báo gốc cho 3 dịch vụ (**Hadoop**, **Web Frontend**, **Cache Follower**) trên 3 đại lượng: *Flow Size*, *Inter-Arrival Time*, *Flow Duration*.
   - Tổ hợp lồi theo trọng số mẫu chuẩn hóa từ Table 3:
     $$w_{\text{Hadoop}} = 42.8\%, \quad w_{\text{Frontend}} = 38.8\%, \quad w_{\text{Cache}} = 18.4\%$$
2. **Hàm Scale Liên tục Chống Nghịch đảo (Piecewise Continuous Scaling):**
   $$S_{\text{scaled}}(s) = \begin{cases} s & \text{khi } s \le S_{\text{threshold}} \ (\text{Mice Flows giữ nguyên } 100\%) \\ S_{\text{threshold}} + (s - S_{\text{threshold}}) \times \alpha & \text{khi } s > S_{\text{threshold}} \ (\text{Elephant Flows co giãn liên tục}) \end{cases}$$
3. **Phân bổ Đích theo 3 Vùng Locality:**
   - **Intra-Rack ($7.2\%$):** Giữa 2 host cùng tủ rack (chỉ đi qua Access switch).
   - **Extra-Rack ($85.0\%$):** Giữa 2 host khác tủ rack (đi qua Access $\to$ Agg $\to$ Core).
   - **Extra-Datacenter ($7.8\%$):** Đi ra/vào node `inet`.
4. **Kiến trúc Bộ đôi Sinh tải Tách rời (Decoupled Engines):**
   - **Engine 1 (`traffic_generator.py`):** Phát lưu lượng nền thống nhất bằng lệnh `iperf3 -c {dst} -p {port} -B {src} -n {S_scaled}` qua đa cổng `5201–5204`.
   - **Engine 2 (`microburst_generator.py`):** Bơm xung đột biến ngắn ($< 10\text{ ms}$, $20 - 80\text{ KB}$) bằng raw TCP socket với `TCP_NODELAY = 1`, cờ ECN `ECT(0) = 0x02`, hỗ trợ cả chế độ ngẫu nhiên và TCP Incast.
5. **Quy trình 2 Pha Xác định Ngưỡng Ground-Truth & Kiểm định KS-Test:**
   - Thu thập dữ liệu thô $\to$ Phân tích phân vị $P80, P90, P95, P99$ của `sbytes` và `Sload` theo nguyên lý Pareto $\to$ Gán nhãn Ground-Truth $\to$ Kiểm định Kolmogorov-Smirnov 2 mẫu (`ks_2samp`) đối chiếu với đường cong gốc của Facebook.

---

## 5. KẾ HOẠCH HỌC MÁY (AI/ML) & NHÚNG NFV PROXY

1. **Bộ 10 Đặc trưng Bi-Flow Chuẩn cho Classifier (`XGBoost / LightGBM`):**
   - *5 đặc trưng trực tiếp:* `dur`, `sbytes`, `dbytes`, `Spkts`, `Dpkts`.
   - *5 đặc trưng phái sinh:* `Sload`, `Dload`, `smeansz`, `dmeansz`, `Ratio` ($sbytes / dbytes$).
   - Mục tiêu: Đạt $\text{Recall} > 95\%$, $\text{Precision} > 90\%$, $\text{F1-Score} > 92\%$, thời gian suy luận $< 1\text{ ms/luồng}$.
2. **Mô hình Đồ thị & Học tăng cường (`GAT + PPO`):**
   - **GAT:** Nén trạng thái toàn mạng (băng thông khả dụng, utilization, queue drops, TCAM) thành các Node Embeddings trong $< 2\text{ ms}$.
   - **PPO:** Nhận trạng thái từ GAT để xuất ra ma trận tỷ lệ phân tải đa đường (Traffic Splitting Ratios) tối ưu hóa Bisection Bandwidth và giảm độ lệch chuẩn tải liên kết, thời gian quyết định $< 10\text{ ms}$.
3. **Embedded NFV Proxy (`proxy-int`):**
   - Đón luồng Voi từ luật OpenFlow Priority 1000, cắt gói thành các khối $64\text{ KB}$, rải qua các đường truyền theo tỷ lệ PPO, và gom/sắp xếp lại đúng thứ tự TCP Sequence tại Egress Proxy (đảm bảo $\text{Out-of-Order} = 0\%$, toàn vẹn mã băm SHA-256/MD5 $100\%$).

---

## 6. HỆ THỐNG TIÊU CHÍ ĐÁNH GIÁ (METRICS) & 5 KỊCH BẢN THỰC NGHIỆM

### 6.1. Lý thuyết Chọn lọc Metric theo Bản chất Giao thức TCP
- **Đối với Luồng Chuột (Mice Flows - Latency-sensitive):** Đo lường **FCT (Flow Completion Time)** và **Tail Latency ($p95, p99$)** vì luồng Chuột kết thúc ngay trong pha TCP Slow Start (bị giới hạn bởi RTT chứ không phải băng thông).
- **Đối với Luồng Voi (Elephant Flows - Throughput-sensitive):** Đo lường **Goodput (Mbps)**, **Achieved Bisection Bandwidth ($> 85 - 90\%$)** và **Jain's Fairness Index ($\mathcal{J} > 0.9$)** vì luồng Voi hoạt động ở pha TCP Congestion Avoidance.

### 6.2. 5 Kịch bản Kiểm chứng Toàn diện
| Kịch bản | Mục tiêu cốt lõi | Điều kiện tải | Chỉ số KPI mục tiêu |
| :--- | :--- | :---: | :--- |
| **1. Saturation & Noise** | Chia tải đa đường & chống đảo đường (Anti-flapping) | $80\% - 100\%$ + Nhiễu | Bisection BW $> 85\%$, Jain's $> 0.9$, Flapping $< 3$/phút |
| **2. Baseline & Data Shift** | Độ bền phân loại ML khi dịch chuyển tỷ lệ Voi/Chuột | $30\% - 50\%$ (3 Profiles) | F1-Score $> 92\%$, Mice FCT giảm $30\% - 50\%$ |
| **3. Link/Node Failures** | Tự phục hồi khi đứt cáp & Hạ cấp mềm (Fail-open) | $100\%$ đơn luồng | Hội tụ $< 2\text{s}$, Khi tắt AI tự về ECMP ($\text{Downtime} = 0$) |
| **4. TCP Incast** | Tốc độ vòng lặp điều khiển trước xung Microburst | Đột biến dồn 1 đích | Time-to-Steer $< 50\text{ms}$, Packet Loss $< 0.1\%$ |
| **5. Scalability Test** | Khả năng mở rộng quy mô topo (Spine-Leaf $\to$ Fat-Tree) | Tải nền phân tán | Southbound BW $< 20\text{ Mbps}$, GAT Latency $< 10\text{ms}$ |

---

## 7. LỘ TRÌNH 4 GIAI ĐOẠN LỚN CỦA ĐỀ TÀI

- **Giai đoạn 1:** Xây dựng Hạ tầng Cơ sở, Controller OpenFlow 1.3, Tầng Quản trị Telemetry (OpenFlow + eBPF/XDP), Bộ Sinh tải Thống nhất Facebook, Thu thập Dataset & Kiểm định Thống kê KS-Test.
- **Giai đoạn 2:** Huấn luyện và đánh giá các mô hình Học máy (Bộ phân loại luồng XGBoost/LightGBM và mô hình định tuyến đồ thị GAT + PPO trên môi trường Gymnasium).
- **Giai đoạn 3:** Phát triển ứng dụng Embedded NFV Proxy (cắt/ghép khối 64KB) và tích hợp vòng lặp điều khiển đóng (Closed-Loop Control) thời gian thực giữa Ryu – AI – Proxy.
- **Giai đoạn 4:** Chạy đối sánh 5 kịch bản thực nghiệm (ECMP truyền thống vs. SDN-AI), tổng hợp biểu đồ khoa học và hoàn thiện cuốn Luận văn Tốt nghiệp.
