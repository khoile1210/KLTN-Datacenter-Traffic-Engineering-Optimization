# BÁO CÁO TỔNG KẾT TOÀN BỘ NHỮNG GÌ ĐÃ LÀM ĐƯỢC (PROJECT COMPLETED ACHIEVEMENTS)

> **Tên đề tài:** Research on Traffic Engineering Optimization in Data Center Networks Based on Software-Defined Network and Artificial Intelligence  
> **Ngày tổng kết:** 2026-10-17  
> **Phiên bản hệ thống hiện tại:** v3.2 (OpenFlow 1.3 Multi-Table + Hybrid eBPF/XDP Telemetry + Facebook Unified Workload)  
> **Trạng thái kiểm định:** Đã chạy thực nghiệm thành công, thu thập đủ 6 tệp dữ liệu chuẩn sạch $100\%$ và vượt qua kiểm định thống kê Kolmogorov-Smirnov (KS-Test).

---

## 1. TỔNG QUAN CÁC HẠNG MỤC ĐÃ HOÀN THÀNH

Tính đến thời điểm hiện tại, dự án đã **hoàn thành trọn vẹn 100% Giai đoạn 1 (với 8/8 phân đoạn nhỏ)** và **nâng cấp vượt chuẩn kiến trúc ban đầu** ở cả 3 mặt phẳng: Hạ tầng Dữ liệu (Data Plane), Điều khiển SDN (Control Plane) và Quản trị Giám sát Vi mô (Management & eBPF/XDP Telemetry Plane).

| Phân Hệ / Hạng Mục | Trạng Thái | Tệp Tin Thực Thi & Đầu Ra Chính | Mức Độ Hoàn Thiện |
| :--- | :---: | :--- | :---: |
| **1. Hạ tầng Spine-Leaf & Docker Images** | ✅ Hoàn thành | `spine_leaf_topo.py`, `Dockerfile.host`, `Dockerfile.ovs` | **100%** |
| **2. Cấu hình Động Infrastructure-as-Code** | ✅ Hoàn thành | `topology_config.json`, `traffic_config.json` | **100%** |
| **3. SDN Controller OpenFlow 1.3 Đa Bảng** | ✅ Hoàn thành | `controller/controller.py` | **100%** |
| **4. Số hóa & Hòa trộn ECDF Facebook** | ✅ Hoàn thành | `digitize_paper_plots.py`, `blend_cdfs.py`, `cdf_profiles/*.csv` | **100%** |
| **5. Bộ Lấy Mẫu & Bộ Đôi Sinh Tải DCN** | ✅ Hoàn thành | `unified_sampler.py`, `traffic_generator.py`, `microburst_generator.py` | **100%** |
| **6. Tầng Quản Trị & Hybrid eBPF/XDP** | ✅ Hoàn thành | `management_plane.py`, `ebpf_telemetry.c`, `ebpf_loader.py` | **100%** |
| **7. Thực Nghiệm Thu Thập 6 Tập Dữ Liệu** | ✅ Hoàn thành | `results/*.csv` (6 files, $77,993$ bi-flows) | **100%** |
| **8. Phân Tích Pareto & Kiểm Định KS-Test** | ✅ Hoàn thành | `analyze_and_label_dataset.py`, `validate_workload_kstest.py` | **100%** |
| **9. Tài Liệu Vận Hành & Nhật Ký Thay Đổi** | ✅ Hoàn thành | `TESTING_AND_OVERHAUL_GUIDE.md`, `.ChangingLog/*`, `.FileTree.md` | **100%** |

---

## 2. CHI TIẾT KỸ THUẬT CÁC THÀNH TỰU ĐÃ ĐẠT ĐƯỢC

### 2.1. Hạ Tầng Ảo Hóa Spine-Leaf & Cô Lập Tài Nguyên Cgroups (Data Plane)
- **Xây dựng bộ Docker Images chuyên dụng (`controller/docker_image/`):**
  - [`Dockerfile.host`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/docker_image/Dockerfile.host): Đóng gói `dcn-host:latest` tích hợp đầy đủ công cụ mạng (`iperf3`, `iproute2`, `net-tools`, `tcpdump`, `python3`).
  - [`Dockerfile.ovs`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/docker_image/Dockerfile.ovs) & [`entrypoint_ovs.sh`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/docker_image/entrypoint_ovs.sh): Đóng gói `dcn-ovs:latest` khởi tạo Open vSwitch và tự động nhúng cổng nội bộ `proxy-int` phục vụ NFV Proxy.
