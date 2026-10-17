# KẾ HOẠCH TỔNG THỂ & THIẾT KẾ HỆ THỐNG V2 (OVERVIEW PLAN V2)

- **Tên đề tài:** Research on Traffic Engineering Optimization in Data Center Networks Based on Software-Defined Network and Artificial Intelligence
- **Môi trường mô phỏng:** Containernet (Trên nền tảng Ubuntu Server 22.04 LTS)
- **Ngôn ngữ lập trình:** Python 3.10+
- **SDN Controller:** Ryu Controller (Giao thức OpenFlow 1.3)
- **Chuyển mạch:** Open vSwitch (Mô hình Docker OVS Switches có nhúng NFV Proxy)
- **Mô hình Topology:** Multi-tier Spine-Leaf (02 Core, 04 Aggregation, 08 Access Leaf, 08 Hosts nội bộ, 01 Host Internet)

---

## I. KIẾN TRÚC TỔNG THỂ 4 TẦNG (FOUR-TIER ARCHITECTURE)

```
========================================================================================
[ 1. TẦNG HỌC MÁY - AI / ML Plane ] (Triển khai trên GPU/CPU Server độc lập)
  +----------------------------------------------------------------------------------+
  |                                AI / ML ENGINE                                    |
  |----------------------------------------------------------------------------------|
  | 1. Flow Classifier (XGBoost / LightGBM): Phân loại luồng Voi/Chuột từ 10 features|
  | 2. GAT (Graph Attention Network): Nén đặc trưng topo & sức khỏe mạng thành Graph |
  | 3. PPO (Proximal Policy Optimization): Tính ma trận tỷ lệ định tuyến đa đường    |
  +-----------------------------------------+----------------------------------------+
                     ▲                      │
     (Nhận Telemetry)| REST / gRPC API      │ (Gửi Quyết định / Action Steering)
                     │                      ▼ REST / gRPC API
=====================|==================================================================
[ 2. TẦNG QUẢN TRỊ - Management Plane ]     │
  +------------------+-------------------+  │
  |     Network Monitoring & Telemetry   |  │
  |--------------------------------------|  │
  | - Quản lý đồ thị mạng (NetworkX)     |  │
  | - Thu thập Telemetry (Chu kỳ 1.0s)   |  │
  | - Trích xuất Bộ 10 FEATURES Bi-Flow  |  │
  | - Lần vết Full Hop-by-Hop Paths      |  │
  | - Xuất Datasets (.csv) cho AI Plane  |  │
  +------------------+-------------------+  │
                     ▲                      │
       (HTTP Polling)| REST API (:8080)     │
=====================|======================|===========================================
[ 3. TẦNG ĐIỀU KHIỂN - Control Plane ]      ▼
  +----------------------------------------------------------------------------------+
  |                           RYU CONTROLLER (OpenFlow 1.3)                          |
  |----------------------------------------------------------------------------------|
  | - Tự động phát hiện liên kết LLDP (Có cơ chế Debounce Timer 2.0s chống bão rule) |
  | - Dynamic Host Discovery & Proxy ARP thông minh (chống Broadcast Storm)          |
  | - Cài đặt cặp Flow Rule 5-tuple đối xứng (Priority 150) để OVS đếm riêng 2 chiều |
  | - Cài đặt ECMP Group Table (OFPGT_SELECT) cho luồng Chuột (Priority 100)         |
  | - Cài đặt Traffic Steering (Priority 1000) bẻ luồng Voi vào cổng "proxy-int"     |
  +-----------------------------------------▲----------------------------------------+
                                            │
                                            │ Giao thức OpenFlow 1.3 (TCP Port 6653)
                                            ▼
========================================================================================
[ 4. TẦNG DỮ LIỆU - Data Plane (Môi trường Containernet / Docker OVS) ]

+----------+        +---------------------------------------------------+        +----------+
|          |        | DOCKER OVS SWITCHES (Access / Aggregation / Core) |        |          |
| Host SRC |------->| - Table 0: Flow Table phân cấp (Priority 100/150) |------->| Host DST |
|          |        | - ECMP Hash Engine (OFPGT_SELECT) chia tải Mice   |        |          |
+----------+        +-------------------------+-------------------------+        +----------+
                                              │
                                              │ (Priority 1000: Bẻ hướng luồng Voi)
                                              ▼
                         +------------------------------------------+
                         | CỔNG NỘI BỘ: proxy-int (type=internal)   |
                         |   └── NFV Proxy Ingress (Cắt gói 64KB)   |
                         |       └── Đa đường Core/Agg qua AI PPO   |
                         |           └── NFV Proxy Egress (Gom gói) |
                         +------------------------------------------+
```

---

## II. ĐẶC TẢ CHI TIẾT CÁC CƠ CHẾ HOẠT ĐỘNG

### 1. Khám Phá Mạng & Chống Bão Bản Tin (Bootstrapping & Debounce)

- Khi các Switch OVS khởi động, các gói tin LLDP gửi về Controller để tổng hợp sơ đồ liên kết vào thư viện NetworkX (`DiGraph`).
- **Debounce Timer (2.0s):** Controller trì hoãn tính toán cho tới khi topology hoàn toàn ổn định (không còn sự kiện LinkAdd mới trong 2 giây). Khi đó Controller mới nạp đồng loạt ECMP Group Table, loại bỏ triệt để hiện tượng bão bản tin FlowMod/GroupMod làm nghẽn kênh điều khiển.
- **Dynamic Host Discovery & Proxy ARP:** Controller tự động học vị trí của Host $(IP, MAC)$ qua các bản tin ARP/IP đầu tiên từ cổng Access. Bản tin ARP Request được Controller trả lời trực tiếp (Proxy ARP), ngăn chặn hoàn toàn nguy cơ Broadcast Storm trong cấu trúc liên kết vòng Spine-Leaf.

---

### 2. Định Danh Luồng & Bộ 10 Đặc Trưng (Bi-Flow Telemetry Dataset)

Để mô hình Machine Learning phân loại chính xác luồng Voi và luồng Chuột, hệ thống định danh luồng theo **5-tuple song hướng (Bidirectional Flow / Bi-Flow)**:

$$
\text{Bi-Flow ID} = \Big(\min(\text{IP}_A, \text{IP}_B),\; \max(\text{IP}_A, \text{IP}_B),\; \min(\text{Port}_A, \text{Port}_B),\; \max(\text{Port}_A, \text{Port}_B),\; \text{Protocol}\Big)
$$

Dữ liệu được trích xuất định kỳ (1.0s/lần) gồm **Bộ 10 Features chuẩn mực**:

#### Nhóm 1: Các đặc trưng trực tiếp (Lấy từ bộ đếm phần cứng OVS)

1. **`dur`** (Flow Duration): Thời gian tồn tại của luồng (giây).
2. **`sbytes`** (Forward Bytes): Tổng số byte truyền theo chiều đi từ nguồn sang đích.
3. **`dbytes`** (Backward Bytes): Tổng số byte truyền theo chiều về từ đích trả về nguồn.
4. **`Spkts`** (Forward Packets): Tổng số gói tin truyền theo chiều đi.
5. **`Dpkts`** (Backward Packets): Tổng số gói tin truyền theo chiều về.

#### Nhóm 2: Các đặc trưng phái sinh (Tính toán tại chỗ với $\epsilon = 10^{-6}$ chống chia 0)

6. **`Sload`** (Forward Throughput): Tốc độ truyền chiều đi:

   $$
   Sload = \frac{sbytes}{\max(dur, \epsilon)} \quad (\text{Bytes/s})
   $$

7. **`Dload`** (Backward Throughput): Tốc độ truyền chiều về:

   $$
   Dload = \frac{dbytes}{\max(dur, \epsilon)} \quad (\text{Bytes/s})
   $$

8. **`smeansz`** (Mean Packet Size Forward): Kích thước trung bình gói tin chiều đi:

   $$
   smeansz = \frac{sbytes}{\max(Spkts, 1)} \quad (\text{Bytes})
   $$

9. **`dmeansz`** (Mean Packet Size Backward): Kích thước trung bình gói tin chiều về:

   $$
   dmeansz = \frac{dbytes}{\max(Dpkts, 1)} \quad (\text{Bytes})
   $$

