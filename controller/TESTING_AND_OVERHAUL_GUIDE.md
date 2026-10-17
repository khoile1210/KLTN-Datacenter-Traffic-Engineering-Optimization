# HƯỚNG DẪN KIỂM THỬ VÀ VẬN HÀNH TOÀN DIỆN HỆ THỐNG MẠNG DCN SDN-AI (v3)

> **Đề tài:** Research on Traffic Engineering Optimization in Data Center Networks Based on Software-Defined Network and Artificial Intelligence
> **Phiên bản:** Controller v3 — Kiến trúc Unified Workload Facebook (ACM SIGCOMM 2015) & Mặc định 1 Rack = 4 Hosts
> **Tài liệu tham chiếu:** [`.Project Plans/UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md) | [`.Project Plans/TRAFFIC_SIMULATION_CHECKLIST.md`](file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/TRAFFIC_SIMULATION_CHECKLIST.md)
> **Ngày cập nhật:** 2026-10-16

---

## 1. TỔNG QUAN KIẾN TRÚC & ĐỢT CẢI TỔ HỆ THỐNG TOÀN DIỆN

Hệ thống đã trải qua đợt cải tổ kiến trúc toàn diện và nâng cấp triệt để từ mô hình thử nghiệm ban đầu lên môi trường mô phỏng trung tâm dữ liệu chuẩn học thuật quốc tế:

```
+----------------------------------------------------------------------------------------------------+
|                                    RYU SDN CONTROLLER (OF 1.3)                                     |
|  - LLDP Topology Discovery (Debounce 2.0s)       - Dynamic Host Discovery & Proxy ARP              |
|  - Safe Group Table Synchronization              - Symmetric 5-Tuple Bi-flow Rules (Priority 150)  |
|  - ECMP Load Balancing (Priority 100)            - AI Elephant Flow Steering (Priority 1000)      |
+----------------------------------------------------------------------------------------------------+
                                      │ OpenFlow 1.3 (TCP 6653)
                                      ▼
+----------------------------------------------------------------------------------------------------+
|                       MULTI-TIER SPINE-LEAF DCN (CONTAINERNET & DOCKER OVS)                        |
|                                                                                                    |
|  [Tier 1] Core Spine (2 Switches)       : c1, c2 (Facebook 6-pack FSW, 12MB Buffer)                |
|  [Tier 2] Aggregation (4 Switches)      : ag1 -> ag4 (Facebook 6-pack CSW, 12MB Buffer)            |
|  [Tier 3] Access / ToR (8 Switches)     : a1 -> a8 (Facebook Wedge 40 RSW, 12MB Buffer)            |
|                                           + Embedded NFV Proxy Internal Port (proxy-int)           |
|  [Tier 4] Edge Compute (32+1 Hosts)     : Mặc định 1 Rack = 4 Hosts (h1_1..h8_4) + 1 Node inet     |
+----------------------------------------------------------------------------------------------------+
                                      ▲
                                      │ Traffic Workload & Telemetry
+----------------------------------------------------------------------------------------------------+
|                              DATA & MANAGEMENT PLANE SUBSYSTEMS                                    |
|  - Management Plane (1.0s Polling)      : Thu thập 10 Features & Hop-by-Hop Path Tracing           |
|  - Unified CDF Sampler (SIGCOMM 2015)   : Hòa trộn 3 Workload (Hadoop, Frontend, Cache)            |
|  - Background Traffic Generator         : Đồng nhất iperf3 -n {S_scaled} theo 3 vùng Locality      |
|  - Ephemeral Microburst Generator       : Bơm TCP Socket burst (< 10ms, TOS 0x02 ECT-0)            |
|  - Analytics & KS-Test Validation       : Phân tích Pareto P90 gán nhãn AI & Kiểm định 2 mẫu       |
+----------------------------------------------------------------------------------------------------+
```

### 1.1. Hạ Tầng Mạng Spine-Leaf & Ảo Hóa Phần Cứng (Infrastructure-as-Code)

- **Kiến trúc mặc định 1 Rack = 4 Hosts:**
  - 8 Access Switches (`a1` – `a8`) đóng vai trò là 8 switch đỉnh tủ (**Top-of-Rack - ToR**).
  - Mỗi tủ rack chứa 4 Docker Hosts (`h{rack}_{host}`): từ `h1_1..h1_4` đến `h8_1..h8_4` $\implies$ Tổng cộng **32 Hosts nội bộ** mang dải IP `10.0.0.1/24` đến `10.0.0.32/24`.
  - Node Internet ngoài DCN (`inet` - `10.0.0.100/24`) cắm trực tiếp vào Core Switches.
- **Ma trận phân bổ tài nguyên cgroups cô lập (Hardware Scaling Matrix):**
  - Từng Switch OVS và Docker Host được giới hạn tài nguyên độc lập (`cpus`: $1.0\text{ Core}$, `cpu_quota`: $100\text{k}\mu\text{s}$, `mem_limit`: $1024\text{m}$, `memswap_limit`: $2048\text{m}$).
  - Bảo toàn độ trễ xả đệm vật lý $\tau_{\text{buf}} \approx 9.6 - 10\text{ ms}$ tương đương $12\text{ MB}$ SmartBuffer của dòng chip Broadcom Trident II BCM56850 trên switch Wedge 40 thực tế.
- **Hệ thống 2 tệp cấu hình tham chiếu động chống lệch pha:**
  - [`controller/topology_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/topology_config.json): Quản lý gốc toàn bộ hạ tầng phần cứng, dải IP, switch DPID, băng thông liên kết và tham số container cgroups.
  - [`controller/traffic_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_config.json): Quản lý tham số mô hình phụ tải, tự động kế thừa các thông số dùng chung từ `topology_config.json` qua cú pháp JSON Pointer `ref:topology_config.json#/...`. **Người dùng thay đổi số host/rack hoặc băng thông chỉ cần sửa 1 nơi duy nhất, không cần sửa bất kỳ dòng code Python nào.**

---

### 1.2. Tầng Điều Khiển — [`controller.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/controller.py)

- **Debounce Timer chống bão FlowMod (2.0s):** Sử dụng `ryu.lib.hub.spawn_after(2.0, ...)`. Khi topo khởi động dồn dập hàng chục link LLDP, Controller hoãn tính toán cho đến khi toàn mạng ổn định trong 2 giây rồi mới lập trình ECMP, giảm $> 90\%$ tải kênh Southbound.
- **Đồng bộ Group Table an toàn:** Tự động dọn dẹp trạng thái `installed_groups` theo DPID khi switch kết nối lại, đảm bảo lệnh gửi xuống luôn là `OFPGC_ADD`, loại bỏ triệt để lỗi `OFPGMFC_UNKNOWN_GROUP`.
- **Dynamic Host Discovery & Proxy ARP:** Nhận diện vị trí host động qua bản tin ARP/IP tại cổng Access, tự động phân giải ARP Reply từ Controller, loại bỏ hoàn toàn việc gán bảng tĩnh.
- **Cặp Flow Rule 5-tuple đối xứng (Bi-flow) tại Ingress Switch:**
  - Cài 2 rule có `Priority = 150` và `idle_timeout = 30s` tại Switch Access nguồn.
  - _Forward Rule:_ Khớp $(A \to B) \implies$ OVS đếm riêng `sbytes`, `Spkts`, `dur`.
  - _Backward Rule:_ Khớp $(B \to A) \implies$ OVS đếm riêng `dbytes`, `Dpkts`.
- **Sẵn sàng chuyển hướng luồng Voi (Elephant Steering):** Cung cấp sẵn hàm `steer_elephant_flow()` đẩy luật `Priority = 1000` điều hướng luồng Voi vào cổng nội bộ `proxy-int` khi AI ra quyết định.

---

### 1.3. Tầng Quản Trị & Telemetry Toàn Diện — [`management_plane.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/management_plane.py)

Phục vụ đồng bộ cả 3 mục tiêu cốt lõi của đề tài (Thu thập Data, Giám sát và Đánh giá học thuật):

- **1. Thu Thập Dataset Luồng Cho AI (`results/traffic_flow_dataset_with_paths.csv`):**
  - _Trực tiếp từ OVS counter:_ `dur`, `sbytes`, `dbytes`, `Spkts`, `Dpkts`.
  - _Phái sinh có cơ chế bảo vệ chia cho 0 ($\epsilon = 10^{-6}$):_ $\text{Sload}$ (Bytes/s), $\text{Dload}$ (Bytes/s), $\text{smeansz}$ (Bytes), $\text{dmeansz}$ (Bytes), $\text{Ratio}$ (sbytes / dbytes).
  - _Đặc trưng mở rộng:_ `pkt_rate`, `byte_rate`, phân vùng `locality` (Intra-Rack, Extra-Rack, Extra-DC).
  - _Lần vết ĐƯỜNG ĐI CHI TIẾT TỪNG CHẶNG (Full Hop-by-Hop Path):_ Định dạng `h_src -> a_src[in:X->out:Y] -> ag_src[in:X->out:Y] -> c_core[in:X->out:Y] -> ag_dst[in:X->out:Y] -> a_dst[in:X->out:Y] -> h_dst`, kèm `hop_count`.
  - _Ghép cặp Bi-flow đối xứng:_ Ghép trực tiếp từ OpenFlow Flow Stats, loại bỏ `docker exec ss` nặng nề, hoàn tất chu kỳ Polling $< 1.0\text{s}$.
- **2. Giám Sát Tài Nguyên Thiết Bị & Sức Khỏe Mạng (`results/device_resource_utilization.csv` & `results/system_and_network_health.csv`):**
  - Bóc tách CPU (%), RAM used (MB), RAM limit (MB), RAM (%) của từng Docker Host Container và Switch OVS qua non-blocking `docker stats`.
  - Thống kê Network Rx/Tx bytes, Network I/O throughput (Mbps), drops delta, packet errors và số lượng active flow rules trong TCAM Table 0.
- **3. Giám Sát Liên Kết Mạng Phục Vụ GAT + DRL (`results/link_utilization_telemetry.csv`):**
  - Bóc tách thông lượng tức thời (Throughput Mbps), băng thông thiết kế (Capacity), tỷ lệ tải (Utilization %) và số gói rớt của toàn bộ các liên kết Core-Agg, Agg-Access, Access-Host.
- **4. Đánh Giá Hiệu Năng Học Thuật & Benchmark KPIs (`results/network_evaluation_kpis.csv`):**
  - Tổng thông lượng toàn mạng (Total Throughput Mbps).
  - Tỷ lệ chiếm dụng băng thông đường cắt ngang lõi (Bisection Bandwidth Utilization Core-Agg %).
  - Tỷ lệ rớt gói toàn mạng (Overall Packet Loss Rate %).
  - **Chỉ số công bằng Jain's Fairness Index:** Đo đạc mức độ phân bổ lưu lượng đồng đều trên các đường truyền song song Core-Agg ($J = \frac{(\sum u_i)^2}{m \sum u_i^2}$).
  - **Độ lệch chuẩn tải liên kết lõi ($\sigma_u$):** Thước đo cốt lõi để so sánh khả năng cân bằng tải giữa thuật toán ECMP truyền thống và mô hình AI định tuyến (GAT + PPO).
  - Thời gian hoàn thành trung bình của luồng Chuột (Mice Flow Completion Time).

---

### 1.4. Bộ Sinh Tải Thống Nhất & Heavy Jitter (Facebook SIGCOMM 2015)

- **Bộ lấy mẫu toán học thích ứng [`unified_sampler.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/unified_sampler.py):**
  - Hòa trộn lồi 3 phân phối cụm thực nghiệm Facebook (Hadoop $42.8\%$, Frontend $38.8\%$, Cache $18.4\%$).
  - Co giãn phi tuyến liên tục (Piecewise Continuous Scaling) cho luồng lớn theo $\alpha = C_{\text{host}} / 10\text{Gbps}$ trong khi giữ nguyên gói tin nhỏ $\le S_{\text{threshold}}$.
  - Giãn nhịp phát (Time Dilation $D_{\text{arrival}} = 16.0$) dựa trên tỷ số năng lực CPU máy chủ vật lý so với container.
  - Phân bổ 3 vùng Locality chuẩn Table 3: $7.2\%$ Intra-rack, $85.0\%$ Extra-rack, $7.8\%$ Extra-DC Internet.
- **Đồng nhất công cụ phát nền [`traffic_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_generator.py):**
  - Mọi luồng nền phát bằng lệnh đồng nhất: `iperf3 -c {dst_ip} -p {port} -B {src_ip} -n {S_scaled}` qua đa cổng `5201-5204`. Không dùng `-t`, `-b` áp đặt thời gian cứng, để mạng tự quyết định FCT và thông lượng.
- **Module Heavy Jitter / Microburst độc lập [`microburst_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/microburst_generator.py):**
  - Bơm microburst tức thời ($< 10\text{ ms}$, $20\text{ KB} - 80\text{ KB}$) bằng Python TCP socket trực tiếp với cờ `TCP_NODELAY = 1` và IP TOS `0x02` (ECT-0).
  - Tự ghi nhật ký Ground-Truth phía Client vào `results/microburst_client_ground_truth.csv`, hỗ trợ cả 2 chế độ Random và Incast.

---

### 1.5. Bộ Công Cụ Phân Tích & Kiểm Định Thống Kê Học Thuật

- [`analyze_and_label_dataset.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/analyze_and_label_dataset.py): Phân tích phân vị thực nghiệm ($P80, P90, P95, P99$) của `sbytes` và `Sload`, tự động gợi ý ngưỡng theo nguyên lý Pareto, gán nhãn chuẩn Ground-Truth (`label = 1` cho Elephant, `label = 0` cho Mice) và xuất `results/final_labeled_flow_dataset.csv`.
- [`validate_workload_kstest.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/validate_workload_kstest.py): Kiểm định 2 mẫu Kolmogorov-Smirnov (`scipy.stats.ks_2samp`) đối chiếu dữ liệu đo đạc thực nghiệm Mininet với phân phối gốc Facebook, xuất biểu đồ so sánh chồng hình (Overlay Plot) chất lượng cao phục vụ viết Luận văn.

---

## 2. QUY TRÌNH THỰC THI CHI TIẾT TỪNG BƯỚC (STEP-BY-STEP EXECUTION)

Quy trình chuẩn được vận hành qua **5 đến 6 cửa sổ Terminal độc lập** trên máy chủ hoặc máy ảo Linux (Ubuntu 20.04/22.04 LTS có cài Containernet, OVS và Ryu):

```
+----------------------------------------------------------------------------------------------------+
| BƯỚC 0: Build Docker Images (dcn-host:latest, dcn-ovs:latest trong controller/docker_image/)        |
|         ./controller/docker_image/build_images.sh                                                  |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| BƯỚC 1: Khởi động Ryu SDN Controller (Terminal 1)                                                  |
|         ryu-manager --observe-links controller/controller.py ryu.app.ofctl_rest ...                 |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| BƯỚC 2: Khởi tạo Topology Spine-Leaf 32 Hosts & pingall kích hoạt mạng (Terminal 2)               |
|         sudo python3 controller/spine_leaf_topo.py  ==>  containernet> pingall                     |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| BƯỚC 3: Khởi động Management Plane thu thập Telemetry 10 Features (Terminal 3)                     |
|         python3 controller/management_plane.py                                                     |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| BƯỚC 4: Khởi động Background Traffic Generator phát sinh tải thống nhất (Terminal 4)               |
|         sudo python3 controller/traffic_generator.py                                               |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| BƯỚC 5 (Tùy chọn): Bơm Heavy Jitter / Microburst kiểm thử hàng đợi & ECN (Terminal 5)              |
|         sudo python3 controller/microburst_generator.py --mode random                              |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| BƯỚC 6: Phân tích phân vị P90 & Gán nhãn Dataset cho AI (Terminal 6)                               |
|         python3 controller/analyze_and_label_dataset.py                                            |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
| BƯỚC 7: Kiểm định thống kê học thuật Kolmogorov-Smirnov (KS-Test) & Xuất biểu đồ (Terminal 6)      |
|         python3 controller/validate_workload_kstest.py                                             |
+----------------------------------------------------------------------------------------------------+
```

---

### BƯỚC 0: Chuẩn Bị Môi Trường & Build Docker Images

Mở Terminal, đứng tại thư mục gốc của dự án `~/dcn`:

```bash
cd ~/dcn

# Cách 1: Sử dụng script build tự động
chmod +x controller/docker_image/build_images.sh
./controller/docker_image/build_images.sh

# Cách 2: Build thủ công từng image
docker build -t dcn-host:latest -f controller/docker_image/Dockerfile.host controller/docker_image/
docker build -t dcn-ovs:latest -f controller/docker_image/Dockerfile.ovs controller/docker_image/

# Kiểm tra xác nhận 2 images đã sẵn sàng
docker images | grep -E "dcn-host|dcn-ovs"
```

---

### BƯỚC 1: Khởi Động Ryu SDN Controller (Terminal 1)

Đứng tại thư mục gốc `~/dcn`, khởi chạy Ryu Controller với các ứng dụng OpenFlow 1.3 REST và Topology Discovery:

```bash
cd ~/dcn
ryu-manager --observe-links controller/controller.py ryu.app.ofctl_rest ryu.app.rest_topology --ofp-tcp-listen-port 6653
```

**Dấu hiệu thành công:**

- Màn hình hiển thị: `[+] Multi-Tier Spine-Leaf Controller (Cải tổ v2) đã khởi động thành công.`
- Controller mở cổng lắng nghe `6653` (OpenFlow Southbound) và cổng `8080` (Northbound REST API).

---

### BƯỚC 2: Khởi Động Topology Spine-Leaf 32 Hosts (Terminal 2)

Đứng tại thư mục `~/dcn`, khởi chạy topology mạng Containernet với tài nguyên cô lập:

```bash
cd ~/dcn
sudo python3 controller/spine_leaf_topo.py
```

**Dấu hiệu thành công:**

- In banner thông số mạng chi tiết:

  ```
  [*] KHỞI TẠO TOPOLOGY SPINE-LEAF DOCKER DCN (CONTAINERNET)
      - Controller        : 127.0.0.1:6653 (OpenFlow13)
      - Mô hình Switch    : docker_ovs (Core: 2, Agg: 4, Access: 8)
      - Tài nguyên Switch : CPU Limit=1.0 Core (100000us), RAM Limit=1024m
      - Tài nguyên Host   : CPU Limit=1.0 Core (100000us), RAM Limit=1024m
      - Phân bố Host      : 8 Racks x 4 Hosts = 32 Hosts nội bộ + 1 Inet Node
      - Băng thông phân tầng: Host=20.0M | Agg-Access=50M | Core-Agg=100M | Inet=100M
  ```

- Xuất hiện log cấu hình cổng NFV Proxy trên 8 Access Switches:

  ```
  [*] Bước 5.1: Thiết lập cổng nội bộ NFV Proxy trên Access Leaf Switches...
      - Switch a1: Cổng 'proxy-int' sẵn sàng (IP: 10.255.0.1/24)
      ...
      - Switch a8: Cổng 'proxy-int' sẵn sàng (IP: 10.255.0.8/24)
  ```

- Ở Terminal 1 (Ryu): Sau khoảng 2 giây kể từ liên kết cuối, Debounce Timer kích hoạt:`[*] Topo đã ổn định: 14 Switches, 48 Links LLDP. Bắt đầu nạp luật ECMP...`
- **Kích hoạt học MAC/IP toàn mạng:** Tại dấu nhắc `containernet>`, thực thi lệnh:

  ```
  containernet> pingall
  ```

  _(Kết quả: `0% dropped`, toàn bộ các host ping thông nhau $100\%$, Controller học toàn bộ 33 hosts)._

---

### BƯỚC 3: Khởi Động Tầng Quản Trị & Telemetry Toàn Diện (Terminal 3)

Đứng tại thư mục `~/dcn`, khởi chạy tiến trình Polling thu thập đa luồng metrics (Dataset luồng, Device Telemetry, Link Telemetry, Benchmark KPIs):

```bash
cd ~/dcn

# Khuyến nghị: Chạy với sudo để mở khóa Tier 1 eBPF / XDP Kernel Telemetry (hoặc không cần sudo cho Tier 3 Fallback)
sudo python3 controller/management_plane.py
```

**Dấu hiệu thành công:**

- Terminal hiển thị banner khởi tạo 4 tệp tin CSV chuyên biệt và trạng thái động cơ eBPF:

  ```
  [+] Khởi tạo file Dataset luồng (10 Features): results/traffic_flow_dataset_with_paths.csv
  [+] Khởi tạo file Giám sát tài nguyên thiết bị (CPU/RAM/Net IO): results/device_resource_utilization.csv
  [+] Khởi tạo file Sức khỏe hệ thống và switch OVS: results/system_and_network_health.csv
  [+] Khởi tạo file Giám sát & Đánh giá băng thông liên kết (Link Telemetry): results/link_utilization_telemetry.csv
  [+] Khởi tạo file Chỉ số KPI đánh giá toàn mạng (Benchmark KPIs): results/network_evaluation_kpis.csv

  ================================================================================
  [*] TẦNG QUẢN TRỊ & TELEMETRY TOÀN DIỆN (COMPREHENSIVE MANAGEMENT PLANE - v3)
      - Cổng Ryu REST API : http://127.0.0.1:8080
      - Chu kỳ Polling    : 1.0 giây
      - 1. Dataset AI     : results/traffic_flow_dataset_with_paths.csv (10 Features + Hop-by-Hop + Locality)
      - 2. Giám sát Node  : results/device_resource_utilization.csv (CPU %, RAM MB, Net IO)
      - 3. Giám sát Link  : results/link_utilization_telemetry.csv (Throughput Mbps, Utilization %, Drops)
      - 4. Benchmark KPIs : results/network_evaluation_kpis.csv (Total Throughput, Jain's Fairness, Loss %)
      - 5. eBPF Engine    : Tier 1: Full High-Res eBPF/XDP + Perf Ring Buffer
  ================================================================================
  ```

- Mỗi giây xuất hiện dashboard thời gian thực tổng hợp tình trạng toàn mạng:

  ```
  [16:30:00] [Telemetry Poller] Flows:  24 (Voi:  2, Chuột: 22) | Throughput: 142.50 Mbps | Core-Agg:  45.2% (Jain's: 0.985) | Nodes: 47 | Drops: 0
  ```

---

### BƯỚC 4: Khởi Động Background Traffic Generator (Terminal 4)

Đứng tại thư mục `~/dcn`, khởi chạy engine sinh lưu lượng nền thống nhất Facebook:

```bash
cd ~/dcn

# Chế độ mặc định: Chạy liên tục vô hạn (chỉ dừng khi bấm Ctrl + C)
sudo python3 controller/traffic_generator.py

# Hoặc chế độ hẹn giờ: Chạy đúng 1 giờ rồi tự động dừng (1h = 3600s)
sudo python3 controller/traffic_generator.py --duration 1h
```

**Dấu hiệu thành công:**

- Tự động quét và nhận diện đủ **33 Docker Containers** (`h1_1` đến `h8_4` và `inet`):
  ```
  [+] Nhận diện thành công 33 Docker Hosts trong mạng DCN:
      - Node: h1_1  | Container: mn.h1_1  | IP DCN: 10.0.0.1
      ...
      - Node: inet  | Container: mn.inet  | IP DCN: 10.0.0.254
  ```
- Khởi động server iperf3 đa cổng (`5201, 5202, 5203, 5204`) trên toàn bộ containers:
  ```
  [+] Toàn bộ iperf3 servers đa cổng đã sẵn sàng.
  ```
- Bắt đầu sinh tải liên tục theo đúng phân phối 3 vùng Locality:
  - `[Intra-Rack] h1_1 -> h1_3 | Size: 1,204 B | Sleep: 23.5ms` (gói tin chỉ đi nội bộ qua switch `a1`).
  - `[Extra-Rack] h1_2 -> h5_4 | Size: 48,290 B | Sleep: 125.0ms` (gói tin đi qua tầng Core/Agg).
  - `[Extra-DC  ] h3_1 -> inet | Size: 2,150 B | Sleep: 10.0ms` (gói tin hướng ra ngoài Internet).
  - **Tuyệt đối không xuất hiện lỗi `the server is busy`**.
- **Chủ động ngắt bất kỳ lúc nào:**
  - Chế độ mặc định là **chạy liên tục vô hạn**. Khi muốn dừng sinh tải, bạn chỉ cần bấm **`Ctrl + C`**.
  - Hệ thống sẽ ngắt ngay lập tức (không bị trễ sleep), in bảng tổng kết số luồng đã phát theo 3 vùng, đồng thời kích hoạt lệnh dọn dẹp song song trên toàn bộ 33 container để giải phóng triệt để các tiến trình `iperf3`.

---

### BƯỚC 5 (Tùy Chọn): Bơm Heavy Jitter / Microbursts (Terminal 5)

Để kiểm thử độ bền hàng đợi switch, hiện tượng tràn bộ đệm và khả năng đánh dấu cờ ECN Congestion Experienced (`0x03`), đứng tại thư mục `~/dcn`, mở Terminal 5 để kích hoạt bơm Microburst:

```bash
cd ~/dcn

# Chế độ 1 (Khuyên Dùng): Bắn ngẫu nhiên với chu kỳ ngẫu nhiên Uniform (ví dụ: nghỉ ngẫu nhiên từ 10s đến 30s giữa các đợt, chạy 1 giờ)
sudo python3 controller/microburst_generator.py --mode random --duration 1h --mininterval 10s --maxinterval 30s

# Chế độ 2: Bắn chu kỳ cố định có hẹn giờ (ví dụ: cứ 2.0s bắn 1 đợt, chạy trong 1 giờ)
sudo python3 controller/microburst_generator.py --mode random --duration 1h --interval 2.0

# Chế độ 3: Bắn số lượt cố định với chu kỳ ngẫu nhiên (ví dụ: 30 đợt, nghỉ ngẫu nhiên từ 5s đến 15s)
sudo python3 controller/microburst_generator.py --mode random --count 30 --mininterval 5s --maxinterval 15s

# Chế độ 4: Incast Congestion - Toàn bộ các host đồng loạt bắn dồn về 1 host mục tiêu (h1_1)
sudo python3 controller/microburst_generator.py --mode incast --target h1_1 --duration 1h --mininterval 10s --maxinterval 20s
```

**Dấu hiệu thành công:**

- Dữ liệu microburst được gửi ở line-rate cực cao và hoàn tất trong $2.0 - 6.0\text{ ms}$.
- Nhật ký Ground-Truth client-side được ghi nhận tức thì vào `results/microburst_client_ground_truth.csv`.

---

### BƯỚC 6: Phân Tích Phân Vị & Gán Nhãn Dataset Cho AI (Terminal 6)

Sau khi bộ sinh tải chạy từ **5 đến 10 phút** để tích lũy hàng nghìn mẫu luồng, đứng tại thư mục `~/dcn`:

```bash
cd ~/dcn
python3 controller/analyze_and_label_dataset.py
```

**Các bước tương tác:**

1. Script đọc `results/traffic_flow_dataset_with_paths.csv` và tính toán các mốc phân vị $P50, P80, P90, P95, P99$.
2. Hiển thị bảng khuyến nghị ngưỡng phân tách Elephant Flow dựa trên nguyên lý Pareto 80/20.
3. Vẽ và lưu biểu đồ phân tích 4 ô vào `results/flow_distribution_and_threshold_analysis.png`.
4. Người dùng xác nhận chọn ngưỡng:
   - **Khuyến nghị chuẩn Pareto:** Nhập `90` (hoặc nhấn Enter để lấy mặc định $P90$: `sbytes >= 124,219 B`, `Sload >= 1,062,302 B/s`).
5. Script tự động gán nhãn Ground-Truth (`label = 1` cho Elephant, `label = 0` cho Mice) và xuất file sạch:
   $$
   \text{Tệp đầu ra: } \mathbf{results/final\_labeled\_flow\_dataset.csv}
   $$
6. Tự động đồng bộ ngưỡng `S_threshold_bytes` vào [`controller/traffic_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_config.json).

---

### BƯỚC 7: Kiểm Định Thống Kê Học Thuật (KS-Test & Overlay Plot) (Terminal 6)

Để chứng minh tính khoa học và tính tương đồng phân phối giữa dữ liệu đo đạc thực nghiệm Mininet với dữ liệu bài báo gốc của Facebook (phục vụ viết báo cáo Luận văn Tốt nghiệp), đứng tại thư mục `~/dcn`:

```bash
cd ~/dcn
python3 controller/validate_workload_kstest.py
```

**Kết quả thu được:**

- Thực hiện kiểm định 2 mẫu Kolmogorov-Smirnov (`ks_2samp`):
  - **Flow Size (Kích thước luồng):** Đạt $p\text{-value} > 0.05$ (Khẳng định dữ liệu mô phỏng tuân theo cùng phân phối với Facebook trace).
  - **Flow Duration (Thời lượng luồng):** Đạt $p\text{-value} > 0.05$.

- Xuất biểu đồ so sánh chồng hình (Overlay Plot) chất lượng cao 300 DPI:

  $$
  \text{Tệp đồ thị: } \mathbf{results/chart\_facebook\_workload\_validation.png}
  $$

  _(Gồm 2 đường: Nét đứt là Facebook Ground Truth, Nét liền là Mininet Thực nghiệm)._

---

## 3. BẢNG TIÊU CHÍ NGHIỆM THU HỆ THỐNG (VERIFICATION CRITERIA)

| Hạng Mục Kiểm Tra                     | Kết Quả Đạt Chuẩn (Expected Behavior)                                                               | Cách Xác Minh                                           |
| :------------------------------------ | :-------------------------------------------------------------------------------------------------- | :------------------------------------------------------ |
| **Không bão FlowMod lúc khởi động**   | Ryu chỉ in log `Bắt đầu nạp luật ECMP...` đúng 01 lần duy nhất sau khi topology ổn định 2 giây.     | Xem màn hình Terminal 1 (Ryu).                          |
| **Nhận diện đủ 33 Docker Containers** | Traffic Generator và Microburst Generator quét thấy đủ `h1_1` đến `h8_4` và `inet`.                 | Xem màn hình Terminal 4 & 5.                            |
| **Độ thông suốt liên mạng (pingall)** | $100\%$ các host ping thông nhau (`0% packet drop`).                                                | Gõ `pingall` trên CLI `containernet>`.                  |
| **Không nghẽn server busy**           | `iperf3` chạy song song liên tục trên 4 cổng `5201-5204` mà không phát sinh ngoại lệ.               | Quan sát log Terminal 4.                                |
| **Đầy đủ Bộ 10 Features**             | File CSV có đủ các cột: `dur, sbytes, dbytes, Spkts, Dpkts, Sload, Dload, smeansz, dmeansz, Ratio`. | `head -n 1 results/traffic_flow_dataset_with_paths.csv` |
| **Lần vết đường đi Hop-by-Hop**       | Cột `path` ghi rõ từng chặng kèm cổng vào/ra (ví dụ `h1_1 -> a1[in:5->out:1] -> ag1[...] -> h5_2`). | Kiểm tra cột `path` trong file CSV.                     |
| **Phân bổ 3 vùng Locality chuẩn**     | Khoảng $7.2\%$ luồng cùng rack, $85.0\%$ luồng liên rack, $7.8\%$ luồng ra node `inet`.             | Xem thống kê in ra từ `unified_sampler.py`.             |
| **Cổng NFV Proxy sẵn sàng**           | Toàn bộ 8 Access Switches (`a1..a8`) đều có interface `proxy-int` ở trạng thái UP.                  | Chạy `ovs-vsctl show` trong container switch.           |
| **Kiểm định thống kê KS-Test**        | Giá trị $p\text{-value} > 0.05$ đối với phân phối kích thước luồng so với số liệu bài báo Facebook. | Xem kết quả chạy `validate_workload_kstest.py`.         |

---

## 4. QUY TRÌNH TREO MÁY SSH, XÁC MINH TIẾN TRÌNH VÀ DỌN DẸP HỆ THỐNG (SSH DETACH, VERIFICATION & CLEANUP)

Khi thực nghiệm mô phỏng quy mô lớn trong thời gian dài (ví dụ: hẹn giờ chạy 1 giờ hoặc nhiều giờ) qua kết nối mạng từ xa (SSH), quy trình sau đây đảm bảo tiến trình **không bị chết khi mất mạng**, giúp bạn **xác minh chính xác tiến trình đã chạy xong chưa khi SSH trở lại**, và **tắt sạch sẽ hệ thống**.

---

### 4.1. Hướng Dẫn Treo Máy An Toàn Qua SSH (Sử dụng `tmux`)

Nếu chỉ chạy terminal SSH thông thường, khi bạn tắt máy tính cá nhân hoặc kết nối SSH bị ngắt, Linux sẽ gửi tín hiệu `SIGHUP` làm chết toàn bộ tiến trình. Sử dụng `tmux` (Terminal Multiplexer có sẵn trên Ubuntu) để khắc phục.

Bạn có thể chọn **1 trong 2 cách tổ chức** tùy theo thói quen:

---

#### CÁCH 1 (Khuyên Dùng): Chỉ cần 01 session `tmux` duy nhất chứa 5 Cửa Sổ (Tabs)

Bạn không cần mở nhiều tmux riêng lẻ, mà quản lý 5 terminal tương tự như 5 tab trình duyệt bên trong 1 phiên:

1. **Khởi tạo session duy nhất:**
   ```bash
   tmux new -s dcn_sim
   ```
2. **Thao tác tạo và chuyển đổi giữa 5 Terminal (Tabs):**
   - **Tạo tab mới:** Bấm **`Ctrl + B`** rồi ấn phím **`C`** (Create Window).
   - **Đổi tên tab cho dễ nhớ:** Bấm **`Ctrl + B`** rồi ấn phím **`,`** (nhập tên: `ryu`, `topo`, `mgmt`, `traffic`, `burst`).
   - **Chuyển qua lại các tab:**
     - Bấm **`Ctrl + B`** rồi ấn phím số **`0`**, **`1`**, **`2`**, **`3`**, **`4`** để nhảy ngay tới terminal tương ứng.
     - Hoặc **`Ctrl + B`** rồi ấn phím **`N`** (Next) / **`P`** (Previous).
   - _Khởi chạy lần lượt (tất cả đều đứng tại thư mục `~/dcn`):_
     - **Tab 0 (`ryu`):** `ryu-manager --observe-links controller/controller.py ryu.app.ofctl_rest ryu.app.rest_topology --ofp-tcp-listen-port 6653`
     - **Tab 1 (`topo`):** `sudo python3 controller/spine_leaf_topo.py` (chờ ổn định rồi gõ `pingall`)
     - **Tab 2 (`mgmt`):** `python3 controller/management_plane.py`
     - **Tab 3 (`traffic`):** `sudo python3 controller/traffic_generator.py --duration 1h`
     - **Tab 4 (`burst`):** `sudo python3 controller/microburst_generator.py --mode random --duration 1h --mininterval 10s --maxinterval 30s`
3. **Treo máy & Thoát SSH an toàn (Detach):**
   - Nhấn tổ hợp phím: **`Ctrl + B`**, sau đó thả tay ra và nhấn phím **`D`** (Detach).
   - Màn hình hiển thị: `[detached (from session dcn_sim)]`.
   - **Bây giờ bạn có thể tắt máy tính cá nhân, ngắt kết nối SSH thoải mái.** Cả 5 tab vẫn tiếp tục chạy ngầm 100% trên máy chủ ảo.

---

#### CÁCH 2 (Dễ Nhớ Cho Người Mới): Mỗi Terminal là 01 session `tmux` riêng biệt

Nếu bạn quen mở nhiều cửa sổ SSH độc lập (tất cả đều đứng tại `cd ~/dcn`), bạn có thể tạo 5 session riêng biệt:

- **Terminal 1 (Ryu):** `tmux new -s ryu` $\to$ `ryu-manager --observe-links controller/controller.py ryu.app.ofctl_rest ryu.app.rest_topology --ofp-tcp-listen-port 6653` $\to$ Bấm `Ctrl+B, D`.
- **Terminal 2 (Topo):** `tmux new -s topo` $\to$ `sudo python3 controller/spine_leaf_topo.py` & gõ `pingall` $\to$ Bấm `Ctrl+B, D`.
- **Terminal 3 (Mgmt):** `tmux new -s mgmt` $\to$ `python3 controller/management_plane.py` $\to$ Bấm `Ctrl+B, D`.
- **Terminal 4 (Traffic):** `tmux new -s traffic` $\to$ `sudo python3 controller/traffic_generator.py --duration 1h` $\to$ Bấm `Ctrl+B, D`.
- **Terminal 5 (Burst):** `tmux new -s burst` $\to$ `sudo python3 controller/microburst_generator.py --mode random --duration 1h --mininterval 10s --maxinterval 30s` $\to$ Bấm `Ctrl+B, D`.

_Khi SSH vào lại, muốn xem terminal nào chỉ cần gõ:_ `tmux attach -t traffic` hoặc `tmux attach -t mgmt`. (Gõ `tmux ls` để liệt kê danh sách toàn bộ session).

---

### 4.2. Quy Trình Xác Minh Tiến Trình Khi SSH Kết Nối Lại

Khi mở máy tính và SSH trở lại máy ảo sau thời gian hẹn giờ (ví dụ sau 1 giờ):

#### Cách 1: Kết nối lại phiên làm việc `tmux` (Trực quan nhất)

```bash
tmux attach -t dcn_sim
```

- Màn hình sẽ hiển thị lại **nguyên vẹn toàn bộ log và dashboard** tại thời điểm bạn rời đi.
- Nếu hết giờ, màn hình sẽ hiển thị rõ bảng tổng kết:
  `[*] Đã đạt giới hạn thời gian chạy (3600.0s). Tự động dừng sinh tải.`

#### Cách 2: Kiểm tra trạng thái tiến trình bằng lệnh Linux (Process Status)

Kiểm tra xem các tiến trình hẹn giờ còn đang chạy hay đã kết thúc:

```bash
# Kiểm tra 2 tiến trình sinh tải nền và tiêm microburst
pgrep -a -f "traffic_generator|microburst_generator"
```

- **Nếu không có dòng nào xuất hiện:** $\implies$ Cả 2 tiến trình hẹn giờ đã chạy đủ thời gian và **tự động hoàn thành, dừng an toàn**.
- **Nếu vẫn hiện PID:** $\implies$ Tiến trình vẫn đang trong thời gian sinh tải, chưa hết giờ.

Kiểm tra các tiến trình nền khác của hệ thống:

```bash
pgrep -a -f "ryu-manager|management_plane|spine_leaf_topo"
```

#### Cách 3: Xác minh dữ liệu đầu ra trong thư mục `results/`

Kiểm tra xem dữ liệu đo đạc đã được ghi đầy đủ chưa:

```bash
# 1. Xem dung lượng các file CSV kết quả
ls -lh results/

# 2. Đếm số lượng luồng nền thu thập được (thường > 15,000 luồng sau 1h)
wc -l results/traffic_flow_dataset_with_paths.csv

# 3. Xem các đợt tiêm microburst cuối cùng trong nhật ký Ground-Truth
tail -n 10 results/microburst_client_ground_truth.csv

# 4. Xem các chỉ số KPI đánh giá toàn mạng chu kỳ mới nhất
tail -n 5 results/network_evaluation_kpis.csv
```

---

### 4.3. Trình Tự Tắt Tiến Trình & Dọn Dẹp An Toàn

Sau khi các tiến trình sinh tải đã kết thúc đúng giờ và bạn đã hoàn tất phân tích dataset (Bước 6), hãy tắt các tiến trình còn lại theo đúng trình tự sau:

#### Bước 1: Dừng tầng Quản trị & Telemetry (Management Plane)

```bash
sudo pkill -f "management_plane.py"
```

#### Bước 2: Dừng hạ tầng mạng Mininet / Containernet & giải phóng Switch OVS

- Nếu đang ở giao diện Mininet CLI: gõ `exit`.
- Nếu terminal Mininet bị ngắt kết nối hoặc chạy nền:

  ```bash
  sudo mn -c
  ```

  _(Lệnh này tự động dọn dẹp các switch ảo OVS, xóa các cặp interface veth và khôi phục bảng định tuyến Linux kernel)._

#### Bước 3: Dừng Ryu SDN Controller

```bash
sudo pkill -f "ryu-manager"
```

#### Bước 4: Giải phóng triệt để các tiến trình con và Docker Containers (Bảo đảm sạch 100%)

```bash
# Tiêu diệt triệt để tiến trình iperf3 còn sót (nếu có)
sudo killall -9 iperf3 2>/dev/null

# Xóa sạch các container do Containernet khởi tạo
docker rm -f $(docker ps -a -q --filter "name=mn.") 2>/dev/null

# Kiểm tra lại danh sách container đang chạy (đảm bảo không còn container mn.*)
docker ps
```

---

### 4.4. Xử Lý Sự Cố & Reset Toàn Diện Môi Trường (Hard Reset)

Nếu trong quá trình thử nghiệm hệ thống bị treo hoặc muốn xóa trắng làm lại từ đầu:

```bash
# 1. Tiêu diệt toàn bộ tiến trình liên quan đến mô phỏng
sudo killall -9 containernet mn ryu-manager python3 iperf3 ping 2>/dev/null

# 2. Xóa sạch container Containernet
docker rm -f $(docker ps -a -q --filter "name=mn.") 2>/dev/null

# 3. Dọn dẹp card mạng ảo và Open vSwitch
sudo mn -c

# 4. Khôi phục lại trạng thái hiển thị bình thường của Terminal (nếu chữ gõ bị ẩn)
stty sane && reset
```

---

## 5. TỔNG KẾT CÁC TỆP TIN DỰ ÁN LIÊN QUAN

- **Mã nguồn lõi:**
  - [`controller/spine_leaf_topo.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/spine_leaf_topo.py): Khởi tạo mạng Spine-Leaf 32 Hosts Containernet.
  - [`controller/controller.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/controller.py): Ryu OpenFlow 1.3 Controller với Debounce và Bi-flow.
  - [`controller/management_plane.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/management_plane.py): Tầng quản trị thu thập 10 Features và đường đi Hop-by-Hop.
  - [`controller/unified_sampler.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/unified_sampler.py): Bộ lấy mẫu toán học nghịch đảo ECDF Facebook.
  - [`controller/traffic_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_generator.py): Engine phát lưu lượng nền thống nhất đa kênh.
  - [`controller/microburst_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/microburst_generator.py): Engine phát Heavy Jitter / Microburst và ghi nhật ký ground-truth.
  - [`controller/analyze_and_label_dataset.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/analyze_and_label_dataset.py): Phân tích phân vị và gán nhãn dataset cho AI.
  - [`controller/validate_workload_kstest.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/validate_workload_kstest.py): Kiểm định thống kê 2 mẫu Kolmogorov-Smirnov.
- **Cấu hình:**
  - [`controller/topology_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/topology_config.json): Master cấu hình hạ tầng & tài nguyên cgroups.
  - [`controller/traffic_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_config.json): Cấu hình mô hình lưu lượng tham chiếu động.
- **Docker Image:**
  - [`controller/docker_image/Dockerfile.host`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/docker_image/Dockerfile.host): Image máy trạm Ubuntu 20.04.
  - [`controller/docker_image/Dockerfile.ovs`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/docker_image/Dockerfile.ovs): Image Open vSwitch nhúng NFV Proxy.
  - [`controller/docker_image/build_images.sh`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/docker_image/build_images.sh): Script build tự động cả 2 images.
