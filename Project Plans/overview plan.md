- Tên đề tài: Research on Traffic Engineering Optimization in Data Center Networks Based on Software-Defined Network and Artificial Intelligence
- Môi trường: Containernet (Cho mạng SDN trong Ubuntu Server 22.04 LTS)
- Ngôn ngữ lập trình: Python
- Controller: Ryu (OpenFlow 1.3)
- Switch: OpenVSwitch

### Phân Loại Flows (Elephant, Mice)

- ML Architecture: XGBoost or LightGBM.

# Xử lý

```
========================================================================================
[ TẦNG HỌC MÁY - ML Plane ]
(Có thể triển khai trên GPU Server độc lập)
    +--------------------------------------------------------------------------+
    |                               AI / ML Server                             |
    |--------------------------------------------------------------------------|
    | - Nhận diện luồng Voi/Chuột (XGBoost / LightGBM)                         |
    | - GAT: Trích xuất đặc trưng topology và sức khỏe mạng thành Graph.       |
    | - PPO: Tính toán tỷ lệ định tuyến đa đường (Traffic Matrix)              |
    +-----------+--------------------------------------------------+-----------+
                ^                                                  |
   (Nhận Data)  | REST / gRPC API                                  | REST / gRPC API
                |                                                  v (Gửi Action)
================|==================================================|====================
[ TẦNG QUẢN TRỊ - Management Plane ]                               |
    +-----------+--------------+                                   |
    |  Network Monitoring &    |                                   |
    |  Topology App            |                                   |
    |--------------------------|                                   |
    | - Dựng Graph (NetworkX)  |                                   |
    | - Giám sát sức khỏe mạng |                                   |
    | - Thu thập Telemetry     |                                   |
    |   (Port/Flow Stats, ... )|                                   |
    +-----------+--------------+                                   |
                ^                                                  |
  (Polling Data)| REST / gRPC API                                  |
================|==================================================|====================
[ TẦNG ĐIỀU KHIỂN - Control Plane ]                                |
    +-----------+--------------------------------------------------v-----------+
    |                              RYU CONTROLLER                              |
    |--------------------------------------------------------------------------|
    | - Đóng vai trò trung chuyển số liệu thống kê (Stats) lên Management Plane|
    | - Nhận quyết định từ ML Plane để dịch thành tập lệnh OpenFlow            |
    | - Đẩy luật OFPGroupMod (Mice) & OFPFlowMod (Elephant)                    |
    +------------------------------------^-------------------------------------+
                                         |
    				(Thu thập/Điều khiển)|   Giao thức OpenFlow 1.3
=========================================|==============================================
[ TẦNG DỮ LIỆU - Data Plane (Môi trường Containernet) ]
                                         |
                   +---------------------v---------------------+
                   |                                           |
+----------+       v        +-------------------------+        v       +----------+
|          |    +-----+     | ECMP Hash Engine (Switch|     +-----+    |          |
| Host SRC |--->| OVS |====>| phân tải Mice Flows)    |====>| OVS |--->| Host DST |
|          |    +--+--+     +-------------------------+     +--+--+    |          |
+----------+       |                                           ^       +----------+
                   | (Priority 1000 chặn luồng Voi)            |
                   v                                           |
          +-------------------+                       +--------+----------+
          | NFV_Proxy_Ingress |                       | NFV_Proxy_Exgress |
          |-------------------|                       |-------------------|
          | - Cắt gói (64KB)  |======================>| - Gom gói 64KB    |
          | - Rải theo tỷ lệ  | (Đa đường - Multipath)| - Sắp xếp lại TCP |
          +-------------------+                       +-------------------+
```

### Boostraping

- Khi các switch khởi động, các gói tin LLDP được gửi đến Controller và tổng hợp lại thành 1 sơ đồ mạng hoàn chỉnh.
- Sơ đồ mạng được nạp vào thư viện NetworkX. Tại đây sẽ tìm được `N` đường dẫn từ `Source` đến `Destination`.

### Lập trình ECMP - WCMP (Group Table) cho luồng xử lý Mice Flows

- Ryu Controller sẽ đẩy gói tin `OFPGroupMod` xuống các Switch nằm trong các đường đi được chọn. Bản tin này chứa các thông số:
  - Group ID: 1 (Đặt tên cho cỗ máy băm này là Nhóm số 1).
  - Group Type: SELECT. (Từ khóa cực kỳ quan trọng! SELECT ra lệnh cho chip phần cứng của Switch bật thuật toán Hash để chia tải, thay vì gửi nhân bản - Broadcast).
  - Buckets (Các xô hứng): Khai báo 3 cái "xô" tương ứng với 3 con đường mà NetworkX vừa tìm ra.
    - Bucket 1: Action = Gửi gói tin ra cổng 1.
    - Bucket 2: Action = Gửi gói tin ra cổng 2.
    - Bucket 3: Action = Gửi gói tin ra cổng 3.
    - Bucket `N`: Action = Gửi gói tin ra cổng `N`.

- Để đưa dữ liệu (Mouse Flows) vào cỗ máy băm trên, Ryu Controller đẩy tiếp một bản tin OFPFlowMod để tạo ra một Luật định tuyến (Flow Rule) trên Switch `Source`. Luật này đóng vai trò như một "cái phễu" khổng lồ hứng mọi thứ:
  - Match (Điều kiện khớp): Để trống hoặc cấu hình rất rộng (Ví dụ: Khớp mọi gói tin IPv4).
  - Priority (Độ ưu tiên): Đặt là 100 (Mức cơ bản, thấp).
  - Action (Hành động): Thay vì chỉ định xuất ra một cổng vật lý (Ví dụ: Output Port 1), Controller ra lệnh: Output sang Group 1.

