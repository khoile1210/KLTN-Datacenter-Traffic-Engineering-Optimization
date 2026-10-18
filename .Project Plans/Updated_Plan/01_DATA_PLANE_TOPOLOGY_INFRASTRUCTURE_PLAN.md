# KẾ HOẠCH CHI TIẾT: HẠ TẦNG MẠNG 2-CLUSTER CLOS & PHẢN XẠ DATA PLANE ECN
## (DATA PLANE TOPOLOGY & FAST-PATH REFLEX PLAN)

> **Mã chuyên đề:** `PLAN-WP01-DATA-PLANE`  
> **Thuộc dự án:** Nghiên cứu Tối ưu hóa Kỹ thuật Lưu lượng trong Mạng DCN Dựa trên SDN và AI (SDN-AI DCN)  
> **Cố vấn chuyên môn:** Senior SDN Architect (Gemini 4 Argon)  
> **Trạng thái thực tế:** **ĐÃ HOÀN THÀNH 100% (PHASE 1 CORE RUNTIME)**  
> **Mã nguồn liên quan:** [`controller/spine_leaf_topo.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/spine_leaf_topo.py), [`controller/topology_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/topology_config.json), [`controller/traffic_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_config.json)  

---

## 1. MỤC TIÊU & PHẠM VI KỸ THUẬT

1. **Hiện thực hóa Kiến trúc Mạng Đa tầng Clos 2 Cụm (2-Cluster 4-Post Clos Fabric):** Xây dựng môi trường giả lập độ trung thực cao (High-Fidelity Emulation) trên nền tảng Containernet, mô phỏng chính xác cấu trúc mạng trung tâm dữ liệu Facebook (ACM SIGCOMM 2015).
2. **Thiết lập Mô hình Đồng dạng Phần cứng 4 Miền (4-Domain Similitude Scaling):** Co giãn khoa học dung lượng băng thông, năng lực CPU và bộ đệm switch từ quy mô siêu trung tâm dữ liệu ($10\text{ Gbps} - 40\text{ Gbps}$, 16-core servers) xuống môi trường máy ảo nghiên cứu ($100\text{ Mbps}$, 1-core containers) mà vẫn bảo toàn các đặc trưng vật lý mạng (BDP, FCT, Queueing dynamics).
3. **Triển khai Cơ chế Phản xạ Tức thời Data Plane (Fast-Path Reflex):** Tích hợp thuật toán đánh dấu tắc nghẽn sớm **ECN (Explicit Congestion Notification - RFC 3168 / RFC 8257 DCTCP)** trên các hàng đợi Open vSwitch (OVS) bằng Linux TC RED/ECN qdisc, cho phép ghìm Microburst và bảo vệ luồng Chuột ở tốc độ dây ($\tau \le 10\mu\text{s}$), giải phóng Controller khỏi bão bản tin `Packet-In`.

---

## 2. CƠ SỞ KHOA HỌC, ĐỊNH LÝ GỐC & TÀI LIỆU THAM KHẢO

- **[Định lý Buckingham $\Pi$ & Đồng dạng Mạng]** E. Buckingham, *"On Physically Similar Systems: Illustrations of the Use of Dimensional Equations"*, Physical Review, 1914; kết hợp B. Heller, et al. (Stanford University), *"Reproducing Network Research with Mininet"*, ACM SIGCOMM CCR, 2012. *(Cơ sở phân tích thứ nguyên và bảo toàn các tỷ số không thứ nguyên $\Pi$-groups giữa môi trường mô phỏng và mạng thực tế).*
- **[Lý thuyết Hàng đợi Markovian $M/M/1/K$]** L. Kleinrock, *"Queueing Systems, Volume 1: Theory"*, Wiley-Interscience, 1975; A. K. Erlang (1909). *(Mô hình phân tích xác suất đầy hàng đợi $P_K$, thời gian lưu đệm và tỷ lệ rớt gói khi hàng đợi switch hữu hạn).*
- **[Mô hình Động học Dòng Chất lỏng DCTCP]** M. Alizadeh, A. Greenberg, D. A. Maltz, J. Padhye, P. Patel, B. Prabhakar, S. Sengupta, M. Sridharan, *"Data Center TCP (DCTCP)"*, ACM SIGCOMM 2010. *(Mô hình vi phân dòng chất lỏng $\frac{dQ(t)}{dt}$, phân tích ổn định Lyapunov chứng minh ngưỡng $K > \frac{1}{7} BDP$ triệt tiêu dao động hàng đợi mà không làm rớt thông lượng).*
- **[Facebook Clos Topology]** A. Roy, H. Zeng, J. Bagga, G. Porter, A. C. Snoeren, *"Inside the Social Network's (Datacenter) Network"*, ACM SIGCOMM 2015. *(Cơ sở kiến trúc 4-Post Cluster, tỷ lệ nén Oversubscription 2:1 tại Top-of-Rack).*
- **[Fat-Tree SIGCOMM 2008]** M. Al-Fares, A. Loukissas, A. Vahdat, *"A Scalable, Commodity Data Center Network Architecture"*, ACM SIGCOMM 2008. *(Nguyên lý mạng Clos đa tầng không tắc nghẽn - Non-blocking Fabric).*
- **[RFC 3168 / RFC 8257]** K. Ramakrishnan, et al., *"The Addition of Explicit Congestion Notification (ECN) to IP"*, RFC 3168; S. Bensley, et al., *"Data Center TCP (DCTCP): TCP Congestion Control for Data Centers"*, RFC 8257, 2017.

---

## 3. MÔ HÌNH TOÁN HỌC & ĐẶC TẢ HẠ TẦNG VẬT LÝ

### 3.1. Sơ đồ Tô-pô 2 Cụm Clos Spine-Leaf (Containernet DCN)
Hệ thống gồm 14 Switch OVS và 33 Docker Container Hosts, phân bổ thành 2 Cụm dịch vụ đối xứng:
- **Cụm 1 (Frontend Web Cluster):** Chịu trách nhiệm tiếp nhận truy vấn Web, gồm 2 Aggregation switches (`ag1, ag2`) và 4 Access switches (`a1..a4`), phục vụ 16 Hosts (`h1_1..h4_4`).
- **Cụm 2 (Backend Cache & Hadoop Cluster):** Chịu trách nhiệm lưu trữ và xử lý phân tán, gồm 2 Aggregation switches (`ag3, ag4`) và 4 Access switches (`a5..a8`), phục vụ 16 Hosts (`h5_1..h8_4`).
- **Tầng Core Spine:** Gồm 2 Core switches (`c1, c2`) kết nối liên cụm (Inter-cluster Fabric) và 1 Node Egress Gateway (`inet`, `10.0.0.254`) mô phỏng kết nối ra mạng diện rộng Internet.

```
                           +-------------------+   +-------------------+
                           |      Core c1      |   |      Core c2      |   (2 Core Switches - 200 Mbps)
                           +---------+---------+   +---------+---------+
                                     | \                   / |
                         +-----------+--\-----------------+--+-----------+
                         |               \               /               |
               [ CLUSTER 1: Frontend Web ]             [ CLUSTER 2: Backend Cache/Hadoop ]
               +------------+------------+             +------------+------------+
               |  Agg ag1   |  Agg ag2   |             |  Agg ag3   |  Agg ag4   | (4 Aggregation Switches)
               +-----+------+-----+------+             +-----+------+-----+------+ (100 Mbps links)
                     |     X      |                          |     X      |
               +-----+-----+------+-----+              +-----+-----+------+-----+
               | a1  | a2  | a3   | a4  |              | a5  | a6  | a7   | a8  | (8 Access / ToR Switches)
               +--+--+--+--+--+---+--+--+              +--+--+--+--+--+---+--+--+
                  |     |     |      |                    |     |     |      |
               [4 Hosts/Rack: R1..R4]                  [4 Hosts/Rack: R5..R8]    (32 Hosts - 100 Mbps)
```

### 3.2. Quy hoạch Băng thông & Tỷ lệ Nghẽn Thiết kế (Oversubscription Ratio)
1. **Tại Switch Access (ToR):**
   - 4 liên kết Downlink nối 4 Host: $4 \times 100\text{ Mbps} = 400\text{ Mbps}$.
   - 2 liên kết Uplink nối 2 Aggregation Switch: $2 \times 100\text{ Mbps} = 200\text{ Mbps}$.
   $$\text{Oversubscription Ratio}_{\text{ToR}} = \frac{400\text{ Mbps}}{200\text{ Mbps}} = 2:1$$
   *(Tỷ lệ $2:1$ phản ánh chính xác thiết kế của Facebook Wedge 40 ToR Switch).*
2. **Tại Switch Aggregation:**
   - 4 liên kết Downlink nối 4 Access Switch: $4 \times 100\text{ Mbps} = 400\text{ Mbps}$.
   - 2 liên kết Uplink nối 2 Core Switch: $2 \times 200\text{ Mbps} = 400\text{ Mbps}$.
   $$\text{Oversubscription Ratio}_{\text{Agg}} = \frac{400\text{ Mbps}}{400\text{ Mbps}} = 1:1 \quad (\text{Non-blocking Fabric})$$
3. **Tại Switch Core:**
   - Mỗi Core switch chịu tải 4 liên kết từ 4 Aggregation switches: $4 \times 200\text{ Mbps} = 800\text{ Mbps}$ đối xứng $\implies$ **Tỷ lệ $1:1$ (Non-blocking)**.

---

### 3.3. Lý thuyết Đồng dạng 4 Miền (4-Domain Similitude Analysis)

Để các kết quả thực nghiệm trên mô hình giả lập Containernet có giá trị học thuật tương đương hệ thống thực tế $10\text{ Gbps}$, đề tài áp dụng **Định lý $\Pi$ của Edgar Buckingham (Buckingham $\Pi$ Theorem)** trong phân tích thứ nguyên mạng (B. Heller et al., ACM SIGCOMM CCR 2012). Một hệ thống mạng gồm các biến vật lý $\{C, RTT, Q_{\text{buffer}}, S_{\text{flow}}, N_{\text{cpu}}\}$ được ánh xạ bảo toàn qua các nhóm đại lượng không thứ nguyên bất biến (Dimensionless Invariant Groups):
$$\Pi_1 = \frac{C \cdot RTT}{Q_{\text{buffer}}} = \text{const}, \quad \Pi_2 = \frac{S_{\text{flow}}}{C \cdot RTT} = \text{const}, \quad \Pi_3 = \frac{K_{\text{ecn}}}{C \cdot RTT} = \text{const}$$

#### Miền 1: Đồng dạng Băng thông & FCT ($\alpha = 0.01$)
Hạ băng thông từ $C_{\text{prod}} = 10\text{ Gbps}$ xuống $C_{\text{emu}} = 100\text{ Mbps}$.
$$\alpha = \frac{C_{\text{emu}}}{C_{\text{prod}}} = \frac{100 \times 10^6}{10 \times 10^9} = 0.01$$
Để bảo toàn Thời gian Hoàn thành Luồng (Flow Completion Time - FCT) của các luồng Voi theo $\Pi_2$:
$$T_{\text{fct}} = \frac{S_{\text{prod}}}{C_{\text{prod}}} = \frac{S_{\text{emu}}}{C_{\text{emu}}} \implies S_{\text{emu}} = \alpha \cdot S_{\text{prod}}$$

#### Miền 2: Đồng dạng BDP & Bộ đệm Hàng đợi (Buffer Sizing)
Độ trễ Round-Trip Time không tải (RTT base) trong DCN mô phỏng là $RTT_{\text{base}} \approx 1\text{ ms} = 10^{-3}\text{ s}$.
Tích số Băng thông - Độ trễ (Bandwidth-Delay Product - BDP) trên liên kết $100\text{ Mbps}$:
$$BDP_{\text{emu}} = C_{\text{emu}} \times RTT_{\text{base}} = \frac{100 \times 10^6 \text{ bps} \times 10^{-3} \text{ s}}{8 \times 1024 \text{ B/KB}} \approx 12.2\text{ KB} \sim 8\text{ packets (MSS 1460B)}$$
Trong hệ thống thực tế $10\text{ Gbps}$, chip switch Broadcom Trident II trang bị bộ đệm $12\text{ MB}$ cho toàn chip, tương ứng khoảng $150\text{ KB} - 300\text{ KB}$ cho mỗi hàng đợi cổng ($\approx 10 - 20\text{ BDP}$).
Tại môi trường emu, ta cấu hình bộ đệm tối đa theo nhóm $\Pi_1$:
$$\text{Queue Limit} = 1000\text{ packets} \approx 1.5\text{ MB}$$
Đồng thời, theo mô hình hàng đợi hữu hạn **$M/M/1/K$** (Kleinrock 1975), với cường độ tải $\rho = \frac{\lambda}{\mu} < 1$, xác suất hàng đợi bị tràn và gây rớt gói được chặn trên bởi:
$$P_{\text{overflow}} = P_K = \frac{(1 - \rho)\rho^K}{1 - \rho^{K+1}}$$

#### Miền 3: Ngưỡng Đánh dấu ECN Tức thời tại Data Plane ($K = 30\text{ KB}$)
*Cơ sở dẫn xuất toán học từ bài báo gốc DCTCP (Alizadeh et al., ACM SIGCOMM 2010):*  
Mô hình dòng chất lỏng (Fluid-flow model) biểu diễn động học hàng đợi:
$$\frac{dQ(t)}{dt} = \sum_{i=1}^N \frac{W_i(t)}{RTT} - C$$
Qua phân tích ổn định tiệm cận Lyapunov (Lyapunov Stability Analysis) quanh điểm cân bằng, Alizadeh et al. chứng minh rằng để biên độ dao động hàng đợi không bao giờ chạm đáy bằng $0$ (tránh hiện tượng underflow gây tụt throughput) nhưng cũng không chạm đỉnh bộ đệm (tránh bufferbloat), ngưỡng $K$ phải thỏa mãn bất đẳng thức:
$$K > \left(\frac{\sqrt{2N} - 1}{2}\right) \times \frac{C \cdot RTT}{N} \approx \frac{1}{7} BDP$$
Trong thực tế mạng DCN với đa luồng đồng thời ($N \ge 8$), ngưỡng tối ưu rơi vào vùng $K \approx 2 - 3 \times BDP$. Do đó, đề tài thiết lập:
$$K = 30,000\text{ Bytes} \approx 20\text{ packets} \approx 2.4 \times BDP_{\text{emu}}$$
Hàm xác suất đánh dấu ECN của hàng đợi RED/ECN trên OVS:
$$p(q) = \begin{cases} 0, & \text{nếu } q < K \\ 1, & \text{nếu } q \ge K \quad (\text{Step Marking Mode của DCTCP, RFC 8257}) \end{cases}$$
*(Khi độ dài hàng đợi $q$ vượt ngưỡng $K=30\text{KB}$, OVS tự động bật 2 bit CE `0x03` trên trường IP TOS của gói tin mà **KHÔNG HỀ RỚT GÓI**).*

#### Miền 4: Đồng dạng Tải CPU Host Container ($\beta_{\text{CPU}} = 1/16$)
Máy chủ Facebook sử dụng 16 CPU vật lý. Khi mô phỏng, mỗi container được giới hạn `cpus = 1.0` qua Docker Cgroups:
$$\beta_{\text{CPU}} = \frac{1.0}{16.0} = 0.0625 \implies \text{Hệ số giãn khoảng cách phát luồng } D_{\text{arrival}} = \frac{1}{\beta_{\text{CPU}}} = 16.0$$

---

## 4. CHI TIẾT TRIỂN KHAI MÃ NGUỒN & QUY CHUẨN ĐẤU NỐI

### 4.1. Bản đồ Cổng Cứng (Deterministic Port Allocation)
Để thuật toán OpenFlow và eBPF loader hoạt động xác định $100\%$, sơ đồ cổng trên 14 Switch OVS được cố định tuyệt đối:

| Switch Tier | Switch Name | DPID (Thập lục phân) | Cổng 1 | Cổng 2 | Cổng 3 | Cổng 4 | Cổng 5 | Cổng 6 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Access** | `a1` .. `a8` | `0x01` .. `0x08` | Uplink `ag1/ag3` | Uplink `ag2/ag4` | Host 1 | Host 2 | Host 3 | Host 4 |
| **Aggregation** | `ag1` .. `ag4`| `0x11` .. `0x14` | Downlink `a(odd)`| Downlink `a(even)`| Downlink `a...` | Downlink `a...` | Uplink `c1` | Uplink `c2` |
| **Core** | `c1` .. `c2` | `0x21` .. `0x22` | Downlink `ag1` | Downlink `ag2` | Downlink `ag3` | Downlink `ag4` | Port Egress | Node `inet` |

### 4.2. Khởi tạo Hàng đợi RED/ECN trên Linux TC Subsystem
Trong [`controller/spine_leaf_topo.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/spine_leaf_topo.py), hàm `apply_ecn_qdisc_to_switch()` tự động cấu hình hàng đợi RED hỗ trợ ECN trên mọi giao diện switch:
```bash
# Thiết lập hàng đợi RED có cờ ecn trên giao diện switch port
tc qdisc add dev {intf_name} root handle 1: red \
   limit 1500000 min 30000 max 30001 avpkt 1500 \
   burst 20 ecn bandwidth 100Mbit probability 1.0
```

