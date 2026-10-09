# HƯỚNG DẪN KIỂM THỬ VÀ TÀI LIỆU CẢI TỔ HỆ THỐNG CONTROLLER (v2)

> **Dự án:** Research on Traffic Engineering Optimization in Data Center Networks Based on Software-Defined Network and Artificial Intelligence  
> **Phiên bản:** Controller v2 (Cải tổ toàn diện: Docker OVS, 10 Features, Full Hop-by-Hop Path Tracing)  
> **Ngày cập nhật:** 2026-10-09  

---

## 1. TỔNG HỢP CÁC THAY ĐỔI ĐÃ THỰC HIỆN

Hệ thống đã trải qua đợt cải tổ lớn nhằm giải quyết triệt để các lỗi logic, khắc phục hiện tượng thắt cổ chai và đáp ứng hoàn hảo yêu cầu trích xuất dữ liệu đầu vào cho các mô hình Trí tuệ Nhân tạo (**XGBoost / LightGBM** và **GAT + PPO**):

### 1.1. Tầng Điều Khiển — [`controller.py`](controller.py)
* **Vá lỗi `OFPGC_MODIFY` khi Switch kết nối lại:** Xóa sạch trạng thái `self.installed_groups` theo DPID trong `switch_features_handler`. Đảm bảo khi switch reconnect, Controller luôn gửi lệnh `OFPGC_ADD`, tránh hoàn toàn lỗi `OFPGMFC_UNKNOWN_GROUP`.
* **Chống bão bản tin FlowMod/GroupMod (Debounce Timer 2.0s):** Sử dụng `ryu.lib.hub.spawn_after(2.0, ...)`. Khi phát hiện hàng chục liên kết LLDP dồn dập lúc khởi động mạng, Controller sẽ hoãn tính toán cho đến khi topology hoàn toàn ổn định (không còn link mới trong 2 giây), giảm hơn 90% tải kênh Southbound.
* **Học vị trí Host động (Dynamic Host Discovery):** Bổ sung hàm `learn_host()`, tự động ghi nhận Host $(IP, MAC)$ qua các gói ARP/IP từ cổng Access, không còn phụ thuộc cứng vào bảng tĩnh.
* **Cài đặt cặp Flow Rule 5-tuple đối xứng (Bi-Flow) tại Ingress Switch:**
  * Bổ sung hàm `install_symmetric_biflow`: Cài 2 rule có `Priority = 150` và `idle_timeout = 30s` trên Access Switch nguồn.
  * **Forward Rule:** Khớp $(A \to B, \text{proto}, pA, pB) \implies$ OVS tự đếm **`sbytes`, `Spkts`, `dur`**.
  * **Backward Rule:** Khớp $(B \to A, \text{proto}, pB, pA) \implies$ OVS tự đếm **`dbytes`, `Dpkts`**.
* **Sẵn sàng cho NFV Proxy (Priority 1000):** Tích hợp phương thức `steer_elephant_flow()` để khi AI ra quyết định, Controller đẩy rule `Priority = 1000` điều hướng luồng Voi vào cổng nội bộ `proxy-int`.

---

### 1.2. Tầng Quản Trị & Trích Xuất Dữ Liệu — [`management_plane.py`](management_plane.py)
* **Thu thập đủ Bộ 10 FEATURES chuẩn:**
  * **Nhóm 1 (Trực tiếp từ OVS counter):** `dur`, `sbytes`, `dbytes`, `Spkts`, `Dpkts`.
  * **Nhóm 2 (Phái sinh có cơ chế bảo vệ chia cho 0 với $\epsilon = 10^{-6}$):**
    * $\text{Sload} = sbytes / \max(dur, 10^{-6})$ (Tốc độ truyền chiều đi - Bytes/s)
    * $\text{Dload} = dbytes / \max(dur, 10^{-6})$ (Tốc độ truyền chiều về - Bytes/s)
    * $\text{smeansz} = sbytes / \max(Spkts, 1)$ (Kích thước trung bình gói chiều đi - Bytes)
    * $\text{dmeansz} = dbytes / \max(Dpkts, 1)$ (Kích thước trung bình gói chiều về - Bytes)
    * $\text{Ratio} = sbytes / (dbytes + 10^{-6})$ (Tỷ lệ chênh lệch dung lượng 2 chiều)