- Lưu ý: ở mỗi Hop, gói tin sẽ được băm 1 lần nếu ở đó tồn tại ngã 3 có nhiều đường đi với chi phí bằng nhau để quyết định xem nó sẽ ra ở cổng nào

### Luồng xử lý Elephant Flows

- Đánh chặn (Traffic Steering): Ryu Controller lập tức ra tay chặn luồng TCP này lại. Nó tạo một lệnh OpenFlow đẩy xuống Switch Source: Ép luồng dữ liệu (Elephant Flows) vào `NFV_Proxy_Ingress`. Đồng thời Controller (hoặc AI Server) cho hệ thống GAT + PPO hoạt động.
  - Lưu ý nhỏ: `NFV_Proxy` trong đồ án là 1 container chạy bên cạnh các `Edge/Leaf Switch` như 1 Server riêng biệt (Băng thông tới Switch phải cao). Tuy nhiên trong thực tế có thể cải thiện chi phí bằng các cách sau:
    - Chạy Container trực tiếp trên hệ điều hành của Switch (White-box Switches) như các Switch của hãng Edgecore hay Mellanox không chạy hệ điều hành đóng kín. Chúng chạy một phiên bản Linux tinh chỉnh như SONiC (do Microsoft phát triển) hoặc Cumulus Linux.
    - Sử dụng Application Hosting trên các Switch có tích hợp Compute Node / DPU để chạy NFV_Proxy (Ví dụ: dòng Cisco Catalyst 9000 hoặc các switch tích hợp SmartNIC/DPU)
    - Lập trình chương trình Proxy trực tiếp vào Switch bằng ngôn ngữ P4.
- Tại Controller (hoặc AI Server):
  - GAT lấy thông tin toàn mạng và cho ra cái nhìn tổng quan về sức khỏe của toàn mạng.
  - PPO tính toán và chốt phương án có `N` đường để gửi gói tin. Lưu ý: PPO sẽ xuất ra ma trận tỷ lệ cho toàn bộ lộ trình nhằm phục vụ cho hệ thống mạng phức tạp và linh hoạt (Không riêng gì Spine-Leaf)
- Tại `NFV_Proxy_Ingress`, Gói tin lớn được chia thành nhiều gói tin nhỏ (64KB) và được rải để là các port để trả lại switch để điều phối tới `NFV_Proxy_Exgress`.
- Các gói tin tiếp theo của Luồng Voi đi vào Switch, khớp ngay với quy tắc Priority 1000. Switch không ném nó vào cỗ máy băm ECMP nữa, mà ngoan ngoãn đẩy thẳng nó ra cổng đi về phía Path 2 đúng như AI chỉ định.
- Tại `NFV_Proxy_Exgress`, Các gói tin nhỏ sẽ được gép lại và trả về Switch đích -> Host đích
- Lưu ý nhỏ: `NFV_Proxy_Ingress` và `NFV_Proxy_Exgress` 2 chức năng chạy trên 1 container được nối với từng Switch.

---

---

---

# **Đánh giá**

---

## 1. Độ chính xác của các Model AI

### 1.1. Khả năng phân loại luồng Voi/Chuột (XGBoost/LightGBM)

- **Mô tả:** Đánh giá độ chuẩn xác của mô hình học máy dạng cây trong việc phân tích các đặc trưng (features) trích xuất từ bản tin OpenFlow để gán nhãn luồng dữ liệu là Elephant (Voi) hay Mice (Chuột).
- **Ý nghĩa:** Phân loại đúng là tiền đề cốt lõi. Bỏ sót luồng Voi sẽ làm nghẽn mạng do tiếp tục đi vào đường ECMP mặc định; gán nhầm luồng Chuột thành Voi sẽ gây lãng phí tài nguyên cắt/ghép gói của NFV Proxy.
- **Phương pháp đánh giá:** Phân tích ma trận nhầm lẫn (Confusion Matrix) trên tập dữ liệu kiểm thử (Test set) đã được gán nhãn chuẩn (Ground truth).
- **Kịch bản đánh giá:** Trích xuất tập dữ liệu lưu lượng mạng (PCAP) chuẩn hoặc tự sinh bằng `iperf3` / `D-ITG` với phân bổ tỷ lệ 20% luồng Voi và 80% luồng Chuột. Đưa qua mô hình dự đoán và đối chiếu với nhãn thực tế.
- **Bộ thông số đánh giá:**
  - **Recall (Độ phủ):** Đạt ngưỡng **> 95%** (khẳng định mô hình hầu như không bỏ sót luồng Voi).
  - **Precision (Độ chuẩn xác):** Đạt ngưỡng **> 90%** (đảm bảo luồng chuyển hướng qua Proxy thực sự là luồng Voi).
  - **F1-Score:** Đạt ngưỡng **> 92%** (chứng minh tính cân bằng giữa Precision và Recall trên tập dữ liệu mất cân bằng).

### 1.2. Chất lượng học biểu diễn Topology (GAT)

- **Mô tả:** Khả năng của Graph Attention Network (GAT) trong việc nén trạng thái topo mạng (Switch, Link, băng thông khả dụng, độ trễ) thành các vector đặc trưng (Node Embeddings) mà không làm thất thoát thông tin không gian.
- **Ý nghĩa:** Cung cấp cho tác tử PPO phía sau "bức tranh" mạng lưới chuẩn xác nhất để đưa ra quyết định định tuyến tối ưu.
- **Phương pháp đánh giá:** Đo lường hàm mất mát (Loss function) trong chu trình huấn luyện tự giám sát (Self-supervised learning).
- **Kịch bản đánh giá:** Thay đổi liên tục topo mạng trong Mininet/Containernet (đánh sập link, bổ sung switch) và theo dõi biến thiên của các vector nhúng đầu ra.
- **Bộ thông số đánh giá:**
  - **Reconstruction Loss:** Đường cong Loss hội tụ tiệm cận về 0 và duy trì ổn định.
  - **Inference Time:** Đạt **< 2 ms** cho mỗi lần trích xuất đồ thị, đảm bảo tính thời gian thực.