- **Thiết lập Topology Spine-Leaf 3 Tầng chuẩn mực ([`controller/spine_leaf_topo.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/spine_leaf_topo.py)):**
  - Khởi tạo **14 Switch OVS** (2 Core `c1..c2`, 4 Aggregation `ag1..ag4`, 8 Access/ToR `a1..a8`) và **33 Docker Containers** (32 Hosts nội bộ `h1_1..h8_4` theo chuẩn **1 Rack = 4 Hosts** + 1 Node Internet `inet` tại `10.0.0.254/24`).
  - Áp dụng nghiêm ngặt **Ma trận Đồng dạng 4 Miền**: Giới hạn `cgroups` từng container (`cpus = 1.0`, `cpu_quota = 100000us`, `mem_limit = 1024m`), thiết lập băng thông phân tầng `TCLink` ($20\text{M} / 50\text{M} / 100\text{M}$) và độ dài hàng đợi $1000\text{ pkts}$ bảo toàn thời gian xả đệm $\tau_{\text{buf}} \approx 9.6 - 10\text{ ms}$.
- **Kiến trúc Cấu hình Kép Tham chiếu Động (Infrastructure-as-Code):**
  - Tách biệt [`topology_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/topology_config.json) (Gốc phần cứng) và [`traffic_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_config.json) (Mô hình phụ tải) liên kết qua cú pháp JSON Pointer `ref:topology_config.json#/...`, đảm bảo thay đổi cấu hình tại 1 nơi sẽ tự động cập nhật toàn hệ thống.

---

### 2.2. Cải Tổ Toàn Diện Ryu SDN Controller OpenFlow 1.3 ([`controller/controller.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/controller.py))
- **Kiến trúc OpenFlow 1.3 Multi-Table Pipeline (2 Bảng tách biệt):**
  - Khắc phục triệt để lỗi "mù luồng mới" khi cài đặt ECMP proactive.
  - **Table 0 (Flow Classification & Reactive Learning):**
    - Luật ưu tiên `Priority = 150` (`idle_timeout = 30s`): Khớp chính xác 5-tuple đối xứng (`ipv4_src`, `ipv4_dst`, `ip_proto`, `l4_src`, `l4_dst`) để OVS đếm riêng dung lượng và số gói tin 2 chiều (`sbytes/dbytes`, `Spkts/Dpkts`), sau đó chuyển tiếp sang `Goto-Table(1)`.
    - Luật bắt luồng mới tại cổng Host trên Access Switch (`Priority = 50`): Vừa gửi bản sao header $128\text{ bytes}$ lên Controller (`OFPP_CONTROLLER`) để học và cài luật 5-tuple, vừa đẩy gói tin đi ngay lập tức sang `Goto-Table(1)` (**Zero Packet Delay / Zero Loss**).
  - **Table 1 (Routing & ECMP Group Forwarding):**
    - Chứa các luật định tuyến đích `ipv4_dst` (`Priority = 100`) trỏ vào **ECMP Group Table (`OFPGT_SELECT`)** chia tải đa đường lên tầng Aggregation/Core hoặc xuất trực tiếp ra cổng Host cục bộ.
- **Khám phá Liên kết LLDP kèm Debounce Timer (2.0s):** Trì hoãn tính toán đường đi cho đến khi toàn bộ 14 Switches và 48 Links ổn định hoàn toàn, triệt tiêu hiện tượng bão bản tin `FlowMod/GroupMod` lúc khởi động.
- **Dynamic Host Discovery & Proxy ARP:** Tự động học vị trí Host $(IP, MAC, DPID, Port)$ và trả lời trực tiếp ARP Request từ bộ nhớ đệm của Controller, ngăn chặn hoàn toàn bão quảng bá (Broadcast Storm) trong mạng vòng.
- **Đồng bộ Group Table An toàn:** Gửi tuần tự `OFPGC_DELETE` kèm `OFPBarrierRequest` trước khi `OFPGC_ADD`, khắc phục triệt để lỗi `OFPGMFC_GROUP_EXISTS` khi switch kết nối lại.

---

### 2.3. Hệ Sinh Thái Sinh Tải Thống Nhất Chuẩn Học Thuật Facebook (ACM SIGCOMM 2015)
- **Trích xuất & Số hóa chính xác 9 đường cong ECDF thực nghiệm:**
  - Sử dụng [`extract_paper_figures.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/extract_paper_figures.py) và [`digitize_paper_plots.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/digitize_paper_plots.py) trích xuất 12 ảnh 400 DPI từ PDF gốc và số hóa thành 9 tệp CSV thô trong `controller/raw_digitized/` (đầy đủ phần đuôi dài chạm mốc $\text{CDF} = 1.0$).
- **Hòa trộn Phân phối Thống nhất ([`controller/blend_cdfs.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/blend_cdfs.py)):**
  - Tổ hợp lồi theo trọng số mẫu chuẩn hóa ($42.8\%$ Hadoop, $38.8\%$ Web Frontend, $18.4\%$ Cache) trên lưới 1.000 điểm phân vị nội suy logarit, xuất ra 3 hồ sơ chuẩn SI tại `controller/cdf_profiles/`.
- **Bộ Lấy Mẫu Toán Học ([`controller/unified_sampler.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/unified_sampler.py)):**
  - Thực thi lấy mẫu biến đổi ngược (Inverse Transform Sampling), hàm scale liên tục chống nghịch đảo kích thước (Piecewise Continuous Scaling $\alpha = 0.002$), giãn nhịp phát $D_{\text{arrival}} = 16.0$, và chọn đích theo 3 vùng Locality ($7.2\%$ Intra-Rack, $85.0\%$ Extra-Rack, $7.8\%$ Extra-DC).
- **Bộ Đôi Engine Sinh Tải Độc Lập:**
  - [`controller/traffic_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_generator.py): Tự động quản lý các `iperf3` servers đa cổng (`5201–5204`) trên toàn bộ 33 containers và phát lưu lượng nền đồng nhất qua `iperf3 -n {S_scaled}`.
  - [`controller/microburst_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/microburst_generator.py): Bơm xung đột biến siêu ngắn ($< 10\text{ ms}$, $20 - 80\text{ KB}$) bằng raw TCP socket (`TCP_NODELAY = 1`, cờ ECN `TOS = 0x02`), hỗ trợ cấu hình khoảng nghỉ ngẫu nhiên linh hoạt (`--mininterval` và `--maxinterval`, ví dụ `10s` đến `30s`) và tự ghi nhật ký `results/microburst_client_ground_truth.csv`.

---

### 2.4. Tầng Quản Trị Toàn Diện & Động Cơ Giám Sát Vi Mô eBPF/XDP
- **Thu thập Đa luồng Phi Phong Tỏa ([`controller/management_plane.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/management_plane.py)):**
  - Trích xuất **Bộ 10 Features chuẩn Bi-Flow** + `pkt_rate`, `byte_rate`, `locality`, `hop_count` và lần vết đường đi chi tiết từng chặng (**Full Hop-by-Hop Path**).
  - Triển khai `DockerStatsCollectorThread` chạy nền bất đồng bộ có cơ chế **Stale Cache Retention**, giải quyết triệt để lỗi `TimeoutExpired` khi thu thập CPU/RAM/NetIO của 33 containers dưới tải cao.
- **Mô hình Phân bổ Tài nguyên Động (Dynamic Two-Phase Resource Attribution Model):**
  - Thay thế phép chia cào bằng $1/14$ của tiến trình `ovs-vswitchd` bằng mô hình phân bổ theo trọng số tải thực tế của từng switch:
    - **Pha 1:** Đếm tổng số Flow Rules trên **toàn bộ các bảng OpenFlow (Table 0 + Table 1)** và tính tốc độ gói $\text{PPS}_i$ của từng switch.
    - **Pha 2:** Phân bổ $10\%$ Baseline tĩnh + $90\%$ động theo tỷ trọng **CPU ($70\% \text{ PPS} + 30\% \text{ Rules}$)** và **RAM ($80\% \text{ Rules} + 20\% \text{ PPS}$)**, kèm chuẩn hóa hậu kiểm bảo toàn $100\%$ tài nguyên ($\sum W_i \equiv 1.0$).
- **Động cơ Giám sát Trong Nhân eBPF / XDP ([`ebpf_telemetry.c`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/ebpf_telemetry.c) & [`ebpf_loader.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/ebpf_loader.py)):**
  - **XDP Passive Ingress Hook:** Đính kèm vào các cổng `veth` với cờ `XDP_FLAGS_SKB_MODE`, bóc tách 5-tuple, bấm giờ phần cứng nano-giây tính FCT vi mô và luôn trả về `XDP_PASS` (không mất gói, không xung đột với OVS).
  - **Cửa sổ trượt 10ms & Perf Ring Buffer:** Phát hiện Microburst ngay tại card mạng và bắn cảnh báo thời gian thực lên Userspace.
  - **Bridge-Port Indexing (`ifindex_to_bridge_map`):** Tra cứu DPID của Switch trong $2\text{ns}$ ngay trong nhân Linux.
  - **Cơ chế Dung nạp Lỗi 3 Tầng (3-Tier Graceful Fallback):** Tự động chuyển đổi mượt mà giữa *Tier 1 (Full eBPF/XDP)*, *Tier 2 (TC-only)* và *Tier 3 (Baseline Dynamic Attribution)* tùy theo quyền hạn và môi trường máy chủ.

---

### 2.5. Kết Quả Thực Nghiệm 6 Tệp Dữ Liệu & Kiểm Định Học Thuật (`results/`)
Hệ thống đã được chạy thực nghiệm hoàn chỉnh và thu thập bộ 6 tệp dữ liệu CSV sạch tuyệt đối (**$0\text{ NaN}$**):
1. `traffic_flow_dataset_with_paths.csv`: **$77,993$ dòng Bi-flow** ($15.55\text{ MB}$), ghi nhận đầy đủ 10 features, đường đi hop-by-hop và phân bố Locality chuẩn xác ($85.04\%$ Extra-Rack, $8.03\%$ Intra-Rack, $6.94\%$ Extra-DC).
2. `device_resource_utilization.csv`: **$14,692$ bản ghi** qua $314$ chu kỳ đo trên toàn bộ $47$ nodes ($33$ hosts + $14$ switches).
3. `system_and_network_health.csv`: **$14,692$ bản ghi** giám sát chi tiết sức khỏe phần cứng, lỗi gói và bảng luồng TCAM.
4. `link_utilization_telemetry.csv`: **$32,970$ bản ghi** theo dõi băng thông tức thời, độ lấp đầy (%) và số gói rớt trên toàn bộ 4 tầng liên kết.
5. `network_evaluation_kpis.csv`: **$314$ chu kỳ** tổng hợp các chỉ số KPI toàn mạng: Số luồng hoạt động trung bình $= 248.38$ luồng/chu kỳ, số chặng trung bình $= 2.33\text{ hops}$, Jain's Fairness Index, Bisection Bandwidth Utilization.
6. `microburst_client_ground_truth.csv`: Ghi nhận chính xác **$23$ đợt xung Microburst** với khoảng cách phát ngẫu nhiên phân phối đều từ $10\text{s} - 30\text{s}$.

**Kết quả Kiểm định Thống kê ([`validate_workload_kstest.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/validate_workload_kstest.py)):**
- Kiểm định Kolmogorov-Smirnov 2 mẫu giữa dữ liệu thực nghiệm và hồ sơ gốc Facebook đạt **$D = 0.0170, p\text{-value} = 0.779 > 0.05$**, chứng minh độ tương đồng xuất sắc về mặt toán học và xuất biểu đồ [`chart_facebook_workload_validation.png`](file:///c:/Users/USER/Desktop/SDN%20KLTN/results/chart_facebook_workload_validation.png) cùng [`flow_distribution_and_threshold_analysis.png`](file:///c:/Users/USER/Desktop/SDN%20KLTN/results/flow_distribution_and_threshold_analysis.png) chất lượng in ấn 300 DPI.