10. **`Ratio`** (Asymmetry Ratio): Tỷ lệ chênh lệch dung lượng hai chiều:

    $$
    Ratio = \frac{sbytes}{dbytes + \epsilon}
    $$

    _(Luồng Voi truyền tải dữ liệu lớn một chiều có $Ratio \gg 1$; Luồng Chuột trao đổi hai chiều có $Ratio \approx 1$)._

---

### 3. Lộ Trình Đa Tầng Đầy Đủ (Full End-to-End Hop-by-Hop Path)

Mỗi mẫu luồng trong dataset ghi nhận toàn bộ chuỗi di chuyển thực tế qua cả 3 phân tầng mạng:

$$
\mathbf{h\_src} \to \mathbf{a\_src}[\text{in}\to\text{out}] \to \mathbf{ag\_src}[\text{in}\to\text{out}] \to \mathbf{c\_core}[\text{in}\to\text{out}] \to \mathbf{ag\_dst}[\text{in}\to\text{out}] \to \mathbf{a\_dst}[\text{in}\to\text{out}] \to \mathbf{h\_dst}
$$

- Cung cấp chỉ số `hop_count` chuẩn xác (tổng số switch tham gia định tuyến).
- Giám sát chính xác gói tin đi qua Switch Aggregation nào (`ag1`..`ag4`) và Core Switch nào (`c1, c2`).

---

### 4. Cơ Chế Xử Lý Luồng Chuột (Mice Flows) — Baseline ECMP

- **Độ ưu tiên:** Luật cơ bản với `Priority = 100` trên Flow Table.
- **Cơ chế:** Gói tin được nạp vào Group Table loại `OFPGT_SELECT`. Switch OVS tự động băm phần cứng (Hash 5-tuple) để phân tải đều qua các cổng kết nối lên tầng Aggregation với trọng số bằng nhau (`weight = 100`).
- **Mục tiêu:** Luồng Chuột chiếm 80% số lượng luồng nhưng dung lượng nhỏ, được chuyển tiếp với độ trễ thấp nhất mà không cần can thiệp phức tạp từ Controller.

---

### 5. Cơ Chế Xử Lý Luồng Voi (Elephant Flows) — AI Traffic Steering & Embedded NFV Proxy

1. **Nhận diện:** Bộ phân loại XGBoost/LightGBM phân tích 10 features từ Telemetry. Khi luồng vượt ngưỡng ($Sload > 1\text{ MB/s}$ hoặc $sbytes > 5\text{ MB}$), nhãn được định danh là Luồng Voi.
2. **Đánh chặn (Traffic Steering):** Controller đẩy ngay bản tin `OFPFlowMod` với **`Priority = 1000`** (ưu tiên cao hơn ECMP 100) xuống Ingress Access Switch, ép luồng chuyển tiếp vào cổng nội bộ **`proxy-int`**.
3. **Mô hình Switch Application Hosting (Embedded NFV Proxy):**
   - NFV Proxy được nhúng trực tiếp trong container Docker của Access Switch, đọc gói từ `proxy-int` với độ trễ cực thấp (near zero-copy).
   - **NFV Proxy Ingress:** Cắt nhỏ gói tin TCP thành các block 64KB.
   - **Điều phối đa đường (GAT + PPO):** GAT nén đồ thị trạng thái toàn mạng; PPO tính toán ma trận tỷ lệ lưu lượng (Traffic Matrix) để rải các block 64KB qua nhiều đường độc lập.
   - **NFV Proxy Egress:** Đệm gói, tái hợp và sắp xếp lại thứ tự TCP trước khi trả về Switch đích $\rightarrow$ Host đích.

---

### 6. Mô Hình Sinh Tải Thực Nghiệm Facebook DCN & Bảng Cấu Hình Phần Cứng Tham Chiếu (2014–2016)

> [!NOTE]
> **Tài liệu đặc tả chi tiết:** Toàn bộ công thức toán học, thuật toán nghịch đảo ECDF, quy trình lấy mẫu và phân tích phân vị được trình bày chi tiết trong tài liệu chuyên biệt: [`.Project Plans/UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md) và tiến độ tại [`.Project Plans/TRAFFIC_SIMULATION_CHECKLIST.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/TRAFFIC_SIMULATION_CHECKLIST.md).

#### 6.1. Tóm Tắt Sơ Bộ Mô Hình Sinh Tải Thống Nhất (Unified DCN Traffic Simulation)

Hệ thống sử dụng mô hình phụ tải thực nghiệm trích xuất từ bài báo của Facebook (_"Inside the Social Network’s (Datacenter) Network"_, ACM SIGCOMM 2015):

1. **Số hóa 9 đường ECDF thực nghiệm:** Trích xuất tọa độ điểm phân vị chuẩn của 3 loại cụm (Web Frontend, Cache, Hadoop Analytics) trên 3 đại lượng: Kích thước luồng (Flow Size - KB), Thời lượng (Flow Duration - ms) và Khoảng cách thời gian giữa các luồng (Inter-Arrival Time - $\mu$s).
2. **Hòa trộn phân phối lồi:** Áp dụng trọng số mẫu $42.8\%$ Hadoop, $38.8\%$ Frontend, $18.4\%$ Cache để tạo ra 3 hồ sơ ECDF đại diện thống nhất (`controller/cdf_profiles/`).
3. **Bộ lấy mẫu toán học thích ứng (`unified_sampler.py`):**
   - Co giãn phi tuyến liên tục (Piecewise Continuous Scaling) cho luồng lớn theo tỷ số băng thông $\alpha = C_{\text{host}} / 10\text{Gbps}$ trong khi giữ nguyên các gói tin nhỏ (Mice Flow).
   - Giãn nhịp phát (Time Dilation $D_{\text{arrival}} = 16.0$) dựa trên tỷ số core CPU máy chủ vật lý so với máy ảo để bảo vệ hệ thống không bị quá tải.
   - Điều hướng địa chỉ đích theo 3 vùng không gian (Locality): $7.2\%$ cùng Rack (giữa các host trong cùng rack `h{r}_1..h{r}_4` chuyển mạch nội bộ qua switch `a{r}`), $85.0\%$ xuyên Rack DCN, $7.8\%$ ra Internet.
4. **Đồng nhất công cụ phát nền & Module Heavy Jitter tách biệt:**
   - Mọi luồng nền được truyền bằng lệnh đồng nhất: `iperf3 -c {dst_ip} -p {port} -n {S_scaled}`.
   - Bơm Heavy Jitter / Microburst ($< 10\text{ ms}$, cờ ECN TOS `0x02`) qua script độc lập `microburst_generator.py` dùng raw socket và tự ghi nhận nhật ký ground-truth phía Client.
5. **Kiến trúc quản lý 2 tệp cấu hình tham chiếu động (Infrastructure-as-Code):**
   - [`controller/topology_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/topology_config.json): Quản lý hạ tầng Spine-Leaf (Controller, Switch DPID, link bandwidth, Docker hosts mặc định **1 Rack = 4 Hosts**, tổng 32 hosts nội bộ `h1_1..h8_4` + 1 node `inet`, NFV proxy) và cấu hình phần cứng gốc.
   - [`controller/traffic_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_config.json): Quản lý mô hình phụ tải, tự động tham chiếu động các thông số dùng chung từ `topology_config.json` qua cú pháp `ref:<file>#/<path>` (loại bỏ hoàn toàn nguy cơ bất đồng nhất khi sửa đổi).

#### 6.2. Bảng Thông Số Phần Cứng Trung Tâm Dữ Liệu Facebook (Giai Đoạn 2014–2016)

Bảng dưới đây tổng hợp các thông số kỹ thuật thực tế của hệ thống chuyển mạch và máy chủ Facebook trong giai đoạn ghi nhận dữ liệu trace, làm căn cứ đối chuẩn cho các thông số mô phỏng:

