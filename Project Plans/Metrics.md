# Phân Loại Các Thông Số Đánh Giá Thực Nghiệm (Experimental Evaluation Metrics)

Bộ chỉ số đo kiểm và giám sát trong môi trường thực nghiệm mạng SDN/NFV tích hợp AI được phân bổ thành 4 nhóm chức năng cốt lõi:

---

## 1. Hiệu Năng Tầng Mạng và Lưu Lượng (Network & Traffic Performance)

Nhóm chỉ số đánh giá chất lượng truyền tải tổng thể của hạ tầng chuyển mạch, sự thông thoáng của các liên kết và trải nghiệm truyền dẫn ứng dụng.

- **Thông lượng tổng thể và từng luồng (Throughput / Goodput):**
  - _Mô tả:_ Tổng lượng dữ liệu hữu ích thực tế truyền tải thành công qua mạng (tính bằng Mbps hoặc Gbps).
  - _Phương pháp đo:_ Đo kiểm trực tiếp qua công cụ `iperf3`, phân tích lưu lượng tại tầng Application sau khi đã trừ hao phí tiêu đề (overhead).
- **Độ trễ trung bình và độ trễ gói tin (Average Latency / RTT):**
  - _Mô tả:_ Thời gian gói tin di chuyển một chiều từ nguồn tới đích hoặc thời gian khứ hồi (Round Trip Time - RTT) tính bằng mili-giây (ms).
  - _Phương pháp đo:_ Giám sát định kỳ thông qua `ping` hoặc các bộ đo timestamp chuyên dụng trên socket TCP.
- **Độ trễ đuôi (Tail Latency - 90th, 99th, 99.9th percentile):**
  - _Mô tả:_ Độ trễ của các gói tin thuộc nhóm chậm nhất (10%, 1%, 0.1% tệ nhất), phản ánh tác động tiêu cực của nghẽn hàng đợi tức thời (_Microburst_) và xung đột tài nguyên.
  - _Ý nghĩa:_ Tiêu chí cốt lõi phản ánh độ ổn định biên của hệ thống phân tán.
- **Độ biến thiên trễ (Jitter):**
  - _Mô tả:_ Mức độ dao động thời gian đến giữa các gói tin liên tiếp trong cùng một luồng.
  - _Ý nghĩa:_ Quyết định độ mượt mà của các dịch vụ truyền thông tương tác thời gian thực (VoIP, Video Streaming).
- **Tỷ lệ mất gói (Packet Loss Rate):**
  - _Mô tả:_ Tỷ lệ phần trăm gói tin bị hủy bỏ do tràn bộ đệm hàng đợi (_Queue Overflow_) tại các cổng chuyển mạch (Switch ports).
  - _Phương pháp đo:_ Truy vấn trực tiếp bộ đếm phần cứng OpenFlow (`rx_dropped`, `tx_dropped`).
- **Thời gian hoàn thành luồng (Flow Completion Time - FCT):**
  - _Mô tả:_ Khoảng thời gian từ khi khởi tạo kết nối (SYN) đến khi đóng luồng thành công (FIN).
  - _Ý nghĩa:_ Đo đạc FCT cho luồng Chuột (Mice FCT) tại các phân vị **p50, p99, p99.9** để chứng minh luồng nhỏ không bị luồng lớn cản trở.