### 1.3. Hiệu quả hội tụ của tác tử học tăng cường (PPO)

- **Mô tả:** Đánh giá quá trình học của thuật toán PPO trong việc xác định ma trận tỷ lệ định tuyến đa đường (Traffic Matrix) để phân bổ gói tin cắt nhỏ từ luồng Voi.
- **Ý nghĩa:** Chứng minh hệ thống AI thực sự học được chính sách tối ưu tài nguyên mạng qua cơ chế thử - sai thay vì lựa chọn ngẫu nhiên hay chia đều tải.
- **Phương pháp đánh giá:** Phân tích log huấn luyện thông qua công cụ trực quan hóa (TensorBoard).
- **Kịch bản đánh giá:** Khởi chạy PPO qua hàng ngàn episodes trong môi trường mô phỏng. Bơm các ma trận lưu lượng ngẫu nhiên và quan sát hành vi chia tải của Agent.
- **Bộ thông số đánh giá:**
  - **Cumulative Reward:** Đồ thị tăng trưởng rõ rệt ở các episode đầu và dao động biên độ nhỏ quanh ngưỡng hội tụ cao nhất ở các episode cuối.
  - **Policy Entropy (Kế thừa Shannon Entropy):** Giảm dần đều và duy trì ở một ngưỡng nhỏ lớn hơn 0 (khẳng định mô hình tự tin với quyết định định tuyến nhưng vẫn duy trì khả năng thăm dò, tránh Overfitting).

---

## 2. Tốc độ phản ứng của các Model

### 2.1. Độ trễ suy luận AI thuần túy (Inference Latency)

- **Mô tả:** Tổng thời gian phần cứng (CPU/GPU) tiêu tốn để tính toán đầu ra cho từng mô hình AI độc lập.
- **Ý nghĩa:** Suy luận chậm sẽ tạo nút thắt cổ chai, khiến quyết định can thiệp bị trễ khi trạng thái luồng mạng đã thay đổi.
- **Phương pháp đánh giá:** Đo thời gian thực thi mã nguồn Python (sử dụng thư viện `time` hoặc `timeit`) khi nạp dữ liệu qua mô hình.
- **Kịch bản đánh giá:** Thực thi vòng lặp 1.000 lần suy luận liên tục với `batch_size = 1` và `batch_size = 32` để lấy giá trị trung bình.
- **Bộ thông số đánh giá:**
  - **Classification Time (LightGBM/XGBoost):** Đạt **< 1 ms / luồng**.
  - **Routing Decision Time (GAT + PPO):** Đạt **< 10 ms / bản đồ mạng**.

### 2.2. Thời gian phản ứng toàn trình (End-to-End Control Loop)

- **Mô tả:** Thời gian thực tế tính từ lúc gói tin đầu tiên của luồng Voi chạm vào Switch nguồn đến khi luật OpenFlow ép luồng vào Proxy được cài đặt thành công.
- **Ý nghĩa:** Quyết định việc chặn bắt luồng Voi có kịp thời hay không; phản ứng chậm sẽ khiến lưu lượng lớn của luồng Voi tràn vào nhóm ECMP chung gây nghẽn.
- **Phương pháp đánh giá:** Đồng bộ đồng hồ hệ thống (NTP), bắt gói tin bằng Wireshark/tcpdump tại Controller và Switch để đo chênh lệch timestamp.
- **Kịch bản đánh giá:** Phát luồng TCP đột ngột bằng `iperf3`. Đo khoảng thời gian từ bản tin `Packet-In` đầu tiên đến bản tin `FlowMod` phản hồi từ Ryu.
- **Bộ thông số đánh giá:**
  - **Time-to-Steer:** Đạt **< 50 ms** (đủ ngắn để cửa sổ nghẽn `cwnd` của TCP kịp phản ứng trước khi gây tràn bộ đệm tại switch).

---

## 3. Sức khỏe hệ thống mạng

### 3.1. Thông lượng và Hiệu năng truyền tải

- **Mô tả:** Năng lực vận chuyển dữ liệu tối đa của mạng mà không phát sinh nghẽn, đã tính đến chi phí tiêu đề (overhead) của Proxy.
- **Ý nghĩa:** Khẳng định thuật toán định tuyến đa đường PPO vượt trội hơn các giải pháp tĩnh (Dijkstra, ECMP).
- **Phương pháp đánh giá:** Đo tốc độ truyền thực tế ở tầng ứng dụng bằng `iperf3` và giám sát bằng `bmon`.
- **Kịch bản đánh giá:** Thiết lập kịch bản All-to-All (các cặp host truyền tải chéo đồng thời) nhằm ép toàn bộ lưu lượng qua các liên kết lõi (Spine-Leaf bottleneck).
- **Bộ thông số đánh giá:**
  - **Achieved Bisection Bandwidth:** Đạt ngưỡng **> 85 - 90%** tổng băng thông vật lý lý thuyết của các liên kết thắt cổ chai cộng lại.
  - **Elephant Flow Goodput:** Đạt **> 80%** băng thông cấp phát (chênh lệch ~20% phản ánh chi phí gắn header phân mảnh tại Ingress Proxy).

### 3.2. Thời gian đáp ứng luồng (Timeliness)