### 4.3. Cấu hình Cgroup & Kernel Parameters trên Container Hosts
Tất cả 32 container Docker được kích hoạt DCTCP/ECN trong hạt nhân:
```python
# Kích hoạt ECN và tối ưu TCP Stack trên container host
host.cmd("sysctl -w net.ipv4.tcp_ecn=1")
host.cmd("sysctl -w net.ipv4.tcp_congestion_control=dctcp")
```

---

## 5. ÁNH XẠ CẤU HÌNH IAC (INFRASTRUCTURE AS CODE)

Toàn bộ thông số hạ tầng được lưu trữ tập trung tại [`controller/topology_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/topology_config.json) và tham chiếu chéo qua JSON Pointer:
- `links.bandwidth_mbps.core_agg`: $200.0\text{ Mbps}$
- `links.bandwidth_mbps.agg_access`: $100.0\text{ Mbps}$
- `links.bandwidth_mbps.access_host`: $100.0\text{ Mbps}$
- `hosts.resources.cpus`: $1.0\text{ Core}$
- `hosts.resources.mem_limit`: `"1024m"`
- Tham chiếu chéo tới ECN: `"ref:traffic_config.json#/ecn_settings/marking_threshold_k_bytes"` ($30,000\text{ Bytes}$).

---

## 6. TIÊU CHÍ KIỂM ĐỊNH & NGHIỆM THU HỌC THUẬT (ACCEPTANCE GATES)

- [x] **Khởi chạy không lỗi:** Topo 14 switch và 33 host khởi chạy thành công trên Containernet.
- [x] **Thông mạng toàn phần:** Lệnh `net.pingAll()` trong Mininet CLI đạt tỷ lệ thành công $100\%$ ($0\%$ packet drop).
- [x] **Đúng tỷ lệ Oversubscription:** Đo đạc băng thông iperf đạt đúng $2:1$ tại Access và $1:1$ tại Agg/Core.
- [x] **Kích hoạt ECN thành công:** Gói tin khi hàng đợi vượt $30\text{KB}$ được bật cờ `CE = 0x03` trên IP TOS mà không bị drop gói.
- [x] **Cô lập tài nguyên:** Host container không bị tràn RAM (OOM) khi sinh tải đồng thời ở mức $95\%$ công suất.
