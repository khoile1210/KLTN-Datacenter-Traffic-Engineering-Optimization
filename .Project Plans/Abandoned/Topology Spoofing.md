### Routing/Topology Spoofing

- Kẻ tấn công nhắm vào giao thức LLDP (Link Layer Discovery Protocol). Chúng tạo ra các gói tin LLDP giả để đánh lừa SDN Controller rằng đang có một liên kết (link) trực tiếp giữa hai Switch không hề kết nối với nhau, hoặc báo cáo sai vị trí của các thiết bị Host.
- Mục đích:
  - Chuyển hướng lưu lượng (Traffic Hijacking): Ép dữ liệu mạng đi qua thiết bị của kẻ tấn công, tạo tiền đề để thực hiện tấn công MitM (nghe lén, sửa đổi).
  - Hố đen (Blackholing) / Tấn công từ chối dịch vụ (DoS): Hướng toàn bộ lưu lượng của mạng đi vào một đường link không tồn tại hoặc một thiết bị có băng thông thấp, làm rớt toàn bộ dữ liệu và gây tê liệt mạng.
  - Vượt rào bảo mật (Bypass Security Policies): Đánh lừa hệ thống điều khiển tạo ra các quy tắc (rules) định tuyến bỏ qua các thiết bị kiểm tra an ninh (Firewall, IDS/IPS).

###### Cơ chế phát hiện tấn công (Đóng vai trò là lớp gác cổng)

- Khi các Switch gửi bản tin khám phá (thường là gói tin LLDP được đóng gói trong sự kiện OFPPacketIn hoặc các sự kiện cập nhật cổng PortStatus) lên Controller.
- Lớp gác cổng sẽ đóng vai trò là một "Middleware Proxy": Chặn lại các sự kiện cập nhật liên kết này, phân tích tính hợp lệ trước khi cho phép ghi nhận vào đồ thị chính thức mà hệ thống GNN + DQN đang sử dụng.

##### Chuẩn bị dữ liệu (Sử dụng EventOFPPacketIn)

- Mạng bình thường: Thu thập cấu trúc đồ thị chuẩn (Adjacency Matrix / Edge Index) trong phòng thí nghiệm Mininet với số lượng Switch và Host cố định.
- Tấn công (Topology Spoofing): Dùng Scapy viết script giả mạo các gói tin LLDP, tạo ra các liên kết chéo vô lý giữa các Switch không hề có kết nối vật lý thực tế.

##### Mô hình Security GNN kiến trúc GraphSAGE

- Đầu vào: Đặc trưng của 2 Node (Switch nguồn và Switch đích): Tần suất gửi gói tin LLDP, lịch sử trạng thái cổng (PortStatus).
- Đặc trưng cấu trúc: Số bước nhảy (Hop count) tối thiểu giữa 2 Node trong đồ thị hiện tại.

##### Cơ chế phản ứng

- Hủy sự kiện: Controller bỏ qua gói tin LLDP đó, không cho thêm vào cấu trúc đồ thị.
- Gửi lệnh Flow Mod: Đẩy một rule drop hoặc giới hạn tốc độ bản tin điều khiển từ cổng đang phát tán bản tin giả
- Log & Alert: Đẩy cảnh báo về hệ thống giám sát trung tâm (như Graylog) để quản trị viên nắm bắt vị trí Switch đang bị tấn công.

##### Lý do chọn GraphSAGE

### So sánh GraphSAGE với các mô hình AI khác trong phát hiện Topology Spoofing

| Đặc tính / Tiêu chí                                              | GraphSAGE                                                                                            | GCN (Graph Convolutional Network)                                                                          | GAT (Graph Attention Network)                                                         | XGBoost / Random Forest                                                                      | LSTM / RNN                                                       |
| :--------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------ | :------------------------------------------------------------------------------------------- | :--------------------------------------------------------------- |
| **Khả năng hiểu cấu trúc đồ thị (Topology Awareness)**           | **Tuyệt đối.** Khai thác trực tiếp các kết nối vật lý (Edges) và đặc trưng thiết bị (Nodes).         | Tuyệt đối.                                                                                                 | Tuyệt đối.                                                                            | **Không.** Chỉ nhìn vào các con số thống kê rời rạc, bỏ qua sự liên kết không gian của mạng. | Thấp. Phù hợp với chuỗi thời gian hơn là không gian đồ thị mạng. |
| **Tính linh hoạt khi mạng thay đổi (Inductive vs Transductive)** | **Rất linh hoạt (Inductive).** Tự động sinh dự đoán cho Switch/Link mới mà không cần huấn luyện lại. | **Kém (Transductive).** Cần toàn bộ ma trận mạng cố định. Thêm 1 Switch mới = Phải huấn luyện lại toàn bộ. | Rất linh hoạt (Inductive).                                                            | Linh hoạt (Nhưng vô dụng vì không hiểu cấu trúc).                                            | Linh hoạt.                                                       |
| **Tốc độ suy diễn (Inference Latency)**                          | **Rất nhanh.** Chỉ lấy mẫu (Sample) một lượng láng giềng cố định, không tính toán toàn mạng.         | Nhanh, nhưng chậm dần nếu kích thước đồ thị mạng quá lớn.                                                  | Chậm hơn do phải tính toán trọng số chú ý (Attention weights) cho từng liên kết.      | Siêu nhanh.                                                                                  | Trung bình - Chậm.                                               |
| **Khả năng mở rộng (Scalability / Memory Usage)**                | **Tốt.** Hỗ trợ mini-batching, không cần load toàn bộ cấu trúc Topology vào RAM của Controller.      | Kém. Phải giữ toàn bộ ma trận kề (Adjacency Matrix) khổng lồ trong bộ nhớ.                                 | Khá. Tốn nhiều RAM hơn để lưu ma trận Attention.                                      | Rất tốt.                                                                                     | Khá.                                                             |
| **Mức độ phù hợp tổng thể cho lớp Security Gate**                | **Tối ưu nhất.** Cân bằng hoàn hảo giữa độ chính xác kiến trúc mạng, tốc độ và tính mở rộng.         | Không khả thi cho SDN thực tế vì topology thay đổi (host up/down) liên tục.                                | Quá nặng nề và phức tạp không cần thiết cho một bài toán phân loại liên kết nhị phân. | Bị mù trước các thay đổi cấu trúc lén lút của Topology Spoofing.                             | Bỏ lọt tấn công vì mất ngữ cảnh không gian vật lý của Switch.    |