- **Mô tả:** Thời gian hoàn thành truyền tải của từng luồng độc lập, đặc biệt tập trung vào nhóm luồng Chuột (Mice Flows).
- **Ý nghĩa:** Chứng minh mục tiêu cốt lõi: tách luồng Voi để giải phóng hàng đợi, nhường đường cho luồng Chuột.
- **Phương pháp đánh giá:** Ghi nhận thời gian từ bước bắt tay 3 bước (SYN) đến khi đóng kết nối (FIN) thông qua `tcpdump`.
- **Kịch bản đánh giá:** Truyền liên tục các tệp tin nhỏ (10 KB - 50 KB) đan xen với các luồng Voi dung lượng lớn (1 GB+), sau đó đo FCT của các tệp tin nhỏ.
- **Bộ thông số đánh giá:**
  - **Mice Flow FCT:** Giảm tối thiểu **30 - 50%** so với kịch bản chạy ECMP truyền thống không có AI can thiệp.
  - **Tail Latency (p99):** Độ trễ của 1% gói tin chậm nhất không vượt quá **3 - 4 lần** độ trễ trung bình.

### 3.3. Độ ổn định truyền dẫn

- **Mô tả:** Hiện tượng suy hao gói tin phát sinh từ tình trạng tràn hàng đợi vật lý tại các cổng chuyển mạch.
- **Ý nghĩa:** Kiểm tra xem thuật toán PPO có vô tình điều hướng quá tải dồn vào một liên kết cục bộ hay không.
- **Phương pháp đánh giá:** Trích xuất bộ đếm rớt gói (`rx_dropped`, `tx_dropped`) bằng lệnh `ovs-ofctl dump-ports`.
- **Kịch bản đánh giá:** Thực hiện bài đo áp lực (Stress Test) ở mức 100% công suất mạng trong 10 phút liên tục.
- **Bộ thông số đánh giá:**
  - **Packet Loss Rate:** Đạt ngưỡng **< 0.1%** trong môi trường trung tâm dữ liệu (lý tưởng đạt 0%).

---

## 4. Tính toàn vẹn thông tin

### 4.1. Bảo toàn thứ tự gói tin mức TCP

- **Mô tả:** Đánh giá mức độ xáo trộn trình tự gói tin 64 KB khi tới Egress Proxy do di chuyển qua các lộ trình mạng có độ trễ không đồng đều.
- **Ý nghĩa:** Giao thức TCP rất nhạy cảm với gói tin sai thứ tự; nếu không tái sắp xếp triệt để tại Egress Proxy, Host đích sẽ kích hoạt cơ chế giảm cửa sổ truyền vì hiểu nhầm mạng bị nghẽn.
- **Phương pháp đánh giá:** Phân tích luồng TCP tại Host đích bằng Wireshark với bộ lọc `tcp.analysis.out_of_order`.
- **Kịch bản đánh giá:** Bơm luồng Voi phân tán đa đường; sử dụng công cụ `tc` (Traffic Control) tạo độ trễ lệch pha có chủ đích giữa các nhánh (ví dụ: Path 1 trễ 5 ms, Path 2 trễ 20 ms).
- **Bộ thông số đánh giá:**
  - **Out-of-Order Packet Ratio tại đích:** Đạt mức **0%** (chứng minh Egress Proxy hoàn thành trọn vẹn việc đệm và tái hợp thứ tự).
  - **TCP Dup-ACKs / Fast Retransmit Count:** Bằng 0 hoặc ở mức không đáng kể (**< 0.01%** tổng số gói).

### 4.2. Tính toàn vẹn của Dữ liệu (Data Integrity)

- **Mô tả:** Xác minh tệp tin sau truyền dẫn không bị sai lệch hoặc rác payload do lỗi logic trong module cắt/ghép của Proxy Container.
- **Ý nghĩa:** Tốc độ truyền tải chỉ có ý nghĩa khi tính toàn vẹn của dữ liệu được đảm bảo tuyệt đối.
- **Phương pháp đánh giá:** Đối chiếu mã băm MD5 hoặc SHA-256 giữa tệp nguồn và tệp đích.
- **Kịch bản đánh giá:** Truyền tải một tệp nhị phân kích thước lớn (ví dụ: file ISO 1 GB) từ Host nguồn sang Host đích xuyên qua cụm Proxy.
- **Bộ thông số đánh giá:**
  - **File Hash Match:** Trùng khớp **100%** (tiêu chí bắt buộc, không có dung sai).

---

## 5. Mức độ thích ứng của hệ thống (Kịch bản khắc nghiệt)

### 5.1. Phản ứng với Link/Switch Failure

- **Mô tả:** Khả năng tự phục hồi (Self-healing) của hệ thống khi cấu trúc liên kết vật lý bị đứt gãy đột ngột.
- **Ý nghĩa:** Đánh giá tính sẵn sàng và khả năng ứng dụng thực tế trong trung tâm dữ liệu khi đối mặt sự cố phần cứng.
- **Phương pháp đánh giá:** Đo thời gian hệ thống khôi phục lại mức thông lượng bình thường sau sự cố.
- **Kịch bản đánh giá:** Khi đang truyền luồng Voi ở tải tối đa, thực thi lệnh Mininet `link s1 s2 down` để ngắt đột ngột một nhánh đường đang được PPO phân bổ lưu lượng.
- **Bộ thông số đánh giá:**
  - **Route Convergence Time:** Đạt **< 1 - 2 giây** (PPO nhận diện thay đổi topo qua GAT và cập nhật ma trận điều hướng mới).
  - **Data Loss during Failure:** Chỉ rớt các gói tin đang trên đường truyền (_in-flight_) tại thời điểm đứt; kết nối TCP tái lập tức thì và không bị ngắt quãng.

### 5.2. Khả năng chịu tải đột biến (Traffic Burst/Stress Test)