| Thiết bị (Server / Switch) | Dòng thiết bị                                                                    | Thời gian & Vị trí sử dụng                                                                                                                                                                                                                                                                                                                                                                                                                                         | Cấu hình (RAM, CPU, ASIC, Cổng, Bộ đệm, Lưu trữ)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Tài liệu tham khảo (Vị trí trích dẫn cụ thể)                                                                                                                                                                                                                                                                                                                                     |
| :------------------------- | :------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Switch**                 | **Facebook Wedge 40\***(Top-of-Rack / Rack Switch - RSW)\*                       | • **Thời gian:** Công bố tháng 6/2014, triển khai sản xuất đại trà từ cuối 2014 đến 2015 (trùng đợt đo đạc trace).• **Vị trí mạng:** Đặt ở đỉnh mỗi tủ rack (**Top-of-Rack / RSW**), kết nối trực tiếp toàn bộ máy chủ trong rack lên tầng Fabric.• **Trung tâm dữ liệu (DC Sites):** Triển khai đầu tiên tại Datacenter **Altoona (Iowa)**, sau đó mở rộng sang **Prineville (Oregon)** và **Forest City (North Carolina)**.                                      | • **Switching ASIC:** Broadcom StrataXGS Trident II (BCM56850), công suất $1.28\text{ Tbps}$ (Full-Duplex).• **Packet Buffer:** $12\text{ MB}$ On-chip Shared Buffer (kiến trúc Broadcom SmartBuffer).• **Cổng mạng (Ports):** $16 \times \text{QSFP+} \ 40\text{ GbE}$ (breakout thành $64 \times 10\text{ GbE}$; thực tế cắm $40 \text{ – } 48$ cổng $10\text{G}$ xuống Server và $4 \text{ – } 16$ cổng $10\text{G}/40\text{G}$ Uplink lên CSW).• **CPU quản lý (Control Plane):** Intel Atom C2550 (4 cores, $2.4\text{ GHz}$) trên module OCP Panther+ Microserver.• **RAM điều khiển:** $8\text{ GB}$ DDR3-1600 ECC.• **Hệ điều hành:** FBOSS trên Linux CentOS.                                                                                                                | 1. **Bài báo SIGCOMM 2015:** Mục 3.1 (Trang 3) và **Reference [35]** (Trang 15): _A. Simpkins, "Facebook open switching system (fboss) and wedge in the open", Facebook Code, 2014_.2. **Tài liệu chuẩn OCP:** _Facebook Wedge 40 Switch Specification v1.0_, Open Compute Project (2014).3. **Broadcom:** _StrataXGS Trident II BCM56850 Product Brief_ (2013).                 |
| **Switch**                 | **Facebook "6-pack"\***(Cluster Switch - CSW / Fabric Switch - FSW)\*            | • **Thời gian:** Công bố tháng 2/2015, đưa vào vận hành thực tế từ đầu 2015.• **Vị trí mạng:** Đóng vai trò làm switch tầng gom cụm (**Cluster Switch - CSW**) và switch trục xương sống (**Fabric Switch - FSW**) trong kiến trúc Data Center Fabric.• **Trung tâm dữ liệu (DC Sites):** Triển khai quy mô lớn tại Datacenter **Altoona (Iowa)** và các DC thế hệ mới của Facebook.                                                                               | • **Kiến trúc:** Khung gầm mô-đun 2 tầng dạng Clos (non-blocking fabric) ghép từ **12 bo mạch Wedge 40** (8 bo line cards mặt trước + 4 bo fabric cards mặt sau).• **Switching ASIC:** $12 \times$ Broadcom Trident II (BCM56850).• **Packet Buffer:** $12\text{ MB}$ trên mỗi bo mạch ASIC.• **CPU & RAM:** Mỗi bo mạch trang bị độc lập 1 module microserver Intel Atom C2550, $8\text{ GB}$ RAM, chạy FBOSS.                                                                                                                                                                                                                                                                                                                                                                       | 1. **Bài báo SIGCOMM 2015:** Mục 2.1 & Mục 3.1 (Trang 3-4, kiến trúc kết nối cụm CSW và Fabric).2. **Facebook Engineering Blog:** _Z. Ahmad, "Introducing '6-pack': the first open modular switch", Facebook Engineering, Tháng 2/2015_.                                                                                                                                         |
| **Server**                 | **Facebook Winterfell (v3) / Leopard (v1)\***(Web Server / Frontend)\*           | • **Thời gian:** 2013 – 2015 (Winterfell ra mắt OCP 2013; Leopard ra mắt cuối 2014, là nền tảng máy chủ web chính trong giai đoạn đo trace).• **Vị trí mạng:** Nằm trong các tủ rack chuyên trách Web (**Web Server Racks**) thuộc **Frontend Clusters / Server Pods**.• **Trung tâm dữ liệu (DC Sites):** Đặt tại các trung tâm dữ liệu chính của Facebook: **Prineville (Oregon)**, **Forest City (North Carolina)**, **Altoona (Iowa)**, **Luleå (Thụy Điển)**. | • **CPU:** Dual-Socket (2 CPU vật lý) **Intel Xeon E5-2600 v2 (Ivy Bridge-EP)** (ví dụ: _Xeon E5-2650 v2 / E5-2660 v2_) hoặc **E5-2600 v3 (Haswell-EP)**; **8 đến 10 Cores mỗi socket** $\implies$ **Tổng cộng $16 \text{ – } 20\text{ Cores}$ vật lý (32 – 40 Threads)**, xung nhịp $2.2 \text{ – } 2.6\text{ GHz}$, L3 Cache $20\text{ MB} \text{ – } 25\text{ MB}$.• **RAM:** $64\text{ GB} \text{ – } 128\text{ GB}$ DDR3/DDR4-1600 ECC (16 khe DIMM).• **Card mạng (NIC):** OCP Mezzanine Card v1/v2, Chipset **Intel 82599ES (Niantic)** hoặc **Mellanox ConnectX-3 10GbE SFP+**.• **MTU:** $1500\text{ Bytes}$ chuẩn.• **Lưu trữ:** $1 \times \text{mSATA / 2.5'' SSD}$ boot OS (máy chủ stateless).• **Khung gầm:** OCP Open Rack v1/v2 (khay 2U chứa 3 node server độc lập). | 1. **Bài báo SIGCOMM 2015:** Mục 3.1 (Trang 3-4, vai trò cụm Web server) và Mục 6.1 (Trang 12, MTU 1500 bytes).2. **Tài liệu chuẩn OCP:** _Facebook Server Intel Xeon Motherboard Specification v3.0 (Winterfell)_, Open Compute Project (2013).3. **Facebook Engineering Blog:** _Under the hood: Facebook's Open Rack and Winterfell (2013)_.                                  |
| **Server**                 | **Facebook Winterfell High-Memory / Leopard\***(Cache Follower & Cache Leader)\* | • **Thời gian:** 2013 – 2015 (vận hành Memcached/Mcrouter xuyên suốt quá trình ghi nhận trace).• **Vị trí mạng:** Nằm trong các tủ rack chuyên trách Cache (**Cache Leader Racks** và **Cache Follower Racks**) thuộc **Cache Clusters / Frontend Pods**.• **Trung tâm dữ liệu (DC Sites):** Đặt tại tất cả các DC chính (**Prineville, Forest City, Altoona, Luleå**) để duy trì bộ đệm gần kề tầng Web.                                                          | • **CPU:** Dual-Socket Intel Xeon E5-2600 v2/v3 ($16 \text{ – } 20\text{ Cores}$ vật lý).• **RAM:** Cấu hình bộ nhớ cực lớn: **$128\text{ GB} \text{ – } 256\text{ GB}$ DDR3/DDR4 ECC** (toàn bộ dữ liệu nằm trên RAM).• **Card mạng (NIC):** Mellanox ConnectX-3 10GbE SFP+ Dual-Port hoặc Intel 82599ES 10GbE.• **Đặc trưng tải:** Xử lý hàng trăm nghìn truy vấn gói nhỏ (Key-Value pairs $< 200\text{ bytes}$) mỗi giây.                                                                                                                                                                                                                                                                                                                                                          | 1. **Bài báo SIGCOMM 2015:** Mục 3.1 & 3.2 (Trang 4, Cache Leader / Follower) và Mục 6.1 (Trang 12, Packet size distribution).2. **Tài liệu chuẩn OCP:** _Facebook Server Intel Xeon Motherboard Specification (High Memory configuration)_, Open Compute Project (2013-2014).3. **Hội nghị NSDI 2013:** _R. Nishtala et al., "Scaling Memcache at Facebook", USENIX NSDI 2013_. |
| **Server**                 | **Facebook Open Vault (Knox) + Compute Sled\***(Hadoop / Analytics Node)\*       | • **Thời gian:** 2013 – 2015 (Open Vault công bố năm 2013, vận hành các kho dữ liệu phân tích lớn nhất của Facebook).• **Vị trí mạng:** Nằm trong các tủ rack riêng biệt thuộc **Hadoop / Data Analytics Clusters**.• **Trung tâm dữ liệu (DC Sites):** Cụm Hadoop tập trung quy mô lớn nhất đặt tại **Prineville (Oregon)** và **Forest City (North Carolina)**.                                                                                                  | • **CPU:** Dual-Socket Intel Xeon E5-2600 v2 ($16\text{ Cores}$ vật lý).• **RAM:** $128\text{ GB}$ DDR3-1600 ECC.• **Lưu trữ (Storage):** Khay lưu trữ ngoài **OCP Open Vault (Knox)** gắn kèm qua SAS; chứa **$30$ ổ đĩa cứng $3.5\text{''}$ SAS/SATA HDD** ($3\text{TB} \text{ – } 4\text{TB}$/ổ $\implies$ **$90\text{ TB} \text{ – } 120\text{ TB}$** lưu trữ HDFS raw trên mỗi khay).• **Card mạng (NIC):** $10\text{ GbE}$ SFP+ (Intel 82599ES / Mellanox ConnectX-3).• **Đặc trưng mạng:** Lưu lượng lưỡng cực (Bimodal: Gói MTU $1500\text{ bytes}$ xen lẫn gói TCP ACK).                                                                                                                                                                                                     | 1. **Bài báo SIGCOMM 2015:** Mục 3.1 (Trang 3-4, Hadoop cluster) và Mục 6.1 (Trang 12, Figure 12 & 13 về tính lưỡng cực của Hadoop).2. **Tài liệu chuẩn OCP:** _Open Vault Storage Specification v1.0 (Knox)_, Open Compute Project (2013).                                                                                                                                      |

