## Phòng chống Low-Rate Flow-Table thông minh

**Low-Rate Flow-Table (LoFT)** – một dạng tấn công nguy hiểm trong mạng SDN (Software-Defined Networking) nhằm làm cạn kiệt bộ nhớ Ternary Content-Addressable Memory (TCAM) của Switch bằng các gói tin tốc độ thấp để qua mặt các hệ thống phát hiện DDoS truyền thống

### Phân tích vấn đề:

- Tấn công LoFT thường tạo ra các gói tin có địa chỉ IP/MAC nguồn hoặc đích thay đổi liên tục, nhưng gửi với tốc độ chậm (low-rate). Điều này gây ra hiện tượng Table-Miss, ép Switch gửi liên tục các bản tin Packet-In lên Controller và Controller phải cài đặt vô số luật (flow rules) mới xuống Switch gây tràn bộ nhớ TCAM của switch.
- Metrics cần giám sát:
  - Số lượng bản tin Packet-In gửi lên Controller trong khoảng thời gian $\Delta t$.
  - Tỷ lệ Single-packet flows: Số lượng các luồng (flow) chỉ chứa đúng 1 gói tin / Tổng số luồng trong bảng TCAM
  - Độ tăng trưởng Flow-Table: Vận tốc thêm mới flow rule so với vận tốc rule bị xóa do timeout.
  - Thời gian tồn tại trung bình của Flow (Average Flow Duration): Các luồng LoFT thường có thời gian tồn tại rất ngắn.
  - Byte/Packet Ratio: Tỷ lệ byte trên mỗi gói tin của một luồng. Tấn công LoFT thường dùng gói tin có kích thước cực nhỏ để tiết kiệm băng thông nhưng vẫn ép Switch tạo rule.
    | Tiêu chí | XGBoost | Random Forest | LSTM / RNN | SVM / KNN |
    | :--- | :--- | :--- | :--- | :--- |
    | **Cơ chế hoạt động** | Tối ưu hóa Gradient Boosting (Cải tiến tuần tự từng cây) | Gộp nhóm song song các cây quyết định độc lập (Bagging) | Mạng nơ-ron tái diễn xử lý chuỗi thời gian | Phân cách siêu phẳng / Khoảng cách láng giềng |
    | **Độ nhạy với tấn công lén lút (LoFT)** | **Cao:** Bắt tốt các tổ hợp đặc trưng phức tạp (Entropy, Ratios) | Khá: Dễ bị bỏ sót các mẫu tấn công quá tinh vi | **Rất cao:** Chuyên trị dữ liệu chuỗi thời gian nguyên bản | Kém: Không xử lý được các biên giới phân loại mờ |
    | **Tốc độ suy diễn (Inference)** | **Rất nhanh** (Tối ưu hóa cho bảng dữ liệu) | Nhanh | Chậm (Yêu cầu tính toán tuần tự) | Rậm rạp và chậm khi dữ liệu lớn |
    | **Xử lý dữ liệu mất cân bằng** | **Xuất sắc** (Hỗ trợ sẵn `scale_pos_weight`) | Cần tinh chỉnh cấu trúc hoặc SMOTE thủ công | Phức tạp, dễ thiên vị lớp đa số | Kém, nhạy cảm với nhiễu |
    | **Nhược điểm** | Cần tinh chỉnh kỹ các siêu tham số (`max_depth`, `learning_rate`) để tránh quá khớp | Kích thước file model lớn, ít linh hoạt hơn XGBoost | Tốn tài nguyên huấn luyện, dễ bị quá tải trên Controller | Hoàn toàn không phù hợp với quy mô luồng mạng lớn |

### Model AI: XGBoost

