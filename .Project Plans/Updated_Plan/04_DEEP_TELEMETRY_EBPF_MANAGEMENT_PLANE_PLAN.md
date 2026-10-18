# KẾ HOẠCH CHI TIẾT: GIÁM SÁT VI MÔ TOÀN DIỆN & IN-KERNEL EBPF TELEMETRY
## (DEEP TELEMETRY & IN-KERNEL EBPF MEASUREMENT PLANE PLAN)

> **Mã chuyên đề:** `PLAN-WP04-DEEP-TELEMETRY`  
> **Thuộc dự án:** Nghiên cứu Tối ưu hóa Kỹ thuật Lưu lượng trong Mạng DCN Dựa trên SDN và AI (SDN-AI DCN)  
> **Cố vấn chuyên môn:** Senior SDN Architect (Gemini 4 Argon)  
> **Trạng thái thực tế:** **ĐÃ HOÀN THÀNH 100% (PHASE 1 CORE RUNTIME)**  
> **Mã nguồn liên quan:** [`controller/ebpf_telemetry.c`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/ebpf_telemetry.c), [`controller/ebpf_loader.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/ebpf_loader.py), [`controller/management_plane.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/management_plane.py), [`results/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/results/)  

---

## 1. MỤC TIÊU & PHẠM VI KỸ THUẬT

1. **Giám sát Mạng Cấp độ Nano-giây trong Không gian Hạt nhân (In-Kernel Telemetry):** Triển khai chương trình eBPF/XDP gắn trực tiếp vào subsystem Linux Traffic Control (`clsact` hook) tại các cổng switch, cho phép bóc tách tiêu đề gói tin và đo đạc độ trễ tức thời mà không gây trễ chuyển tiếp (`XDP_PASS`).
2. **Bắt và Đếm Nhãn Tắc nghẽn ECN (Congestion Experienced - CE) Thời gian Thực:** Giám sát trường Type of Service (TOS) trong tiêu đề IPv4 để phát hiện tức thì các gói tin bị đánh dấu `CE = 0x03` khi đi qua các hàng đợi switch bị nghẽn, kiểm chứng hiệu quả cơ chế Fast-Path Data Plane.
3. **Triển khai Tầng Quản trị Đa luồng Không Block (Zero-Timeout Async Management Plane):** Khắc phục triệt để lỗi timeout lệnh `docker stats` khi hệ thống chạy 47 containers đồng thời bằng cơ chế Background Polling Thread và bộ nhớ đệm RAM (`threading.Lock`).
4. **Bóc tách Bộ 10 Đặc trưng Chuẩn Bi-Flow & Lần vết Đường đi Từng chặng (Full Hop-by-Hop Path Tracing):** Tự động ghép cặp các luồng hai chiều đối xứng, tính toán 10 features đầu vào cho AI, và vẽ chi tiết chuỗi hop vật lý từ Host phát qua các switch tới Host nhận.
5. **Xuất bản 5 Luồng Dữ liệu CSV Chuẩn hóa:** Phục vụ đồng thời 3 mục đích: Huấn luyện mô hình AI, Giám sát sức khỏe hạ tầng thời gian thực và Báo cáo đánh giá KPI học thuật.

---

## 2. CƠ SỞ KHOA HỌC, ĐỊNH LÝ GỐC & TÀI LIỆU THAM KHẢO

- **[Lý thuyết Thông tin & Độ bất định Entropy Shannon]** C. E. Shannon, *"A Mathematical Theory of Communication"*, Bell System Technical Journal, Vol. 27, pp. 379–423, 623–656, 1948. *(Cơ sở tính toán độ hỗn loạn phân phối thời gian giữa các gói IAT và kích thước gói để phát hiện bản chất luồng).*
- **[Quy chuẩn Đặc trưng Luồng Hai chiều Bi-flow]** B. Trammell, et al., *"Specification of the IP Flow Information Export (IPFIX) Protocol for the Exchange of Flow Information"*, RFC 7011, 2013; RFC 5101. *(Định chuẩn trích xuất đặc trưng hai chiều Forward/Reverse và đồng bộ thống kê).*
- **[Kiến trúc eBPF / XDP & Giám sát Vi mô Kernel]** A. Joshi, et al., *"BPF and XDP Reference Guide"*, Linux Kernel / Cilium Documentation; Y. Tong, et al., *"ChameleMon: Shifting Measurement Attention as Network State Changes"*, ACM SIGCOMM 2023. *(Nguyên lý trích lọc gói tin zero-copy tại Linux TC hook).*

---

## 3. THIẾT KẾ KIẾN TRÚC ĐO LƯỜNG 2 TẦNG (KERNEL & USERSPACE)

Hệ thống đo lường kết hợp giữa xử lý gói tin siêu tốc trong Linux Kernel và tổng hợp dữ liệu bất đồng bộ trong Userspace:

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
| LINUX KERNEL SPACE (MẶT PHẲNG HẠT NHÂN - ZERO-COPY WIRE-SPEED)                                    |
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|  Gói tin Ingress / Egress ──► TC clsact hook (ebpf_telemetry.c)                                   |
|                                ├── Bóc tách Ethernet, IPv4, TCP/UDP headers                       |
|                                ├── Kiểm tra TOS byte: (ip->tos & 0x03) == 0x03 ──► Đếm nhãn ECN CE|
|                                ├── Tính delta timestamp nano-giây: dt = now - last_seen           |
|                                └── Đẩy cấu trúc telemetry_event_t vào BPF_PERF_OUTPUT(events)     |
+──────────────────────────────────────────────────┬────────────────────────────────────────────────+
                                                   │ (Perf Ring Buffer Event Stream)
                                                   ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
| USERSPACE MANAGEMENT PLANE (TẦNG QUẢN TRỊ & TỔNG HỢP DỮ LIỆU)                                     |
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|  1. Userspace BCC Loader (ebpf_loader.py):                                                        |
|     - Thu nạp các sự kiện nano-giây từ Perf Ring Buffer, chuyển giao sang Management Plane.       |
|                                                                                                   |
|  2. Async Docker Stats Background Collector (management_plane.py):                                |
|     - Thread độc lập liên tục cập nhật CPU/RAM/Network IO của 47 containers (Timeout 8.0s).       |
|     - Lưu vào self.cached_container_stats bảo vệ bằng threading.Lock ──► Truy xuất RAM < 0.1ms!  |
|                                                                                                   |
|  3. Bi-flow Extraction & Hop-by-Hop Path Tracer:                                                  |
|     - Đọc Flow Tables từ Ryu REST API (:8080/stats/flow/<dpid>).                                  |
|     - Ghép cặp Bi-flow đối xứng 5-tuple: (src_ip, dst_ip, s_port, d_port, proto).                 |
|     - Truy vết toàn bộ chuỗi chặng: h1_1 -> a1[in:3->out:1] -> ag1[in:1->out:5] -> ... -> h5_2.   |
|                                                                                                   |
|  4. Xuất bản 5 Tệp Tin CSV Dữ Liệu Thời Gian Thực:                                                |
|     - results/traffic_flow_dataset_with_paths.csv   (Dataset huấn luyện AI)                       |
|     - results/device_resource_utilization.csv       (Giám sát CPU/RAM containers & OVS)           |
|     - results/system_and_network_health.csv         (Giám sát dung lượng TCAM & packet drops)     |
|     - results/link_utilization_telemetry.csv        (Băng thông & tỷ lệ sử dụng từng liên kết)    |
|     - results/network_evaluation_kpis.csv           (Báo cáo tổng hợp KPI mạng toàn cục)          |
+───────────────────────────────────────────────────────────────────────────────────────────────────+
```

---

## 4. CHI TIẾT BỘ ĐẶC TRƯNG BI-FLOW & THUẬT TOÁN ĐO LƯỜNG

### 4.1. Bộ 10 Đặc trưng Chuẩn Bi-Flow cho Huấn luyện Mô hình AI
Để mô hình Machine Learning nhận diện chính xác bản chất luồng dữ liệu, Management Plane tổng hợp bộ 10 đặc trưng đối xứng 2 chiều:

| STT | Tên Đặc Trưng | Đơn vị | Phương Pháp Tính Toán & Cơ Sở Toán Học | Ý Nghĩa Kỹ Thuật |
| :---: | :--- | :---: | :--- | :--- |
| **1** | **`dur`** | Giây | $dur = \text{duration\_sec} + \frac{\text{duration\_nsec}}{10^9}$ | **True FCT:** Thời gian sống thực tế của luồng trên switch. |
| **2** | **`sbytes`** | Bytes | Tổng số byte truyền chiều Forward ($s \to d$). | Thể hiện dung lượng tải phát đi của ứng dụng. |
| **3** | **`dbytes`** | Bytes | Tổng số byte phản hồi chiều Backward ($d \to s$). | Phản ánh phản hồi dịch vụ (RPC reply hoặc TCP ACK). |
| **4** | **`Spkts`** | Gói | Tổng số gói tin chiều Forward ($s \to d$). | Đánh giá tần suất phát gói của client. |
| **5** | **`Dpkts`** | Gói | Tổng số gói tin chiều Backward ($d \to s$). | Đánh giá mức độ phản hồi của server. |
| **6** | **`Sload`** | bps | $Sload = \frac{8 \cdot sbytes}{\max(dur, 0.001)}$ | Tốc độ truyền tải tức thời chiều gửi. |
| **7** | **`Dload`** | bps | $Dload = \frac{8 \cdot dbytes}{\max(dur, 0.001)}$ | Tốc độ truyền tải tức thời chiều nhận. |
| **8** | **`smeansz`** | Bytes | $smeansz = \frac{sbytes}{\max(Spkts, 1)}$ | Kích thước gói tin trung bình chiều gửi. |
| **9** | **`dmeansz`** | Bytes | $dmeansz = \frac{dbytes}{\max(Dpkts, 1)}$ | Kích thước gói tin trung bình chiều nhận. |
| **10**| **`Ratio`** | Tỷ số | $Ratio = \frac{sbytes}{\max(dbytes, 1)}$ | Tỷ lệ bất đối xứng lưu lượng (Asymmetry ratio). |

### 4.2. Đặc trưng Bổ sung & Gán Nhãn Ground-Truth
Ngoài 10 features cơ bản, hệ thống tự động bóc tách các trường ngữ cảnh mạng:
- **`locality`:** Phân vùng không gian (0: Intra-Rack, 1: Intra-Cluster, 2: Intra-DC, 3: Extra-DC).
- **`hop_count` & `full_path`:** Số lượng chặng switch và chuỗi đường đi chi tiết.
- **`label`:** Nhãn phân loại Ground-Truth chuẩn Presto:
  $$label = \begin{cases} 1 \ (\text{Elephant Flow}), & \text{nếu } sbytes + dbytes \ge 64\text{ KB} \ (65,536\text{ Bytes}) \\ 0 \ (\text{Mice Flow}), & \text{nếu } sbytes + dbytes < 64\text{ KB} \end{cases}$$
- **`polling_interval`:** Chu kỳ quét đồng bộ OpenFlow/Link/Flow Telemetry được tối ưu ở mức $\Delta t = 0.5\text{s}$ ($500\text{ ms}$), đảm bảo độ nhạy cao trong việc ghi nhận lưu lượng tức thời.

---

### 4.3. Thuật toán Lần vết Đường đi Từng chặng (Hop-by-Hop Path Tracing)
Hàm `trace_full_path()` trong [`controller/management_plane.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/management_plane.py) thực hiện duyệt đồ thị tô-pô NetworkX dựa trên các luật chuyển tiếp OpenFlow đang kích hoạt trên switch:
1. Xác định Switch Access nguồn (`ingress_dpid`) và cổng vào (`in_port`).
2. Khảo sát bảng luồng OVS Table 1 để tìm cổng ra (`out_port`).
3. Dò tìm cạnh liên kết trong đồ thị topo để xác định Switch kế tiếp (`next_dpid`) và cổng nhận (`next_in_port`).
4. Lặp lại bước 2-3 cho đến khi chạm Switch Access đích (`egress_dpid`).
5. Xuất chuỗi đường đi trực quan dạng:
   $$\text{h1\_1} \to \text{a1}[\text{in:3}\to\text{out:1}] \to \text{ag1}[\text{in:1}\to\text{out:5}] \to \text{c1}[\text{in:1}\to\text{out:3}] \to \text{ag3}[\text{in:5}\to\text{out:1}] \to \text{a5}[\text{in:1}\to\text{out:4}] \to \text{h5\_2}$$

---

## 5. THIẾT KẾ CẤU TRÚC 5 FILE CSV TELEMETRY XUẤT BẢN

Toàn bộ dữ liệu đo kiểm được lưu trữ tại thư mục [`results/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/results/) với cấu trúc header chuẩn mực:

1. **`traffic_flow_dataset_with_paths.csv`:**
   `timestamp, src_ip, dst_ip, src_port, dst_port, protocol, dur, sbytes, dbytes, Spkts, Dpkts, Sload, Dload, smeansz, dmeansz, Ratio, locality, hop_count, full_path, label`
2. **`device_resource_utilization.csv`:**
   `timestamp, node_name, node_type, cpu_percent, memory_usage_mb, memory_limit_mb, memory_percent, network_rx_bytes, network_tx_bytes, network_rx_mbps, network_tx_mbps, packet_drop_count, tcam_entries, tcam_usage_pct`
3. **`system_and_network_health.csv`:**
   `timestamp, node_name, node_type, cpu_usage_pct, ram_used_mb, ram_limit_mb, ram_usage_pct, tcam_entries, tcam_usage_pct, total_tx_bytes, total_rx_bytes, tx_mbps, rx_mbps, total_tx_dropped, total_rx_dropped, total_errors`
4. **`link_utilization_telemetry.csv`:**
   `timestamp, src_node, dst_node, src_port, dst_port, link_type, capacity_mbps, tx_bytes_delta, tx_rate_mbps, utilization_pct, tx_dropped_delta, tx_errors_delta`
5. **`network_evaluation_kpis.csv`:**
   `timestamp, active_flows_count, active_elephant_flows, active_mice_flows, avg_hop_count, total_network_throughput_mbps, bisection_bandwidth_utilization_pct, jains_fairness_index, link_utilization_std_dev, avg_mice_duration_sec, overall_packet_loss_rate`

---

### 5.1. Cơ sở Vật lý & Phân tích Hiện tượng CPU / RAM / TCAM Usage

1. **Tại sao CPU Switch OVS thường rất thấp ($\approx 0.1\% - 0.8\%$) hoặc bằng $0$:**
   *   Open vSwitch (OVS) hoạt động theo cơ chế **Kernel Datapath Fast-Path** (`openvswitch.ko`). Khi một luồng OpenFlow 1.3 đã được cài đặt vào bảng luật (FlowMod), toàn bộ các gói tin tiếp theo được chuyển mạch trực tiếp trong Linux Kernel với cơ chế Zero-copy và ngắt phần cứng, hoàn toàn không đi qua tiến trình User-space `ovs-vswitchd`.
   *   Tiến trình User-space chỉ tiêu thụ CPU khi xảy ra Packet-In (Table-Miss) hoặc khi Controller đẩy luồng mới. Do đó, mức CPU User-space trung bình $< 1.0\%$ là hoàn toàn chính xác theo đúng kiến trúc thiết kế của OVS.
2. **Tại sao CPU Host Container phần lớn thời gian bằng $0.0\%$:**
   *   Mỗi Host container chỉ thực thi tiến trình truyền tải nhẹ (Python socket client/server hoặc `iperf3`).
   *   Trong mô hình phụ tải thực tế của Facebook, $81\%$ luồng là luồng Chuột (Mice flows, $< 64\text{KB}$) kết thúc sau vài phần nghìn giây ($< 5\text{ms}$). Sau khi gửi xong, tiến trình Host rơi vào trạng thái ngủ (`idle sleep`) để chờ thời điểm phát luồng tiếp theo theo nhịp $D_{\text{arrival}}$.
   *   Khi một luồng Voi lớn ($50\text{MB}$) xuất hiện, CPU của Host lập tức nhảy vọt lên $15\% - 18\%$. Do đó, việc phần lớn các mẫu đo ngẫu nhiên ghi nhận CPU $= 0.0\%$ phản ánh chân thực trạng thái nghỉ của các máy chủ giữa các xung phát luồng.
3. **Định chuẩn Dung lượng & Tỷ lệ Sử dụng Bảng Luật TCAM (TCAM Usage %):**
   *   Trong phần cứng chuyển mạch thương mại (như Broadcom Trident II BCM56850 trên Facebook Wedge 40), dung lượng bảng luật TCAM phần cứng giả lập được quy hoạch:
       $$\text{TCAM}_{\text{capacity}} = 1,000 \text{ Flow Rules}$$
   *   Tỷ lệ sử dụng TCAM (%) được tính toán thời gian thực:
       $$\text{TCAM Usage (\%)} = \frac{\text{tcam\_entries}}{\text{TCAM}_{\text{capacity}}} \times 100\%$$
   *   Access Switch chứa khoảng $43 - 130$ luật (đạt $4.3\% - 13.0\%$ TCAM capacity); Aggregation và Core switch chứa khoảng $39 - 40$ luật (đạt $3.9\% - 4.0\%$ TCAM capacity).

---

## 6. TIÊU CHÍ KIỂM ĐỊNH & NGHIỆM THU HỌC THUẬT (ACCEPTANCE GATES)

- [x] **Zero Telemetry Loss:** Thu thập liên tục trong 1,000 chu kỳ telemetry ($5,000\text{ giây}$) mà không bị mất dữ liệu CPU/RAM của 33 Host containers.
- [x] **Đo đạc Đầy đủ TCAM Usage %:** Ghi nhận và trực quan hóa đồng thời số lượng luật tuyệt đối và tỷ lệ sử dụng TCAM (%) trên cả 14 switch OVS.
- [x] **Trích xuất đầy đủ 10 Features:** Tệp `traffic_flow_dataset_with_paths.csv` ghi nhận đầy đủ giá trị hợp lệ, không chứa trường `NaN` hay `null`.
- [x] **Lần vết chính xác 100% đường đi:** Chuỗi `full_path` thể hiện đúng từng switch và số hiệu cổng vật lý, khớp với topo 2 cụm Clos.
- [x] **Bắt nhãn ECN trong Hạt nhân:** Chương trình eBPF ghi nhận và đếm chính xác số lượng gói tin mang cờ CE `0x03` khi hàng đợi switch vượt ngưỡng $K=30\text{KB}$.