* **Lần vết TOÀN BỘ ĐƯỜNG ĐI CHI TIẾT NHẤT (Full End-to-End Hop-by-Hop):**
  * Hiển thị rõ ràng từng chặng từ Host đầu đến Host cuối xuyên suốt 3 tầng Access - Aggregation - Core:
    $$\text{Định dạng: } h\_src \to a\_src[in \to out] \to ag\_src[in \to out] \to c\_core[in \to out] \to ag\_dst[in \to out] \to a\_dst[in \to out] \to h\_dst$$
  * Tính toán chính xác `hop_count` (tổng số switch tham gia định tuyến).
* **Ghép cặp Luồng đối xứng (Bidirectional Flow Pairing):**
  * Bóc tách trực tiếp từ OpenFlow Flow Stats của Ingress Switch, loại bỏ hoàn toàn việc gọi subprocess `docker exec ss -tuna` nặng nề, giúp chu kỳ polling luôn hoàn tất mượt mà dưới 1.0 giây.

---

### 1.3. Tầng Dữ Liệu & Topology — [`spine_leaf_topo.py`](spine_leaf_topo.py) & Docker OVS
* **Tạo mới [`Dockerfile.ovs`](Dockerfile.ovs) & [`entrypoint_ovs.sh`](entrypoint_ovs.sh):** Đóng gói Open vSwitch trong container, cấu hình bridge OpenFlow 1.3 và tự động tạo cổng nội bộ `proxy-int`.
* **Cập nhật `spine_leaf_topo.py`:** Tự động thiết lập cổng nội bộ `proxy-int` (`10.255.0.1/24` đến `10.255.0.8/24`) trên toàn bộ 8 Access Switches (`a1` – `a8`) để nhúng NFV Proxy trực tiếp trên Switch.

---

### 1.4. Trình Sinh Tải Thực Nghiệm — [`traffic_generator.py`](traffic_generator.py)
* **Đa cổng iperf3 song song (`5201, 5202, 5203, 5204`):** Khởi chạy nhiều server trên mỗi host, client chọn ngẫu nhiên cổng $\rightarrow$ **Giải quyết dứt điểm lỗi `iperf3: error - the server is busy`**.
* **Luồng Chuột đa dạng (Mice Flow):** Kết hợp cả gói Ping nhỏ (ICMP) và các phiên TCP burst ngắn (20KB – 50KB qua `iperf3 -n`) kết thúc nhanh $\rightarrow$ Tạo ra lưu lượng hai chiều thực tế có Request nhỏ và Response trả về, giúp đặc trưng `Ratio` phản ánh chuẩn xác bản chất luồng chuột.

---

### 1.5. Công Cụ Phân Tích — [`analyze_csv_result.py`](analyze_csv_result.py)
* Tương thích hoàn toàn với bộ 10 Features mới (`Sload`, `Ratio`, `smeansz`...).
* Phân tích phân bổ lộ trình qua tất cả các tầng Core Switch (`c1, c2`) và Aggregation Switch (`ag1..ag4`).
* Tự động lưu 6 biểu đồ học thuật độ phân giải cao vào thư mục `results/`.

---

## 2. QUY TRÌNH KIỂM THỬ TỪNG BƯỚC (STEP-BY-STEP TESTING WORKFLOW)

Quy trình này được thiết kế để bạn thực hiện trên môi trường máy ảo hoặc máy chủ Linux (Ubuntu 20.04/22.04 LTS có cài Containernet, OVS và Ryu):

```
+-----------------------------------------------------------------------------------+
| BƯỚC 0: Build Docker Images (dcn-host, dcn-ovs)                                   |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
| BƯỚC 1: Khởi động Ryu Controller (Terminal 1)                                     |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
| BƯỚC 2: Khởi động Topology Spine-Leaf & pingall (Terminal 2)                       |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
| BƯỚC 3: Khởi động Management Plane thu thập Telemetry (Terminal 3)               |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
| BƯỚC 4: Khởi động Traffic Generator sinh tải Voi/Chuột (Terminal 4)               |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
| BƯỚC 5: Kiểm tra file CSV và Chạy script phân tích vẽ biểu đồ (Terminal 5)        |
+-----------------------------------------------------------------------------------+
```

---

### BƯỚC 0: Chuẩn bị Môi trường & Build Docker Images
Mở Terminal, di chuyển vào thư mục `controller/`:

```bash
cd ~/dcn/controller  # Hoặc đường dẫn thư mục controller của bạn

# 1. Build image Docker Host (dcn-host:latest)
docker build -t dcn-host:latest -f Dockerfile .

# 2. Build image Docker OVS Switch nhúng NFV Proxy (dcn-ovs:latest)
docker build -t dcn-ovs:latest -f Dockerfile.ovs .

# 3. Kiểm tra xem 2 images đã xuất hiện chưa
docker images | grep -E "dcn-host|dcn-ovs"
```