---

## III. HỆ THỐNG TIÊU CHÍ ĐÁNH GIÁ CHI TIẾT (EVALUATION METRICS & KPIS)

---

### 1. Độ Chính Xác của Các Mô Hình Trí Tuệ Nhân Tạo (AI Performance)

#### 1.1. Khả năng phân loại luồng Voi/Chuột (XGBoost / LightGBM)

- **Mô tả:** Đánh giá độ chuẩn xác của mô hình học máy dạng cây trong việc phân tích Bộ 10 Features (`dur`, `sbytes`, `dbytes`, `Spkts`, `Dpkts`, `Sload`, `Dload`, `smeansz`, `dmeansz`, `Ratio`) để gán nhãn luồng dữ liệu là Elephant (Voi) hay Mice (Chuột).
- **Ý nghĩa:** Phân loại đúng là tiền đề cốt lõi. Bỏ sót luồng Voi sẽ làm nghẽn mạng do tiếp tục đi vào đường ECMP mặc định; gán nhầm luồng Chuột thành Voi sẽ gây lãng phí tài nguyên cắt/ghép gói của NFV Proxy.
- **Phương pháp đánh giá:** Phân tích ma trận nhầm lẫn (Confusion Matrix) trên tập dữ liệu kiểm thử (Test set) đã được gán nhãn chuẩn (Ground Truth).
- **Kịch bản đánh giá:** Trích xuất tập dữ liệu từ file `results/traffic_flow_dataset_with_paths.csv` sinh bởi `traffic_generator.py` với phân bổ tỷ lệ 20% luồng Voi và 80% luồng Chuột. Đưa qua mô hình dự đoán và đối chiếu với nhãn thực tế.
- **Bộ thông số đánh giá:**
  - **Recall (Độ phủ):** Đạt ngưỡng **$> 95\%$** (khẳng định mô hình hầu như không bỏ sót luồng Voi).
  - **Precision (Độ chuẩn xác):** Đạt ngưỡng **$> 90\%$** (đảm bảo luồng chuyển hướng qua Proxy thực sự là luồng Voi).
  - **F1-Score:** Đạt ngưỡng **$> 92\%$** (chứng minh tính cân bằng giữa Precision và Recall trên tập dữ liệu mất cân bằng).

#### 1.2. Chất lượng học biểu diễn Topology (GAT - Graph Attention Network)

- **Mô tả:** Khả năng của Graph Attention Network trong việc nén trạng thái topo mạng (Switch, Link, băng thông khả dụng, độ trễ, số lượng drop) thành các vector đặc trưng (Node Embeddings) mà không làm thất thoát thông tin không gian.
- **Ý nghĩa:** Cung cấp cho tác tử PPO phía sau "bức tranh" mạng lưới chuẩn xác nhất để đưa ra quyết định định tuyến tối ưu.
- **Phương pháp đánh giá:** Đo lường hàm mất mát (Loss function) trong chu trình huấn luyện tự giám sát (Self-supervised learning).
- **Kịch bản đánh giá:** Thay đổi liên tục topo mạng trong Containernet (đánh sập link, bổ sung switch) và theo dõi biến thiên của các vector nhúng đầu ra.
- **Bộ thông số đánh giá:**
  - **Reconstruction Loss:** Đường cong Loss hội tụ tiệm cận về 0 và duy trì ổn định.
  - **Inference Time:** Đạt **$< 2\text{ ms}$** cho mỗi lần trích xuất đồ thị, đảm bảo tính thời gian thực.

#### 1.3. Hiệu quả hội tụ của tác tử học tăng cường (PPO - Proximal Policy Optimization)

- **Mô tả:** Đánh giá quá trình học của thuật toán PPO trong việc xác định ma trận tỷ lệ định tuyến đa đường (Traffic Matrix) để phân bổ các gói tin cắt nhỏ 64KB từ luồng Voi.
- **Ý nghĩa:** Chứng minh hệ thống AI thực sự học được chính sách tối ưu tài nguyên mạng qua cơ chế thử - sai thay vì lựa chọn ngẫu nhiên hay chia đều tải.
- **Phương pháp đánh giá:** Phân tích log huấn luyện thông qua công cụ trực quan hóa (TensorBoard).
- **Kịch bản đánh giá:** Khởi chạy PPO qua hàng ngàn episodes trong môi trường mô phỏng Gymnasium DCN. Bơm các ma trận lưu lượng ngẫu nhiên và quan sát hành vi chia tải của Agent.
- **Bộ thông số đánh giá:**
  - **Cumulative Reward:** Đồ thị tăng trưởng rõ rệt ở các episode đầu và dao động biên độ nhỏ quanh ngưỡng hội tụ cao nhất ở các episode cuối.
  - **Policy Entropy:** Giảm dần đều và duy trì ở một ngưỡng nhỏ lớn hơn 0 (khẳng định mô hình tự tin với quyết định định tuyến nhưng vẫn duy trì khả năng thăm dò, tránh Overfitting).

---

### 2. Tốc Độ Phản Ứng Toàn Trình (Responsiveness & Latency)

#### 2.1. Độ trễ suy luận AI thuần túy (Inference Latency)

- **Mô tả:** Tổng thời gian phần cứng (CPU/GPU) tiêu tốn để tính toán đầu ra cho từng mô hình AI độc lập.
- **Ý nghĩa:** Suy luận chậm sẽ tạo nút thắt cổ chai, khiến quyết định can thiệp bị trễ khi trạng thái luồng mạng đã thay đổi.
- **Phương pháp đánh giá:** Đo thời gian thực thi mã nguồn Python (sử dụng thư viện `time` hoặc `timeit`) khi nạp dữ liệu qua mô hình.
- **Kịch bản đánh giá:** Thực thi vòng lặp 1.000 lần suy luận liên tục với `batch_size = 1` và `batch_size = 32` để lấy giá trị trung bình.
- **Bộ thông số đánh giá:**
  - **Classification Time (LightGBM/XGBoost):** Đạt **$< 1\text{ ms / luồng}$**.
  - **Routing Decision Time (GAT + PPO):** Đạt **$< 10\text{ ms / bản đồ mạng}$**.

#### 2.2. Thời gian phản ứng toàn trình (End-to-End Control Loop / Time-to-Steer)

- **Mô tả:** Thời gian thực tế tính từ lúc gói tin đầu tiên của luồng Voi chạm vào Ingress Switch đến khi luật OpenFlow Priority 1000 ép luồng vào `proxy-int` được cài đặt thành công.
- **Ý nghĩa:** Quyết định việc chặn bắt luồng Voi có kịp thời hay không; phản ứng chậm sẽ khiến lưu lượng lớn của luồng Voi tràn vào nhóm ECMP chung gây nghẽn hàng đợi.
- **Phương pháp đánh giá:** Đồng bộ đồng hồ hệ thống (NTP), bắt gói tin bằng Wireshark/tcpdump tại Controller và Switch để đo chênh lệch timestamp.
- **Kịch bản đánh giá:** Phát luồng TCP đột ngột bằng `iperf3`. Đo khoảng thời gian từ bản tin `Packet-In` đầu tiên đến bản tin `FlowMod (Priority 1000)` phản hồi từ Ryu.
- **Bộ thông số đánh giá:**
  - **Time-to-Steer:** Đạt **$< 50\text{ ms}$** (đủ ngắn để cửa sổ nghẽn `cwnd` của TCP kịp phản ứng trước khi gây tràn bộ đệm tại switch).