- **Mô tả:** Đánh giá phản ứng của hạ tầng khi xuất hiện các xung lưu lượng tăng vọt trong khoảng thời gian rất ngắn.
- **Ý nghĩa:** Kiểm tra nguy cơ sập mặt phẳng điều khiển (Control Plane) do bùng nổ bản tin `Packet-In`.
- **Phương pháp đánh giá:** Tạo đột biến lưu lượng cường độ cao, theo dõi độ biến thiên trễ (Jitter) và tải của Controller.
- **Kịch bản đánh giá:** Sử dụng `D-ITG` hoặc `tcpreplay` phát lại file PCAP chứa hàng chục ngàn kết nối TCP đồng thời (SYN Flood).
- **Bộ thông số đánh giá:**
  - **Jitter luồng Chuột:** Biến thiên không vượt quá **5 ms** so với điều kiện tải thông thường.
  - **Controller CPU Load:** Không xảy ra hiện tượng treo; luồng Chuột duy trì di chuyển qua ECMP bình thường mà không cần sự can thiệp thủ công từ Ryu.

### 5.3. Độ ổn định của chính sách (Policy Stability)

- **Mô tả:** Đo tần suất thuật toán thay đổi lộ trình liên tục (Route Flapping) cho cùng một luồng dữ liệu do metric đo kiểm mạng biến động nhỏ.
- **Ý nghĩa:** Đổi đường quá thường xuyên gây trễ sắp xếp gói, lãng phí tài nguyên CPU của switch và tăng nguy cơ nghẽn cục bộ.
- **Phương pháp đánh giá:** Ghi nhận số lượng bản tin `OFPFlowMod` được đẩy xuống switch cho cùng một định danh luồng Voi trong 1 phút.
- **Kịch bản đánh giá:** Duy trì 1 luồng Voi trong 5 phút dưới điều kiện lưu lượng nền (_background traffic_) dao động liên tục.
- **Bộ thông số đánh giá:**
  - **Route Flapping Frequency:** Đạt mức **< 2 - 3 lần / phút** (khẳng định chính sách PPO có tính lọc nhiễu tốt trước các dao động vi mô).

---

## 6. Mức độ tận dụng tài nguyên và Chi phí vận hành (Overhead)

### 6.1. Tài nguyên của NFV Proxy (Ingress/Egress Container)

- **Mô tả:** Tải tính toán (CPU) và dung lượng bộ nhớ cấp phát cho tiến trình container thực hiện cắt và ghép gói.
- **Ý nghĩa:** Đảm bảo giải pháp Proxy không biến thành điểm thắt cổ chai mới thay thế cho hạ tầng chuyển mạch.
- **Phương pháp đánh giá:** Giám sát liên tục qua `docker stats` hoặc tích hợp Prometheus kết hợp Grafana.
- **Kịch bản đánh giá:** Đo đạc tải của Proxy khi đẩy lưu lượng luồng Voi qua các mốc băng thông: 1 Gbps, 2 Gbps và 5 Gbps.
- **Bộ thông số đánh giá:**
  - **CPU Usage:** Tăng tuyến tính theo lưu lượng và không chạm ngưỡng bão hòa 100% core (hỗ trợ scale đa luồng).
  - **RAM / Reassembly Buffer:** Duy trì ổn định dưới **100 MB - 200 MB** (chứng minh bộ đệm tái hợp được giải phóng tuần tự, không bị rò rỉ bộ nhớ).
  - **Proxy Processing Latency:** Đạt **< 500 $\mu\text{s}$** cho mỗi tác vụ băm/cắt gói.

### 6.2. Tài nguyên của Switch (TCAM / Flow Table/RAM/CPU)

- **Mô tả:** Số lượng mục luật (Flow Entries) được cài đặt vào bộ nhớ phần cứng của Open vSwitch.
- **Ý nghĩa:** Đánh giá khả năng mở rộng (Scalability), do dung lượng bộ nhớ TCAM trên switch vật lý luôn bị giới hạn nghiêm ngặt.
- **Phương pháp đánh giá:** Trích xuất số lượng rule bằng lệnh `ovs-ofctl dump-flows`.
- **Kịch bản đánh giá:** Đồng thời thiết lập 10.000 luồng Mice và 100 luồng Elephant trong toàn mạng.
- **Bộ thông số đánh giá:**
  - **Flow Table Occupancy:** Duy trì **< 500 entries** (10.000 luồng Chuột được gom vào 1 luật Group Table chung; 100 luồng Voi tiêu tốn 100 - 200 luật cụ thể).
  - **RAM/CPU** chỉ để theo dõi sức khỏe.

### 6.3. Tải của mặt phẳng điều khiển và AI Server (Control & AI Plane Overhead)

- **Mô tả:** Băng thông tiêu hao trên kênh điều khiển quản trị (Southbound) và tải xử lý của Ryu Controller kèm máy chủ AI.
- **Ý nghĩa:** Bảo đảm kiến trúc tách rời Controller/AI không gây nghẽn đường truyền quản lý nội bộ.
- **Phương pháp đánh giá:** Đo băng thông trên interface điều khiển kết nối Controller với OVS; theo dõi tải GPU/CPU của AI Server.
- **Kịch bản đánh giá:** Rút ngắn chu kỳ truy vấn thống kê (Stats Polling) của Ryu xuống **1 giây / lần** trên quy mô topo 50 switch.
- **Bộ thông số đánh giá:**
  - **Southbound Traffic Bandwidth:** Đạt **< 10 - 20 Mbps** (không chiếm dụng đáng kể kênh truyền điều khiển).
  - **AI Server GPU Utilization:** Giữ dưới mức **60 - 70%** ở điều kiện mạng bận nhất (đảm bảo biên dự phòng tài nguyên).

### 6.4. Tỉ lệ liên kết được sử dụng (Link Utilization)