- **Hệ số công bằng băng thông (Jain's Fairness Index):**
  - _Mô tả:_ Chỉ số đánh giá mức độ công bằng trong việc chia sẻ tài nguyên băng thông giữa các luồng có cùng dung lượng và độ ưu tiên:
    $$
    \mathcal{J}(x_1, x_2, \dots, x_n) = \frac{\left( \sum_{i=1}^{n} x_i \right)^2}{n \cdot \sum_{i=1}^{n} x_i^2}
    $$
- **Tỷ lệ sử dụng liên kết (Link Utilization):**
  - _Mô tả:_ Mức độ phân bổ tải trọng trên các đường truyền song song trong mạng lõi.
  - _Phương pháp đo:_ Tính giá trị phần trăm sử dụng tối đa (_Max Link Utilization_) và độ lệch chuẩn tải giữa các liên kết để phát hiện điểm nóng nghẽn mạch (_Hotspot_).

---

## 2. Đảm Bảo Toàn Vẹn Giao Thức TCP và Tầng Biên (TCP Integrity & Edge Metrics)

Nhóm chỉ số đánh giá tác động của kỹ thuật cắt gói, phân mảnh và rải đường đa lộ trình (Multi-path Packet Slicing) lên cơ chế điều khiển của TCP.

- **Số phân đoạn TCP nhận sai thứ tự (TCP Out-of-Order Packets):**
  - _Mô tả:_ Tổng số lượng gói tin đến đích không đúng trình tự tuần tự do độ trễ chênh lệch giữa các đường truyền khác nhau.
  - _Ý nghĩa:_ Đánh giá hiệu quả của bộ đệm tái hợp thứ tự (_Reassembly Buffer_) tại NFV Egress Proxy.
- **Số lượng bản tin báo nhận trùng lặp (Duplicate ACKs / Fast Retransmissions):**
  - _Mô tả:_ Tần suất xuất hiện các bản tin Dup-ACK và các lần kích hoạt cơ chế truyền lại nhanh của TCP.
  - _Ý nghĩa:_ Đo lường mức độ TCP bị "đánh lừa" là mất gói do hiện tượng xáo trộn thứ tự, từ đó ngăn chặn tình trạng bóp nghẽn cửa sổ truyền ($cwnd$) ngoài ý muốn.
- **Kích thước phân đoạn đẩy lên TCP (Segment Size Distribution):**
  - _Mô tả:_ Phân phối kích thước các khối dữ liệu sau khi được ghép nối và bàn giao cho TCP stack tại trạm nhận.
  - _Ý nghĩa:_ Kiểm chứng hiệu quả của khối gộp gói (_Generic Receive Offload - GRO_), đảm bảo các mảnh 64 KB được hợp nhất nguyên vẹn, tránh tình trạng phát tán hàng loạt phân đoạn siêu nhỏ (_Small Segment Flooding_).

---

## 3. Hiệu Năng Mô Hình Học Máy & Trí Tuệ Nhân Tạo (AI & Controller Metrics)

Nhóm chỉ số định lượng độ chính xác, tốc độ và tính ổn định của các thuật toán thông minh (XGBoost/LightGBM, GAT, PPO) trên mặt phẳng điều khiển.

- **Độ chính xác phân loại luồng (Classification Metrics):**
  - _Bộ thông số:_ Accuracy, Precision, Recall và F1-Score của mô hình cây quyết định/học máy (XGBoost / LightGBM) khi gán nhãn luồng Voi (_Elephant_) và Chuột (_Mice_).
  - _Trọng tâm:_ Ưu tiên cực đại hóa **Recall** cho luồng Voi để triệt tiêu nguy cơ bỏ sót luồng lớn.
- **Thời gian nhận diện luồng (Detection Delay):**
  - _Mô tả:_ Tổng độ trễ tính từ thời điểm luồng bắt đầu xuất hiện trên mạng cho đến khi hệ thống AI hoàn tất việc trích xuất đặc trưng và xác định thành công nhãn luồng.
- **Độ trễ suy luận (Inference Time):**
  - _Mô tả:_ Thời gian tính toán thuần túy của phần cứng (tính bằng ms) cho mỗi chu kỳ suy luận:
    - Thời gian phân loại luồng của XGBoost/LightGBM.
    - Thời gian trích xuất không gian topo của GAT kết hợp tính toán ma trận tỷ lệ phân tải của PPO.
- **Hội tụ của thuật toán DRL (Convergence Rate & Reward):**
  - _Mô tả:_ Tốc độ tăng trưởng và mức độ ổn định của đường cong hàm phần thưởng tích lũy (_Cumulative Reward Curve_) qua hàng ngàn episode huấn luyện, khẳng định Agent học được chính sách tối ưu hóa mạng bền vững.

---

## 4. Khả Năng Mở Rộng và Tài Nguyên Hệ Thống (System & Overhead Metrics)

Nhóm chỉ số đánh giá chi phí vận hành, tính khả thi khi mở rộng quy mô và mức độ tiêu hao tài nguyên phần cứng của giải pháp đề xuất.

- **Thời gian hội tụ và phục hồi khi có sự cố (Convergence / Recovery Time):**
  - _Mô tả:_ Khoảng thời gian từ khi phát sinh sự cố đứt liên kết vật lý (_Link Down_) đến khi SDN Controller và PPO phát hiện, tính toán và tái cấu hình toàn bộ bảng luồng mới.
- **Mức tiêu hao tài nguyên CPU/RAM (Host, Proxy, Controller):**
  - _Mô tả:_ Tỷ lệ chiếm dụng tài nguyên tính toán và dung lượng bộ nhớ thực tế của:
    - Máy chủ chạy NFV Proxy (xử lý cắt/ghép gói tốc độ cao).
    - SDN Controller (Ryu) và AI Inference Server.
    - Các nút mạng đầu cuối (Host nodes).
- **Số lượng luật trên bảng chuyển tiếp (Flow Table / Group Table Entries):**
  - _Mô tả:_ Số lượng mục luật (rules) thực tế được cài đặt và chiếm dụng trên bộ nhớ TCAM/SRAM của switch.
  - _Ý nghĩa:_ Chứng minh hiệu quả tiết kiệm tài nguyên bộ nhớ phần cứng thông qua giải pháp gom cụm luồng Chuột bằng Group Table, hạn chế triệt để nguy cơ bùng nổ bảng luồng (_Table Explosion_).

---

## Bảng Tổng Hợp Công Cụ và Phương Pháp Thu Thập Metrics

| Nhóm chức năng        | Thông số tiêu biểu         | Đơn vị đo         | Công cụ / Phương thức thu thập                   |
| :-------------------- | :------------------------- | :---------------- | :----------------------------------------------- |
| **Network & Traffic** | Throughput, Goodput        | Mbps / Gbps       | `iperf3`, `bmon`                                 |
|                       | Latency (Mean, p99)        | ms /$\mu\text{s}$ | `ping`, `tcpdump`, Wireshark                     |
|                       | Packet Loss, Jitter        | % / ms            | `ovs-ofctl dump-ports`, D-ITG                    |
|                       | Flow Completion Time (FCT) | ms / s            | Phân tích gói tin TCP Handshake$\rightarrow$ FIN |
|                       | Link Utilization           | %                 | Polling OpenFlow Port Stats qua Ryu              |
| **TCP Integrity**     | Out-of-Order Packets       | Số gói / %        | Wireshark filter`tcp.analysis.out_of_order`      |
|                       | TCP Dup-ACKs / Retransmit  | Số lần            | Bộ đếm TCP socket (`/proc/net/snmp`, `ss -i`)    |
| **AI & Controller**   | Precision, Recall, F1      | %                 | Scikit-learn, Confusion Matrix                   |
|                       | Inference Latency          | ms                | Thư viện`timeit`, profiling mã nguồn Python      |
|                       | DRL Cumulative Reward      | Điểm thưởng       | TensorBoard, Wandb                               |
| **System & Overhead** | CPU / RAM Usage            | % / MB            | `docker stats`, `cAdvisor`, Prometheus           |
|                       | Flow Table Occupancy       | Số entries        | Lệnh`ovs-ofctl dump-flows` / `dump-groups`       |
|                       | Recovery Time              | ms / s            | Log biến cố Topology Event trên Ryu Controller   |
