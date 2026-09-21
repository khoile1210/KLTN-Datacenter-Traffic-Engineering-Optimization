---
## Tại sao không đánh giá Latency, Mice Flows GoodPut và Elephant Flows FCT?

## Cơ Sở Kỹ Thuật Lựa Chọn Metric Đánh Giá: Luồng Chuột (Mice), Luồng Voi (Elephant) và Tail Latency

Trong các hội đồng bảo vệ đồ án chuyên sâu về Mạng và SDN, việc ghép cặp các chỉ số đo kiểm theo từng loại luồng dữ liệu phản ánh mức độ hiểu biết bản chất về cơ chế điều khiển luồng của giao thức TCP và đặc thù lưu lượng mạng trung tâm dữ liệu (Data Center Network).
---

## 1. Tại sao không đánh giá Goodput cho luồng Chuột (Mice Flows)?

- **Đặc thù kích thước luồng:** Luồng Chuột có kích thước rất nhỏ (dao động từ vài KB đến vài MB), điển hình là các truy vấn DNS, HTTP request, REST API calls hoặc các gói tin điều khiển SSH.
- **Hạn chế từ cơ chế TCP Slow Start:**
  - Khi khởi tạo một kết nối TCP mới, tiến trình bắt đầu bằng pha Khởi động chậm (_Slow Start_). Bên gửi phát đi một lượng dữ liệu nhỏ tương ứng với cửa sổ nghẽn ban đầu ($cwnd \approx 10 \text{ MSS}$) và tăng dần theo từng chu kỳ RTT.
  - Do dung lượng tệp tin của luồng Chuột quá bé, toàn bộ dữ liệu thường được truyền xong trước khi TCP kịp thoát khỏi pha Slow Start để chạm tới ngưỡng băng thông vật lý tối đa của đường truyền.
- **Bản chất giới hạn (RTT-bound vs. Bandwidth-bound):**
  - Tốc độ truyền của luồng Chuột bị chặn bởi thời gian khứ hồi ($RTT$ - Round Trip Time) chứ **không bị chặn bởi băng thông** liên kết.
  - Việc đo đạc thông lượng hữu ích (Goodput) cho luồng Chuột là không mang ý nghĩa thực tiễn.
- **Kết luận:** **Flow Completion Time (FCT)** là thước đo chuẩn xác nhất đối với luồng Chuột, phản ánh trực tiếp tốc độ phản hồi và độ nhạy của các ứng dụng tương tác thời gian thực.

---

## 2. Tại sao ưu tiên Goodput thay vì FCT cho luồng Voi (Elephant Flows)?

- **Sự phụ thuộc vào dung lượng tệp dữ liệu:**
  - Luồng Voi đại diện cho các phiên truyền tải dữ liệu dung lượng lớn (sao lưu hệ thống, đồng bộ database, di chuyển máy ảo hoặc luồng stream liên tục).
  - Nếu dùng FCT làm thước đo chính, giá trị thời gian (ví dụ: $30\text{s}$ hay $3\text{ phút}$) không phản ánh độc lập được hiệu năng mạng vì nó phụ thuộc hoàn toàn vào việc kích thước tệp thử nghiệm là $1\text{ GB}$ hay $10\text{ GB}$.
- **Trường hợp luồng dữ liệu không xác định điểm dừng:** Trong các kịch bản luồng truyền trực tuyến kéo dài liên tục, không tồn tại mốc kết thúc truyền tệp (FIN packet), dẫn đến việc không thể xác định giá trị FCT.
- **Cơ chế TCP Congestion Avoidance:**
  - Luồng Voi tồn tại đủ lâu để vượt qua pha Slow Start và bước vào pha Né tránh nghẽn (_Congestion Avoidance_), qua đó chiếm dụng toàn bộ băng thông khả dụng trên đường truyền.
  - Chỉ số **Goodput (Mbps/Gbps)** cung cấp một giá trị được chuẩn hóa: phản ánh chính xác thuật toán (PPO kết hợp NFV Proxy) đã tận dụng và khai thác được bao nhiêu phần trăm năng lực của các liên kết lõi, độc lập với độ dài hay dung lượng luồng.
- **Kết luận:** Mặc dù vẫn có thể đo FCT cho luồng Voi trong trường hợp kích thước tệp cố định, **Goodput** vẫn là chỉ số đại diện cốt lõi nhất để đánh giá hiệu quả tối ưu hóa đường truyền.

---

## 3. Tại sao đánh giá FCT và Tail Latency thay vì Độ trễ trung bình (Average Latency)?

- **Cạm bẫy của giá trị trung bình (Flaw of Averages):**
  - Trong hạ tầng mạng chuyển mạch tốc độ cao, độ trễ trung bình (Mean Latency) thường duy trì ở mức rất thấp ($< 1\text{ ms}$).
  - Tuy nhiên, các xung đột biến vi mô (_Microbursts_) diễn ra trong tích tắc có thể đẩy hàng đợi (Queue) tại switch vào trạng thái bão hòa tạm thời, khiến một lượng nhỏ gói tin bị giữ lại tới $50\text{ ms} - 100\text{ ms}$.
  - Phép tính trung bình cộng sẽ san phẳng các đột biến này, che giấu hoàn toàn các điểm nghẽn cục bộ nghiêm trọng.
- **Ý nghĩa thực tế của Tail Latency ($p95$, $p99$):**
  - Đo lường trễ tại phân vị thứ 95 và 99 phản ánh kịch bản xấu nhất (_Worst-case Scenario_) mà hệ thống chuyển mạch gặp phải.
  - Trong kiến trúc microservices và phân tán, hiện tượng chậm trễ của một vài gói tin quan trọng (Tail Latency cao) sẽ kích hoạt hiện tượng chặn đầu hàng (_Head-of-Line Blocking_), kéo tụt hiệu năng của toàn bộ tác vụ tổng hợp.
- **FCT bao hàm toàn bộ chu trình trễ:**
  - FCT của một luồng dữ liệu thực chất là sự cộng dồn toàn diện của: _Thời gian bắt tay kết nối + Độ trễ lan truyền + Độ trễ hàng đợi + Thời gian phát sinh do rớt gói và truyền lại TCP_.
  - FCT phản ánh chính xác nhất trải nghiệm hoàn tất tác vụ từ góc nhìn của ứng dụng đầu cuối.

---

## 4. Bảng Tổng Hợp Đối Chiếu (Dùng Cho Báo Cáo Bảo Vệ)

| Loại luồng                     | Yếu tố chi phối chính                   | Metric ưu tiên hàng đầu                | Metric phụ trợ / Kiểm chứng       | Lý do kỹ thuật cốt lõi                                                                                      |
| :----------------------------- | :-------------------------------------- | :------------------------------------- | :-------------------------------- | :---------------------------------------------------------------------------------------------------------- | --- | --- |
| **Luồng Chuột (Mice Flows)**   | **Độ trễ** (_Latency-sensitive_)        | **FCT**, **Tail Latency** ($p95, p99$) | Jitter, Packet Loss Rate          | Bị giới hạn bởi RTT và pha TCP Slow Start; không đủ dung lượng để mở rộng cửa sổ$cwnd$ đạt đỉnh băng thông. |     |     |
| **Luồng Voi (Elephant Flows)** | **Băng thông** (_Throughput-sensitive_) | **Goodput** (Mbps), **Bisection BW**   | Link Utilization, Jain's Fairness | Bị chi phối bởi pha TCP Congestion Avoidance; mục tiêu là tối đa hóa tỷ lệ lấp đầy dung lượng liên kết lõi. |