- **Mô tả:** Tỷ lệ phần trăm băng thông thực tế truyền qua từng liên kết so với băng thông vật lý tối đa của liên kết đó.
- **Ý nghĩa:** Đánh giá khả năng rải đều tải trọng trên toàn bộ topo, tránh hiện tượng lệch tải giữa các tuyến truyền dẫn song song.
- **Phương pháp đánh giá:** Thu thập và phân tích dữ liệu băng thông thời gian thực tại toàn bộ các cổng chuyển mạch.
- **Kịch bản đánh giá:** Kích hoạt tải All-to-All để đẩy hệ thống đến trạng thái bão hòa đường truyền.
- **Bộ thông số đánh giá:**
  - **Link Utilization Balance:** Toàn bộ các liên kết lõi đạt **> 85 - 90%** dung lượng khả dụng với độ lệch chuẩn giữa các liên kết ở mức rất thấp.

---

## 7. Tiêu chí khác (Thiết yếu cho độ hoàn thiện)

### 7.1. Mức độ công bằng (Fairness)

- **Mô tả:** Khả năng chia sẻ tài nguyên băng thông bình đẳng giữa các luồng Voi chạy song song khi cùng cạnh tranh hạ tầng.
- **Ý nghĩa:** Ngăn chặn việc mô hình AI tối ưu tổng thông lượng bằng cách hy sinh hoặc bỏ đói (_starvation_) một số luồng cụ thể để ưu tiên cho luồng khác.
- **Phương pháp đánh giá:** Tính toán chỉ số công bằng Jain's Fairness Index dựa trên thông lượng thực tế thu được của từng luồng:

  $$
  \mathcal{J}(x_1, x_2, \dots, x_n) = \frac{\left( \sum_{i=1}^{n} x_i \right)^2}{n \cdot \sum_{i=1}^{n} x_i^2}
  $$

- **Kịch bản đánh giá:** Khởi chạy đồng thời 5 luồng Voi đi qua vùng mạng có tổng băng thông nhỏ hơn nhu cầu cực đại của cả 5 luồng, sau đó đo Throughput riêng biệt của từng luồng.
- **Bộ thông số đánh giá:**
  - **Jain's Fairness Index:** Đạt **> 0.9** (trên thang đo từ 0 đến 1, chứng tỏ các luồng Voi đều được phân chia tài nguyên tương xứng).

### 7.2. Khả năng hạ cấp mềm (Graceful Degradation)

- **Mô tả:** Cơ chế đảm bảo mạng lưới duy trì vận hành ổn định khi cụm AI hoặc Controller gặp sự cố gián đoạn (Fail-safe mechanism).
- **Ý nghĩa:** Tiêu chuẩn bắt buộc cho môi trường viễn thông và trung tâm dữ liệu doanh nghiệp; sự cố ở hệ thống tối ưu không được phép gây tê liệt toàn bộ hạ tầng mạng.
- **Phương pháp đánh giá:** Kiểm tra sự kích hoạt của các luật dự phòng (Fallback Rules) và lưu lượng thực tế khi ngắt kết nối điều khiển.
- **Kịch bản đánh giá:** Trong lúc lưu lượng đang truyền tải cao, chủ động ngắt tiến trình AI Server hoặc tắt Container Proxy.
- **Bộ thông số đánh giá:**
  - **Fallback Throughput / Luồng gói tin:** Lưu lượng tự động chuyển về xử lý theo luật Priority 100 (Group Table ECMP). Băng thông luồng Voi có thể suy giảm do chia sẻ đường chung với luồng Chuột, nhưng kết nối mạng được duy trì liên tục và tỷ lệ thời gian chết bằng 0 (**Downtime = 0**).

---

# **Kịch Bản Kiểm Chứng Trạng Thái Mạng**

## Bảng Tổng Hợp Các Kịch Bản Kiểm Thử

| Kịch bản                     |    Mức độ ưu tiên    | Trọng tâm kiểm thử                           |     Tải mạng     | Tiêu chí cốt lõi                                   |
| :--------------------------- | :------------------: | :------------------------------------------- | :--------------: | :------------------------------------------------- |
| **1. Saturation & Noise**    | Ưu tiên 1 (Cốt lõi)  | Chia tải đa đường & Lọc nhiễu                |    80% – 100%    | Bisection BW > 85-90%, Route Flapping < 3 lần/phút |
| **2. Baseline & Data Shift** | Ưu tiên 2 (Nền tảng) | Độ bền phân loại ML & FCT luồng chuột        |    30% – 50%     | F1-score > 92%, Inference Latency < 1ms            |
| **3. Link/Node Failures**    | Ưu tiên 3 (Sẵn sàng) | Hội tụ topo & Cơ chế Graceful Fallback       |  100% đơn luồng  | Convergence < 2s, Downtime Proxy = 0               |
| **4. TCP Incast**            | Ưu tiên 4 (Vòng lặp) | Trễ phản hồi điều khiển (Time-to-Steer)      | Đột biến cực hạn | Time-to-Steer < 50ms, Packet Loss < 0.1%           |
| **5. Scalability Test**      | Ưu tiên 5 (Mở rộng)  | Khả năng mở rộng topo Fat-Tree ($k=4 \to 8$) |     Nền nhẹ      | Southbound < 20 Mbps, GAT Latency < 10ms           |

---

## Kịch Bản 1: Stress (gây bão hòa) Mạng Toàn Cục Kết Hợp Nhiễu Loạn Vi Mô (Saturation & Noise)

> **Mục tiêu:** Bài test tra tấn ép tải toàn hệ thống, chứng minh thuật toán Traffic Engineering (PPO + GAT) vượt trội hơn ECMP tĩnh và không bị đánh lừa bởi nhiễu tức thời.

### 1. Mô tả kịch bản

- Toàn bộ Host trong Containernet truyền tải chéo lẫn nhau (All-to-All), chiếm dụng từ 80% đến 100% tổng băng thông Bisection.
- Bơm đồng thời các luồng gói tin rác (UDP/ICMP background noise) với cường độ biến thiên hình sin vào các liên kết ngẫu nhiên để mô phỏng tình trạng dung lượng khả dụng liên tục biến động.