---

### 3. Sức Khỏe Hệ Thống Mạng & Hiệu Năng Truyền Tải (Network Health & Throughput)

#### 3.1. Thông lượng và Hiệu năng truyền tải (Throughput & Goodput)

- **Mô tả:** Năng lực vận chuyển dữ liệu tối đa của mạng mà không phát sinh nghẽn, đã tính đến chi phí tiêu đề (overhead) của Proxy.
- **Ý nghĩa:** Khẳng định thuật toán định tuyến đa đường PPO vượt trội hơn các giải pháp tĩnh (Dijkstra, ECMP).
- **Phương pháp đánh giá:** Đo tốc độ truyền thực tế ở tầng ứng dụng bằng `iperf3` và giám sát bằng `bmon`/`vnStat`.
- **Kịch bản đánh giá:** Thiết lập kịch bản All-to-All (các cặp host truyền tải chéo đồng thời) nhằm ép toàn bộ lưu lượng qua các liên kết lõi (Spine-Leaf bottleneck).
- **Bộ thông số đánh giá:**
  - **Achieved Bisection Bandwidth:** Đạt ngưỡng **$> 85\% - 90\%$** tổng băng thông vật lý lý thuyết của các liên kết thắt cổ chai cộng lại.
  - **Elephant Flow Goodput:** Đạt **$> 80\%$** băng thông cấp phát (chênh lệch ~20% phản ánh chi phí gắn header phân mảnh tại Ingress Proxy).

#### 3.2. Thời gian đáp ứng luồng Chuột (Mice Flow FCT)

- **Mô tả:** Thời gian hoàn thành truyền tải của từng luồng độc lập, đặc biệt tập trung vào nhóm luồng Chuột (Mice Flows).
- **Ý nghĩa:** Chứng minh mục tiêu cốt lõi: tách luồng Voi sang Proxy để giải phóng hàng đợi OVS, nhường đường cho luồng Chuột di chuyển nhanh.
- **Phương pháp đánh giá:** Ghi nhận thời gian từ bước bắt tay 3 bước (SYN) đến khi đóng kết nối (FIN) thông qua `tcpdump`.
- **Kịch bản đánh giá:** Truyền liên tục các tệp tin nhỏ (10 KB - 50 KB) đan xen với các luồng Voi dung lượng lớn (1 GB+), sau đó đo FCT của các tệp tin nhỏ.
- **Bộ thông số đánh giá:**
  - **Mice Flow FCT:** Giảm tối thiểu **$30\% - 50\%$** so với kịch bản chạy ECMP truyền thống không có AI can thiệp.
  - **Tail Latency (p99):** Độ trễ của 1% gói tin chậm nhất không vượt quá **$3 - 4\text{ lần}$** độ trễ trung bình.

#### 3.3. Độ ổn định truyền dẫn & Tỷ lệ rớt gói (Packet Loss Rate)

- **Mô tả:** Hiện tượng suy hao gói tin phát sinh từ tình trạng tràn hàng đợi vật lý tại các cổng chuyển mạch.
- **Ý nghĩa:** Kiểm tra xem thuật toán PPO có vô tình điều hướng quá tải dồn vào một liên kết cục bộ hay không.
- **Phương pháp đánh giá:** Trích xuất bộ đếm rớt gói (`rx_dropped`, `tx_dropped`) từ API `/stats/port/<dpid>` của Ryu.
- **Kịch bản đánh giá:** Thực hiện bài đo áp lực (Stress Test) ở mức 100% công suất mạng trong 10 phút liên tục.
- **Bộ thông số đánh giá:**
  - **Packet Loss Rate:** Đạt ngưỡng **$< 0.1\%$** trong môi trường trung tâm dữ liệu (lý tưởng đạt 0%).

---

### 4. Tính Toàn Vẹn Thông Tin & Giao Thức (Data Integrity & Transport Order)

#### 4.1. Bảo toàn thứ tự gói tin mức TCP (TCP Sequence Preservation)

- **Mô tả:** Đánh giá mức độ xáo trộn trình tự gói tin 64 KB khi tới Egress Proxy do di chuyển qua các lộ trình mạng có độ trễ không đồng đều.
- **Ý nghĩa:** Giao thức TCP rất nhạy cảm với gói tin sai thứ tự; nếu không tái sắp xếp triệt để tại Egress Proxy, Host đích sẽ kích hoạt cơ chế giảm cửa sổ truyền vì hiểu nhầm mạng bị nghẽn.
- **Phương pháp đánh giá:** Phân tích luồng TCP tại Host đích bằng Wireshark với bộ lọc `tcp.analysis.out_of_order`.
- **Kịch bản đánh giá:** Bơm luồng Voi phân tán đa đường; sử dụng công cụ `tc` (Traffic Control) tạo độ trễ lệch pha có chủ đích giữa các nhánh (ví dụ: Path 1 trễ 1 ms, Path 2 trễ 10 ms).
- **Bộ thông số đánh giá:**
  - **Out-of-Order Packet Ratio tại đích:** Đạt mức **$0\%$** (chứng minh Egress Proxy hoàn thành trọn vẹn việc đệm và tái hợp thứ tự).
  - **TCP Dup-ACKs / Fast Retransmit Count:** Bằng 0 hoặc ở mức không đáng kể (**$< 0.01\%$** tổng số gói).

#### 4.2. Tính toàn vẹn của Dữ liệu (Data Integrity)

- **Mô tả:** Xác minh tệp tin sau truyền dẫn không bị sai lệch hoặc rác payload do lỗi logic trong module cắt/ghép của Proxy Container.
- **Ý nghĩa:** Tốc độ truyền tải chỉ có ý nghĩa khi tính toàn vẹn của dữ liệu được đảm bảo tuyệt đối.
- **Phương pháp đánh giá:** Đối chiếu mã băm MD5 hoặc SHA-256 giữa tệp nguồn và tệp đích.
- **Kịch bản đánh giá:** Truyền tải một tệp nhị phân kích thước lớn (ví dụ: file 1 GB) từ Host nguồn sang Host đích xuyên qua cụm Proxy nhúng.
- **Bộ thông số đánh giá:**
  - **File Hash Match:** Trùng khớp **$100\%$** (tiêu chí bắt buộc, không có dung sai).

---

### 5. Mức Độ Thích Ứng Trong Kịch Bản Khắc Nghiệt (Resilience & Adaptability)

#### 5.1. Phản ứng với Link/Switch Failure (Self-Healing)

- **Mô tả:** Khả năng tự phục hồi của hệ thống khi cấu trúc liên kết vật lý bị đứt gãy đột ngột.
- **Ý nghĩa:** Đánh giá tính sẵn sàng và khả năng ứng dụng thực tế trong trung tâm dữ liệu khi đối mặt sự cố phần cứng.
- **Phương pháp đánh giá:** Đo thời gian hệ thống khôi phục lại mức thông lượng bình thường sau sự cố.
- **Kịch bản đánh giá:** Khi đang truyền luồng Voi ở tải tối đa, thực thi lệnh `link a1 ag1 down` để ngắt đột ngột một nhánh đường đang được PPO phân bổ lưu lượng.
- **Bộ thông số đánh giá:**
  - **Route Convergence Time:** Đạt **$< 1 - 2\text{ giây}$** (PPO nhận diện thay đổi topo qua GAT và cập nhật ma trận điều hướng mới).
  - **Data Loss during Failure:** Chỉ rớt các gói tin đang trên đường truyền (_in-flight_) tại thời điểm đứt; kết nối TCP tái lập tức thì và không bị ngắt quãng.

#### 5.2. Khả năng chịu tải đột biến (Traffic Burst / Stress Test)