---

### BƯỚC 1: Khởi động Ryu Controller v2 (Terminal 1)

```bash
# Chạy Ryu Controller với các plugin REST và lắng nghe cổng OpenFlow 6653
ryu-manager --observe-links controller.py ryu.app.ofctl_rest ryu.app.rest_topology --ofp-tcp-listen-port 6653
```

**Dấu hiệu thành công:**
* Xuất hiện thông báo: `[+] Multi-Tier Spine-Leaf Controller (Cải tổ v2) đã khởi động thành công.`
* Controller lắng nghe trên cổng `6653` (OpenFlow) và `8080` (REST API).

---

### BƯỚC 2: Khởi động Topology Spine-Leaf (Terminal 2)

```bash
sudo python3 spine_leaf_topo.py
```

**Dấu hiệu thành công:**
* Xuất hiện log tạo 2 Core, 4 Aggregation, 8 Access Switch, 8 Docker Host, 1 Internet Host.
* Xuất hiện log cấu hình cổng NFV Proxy:
  ```
  [*] Bước 5.1: Thiết lập cổng nội bộ NFV Proxy (proxy-int) trên Access Leaf Switches...
      - Switch a1: Cổng 'proxy-int' sẵn sàng (IP: 10.255.0.1/24)
      ...
      - Switch a8: Cổng 'proxy-int' sẵn sàng (IP: 10.255.0.8/24)
  ```
* Ở Terminal 1 (Ryu): Xuất hiện log `[*] Topo đã ổn định: 14 Switches, 48 Links LLDP. Bắt đầu nạp luật ECMP...` (chứng minh Debounce Timer hoạt động).
* Trên dấu nhắc `containernet>`, gõ lệnh pingall để kích hoạt học MAC/IP toàn mạng:
  ```
  containernet> pingall
  ```
  *(Kết quả: `0% dropped`, toàn bộ các host ping thông nhau 100%).*

---

### BƯỚC 3: Khởi động Tầng Quản Trị — Management Plane (Terminal 3)

```bash
python3 management_plane.py
```

**Dấu hiệu thành công:**
* Terminal hiển thị:
  ```
  [+] Khởi tạo file Dataset luồng (10 Features): results/traffic_flow_dataset_with_paths.csv
  [+] Khởi tạo file Sức khỏe hệ thống: results/system_and_network_health.csv
  [*] Management Plane v2 đang chạy (10 Features + Full Hop-by-Hop Paths). Chu kỳ: 1.0s...
  ```
* Mỗi giây xuất hiện log định kỳ:
  ```
  [15:30:00] Đã ghi: X Bi-Flows (10 Features + Full Path) | 23 Health Nodes.
  ```

---

### BƯỚC 4: Khởi động Trình Sinh Tải Traffic (Terminal 4)

```bash
sudo python3 traffic_generator.py
```

**Dấu hiệu thành công:**
* Script nhận diện đủ 9 Docker containers (`h1`..`h8`, `inet`).
* Khởi chạy iperf3 server đa cổng (`5201, 5202, 5203, 5204`) trên toàn bộ host:
  ```
  [*] Khởi động iperf3 server đa cổng [5201, 5202, 5203, 5204] trên toàn bộ container...
  [+] Toàn bộ iperf3 servers đa cổng đã sẵn sàng.
  ```
* Bắt đầu sinh tải liên tục:
  * Xuất hiện các dòng `[ELEPHANT] h1 (10.0.0.1) -> h6 (10.0.0.6)` (kéo dài 5–10s).
  * Đan xen các luồng Mice ngắn kết thúc ngay.
  * **Không còn xuất hiện lỗi `the server is busy`**.

---

### BƯỚC 5: Kiểm tra Dataset & Xuất Biểu Đồ Phân Tích (Terminal 5)

Để chương trình sinh tải chạy khoảng **3 đến 5 phút** để tích lũy hàng nghìn mẫu dữ liệu, sau đó:

#### 1. Kiểm tra cấu trúc file CSV xuất ra:
```bash
# Xem 5 dòng đầu tiên của dataset luồng
head -n 5 results/traffic_flow_dataset_with_paths.csv
```
**Kiểm tra xem có đủ các cột:**
`timestamp,src_ip,dst_ip,src_port,dst_port,protocol,dur,sbytes,dbytes,Spkts,Dpkts,Sload,Dload,smeansz,dmeansz,Ratio,hop_count,path,label`