### 2. Ý nghĩa thực nghiệm

- Chứng minh khả năng chia tải đa đường tối ưu dung lượng toàn mạng.
- Kiểm chứng tính ổn định của chính sách PPO: không sinh hiện tượng đảo đường liên tục (Route Flapping) làm xáo trộn thứ tự gói tin TCP khi gặp biến động vi mô.

### 3. Quy trình thực hiện

1. Thực thi bash script kích hoạt đồng loạt toàn bộ Host gửi dữ liệu dung lượng lớn qua lại (All-to-All).
2. Chạy tiến trình nền phát sinh tải UDP ngẫu nhiên với biên độ hình sin trực tiếp vào các Switch lõi (Core Switches).
3. Theo dõi tài nguyên hệ thống tại `NFV_Proxy_Ingress` và `NFV_Proxy_Egress`.
4. Đếm tần suất bản tin `OFPFlowMod` từ Ryu Controller gửi xuống OpenFlow Switches.

### 4. Công cụ sử dụng

- **Sinh tải Elephant:** `iperf3`, `D-ITG`.
- **Sinh nhiễu (Noise):** `tcpreplay`, `hping3`, `Ostinato`.
- **Giám sát băng thông Switch:** `bmon`, `iftop`, `vnStat`.
- **Giám sát tài nguyên Proxy:** `docker stats`, `htop`, `cAdvisor`.

### 5. Tiêu chuẩn đánh giá (KPIs)

- **Achieved Bisection Bandwidth:** Đạt > 85% – 90% dung lượng lý thuyết.
- **Jain's Fairness Index:** Đạt > 0.9 giữa các luồng Elephant.
- **Route Flapping Frequency:** < 2 – 3 lần/phút.
- **Tài nguyên Proxy Container:** CPU không chạm trần 100%, RAM duy trì bộ đệm (Buffer) ổn định < 200MB.

---

## Kịch Bản 2: Vận Hành Tiêu Chuẩn và Biến Thiên Đặc Tính Tải (Baseline & Data Shift) (Biến thiên tỉ lệ Elephant/Mice Flows.

> **Mục tiêu:** Thiết lập mốc đối chuẩn (Benchmarking), đánh giá độ bền vững của mô hình phân loại luồng ML và đảm bảo Control Plane/AI Plane không gây overhead quá mức.

### 1. Mô tả kịch bản

- Mạng vận hành ở mức tải an toàn (30% – 50%).
- Đưa vào kiểm thử 3 kịch bản lưu lượng (Traffic Profiles) với biến thiên tỷ lệ luồng:
  - **Profile A:** 10% Elephant / 90% Mice.
  - **Profile B:** 20% Elephant / 80% Mice (Tiêu chuẩn cân bằng).
  - **Profile C:** 60% Elephant / 40% Mice (Đột biến luồng lớn).

### 2. Ý nghĩa thực nghiệm

- Đo lường độ trễ suy luận (Inference Latency) của bộ phân loại XGBoost/LightGBM.
- Đánh giá tính khái quát hóa của mô hình: đảm bảo mô hình không học vẹt phân phối tĩnh và duy trì độ chính xác cao khi phân phối luồng thay đổi đột ngột.

### 3. Quy trình thực hiện

1. Chạy lần lượt từng Profile lưu lượng trong thời gian tối thiểu 10 phút.
2. Ghi log nhãn dự đoán của mô hình ML và đối chiếu với nhãn thực tế (Ground Truth).
3. Bắt gói tin, bóc tách mốc thời gian bắt tay (`SYN`) và kết thúc (`FIN`) để tính thời gian hoàn thành (FCT) của các luồng Web/HTTP nhỏ.

### 4. Công cụ sử dụng

- **Sinh luồng Mice (Web Traffic):** `wrk`, `Apache JMeter`, `ab` (Apache Benchmark).
- **Sinh luồng Elephant:** `iperf3`.
- **Bắt gói & Tính trễ luồng:** `Wireshark`, `tcpdump`, `tshark`.
- **Đánh giá ML:** `scikit-learn metrics` (Confusion Matrix, Classification Report), `TensorBoard`.

### 5. Tiêu chuẩn đánh giá (KPIs)

- **F1-Score (ML Classification):** > 92% đồng đều trên cả 3 Profile.
- **Inference Latency:** < 1ms/luồng.
- **Mice Flow FCT:** Tương đương hoặc thấp hơn so với khi định tuyến bằng ECMP truyền thống.

---

## Kịch Bản 3: Phản Ứng Với Sự Cố Mạng Cục Bộ (Link/Node Failures)

> **Mục tiêu:** Xác thực độ sẵn sàng trong môi trường trung tâm dữ liệu thực tế: kiểm tra năng lực tái hội tụ của GAT và tính năng tự động dự phòng (Graceful Degradation).

### 1. Mô tả kịch bản

- Ngắt đột ngột liên kết vật lý/logic (Link Down) ngay trên đường truyền chính của luồng Elephant.
- Tắt đột ngột (`docker stop` hoặc `kill -9`) tiến trình AI Server hoặc NFV Proxy khi hệ thống đang vận hành bình thường.

### 2. Ý nghĩa thực nghiệm

- Kiểm chứng cơ chế tự nhận biết biến động topo qua biểu diễn đồ thị GAT để tái định tuyến.
- Chứng minh hệ thống không bị gián đoạn toàn diện khi mất tầng AI/Proxy: lưu lượng tự rơi về quy tắc OpenFlow mặc định (Default Fail-open).

### 3. Quy trình thực hiện

1. Khởi tạo 01 luồng Elephant bão hòa 100% băng thông của một tuyến đường cố định.
2. Dùng CLI can thiệp hạ (down) một link trung gian trên tuyến đang truyền.
3. Thử nghiệm phụ: Tắt ngang container NFV Proxy; theo dõi xem luồng Elephant có tự động rơi xuống bảng luật mặc định (Priority 100) để truyền như luồng Mice thông thường hay không.