- **Mô tả:** Đánh giá phản ứng của hạ tầng khi xuất hiện các xung lưu lượng tăng vọt trong khoảng thời gian rất ngắn.
- **Ý nghĩa:** Kiểm tra nguy cơ sập mặt phẳng điều khiển (Control Plane) do bùng nổ bản tin `Packet-In`.
- **Phương pháp đánh giá:** Tạo đột biến lưu lượng cường độ cao, theo dõi độ biến thiên trễ (Jitter) và tải CPU của Controller.
- **Kịch bản đánh giá:** Sử dụng script kích hoạt đồng loạt hàng chục kết nối TCP ngắn đồng thời.
- **Bộ thông số đánh giá:**
  - **Jitter luồng Chuột:** Biến thiên không vượt quá **$5\text{ ms}$** so với điều kiện tải thông thường.
  - **Controller CPU Load:** Không xảy ra hiện tượng treo; luồng Chuột duy trì di chuyển qua ECMP bình thường mà không cần sự can thiệp thủ công từ Ryu.

#### 5.3. Độ ổn định của chính sách (Policy Stability & Anti-Flapping)

- **Mô tả:** Đo tần suất thuật toán thay đổi lộ trình liên tục (Route Flapping) cho cùng một luồng dữ liệu do metric đo kiểm mạng biến động nhỏ.
- **Ý nghĩa:** Đổi đường quá thường xuyên gây trễ sắp xếp gói, lãng phí tài nguyên CPU của switch và tăng nguy cơ nghẽn cục bộ.
- **Phương pháp đánh giá:** Ghi nhận số lượng bản tin `OFPFlowMod` được đẩy xuống switch cho cùng một định danh luồng Voi trong 1 phút.
- **Kịch bản đánh giá:** Duy trì 1 luồng Voi trong 5 phút dưới điều kiện lưu lượng nền (_background traffic_) dao động liên tục.
- **Bộ thông số đánh giá:**
  - **Route Flapping Frequency:** Đạt mức **$< 2 - 3\text{ lần / phút}$** (khẳng định chính sách PPO có tính lọc nhiễu tốt trước các dao động vi mô).

---

### 6. Tài Nguyên & Chi Phí Vận Hành (Overhead & Resource Footprint)

#### 6.1. Tài nguyên của Embedded NFV Proxy

- **Mô tả:** Tải tính toán (CPU) và dung lượng bộ nhớ cấp phát cho tiến trình proxy thực hiện cắt và ghép gói.
- **Ý nghĩa:** Đảm bảo giải pháp Proxy không biến thành điểm thắt cổ chai mới thay thế cho hạ tầng chuyển mạch.
- **Phương pháp đánh giá:** Giám sát liên tục qua `docker stats` và file `system_and_network_health.csv`.
- **Bộ thông số đánh giá:**
  - **CPU Usage:** Tăng tuyến tính theo lưu lượng và không chạm ngưỡng bão hòa 100% core.
  - **RAM / Reassembly Buffer:** Duy trì ổn định dưới **$100\text{ MB} - 200\text{ MB}$** (bộ đệm tái hợp được giải phóng tuần tự, không bị rò rỉ bộ nhớ).
  - **Proxy Processing Latency:** Đạt **$< 500\ \mu\text{s}$** cho mỗi tác vụ băm/cắt gói.

#### 6.2. Tài nguyên của Switch (TCAM / Flow Table Occupancy)

- **Mô tả:** Số lượng mục luật (Flow Entries) được cài đặt vào bộ nhớ phần cứng của Open vSwitch.
- **Ý nghĩa:** Đánh giá khả năng mở rộng (Scalability), do dung lượng bộ nhớ TCAM trên switch vật lý luôn bị giới hạn nghiêm ngặt.
- **Phương pháp đánh giá:** Trích xuất qua endpoint `/stats/table/<dpid>` của Ryu.
- **Bộ thông số đánh giá:**
  - **Flow Table Occupancy:** Duy trì **$< 500\text{ entries}$** (hàng nghìn luồng Chuột được gom vào luật ECMP chung; luồng Voi tiêu tốn luật 5-tuple cụ thể nhưng có `idle_timeout = 30s-60s` tự thu hồi).

#### 6.3. Tải của Kênh Điều Khiển và Máy Chủ AI (Control & AI Plane Overhead)

- **Mô tả:** Băng thông tiêu hao trên kênh điều khiển Southbound (OpenFlow) và tải xử lý của Ryu Controller kèm máy chủ AI.
- **Ý nghĩa:** Bảo đảm kiến trúc tách rời Controller/AI không gây nghẽn đường truyền quản lý nội bộ.
- **Phương pháp đánh giá:** Đo băng thông giao diện loopback/veth nối Controller với OVS; theo dõi tải GPU/CPU của AI Server.
- **Bộ thông số đánh giá:**
  - **Southbound Traffic Bandwidth:** Đạt **$< 10 - 20\text{ Mbps}$** (nhờ có Debounce Timer và gom Bi-Flow, không flood rule).
  - **AI Server GPU Utilization:** Giữ dưới mức **$60\% - 70\%$** ở điều kiện mạng bận nhất (đảm bảo biên dự phòng tài nguyên).

#### 6.4. Tỉ lệ liên kết được sử dụng (Link Utilization Balance)

- **Mô tả:** Tỷ lệ phần trăm băng thông thực tế truyền qua từng liên kết so với băng thông vật lý tối đa của liên kết đó.
- **Ý nghĩa:** Đánh giá khả năng rải đều tải trọng trên toàn bộ topo, tránh hiện tượng lệch tải giữa các tuyến truyền dẫn song song.
- **Phương pháp đánh giá:** Thu thập và phân tích dữ liệu băng thông thời gian thực tại toàn bộ các cổng chuyển mạch từ `results/system_and_network_health.csv`.
- **Bộ thông số đánh giá:**
  - **Link Utilization Balance:** Toàn bộ các liên kết lõi đạt **$> 85\% - 90\%$** dung lượng khả dụng với độ lệch chuẩn giữa các liên kết ở mức rất thấp.

---

### 7. Tính Công Bằng & Khả Năng Hạ Cấp Mềm (Fairness & Graceful Degradation)

#### 7.1. Mức độ công bằng (Jain's Fairness Index)

- **Mô tả:** Khả năng chia sẻ tài nguyên băng thông bình đẳng giữa các luồng Voi chạy song song khi cùng cạnh tranh hạ tầng.
- **Ý nghĩa:** Ngăn chặn việc mô hình AI tối ưu tổng thông lượng bằng cách hy sinh hoặc bỏ đói (_starvation_) một số luồng cụ thể để ưu tiên cho luồng khác.
- **Phương pháp đánh giá:** Tính toán chỉ số công bằng Jain's Fairness Index dựa trên thông lượng thực tế thu được của từng luồng:
  $$
  \mathcal{J}(x_1, x_2, \dots, x_n) = \frac{\left( \sum_{i=1}^{n} x_i \right)^2}{n \cdot \sum_{i=1}^{n} x_i^2}
  $$
- **Kịch bản đánh giá:** Khởi chạy đồng thời 5 luồng Voi đi qua vùng mạng có tổng băng thông nhỏ hơn nhu cầu cực đại của cả 5 luồng, sau đó đo Throughput riêng biệt của từng luồng.
- **Bộ thông số đánh giá:**
  - **Jain's Fairness Index:** Đạt **$\mathcal{J} > 0.9$** (trên thang đo từ 0 đến 1, chứng tỏ các luồng Voi đều được phân chia tài nguyên tương xứng).

#### 7.2. Khả năng hạ cấp mềm (Graceful Degradation / Fail-Open)

- **Mô tả:** Cơ chế đảm bảo mạng lưới duy trì vận hành ổn định khi cụm AI hoặc tiến trình Proxy gặp sự cố gián đoạn (Fail-safe mechanism).
- **Ý nghĩa:** Tiêu chuẩn bắt buộc cho môi trường viễn thông và trung tâm dữ liệu doanh nghiệp; sự cố ở hệ thống tối ưu không được phép gây tê liệt toàn bộ hạ tầng mạng.
- **Phương pháp đánh giá:** Kiểm tra sự kích hoạt của các luật dự phòng (Fallback Rules) và lưu lượng thực tế khi ngắt kết nối điều khiển.
- **Kịch bản đánh giá:** Trong lúc lưu lượng đang truyền tải cao, chủ động ngắt tiến trình AI Server hoặc tắt cổng Proxy.
- **Bộ thông số đánh giá:**
  - **Fallback Throughput:** Lưu lượng tự động chuyển về xử lý theo luật Priority 100 (Group Table ECMP). Băng thông luồng Voi có thể suy giảm do chia sẻ đường chung với luồng Chuột, nhưng kết nối mạng được duy trì liên tục và tỷ lệ thời gian chết bằng 0 (**Downtime = 0**).

