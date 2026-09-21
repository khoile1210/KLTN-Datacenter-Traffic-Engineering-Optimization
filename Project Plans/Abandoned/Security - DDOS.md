## Phát hiện/phòng chống DOS/DDOS thông minh (Volumetric Attack)

##### Chuẩn bị dữ liệu (50-100k mẫu)

- Sử dụng `ping` hoặc `iperf` để mô phỏng **Normal Traffic** và **Attack Traffic** để sinh dữ liệu.
  - Normal : Áp dụng mô phỏng traffic ở nhiều mức băng thông khác nhau.
  - Attack : Áp dụng mô phỏng ở nhiều cường độ khác nhau (Điều chỉnh time interval).
- Thu thập dữ liệu định kì từ Controller băng `OFPFlowStatsRequest`.
- Thu thập chỉ số: `packet_rate`, `byte_rate`, `avg_packet_size = byte_rate / packet_rate` $\leftarrow$ ổn định, rất nhỏ khi DDOS SYN Flood.
- Dạng dữ liệu: $F_1, F_2, F_3$, label.

###### AI Model - LightGBM

- Lưu ý khi train:
  - num_leaves (Số lượng lá tối đa): Tham số quan trọng nhất. Phải đảm bảo $num\_leaves < 2^{max\_depth}$. Nên bắt đầu thử nghiệm ở mức 31 hoặc nhỏ hơn (ví dụ: 15, 20) vì bạn chỉ có 3 features.
  - max_depth (Độ sâu tối đa): Rất cần thiết để giới hạn sự phình to của cây rẽ nhánh. Nên đặt ở mức 5 đến 7.
  - min_data_in_leaf: Số lượng mẫu tối thiểu trong một lá. Chỉnh cao lên (ví dụ: 20 - 50) để tránh tạo ra các lá quá cụ thể chỉ phục vụ cho một vài điểm nhiễu (outliers).
  - earning_rate: Tốc độ học tập. Có thể thiết lập ở mức 0.05 đến 0.1 cùng với số lượng vòng lặp n_estimators khoảng 100 - 200.
- Đánh giá: `Accuracy`, `Precision`, `Recall`.
- Lý do chọn Model:
  - Độ trễ suy diễn (Inference Latency) cực thấp
  - Cơ chế rẽ nhánh theo lá (Leaf-wise Growth): Thuật toán tập trung chia tách ở những lá có mức độ giảm sai số lớn nhất thay vì phát triển đồng đều các nhánh. Điều này giúp LightGBM hội tụ nhanh hơn, đạt độ chính xác tương đương hoặc nhỉnh hơn các mô hình cùng loại nhưng với cấu trúc cây ít phức tạp hơn.
  - Tối ưu hóa tài nguyên phần cứng (CPU/Memory)

    | Tiêu chí                               | LightGBM                                                          | Deep Learning (ANN, RNN, CNN)                          | XGBoost / Random Forest                         | SVM / KNN                                           |
    | :------------------------------------- | :---------------------------------------------------------------- | :----------------------------------------------------- | :---------------------------------------------- | :-------------------------------------------------- |
    | **Cơ chế hoạt động**                   | Tối ưu hóa Gradient Boosting theo chiều lá (Leaf-wise)            | Mạng nơ-ron đa lớp học đặc trưng tự động               | Cây quyết định / Rẽ nhánh theo mức (Level-wise) | Phân cách siêu phẳng / Tính khoảng cách láng giềng  |
    | **Tốc độ dự đoán (Inference)**         | **Cực kỳ nhanh** (Phù hợp nhất cho SDN/FastAPI)                   | Chậm (Thường yêu cầu GPU để đạt tốc độ tốt)            | Nhanh                                           | Rất chậm khi tập dữ liệu lớn                        |
    | **Tiêu hao tài nguyên**                | Rất thấp                                                          | Rất cao                                                | Trung bình - Cao                                | Trung bình                                          |
    | **Khả năng chống quá tải dữ liệu lớn** | Xuất sắc (Xử lý hàng triệu packet/s mượt mà)                      | Tốt (Nhưng tốn bộ nhớ)                                 | Dễ bị tràn RAM hoặc nghẽn CPU                   | Hoàn toàn bất lợi (Kém khả thi)                     |
    | **Nhược điểm**                         | Dễ bị Overfitting nếu dữ liệu quá nhỏ (cần cấu hình tham số chặt) | Yêu cầu tài nguyên tính toán đắt đỏ, cấu hình phức tạp | Quá trình Training lâu hơn, file model nặng hơn | Không scale được với dữ liệu biến động lớn của DDoS |

##### Hoạt động

- AI Server (FastAPI) nhận dữ liệu liên tục Controller, nếu phát hiện tấn công thì tiến hành tạm khóa (60p)

##### Đánh giá

- Đánh giá mô hình AI: Confusion Matrix
  - Precision
  - Recall
  - Accurracy (F1-Score)
- Đánh giá hoạt động của hệ thống mạng:
  - Độ trễ phát hiện và phản hồi: Khoảng thời gian tính từ lúc bắt đầu tấn công đến khi hệ thống phản hồi. (Phải tính bằng ms và càng thấp càng tốt).
  - Controller and Switch CPU/Memory Usage: Đánh giá biến động tài nguyên của Controller và vùng/thiết bị bị tấn công. Kì vọng: phần còn lại của hệ thống mạng không bị ảnh hưởng nhiều.
  - Thời gian phục hồi dịch vụ của máy chủ nạn nhân

### **Các Timestamp quan trọng cần lưu ý để đánh giá**

- Trạng thái bình thường
- Bắt đầu tấn công
- AI can thiệp
- Phục hồi hoàn toàn
