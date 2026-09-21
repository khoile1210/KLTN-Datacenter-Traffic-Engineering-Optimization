### Bảo mật tầng 1 (Canh gác): Autoencoder Model (Unsupervised Learning)

##### Lý do chọn Autoencoder

- Giải quyết bài toán "Zero-Day Attack"
- Tốc độ xử lý nhanh.
- So sánh trực diện với các đối thủ "Học không giám sát" khác:
  - So với PCA (Principal Component Analysis): PCA cũng nén và phục hồi dữ liệu để tìm dị thường. Tuy nhiên, PCA chỉ tìm được các mối quan hệ tuyến tính. Lưu lượng mạng có tính biến động cực kỳ phức tạp và phi tuyến tính (ví dụ: tốc độ đẩy luật Flow-Mod tăng theo hàm mũ khi mạng bị nghẽn). Autoencoder sử dụng các hàm kích hoạt (như ReLU) nên có khả năng nắm bắt các đặc trưng phi tuyến này xuất sắc hơn rất nhiều.
  - So với Isolation Forest (iForest): iForest hoạt động bằng cách cô lập các điểm dữ liệu bất thường bằng các nhánh cắt ngẫu nhiên. Thuật toán này rất nhanh, nhưng lại yếu khi xử lý các bộ dữ liệu mà các đặc trưng có tính tương quan cao. Trong 18 thông số của chúng ta, số lượng gói tin ($PPS$), dung lượng ($BPS$) và tần suất gói Packet-In có sự tương quan nội tại rất chặt chẽ. Autoencoder được sinh ra để học chính sự tương quan đó.
  - So với One-Class SVM (OCSVM): OCSVM cố gắng vẽ một siêu mặt phẳng (hyperplane) bao quanh dữ liệu bình thường. Vấn đề lớn nhất của OCSVM là độ trễ tính toán (Inference Latency) khi số lượng chiều dữ liệu ($N=18$) và lượng dữ liệu lớn. Đối với bộ điều khiển SDN cần xử lý hàng chục ngàn gói tin mỗi giây, OCSVM quá chậm và sẽ gây nghẽn cổ chai, trong khi Autoencoder (bản chất là tính toán ma trận với trọng số cố định) xử lý luồng dữ liệu thời gian thực mượt mà hơn.

##### Cơ chế

- Khi mạng bình thường: Vì Autoencoder đã được huấn luyện rất kỹ trên dữ liệu bình thường, nó sẽ nén và giải nén rất mượt. Dữ liệu đầu ra gần như y hệt đầu vào. Độ lệch (sai số) rất thấp.
- Khi có tấn công (hoặc bất kỳ dị thường nào): Các thông số như Entropy IP ($H(X)$) hay $R_{single}$ đột ngột thay đổi theo pattern lạ. Khi dữ liệu lạ này đi qua bộ nén, Autoencoder bị bối rối, dẫn đến việc giải nén ra một kết quả sai bét. Sai số sẽ tăng vọt.
- Đại lượng đo lường sự sai lệch này gọi là MSE (Mean Squared Error - Lỗi bình phương trung bình).

##### Dữ liệu

- Flow Table & TCAM Dynamics: Đây là nhóm đặc thù nhất của SDN, phản ánh sự tương tác giữa Switch và Controller.
  - $RIR$ (Rule Installation Rate): Tốc độ cài đặt luật mới (số luật/giây).
  - $TCAM_{usage}$: Tỷ lệ phần trăm bộ nhớ TCAM đang được sử dụng.
  - $R_{single}$ (Single-packet flow ratio): Tỷ lệ các flow chỉ có duy nhất 1 gói tin (dấu hiệu rõ nhất của flow giả mạo).
  - $Avg_{duration}$ (Average Flow Duration): Tuổi thọ trung bình của các luật đang tồn tại. (Tuổi thọ giảm mạnh chứng tỏ luật bị xóa liên tục do hết time-out).
  - $Active_{flows}$ (Total Active Flows): Tổng số lượng luật đang kích hoạt trong bảng flow của Switch.
- Thống kê Lưu lượng và Băng thông (Traffic Volume & Bandwidth): Nhóm này đo lường tải thực tế của mạng (Data Plane), giúp phát hiện các cuộc tấn công DDoS truyền thống tốn băng thông (Volumetric Attacks).
  - $BPS$ (Bytes per Second): Tổng lưu lượng truyền tải trong toàn mạng.
  - $PPS$ (Packets per Second): Tốc độ truyền gói tin.
  - $Avg_{bytes/rule}$: Kích thước trung bình (tính bằng byte) của mỗi luồng. (Luồng bình thường như tải file sẽ có số byte lớn, luồng tấn công thường rất nhỏ).
  - $Asymmetry_{ratio}$ (Tỷ lệ bất đối xứng In/Out): So sánh lưu lượng đi vào và đi ra khỏi một Switch. Nếu một port nhận vào 10,000 gói nhưng không đẩy ra gói nào, đó là dị thường (có thể do drop rác).
- Phân phối Giao thức và Địa chỉ (Protocol & Entropy)
  - $H(SIP)$ (Source IP Entropy): Độ phân tán của IP nguồn. (Tăng vọt khi có IP Spoofing).
  - $H(DIP)$ (Destination IP Entropy): Độ phân tán của IP đích. (Tăng vọt khi có quét mạng - Network Scanning).
  - $H(Port)$ (Destination Port Entropy): Độ phân tán của cổng đích. (Phát hiện Port Scanning).
  - Tỷ lệ TCP/UDP/ICMP: Phân bổ phần trăm của từng loại giao thức trong $\Delta t$. (Ví dụ: ICMP đột ngột chiếm 80% là dấu hiệu của Ping Flood).
- Control Plane Health:
  - $Rate_{PacketIn}$: Tốc độ bản tin Packet-In gửi từ Switch lên Controller. (Đây là nút thắt cổ chai dễ bị tấn công nhất trong SDN).
  - $Rate_{FlowMod}$: Tốc độ bản tin Flow-Mod (thêm/sửa/xóa luật) đẩy từ Controller xuống Switch.
  - Controller CPU/RAM Usage: Phần trăm tài nguyên hệ thống mà Controller (Ryu/ONOS/Floodlight) đang chiếm dụng.

##### Chuẩn bị

- Chuẩn bị dữ liệu traffic thông thường (mô phỏng bằng iperf, ping, python script,...)
- Sử dụng kiến trúc bottleneck cho model AI và train (Input - Dense() - Dense(min) - Dense() - Output)
- Thiết lập Ngưỡng Cảnh báo (Threshold - $\theta$): Đây là bước quan trọng nhất. Sau khi train xong, cho toàn bộ tập dữ liệu Normal chạy qua mô hình một lần nữa để lấy ra một danh sách các giá trị MSE:
  - Tính giá trị Trung bình ($\mu$) và Độ lệch chuẩn ($\sigma$) của danh sách MSE này.
  - Ngưỡng cảnh báo thường được đặt theo quy tắc thống kê: $\theta = \mu + 3\sigma$. (Nghĩa là, bất kỳ gói tin nào có MSE vượt quá 3 độ lệch chuẩn so với mức bình thường thì chắc chắn là dị thường).

##### Đánh giá

- Inference Time
- Tỉ lệ báo động giả (False Positive)
- Độ chính xác.