- Lý do chọn model:
  - **Khả năng bóc tách biên giới phân loại phức tạp**: LoFT không gây ra sự bùng nổ lưu lượng đột ngột mà ẩn mình qua các đặc trưng thống kê kết hợp (như tỷ lệ gói đơn, Shannon Entropy của IP nguồn, và tỷ lệ byte/gói). Cơ chế tối ưu hóa hàm mất mát tuần tự của XGBoost giúp nó vạch ra các ranh giới quyết định (decision boundaries) cực kỳ sắc bén cho dữ liệu dạng bảng, nhận diện chính xác các mẫu hành vi lén lút mà các mô hình cây đơn giản bỏ sót.
  - **Kiểm soát Overfitting hiệu quả với Regularization:** Do dữ liệu tấn công LoFT thường chiếm tỷ lệ rất nhỏ so với traffic thông thường, mô hình rất dễ học vẹt (overfitting). XGBoost tích hợp sẵn các tham số chuẩn hóa L1 (**$alpha$**) và L2 (**$lambda$**) giúp phạt các trọng số lớn, ép mô hình tổng quát hóa tốt hơn trên dữ liệu thực tế

- Dữ liêu đầu vào bao gồm các đặc trưng như sau:
  - Tỷ lệ Single-packet flows - Số lượng các luồng (flow) chỉ chứa đúng 1-2 gói tin / Tổng số luồng trong bảng TCAM
  - Số lượng bản tin Packet-In gửi lên Controller trong khoảng thời gian $\Delta t$.
  - Byte/Packet Ratio: Tỷ lệ byte trên mỗi gói tin của một luồng.
  - Tỷ lệ chiếm dụng TCAM
  - Độ phân tán IP nguồn tính bằng Shanno Entropy (Entropy cao tỉ lệ bị LoFT cao):

    $$
    H(X) = - \sum_{i=1}^{n} P(x_i) \log_2 P(x_i)
    $$
    - $n$: Tổng số lượng các địa chỉ IP nguồn khác nhau (distinct IPs) xuất hiện trong $\Delta t$.
    - $x_i$: Địa chỉ IP nguồn thứ $i$.
    - $P(x_i)$: Xác suất xuất hiện của IP $x_i$. Được tính bằng: Số gói tin của IP $x_i$ / Tổng số gói tin trong mạng.

- Hành động khi phát hiện sự cố:
  - Can thiệp trực tiếp vào Bảng luật (Flow-Table Mitigation):
    - Sử dụng `OFPFlowMod` để giảm `idle_timeout` và `hard_timeout` của các luồng đáng ngờ (chỉ chứa 1-2 gói tin, byte thấp) xuống tối thiểu (từ 10-30s $\rightarrow$ 1-2s) $\rightarrow$ tăng tốc độ dọn dẹp TCAM.
    - Gộp luật bằng Wildcard (Rule Aggregation): Tính toán dải IP cụ thể của nhiều địa chỉ IP tấn công và DROP gói tin, giảm độ ưu tiên.
    - Xóa các Rule rác có `byte counter` rất thấp nhưng vấn chiếm dụng tài nguyên.

- Bảo vệ Controller (Controller Shielding):
  - Sử dụng tính năng Meter Table để thiết lập một bộ định mức băng thông (Rate Limiter), bóp nghẹt hoặc drop bớt các bản tin Packet-In xuất phát từ các cổng (switch ports) đang bị đánh dấu là nguồn phát tán tấn công.

- Cách ly và Giám sát (Isolation & Alerting):
  - Nếu hệ thống truy xuất được MAC address hoặc Ingress Port cụ thể phát sinh số lượng IP Spoofing lớn nhất, Controller sẽ tạo một rule Drop với độ ưu tiên cao nhất (Highest Priority) gắn thẳng vào Port đó trong một khoảng thời gian ngắn (ví dụ 60 giây). Hết thời gian, rule tự động gỡ để kiểm tra lại.
  - Realtime Monitoring bằng Dashboard, Alerting.

##### Chuẩn bị dữ liệu:

- Mạng bình thường: Sử dụng iperf3 hoặc python script để sinh traffic bình thường.
- Tấng công: Giả lập tấn công bằng Scapy.
- Cân bằng dữ liệu (nếu cần): Sử dụng kĩ thuật SMOTE (Synthetic Minority Over-sampling Technique) từ thư viện imbalanced-learn
- Cần ít nhất 15k mẫu dữ liệu ở mỗi loại.