---

## IV. CÁC KỊCH BẢN KIỂM CHỨNG TRẠNG THÁI MẠNG CHI TIẾT (TEST SCENARIOS)

### Bảng Tổng Hợp 5 Kịch Bản Kiểm Thử

| Kịch bản                     |    Mức độ ưu tiên    | Trọng tâm kiểm thử                           |     Tải mạng     | Tiêu chí cốt lõi (KPIs)                                   |
| :--------------------------- | :------------------: | :------------------------------------------- | :--------------: | :-------------------------------------------------------- |
| **1. Saturation & Noise**    | Ưu tiên 1 (Cốt lõi)  | Chia tải đa đường & Lọc nhiễu vi mô          |    80% – 100%    | Bisection BW$> 85-90\%$, Route Flapping $< 3$ lần/phút    |
| **2. Baseline & Data Shift** | Ưu tiên 2 (Nền tảng) | Độ bền phân loại ML & FCT luồng Chuột        |    30% – 50%     | F1-Score$> 92\%$, Inference Latency $< 1\text{ms}$        |
| **3. Link/Node Failures**    | Ưu tiên 3 (Sẵn sàng) | Tự hội tụ topo & Graceful Fallback           |  100% đơn luồng  | Convergence$< 2\text{s}$, Downtime $= 0$                  |
| **4. TCP Incast**            | Ưu tiên 4 (Vòng lặp) | Trễ phản hồi điều khiển (Time-to-Steer)      | Đột biến cực hạn | Time-to-Steer$< 50\text{ms}$, Packet Loss $< 0.1\%$       |
| **5. Scalability Test**      | Ưu tiên 5 (Mở rộng)  | Khả năng mở rộng topo Fat-Tree ($k=4 \to 8$) |     Nền nhẹ      | Southbound$< 20\text{ Mbps}$, GAT Latency $< 10\text{ms}$ |

---

### Kịch Bản 1: Stress Mạng Toàn Cục Kết Hợp Nhiễu Loạn Vi Mô (Saturation & Noise)

> **Mục tiêu:** Ép tải toàn hệ thống đến giới hạn bão hòa, chứng minh thuật toán Traffic Engineering (PPO + GAT) vượt trội hơn ECMP tĩnh và không bị đánh lừa bởi nhiễu tức thời.

1. **Mô tả kịch bản:**
   - Toàn bộ Host trong Containernet truyền tải chéo lẫn nhau (All-to-All), chiếm dụng từ 80% đến 100% tổng băng thông Bisection.
   - Bơm đồng thời các luồng gói tin rác (UDP/ICMP background noise) với cường độ biến thiên hình sin vào các liên kết ngẫu nhiên để mô phỏng tình trạng dung lượng khả dụng liên tục biến động.
2. **Ý nghĩa thực nghiệm:**
   - Chứng minh khả năng chia tải đa đường tối ưu dung lượng toàn mạng.
   - Kiểm chứng tính ổn định của chính sách PPO: không sinh hiện tượng đảo đường liên tục (Route Flapping) làm xáo trộn thứ tự gói tin TCP khi gặp biến động vi mô.
3. **Quy trình thực hiện:**
   - Bước 1: Kích hoạt script đa luồng điều khiển toàn bộ Host gửi dữ liệu dung lượng lớn qua lại (All-to-All).
   - Bước 2: Chạy tiến trình nền phát sinh tải UDP ngẫu nhiên với biên độ hình sin trực tiếp vào các Switch lõi (Core Switches).
   - Bước 3: Theo dõi tài nguyên hệ thống tại cổng `proxy-int` của Switch Access.
   - Bước 4: Đếm tần suất bản tin `OFPFlowMod` từ Ryu gửi xuống OpenFlow Switches.
4. **Công cụ sử dụng:**
   - Sinh tải Elephant: `iperf3` (Đa cổng 5201–5204).
   - Sinh nhiễu (Noise): `tcpreplay`, `hping3`.
   - Giám sát băng thông Switch: `bmon`, `results/system_and_network_health.csv`.
5. **Tiêu chuẩn đánh giá (KPIs):**
   - Achieved Bisection Bandwidth: $> 85\% - 90\%$ dung lượng lý thuyết.
   - Jain's Fairness Index: $> 0.9$ giữa các luồng Elephant.
   - Route Flapping Frequency: $< 2 - 3\text{ lần / phút}$.

---

### Kịch Bản 2: Vận Hành Tiêu Chuẩn và Biến Thiên Đặc Tính Tải (Baseline & Data Shift)

> **Mục tiêu:** Thiết lập mốc đối chuẩn (Benchmarking), đánh giá độ bền vững của mô hình phân loại luồng ML và đảm bảo Control Plane không gây overhead quá mức.

1. **Mô tả kịch bản:**
   - Mạng vận hành ở mức tải an toàn (30% – 50%).
   - Đưa vào kiểm thử 3 kịch bản lưu lượng (Traffic Profiles) với biến thiên tỷ lệ luồng:
     - **Profile A:** 10% Elephant / 90% Mice.
     - **Profile B:** 20% Elephant / 80% Mice (Tiêu chuẩn cân bằng mặc định).
     - **Profile C:** 60% Elephant / 40% Mice (Đột biến luồng lớn).
2. **Ý nghĩa thực nghiệm:**
   - Đo lường độ trễ suy luận (Inference Latency) của bộ phân loại XGBoost/LightGBM.
   - Đánh giá tính khái quát hóa của mô hình: đảm bảo mô hình không học vẹt phân phối tĩnh và duy trì độ chính xác cao khi tỷ lệ luồng thay đổi đột ngột.
3. **Quy trình thực hiện:**
   - Bước 1: Chạy lần lượt từng Profile lưu lượng trong thời gian tối thiểu 10 phút bằng `traffic_generator.py`.
   - Bước 2: Ghi log nhãn dự đoán của mô hình ML và đối chiếu với nhãn Ground Truth trong file CSV.
   - Bước 3: Bắt gói tin, bóc tách mốc thời gian bắt tay (`SYN`) và kết thúc (`FIN`) để tính thời gian hoàn thành (FCT) của các luồng Web/HTTP nhỏ.
4. **Công cụ sử dụng:**
   - Sinh luồng Mice: `iperf3 -n 20K-50K`, `curl`, `ping`.
   - Sinh luồng Elephant: `iperf3 -t 10 -b 50M`.
   - Đánh giá ML: `scikit-learn metrics` (Confusion Matrix, Classification Report), `analyze_csv_result.py`.
5. **Tiêu chuẩn đánh giá (KPIs):**
   - F1-Score: $> 92\%$ đồng đều trên cả 3 Profile.
   - Inference Latency: $< 1\text{ ms / luồng}$.
   - Mice Flow FCT: Giảm $30\% - 50\%$ so với chạy ECMP truyền thống.

---

### Kịch Bản 3: Phản Ứng Với Sự Cố Mạng Cục Bộ (Link/Node Failures)

> **Mục tiêu:** Xác thực độ sẵn sàng trong môi trường trung tâm dữ liệu thực tế: kiểm tra năng lực tái hội tụ của GAT và tính năng tự động dự phòng (Graceful Degradation).

1. **Mô tả kịch bản:**
   - Ngắt đột ngột liên kết vật lý/logic (Link Down) ngay trên đường truyền chính của luồng Elephant.
   - Tắt đột ngột tiến trình AI Server khi hệ thống đang vận hành bình thường.
2. **Ý nghĩa thực nghiệm:**
   - Kiểm chứng cơ chế tự nhận biết biến động topo qua biểu diễn đồ thị GAT để tái định tuyến.
   - Chứng minh hệ thống không bị gián đoạn toàn diện khi mất tầng AI: lưu lượng tự rơi về quy tắc OpenFlow mặc định (Default Fail-open).
3. **Quy trình thực hiện:**
   - Bước 1: Khởi tạo 01 luồng Elephant bão hòa 100% băng thông của một tuyến đường cố định.
   - Bước 2: Dùng lệnh Mininet CLI can thiệp hạ link: `link a1 ag1 down`.
   - Bước 3: Thử nghiệm phụ: Tắt ngang tiến trình AI Server; theo dõi xem luồng Elephant có tự động rơi xuống bảng luật ECMP mặc định (Priority 100) để truyền như luồng Mice hay không.