### 4. Công cụ sử dụng

- **Giả lập sự cố:** Mininet CLI (`link <sX> <sY> down`), Docker CLI (`docker stop <container_id>`).
- **Đo gián đoạn mạng:** `ping`, `mtr`, `tcpdump`, `Wireshark`.

### 5. Tiêu chuẩn đánh giá (KPIs)

- **Route Convergence Time:** < 1 – 2 giây (PPO thiết lập và đẩy đường mới thành công).
- **TCP Out-of-Order / Dup-ACKs:** Thống kê và kiểm soát số gói sai thứ tự phát sinh khi chuyển mạch.
- **Downtime khi sập Proxy:** Bằng 0 (Mạng duy trì thông suốt, chuyển sang chế độ chuyển tiếp cơ bản).

---

## Kịch Bản 4: Tải Đột Biến Cục Bộ (TCP Incast / Traffic Spikes)

> **Mục tiêu:** Đánh giá tốc độ phản hồi toàn trình (Closed-Loop Control) trước hiện tượng nghẽn cổ chai micro-burst trong thời gian cực ngắn tại một switch đích.

### 1. Mô tả kịch bản

- Hàng chục Host nguồn đồng loạt trút lưu lượng Elephant cực lớn về duy nhất 01 Host/Server đích trong thời gian từ 2 đến 3 giây.
- Mô phỏng mô hình giao tiếp phân tán dạng MapReduce/Hadoop Shuffle phase.

### 2. Ý nghĩa thực nghiệm

- Đo đạc thời gian từ lúc gói tin đầu tiên phát sinh (`Packet-In`) cho đến khi Controller và AI tính toán xong để đẩy rule (`FlowMod`) xuống Switch chuyển hướng luồng vào Proxy.
- Đảm bảo hàng đợi Switch không bị tràn làm drop hàng loạt gói tin của luồng Mice chạy song song.

### 3. Quy trình thực hiện

1. Thiết lập kịch bản shell điều khiển nhiều client gọi `iperf3` đổ dồn tải về 1 IP đích duy nhất.
2. Cho các luồng Mice (gói ICMP/HTTP nhỏ) liên tục đi xuyên qua Switch lõi chịu tải Incast để ghi nhận biến động Jitter.
3. Đọc số liệu bộ đệm cổng Switch trước và sau đợt Incast.

### 4. Công cụ sử dụng

- **Phát sinh Incast:** Bash script kích hoạt đa luồng `iperf3` song song.
- **Giám sát rớt gói tại Switch:** `ovs-ofctl dump-ports <switch_name>` (bóc tách trường `rx_dropped`, `tx_dropped`).
- **Tính trễ vòng điều khiển:** `tcpdump`, `Wireshark` (đo độ lệch timestamp giữa `Packet-In` và `FlowMod`).

### 5. Tiêu chuẩn đánh giá (KPIs)

- **Time-to-Steer (End-to-End Control Loop):** < 50ms (đủ nhanh trước khi cửa sổ TCP nghẽn).
- **Packet Loss Rate tại Switch:** < 0.1%.
- **Tail Latency của luồng Mice (p99 Jitter):** Không tăng quá 3 – 4 lần so với mức nền ở Kịch bản 2.

---

## Kịch Bản 5: Kiểm Thử Quy Mô Topology (Scalability Test)

> **Mục tiêu:** Chứng minh năng lực tính toán của mạng GAT và sức chịu tải của kênh điều khiển Southbound khi mở rộng quy mô trung tâm dữ liệu.

### 1. Mô tả kịch bản

- Mở rộng mạng từ mô hình nhỏ (Spine-Leaf cơ bản) sang topo dạng Fat-Tree tiêu chuẩn:
  - **Cấu hình 1:** Fat-Tree $k=4$ (Quy mô 20 Switch).
  - **Cấu hình 2:** Fat-Tree $k=8$ (Quy mô 80 Switch).
- Duy trì mức tải nền phân bố đều trên toàn bộ hạ tầng mới.

### 2. Ý nghĩa thực nghiệm

- Chứng minh khả năng xử lý biểu diễn không gian của GAT với đồ thị lớn.
- Xác nhận Controller không bị quá tải CPU/RAM và kênh điều khiển Southbound không bị bão hòa khi số lượng bản tin trạng thái gửi về tăng theo cấp số nhân.

### 3. Quy trình thực hiện

1. Xây dựng script Python sử dụng Mininet API để tự động khởi tạo cấu trúc topo Fat-Tree $k=8$.
2. Áp dụng lưu lượng nền phân tán nhẹ trên toàn mạng.
3. Giám sát lưu lượng trao đổi trên giao diện mạng ảo (veth/loopback) kết nối giữa Controller và toàn bộ OVS.
4. Đo lường thời gian trích xuất và tính toán ma trận kề/đặc trưng node của mô hình GAT.

### 4. Công cụ sử dụng

- **Khởi tạo quy mô mạng:** Python Mininet API / Containernet Topology Engine.
- **Đo băng thông Southbound Interface:** `iftop`, `vnStat` (gắn trên card mạng giao tiếp OpenFlow).
- **Giám sát phần cứng AI Server:** `nvidia-smi` (nếu dùng GPU), `htop`.

### 5. Tiêu chuẩn đánh giá (KPIs)

- **Southbound Traffic Bandwidth:** < 20 Mbps (không gây nghẽn kênh điều khiển).
- **Tài nguyên AI Server:** Mức sử dụng duy trì dưới 60% – 70% (đảm bảo headroom mở rộng).
- **GAT Inference Time:** Giữ ở mức < 10ms ngay cả khi số lượng nút Switch tăng gấp 4 lần.