**Kiểm tra định dạng cột `path`:**
Cột `path` phải hiển thị chuỗi chi tiết từng hop, ví dụ:
```
h1 -> a1[in:5->out:1] -> ag1[in:1->out:5] -> c1[in:1->out:2] -> ag3[in:5->out:2] -> a5[in:1->out:5] -> h5
```

#### 2. Chạy script phân tích và vẽ biểu đồ:
```bash
python3 analyze_csv_result.py
```

**Kết quả thu được:**
* Báo cáo thống kê chi tiết in ra terminal (Tỷ lệ Voi/Chuột, băng thông trung bình, độ bất đối xứng `Ratio`, phân bổ qua Core/Agg switches).
* Sinh ra 6 tệp biểu đồ PNG chất lượng cao trong thư mục `results/`:
  1. `chart1_byte_rate_distribution.png`: Phân bố tốc độ truyền (Log scale).
  2. `chart2_ecmp_load_balance.png`: Phân bổ lưu lượng qua tầng Core (`c1, c2`) và Aggregation (`ag1..ag4`).
  3. `chart3_hop_count_distribution.png`: Phân bố độ dài chặng (Hop count).
  4. `chart4_switch_tcam_occupancy.png`: Mức chiếm dụng TCAM Table 0 trên 14 Switch.
  5. `chart5_switch_traffic_volume.png`: Tổng lưu lượng vận chuyển qua cổng của các Switch.
  6. `chart6_host_resource_usage.png`: Tiêu thụ RAM & CPU của Docker Container.

---

## 3. CHECKLIST NGHIỆM THU (VERIFICATION CHECKLIST)

Sau khi chạy xong, bạn đối chiếu với bảng sau để khẳng định bài test đạt 100% yêu cầu:

| Tiêu chí kiểm tra | Kết quả mong đợi | Cách xác minh |
| :--- | :--- | :--- |
| **Không bão FlowMod lúc boot** | Ryu chỉ in log `Bắt đầu nạp luật ECMP` 01 lần duy nhất sau khi link ổn định. | Xem log ở Terminal 1. |
| **Switch Reconnect ổn định** | Nếu tắt bật lại 1 switch, OVS không báo lỗi `OFPGMFC_UNKNOWN_GROUP`. | Kiểm tra log OVS. |
| **Đầy đủ 10 Features** | File CSV có đủ `dur, sbytes, dbytes, Spkts, Dpkts, Sload, Dload, smeansz, dmeansz, Ratio`. | `head -n 1 results/traffic_flow_dataset_with_paths.csv` |
| **Độ bất đối xứng Ratio** | Luồng Voi có $\text{Ratio} \gg 1$ (vài chục đến hàng trăm); Luồng Chuột có $\text{Ratio} \approx 1$. | Xem output của `analyze_csv_result.py`. |
| **Full End-to-End Path** | Cột `path` ghi rõ từng hop `h_src -> a_src[in->out] -> ag[in->out] -> ... -> h_dst`. | Kiểm tra nội dung cột `path` trong CSV. |
| **Không lỗi Server Busy** | Traffic Generator chạy mượt mà, không bị exception ngắt ngang. | Xem màn hình Terminal 4. |
| **Cổng NFV Proxy sẵn sàng** | Switch `a1` đến `a8` đều có cổng `proxy-int` ở trạng thái UP. | Lệnh `ovs-vsctl show` trong switch. |

---

## 4. XỬ LÝ SỰ CỐ & DỌN DẸP MÔI TRƯỜNG (CLEANUP & TROUBLESHOOTING)

Nếu trong quá trình thử nghiệm bị treo Terminal hoặc cần reset mạng làm lại từ đầu:

```bash
# 1. Dừng an toàn (Bấm Ctrl + C lần lượt trên các Terminal 4 -> 3 -> 2 -> 1)

# 2. Tiêu diệt toàn bộ tiến trình kẹt
sudo killall -9 containernet mn ryu-manager python3 iperf3 ping 2>/dev/null

# 3. Xóa toàn bộ các Docker container tạm do Mininet tạo ra
docker rm -f $(docker ps -a -q --filter "name=mn.") 2>/dev/null

# 4. Dọn sạch card mạng ảo veth và cấu hình Open vSwitch còn sót lại
sudo mn -c

# 5. Phục hồi trạng thái bình thường của Terminal (nếu chữ gõ bị ẩn)
stty sane && reset
```

---
*Tài liệu này được lưu trữ tại `controller/TESTING_AND_OVERHAUL_GUIDE.md` để phục vụ trực tiếp cho quá trình thực nghiệm và viết báo cáo Khóa Luận Tốt Nghiệp.*