4. **Công cụ sử dụng:**
   - Giả lập sự cố: Mininet CLI (`link <sX> <sY> down`).
   - Đo gián đoạn mạng: `ping`, `mtr`, `tcpdump`, Wireshark.
5. **Tiêu chuẩn đánh giá (KPIs):**
   - Route Convergence Time: $< 1 - 2\text{ giây}$ (PPO thiết lập và đẩy đường mới thành công).
   - TCP Out-of-Order / Dup-ACKs: Không tăng đột biến làm reset kết nối TCP.
   - Downtime khi mất tầng AI: Bằng 0 (Mạng duy trì thông suốt, chuyển sang chế độ chuyển tiếp cơ bản).

---

### Kịch Bản 4: Tải Đột Biến Cục Bộ (TCP Incast / Traffic Spikes)

> **Mục tiêu:** Đánh giá tốc độ phản hồi toàn trình (Closed-Loop Control) trước hiện tượng nghẽn cổ chai micro-burst trong thời gian cực ngắn tại một switch đích.

1. **Mô tả kịch bản:**
   - Hàng chục Host nguồn đồng loạt trút lưu lượng Elephant cực lớn về duy nhất 01 Host/Server đích trong thời gian từ 2 đến 3 giây.
   - Mô phỏng mô hình giao tiếp phân tán dạng MapReduce/Hadoop Shuffle phase.
2. **Ý nghĩa thực nghiệm:**
   - Đo đạc thời gian từ lúc gói tin đầu tiên phát sinh (`Packet-In`) cho đến khi Controller và AI tính toán xong để đẩy rule Priority 1000 chuyển hướng luồng vào Proxy.
   - Đảm bảo hàng đợi Switch không bị tràn làm drop hàng loạt gói tin của luồng Mice chạy song song.
3. **Quy trình thực hiện:**
   - Bước 1: Thiết lập kịch bản shell điều khiển nhiều client gọi `iperf3` đổ dồn tải về 1 IP đích duy nhất (`10.0.0.8`).
   - Bước 2: Cho các luồng Mice liên tục đi xuyên qua Switch lõi chịu tải Incast để ghi nhận biến động Jitter.
   - Bước 3: Đọc số liệu bộ đệm cổng Switch trước và sau đợt Incast qua REST API.
4. **Công cụ sử dụng:**
   - Phát sinh Incast: Script đa luồng `iperf3`.
   - Giám sát rớt gói tại Switch: `ovs-ofctl dump-ports` (bóc tách trường `rx_dropped`, `tx_dropped`).
   - Tính trễ vòng điều khiển: `tcpdump`, Wireshark (đo độ lệch timestamp giữa `Packet-In` và `FlowMod Priority 1000`).
5. **Tiêu chuẩn đánh giá (KPIs):**
   - Time-to-Steer (End-to-End Control Loop): $< 50\text{ ms}$ (đủ nhanh trước khi cửa sổ TCP nghẽn).
   - Packet Loss Rate tại Switch: $< 0.1\%$.
   - Tail Latency của luồng Mice (p99 Jitter): Không tăng quá $3 - 4\text{ lần}$ so với mức nền.

---

### Kịch Bản 5: Kiểm Thử Quy Mô Topology (Scalability Test)

> **Mục tiêu:** Chứng minh năng lực tính toán của mạng GAT và sức chịu tải của kênh điều khiển Southbound khi mở rộng quy mô trung tâm dữ liệu.

1. **Mô tả kịch bản:**
   - Mở rộng mạng từ mô hình nhỏ (Spine-Leaf cơ bản) sang topo dạng Fat-Tree tiêu chuẩn:
     - **Cấu hình 1:** Fat-Tree $k=4$ (Quy mô 20 Switch).
     - **Cấu hình 2:** Fat-Tree $k=8$ (Quy mô 80 Switch).
   - Duy trì mức tải nền phân bố đều trên toàn bộ hạ tầng mới.
2. **Ý nghĩa thực nghiệm:**
   - Chứng minh khả năng xử lý biểu diễn không gian của GAT với đồ thị lớn.
   - Xác nhận Controller không bị quá tải CPU/RAM và kênh điều khiển Southbound không bị bão hòa (nhờ cơ chế Debounce Timer 2.0s và Dynamic Host Discovery).
3. **Quy trình thực hiện:**
   - Bước 1: Xây dựng script Python sử dụng Mininet API để tự động khởi tạo cấu trúc topo Fat-Tree $k=8$.
   - Bước 2: Áp dụng lưu lượng nền phân tán nhẹ trên toàn mạng.
   - Bước 3: Giám sát lưu lượng trao đổi trên giao diện mạng ảo kết nối giữa Controller và toàn bộ OVS.
   - Bước 4: Đo lường thời gian trích xuất và tính toán ma trận kề/đặc trưng node của mô hình GAT.
4. **Công cụ sử dụng:**
   - Khởi tạo quy mô mạng: Mininet Topology Engine.
   - Đo băng thông Southbound Interface: `iftop`, `vnStat`.
   - Giám sát tài nguyên: `nvidia-smi` (nếu dùng GPU), `htop`.
5. **Tiêu chuẩn đánh giá (KPIs):**
   - Southbound Traffic Bandwidth: $< 20\text{ Mbps}$ (không gây nghẽn kênh điều khiển).
   - Tài nguyên AI Server: Mức sử dụng duy trì dưới $60\% - 70\%$.
   - GAT Inference Time: Giữ ở mức $< 10\text{ ms}$ ngay cả khi số lượng nút Switch tăng gấp 4 lần.

---

## V. LỘ TRÌNH THỰC HIỆN ĐỀ TÀI (PROJECT PHASES)

- **GIAI ĐOẠN 1: Hạ Tầng Cơ Sở & Thu Thập Dataset (ĐÃ HOÀN THÀNH V2)**
  - [x] Xây dựng Dockerfile OVS nhúng cổng `proxy-int` và script topology Spine-Leaf.
  - [x] Cải tổ `controller.py`: Vá lỗi Group Reconnect, Debounce LLDP 2.0s, Dynamic Host Discovery, Cài luật 5-tuple Bi-flow.
  - [x] Cải tổ `management_plane.py`: Bộ 10 Features chuẩn, dò vết Full Hop-by-Hop Path.
  - [x] Nâng cấp `traffic_generator.py`: Bộ sinh tải thống nhất Facebook DCN (chuẩn hóa `iperf3 -n`, tách biệt microburst socket ECT-0, kiểm định KS-test, tự động hóa 2 file config `topology_config.json` & `traffic_config.json`).
  - [x] Cập nhật công cụ phân tích `analyze_csv_result.py` và tài liệu kiểm thử `TESTING_AND_OVERHAUL_GUIDE.md`.
- **GIAI ĐOẠN 2: Huấn Luyện Mô Hình Học Máy (ML Training)**
  - [ ] Tiền xử lý dữ liệu từ file `results/traffic_flow_dataset_with_paths.csv`.
  - [ ] Huấn luyện và đánh giá bộ phân loại luồng XGBoost / LightGBM từ 10 features.
  - [ ] Xây dựng môi trường Gymnasium DCN, huấn luyện mô hình đồ thị GAT và tác tử PPO.
- **GIAI ĐOẠN 3: Tích Hợp Vòng Lặp Điều Khiển Đóng (Closed-Loop Integration)**
  - [ ] Triển khai module NFV Proxy phân mảnh/gom gói 64KB gắn vào cổng `proxy-int`.
  - [ ] Kết nối API giữa AI Server và Ryu Controller: Kích hoạt luật `Priority = 1000` điều hướng luồng Voi thời gian thực.
- **GIAI ĐOẠN 4: Thực Nghiệm Đo Kiểm Toàn Diện & Đánh Giá Đề Tài**
  - [ ] Chạy đầy đủ 5 kịch bản kiểm thử (Stress, Incast, Failover, Scalability...).
  - [ ] Thu thập số liệu đối sánh giữa: ECMP truyền thống vs. Giải pháp SDN-AI đề xuất.
  - [ ] Xuất báo cáo biểu đồ khoa học và hoàn thiện luận văn tốt nghiệp.
