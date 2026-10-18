# KẾ HOẠCH CHI TIẾT: THỰC NGHIỆM ĐỐI SÁNH HỌC THUẬT & HỆ THỐNG TIÊU CHÍ ĐÁNH GIÁ
## (PERFORMANCE EVALUATION & ACADEMIC BENCHMARK PLAN)

> **Mã chuyên đề:** `PLAN-WP08-BENCHMARK-EVAL`  
> **Thuộc dự án:** Nghiên cứu Tối ưu hóa Kỹ thuật Lưu lượng trong Mạng DCN Dựa trên SDN và AI (SDN-AI DCN)  
> **Cố vấn chuyên môn:** Senior SDN Architect (Gemini 4 Argon)  
> **Trạng thái thực tế:** **THIẾT KẾ CHI TIẾT (PHASE 4 WORK PACKAGE)**  
> **Thư mục mã nguồn:** [`evaluate/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/evaluate/), [`controller/visualize_all_results.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/visualize_all_results.py), [`results/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/results/)  

---

## 1. MỤC TIÊU & BÀI TOÁN KHOA HỌC

1. **Kiểm chứng Toàn diện Tính Vượt trội của Hệ thống Đề xuất:** Đánh giá định lượng hiệu quả của kiến trúc phân tầng SDN-AI DCN (kết hợp Fast-Path ECN Data Plane, GAT-PPO DRL Routing và Embedded NFV Proxy) so với các giải pháp chuẩn công nghiệp và nghiên cứu quốc tế đỉnh cao.
2. **Thiết lập 5 Kịch bản Thử nghiệm Áp lực Khắc nghiệt (Extreme Stress Test Scenarios):** Đưa mạng DCN vào các điều kiện hoạt động tới hạn: Bão hòa băng thông toàn cục, Dịch chuyển phân phối tải đột ngột (Workload Drift), Đứt cáp vật lý (Link Failure), Bão xung đột TCP Incast, và Thử nghiệm khả năng mở rộng hàng chục ngàn luồng.
3. **Xây dựng Hệ thống Chỉ số Đánh giá Khoa học Đa chiều (Multi-Dimensional Academic KPIs):** Phân tích chi tiết cả hai mặt: *Chất lượng dịch vụ cho ứng dụng (FCT, Tail Latency p95/p99, Goodput)* và *Sức khỏe hạ tầng mạng (Bisection Utilization, Jain's Fairness Index, Packet Drops, TCAM Occupancy)*.
4. **Chuẩn hóa Đồ thị Học thuật Xuất bản Luận văn:** Tự động xuất các biểu đồ phân phối xác suất CDF, biểu đồ hộp Boxplot và chuỗi thời gian Time-series độ nét cao **300 DPI** sẵn sàng chèn trực tiếp vào báo cáo Khóa luận Tốt nghiệp.

---

## 2. CƠ SỞ KHOA HỌC, ĐỊNH LÝ GỐC & CÁC HỆ THỐNG BASELINE ĐỐI SÁNH

- **[Chỉ số Thời gian Hoàn thành Luồng Chuẩn hóa NormFCT]** M. Alizadeh, S. Yang, M. Sharif, S. Katti, N. McKeown, B. Prabhakar, S. Shenker, *"pFabric: Minimal Near-Optimal Datacenter Transport"*, ACM SIGCOMM 2013. *(Cơ sở lý thuyết chuẩn hóa thời gian FCT theo kích thước luồng và RTT không tải để đánh giá mức độ suy hao hiệu năng).*
- **[Độ trễ Đuôi Bách phân vị $P_{95}/P_{99}$ & Trễ Phân tán]** J. Dean, L. A. Barroso (Google), *"The Tail at Scale"*, Communications of the ACM (CACM), Vol. 56, No. 2, pp. 74–80, 2013. *(Nguyên lý độ trễ đuôi chi phối trải nghiệm người dùng trong kiến trúc microservice và truy vấn song song quy mô lớn).*
- **[Chỉ số Công bằng Jain]** R. K. Jain, D.-M. W. Chiu, W. R. Hawe, *"A Quantitative Measure of Fairness and Discrimination for Resource Allocation in Shared Computer Systems"*, DEC Research Report TR-301, 1984. *(Độ đo toán học thỏa mãn 5 tiên đề công bằng trong chia sẻ tài nguyên).*
- **[Các Baseline Đối sánh Học thuật]** Static ECMP (RFC 2992); Hedera (M. Al-Fares, et al., USENIX NSDI 2010); Pure Presto (K. He, et al., ACM SIGCOMM 2015).

Đề tài tiến hành thực nghiệm đối đầu trực tiếp với 3 cơ chế định tuyến đại diện tiêu biểu:

| STT | Hệ Thống Đối Sánh (Baseline) | Cơ Chế Hoạt Động & Bản Chất Kỹ Thuật | Nhược Điểm Cốt Lõi |
| :---: | :--- | :--- | :--- |
| **1** | **Static ECMP** *(Chuẩn mặc định công nghiệp)* | Băm tĩnh 5-tuple (`src_ip, dst_ip, proto, src_port, dst_port`) phân bổ đều ra các Spine. | **Xung đột băm mù (Hash Collision):** Luồng Voi đụng độ làm sập liên kết, trừng phạt luồng Chuột. |
| **2** | **Hedera** *(Al-Fares et al., NSDI 2010)* | SDN Controller định kỳ polling thống kê switch, phát hiện luồng Voi vượt $10\%$ link và bẻ nguyên luồng (Global Rerouting). | **Trễ điều khiển lớn ($1 - 5\text{s}$):** Không xử lý được Microburst; bẻ nguyên luồng dễ gây đảo luồng (Flapping). |
| **3** | **Pure Presto** *(He et al., SIGCOMM 2015)* | Cắt Flowcell $64\text{ KB}$ tại Edge vSwitch và phân bổ Round-Robin mù (không có AI nhận biết trạng thái mạng). | **Bất đối xứng tải:** Khi một liên kết bị nghẽn hoặc đứt cáp, Round-Robin vẫn đẩy gói vào gây rớt dữ liệu. |
| **4** | **Hệ Thống Đề Xuất (SDN-AI DCN)** | **Phân tầng 2 miền:** Data Plane ECN ghìm Microburst/Mice; GAT-PPO DRL phân rải Flowcell $64\text{ KB}$ thích ứng tải; NFV Proxy tái hợp TCP. | **Tối ưu toàn diện:** Tận dụng tối đa băng thông, bảo toàn $cwnd$, FCT luồng Chuột đạt mức cực tiểu. |

---

## 3. THIẾT KẾ 5 KỊCH BẢN THỰC NGHIỆM KHẮC NGHIỆT

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
| 5 KỊCH BẢN KIỂM THỬ THỰC NGHIỆM ĐỐI SÁNH (EXTREME BENCHMARK SCENARIOS)                             |
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|  KỊCH BẢN 1: BÃO HÒA BĂNG THÔNG TOÀN CỤC & NHIỄU VI MÔ (SATURATION & NOISE)                       |
|  - Ép tải nền tăng dần từ 50% -> 70% -> 85% -> 95% công suất Bisection Bandwidth.                 |
|  - Mục tiêu: Đo lường thông lượng tối đa, độ lệch chuẩn tải và độ ổn định của PPO DRL.            |
|                                                                                                   |
|  KỊCH BẢN 2: DỊCH CHUYỂN PHÂN PHỐI LƯU LƯỢNG ĐỘT NGỘT (WORKLOAD DRIFT & DATA SHIFT)               |
|  - Đột ngột hoán chuyển tỷ lệ giữa 3 cụm Facebook: Web-Heavy -> Cache-Heavy -> Hadoop-Heavy.      |
|  - Mục tiêu: Kiểm chứng độ bền vững của bộ phân loại Early Classifier và khả năng thích ứng của AI.|
|                                                                                                   |
|  KỊCH BẢN 3: SỰ CỐ ĐỨT CÁP VẬT LÝ & CƠ CHẾ PHỤC HỒI FAIL-OPEN (LINK FAILURE RESILIENCE)          |
|  - Đột ngột ngắt kết nối liên kết Spine c1 - Agg ag1 tại giây thứ 60 trong lúc đỉnh tải.           |
|  - Mục tiêu: Đo thời gian hội tụ lại đồ thị GAT (< 50ms) và kiểm chứng cơ chế Fail-Open (Zero Downtime). |
|                                                                                                   |
|  KỊCH BẢN 4: TẢI ĐỘT BIẾN CỤC BỘ & TCP INCAST (LOCALIZED INCAST & MICROBURST)                     |
|  - 16 Host đồng thời bơm các đợt Microburst 50KB về cùng 1 Host đích trong cửa sổ 10ms.            |
|  - Mục tiêu: Kiểm chứng cơ chế Fast-Path ECN Marking K=30KB ghìm nghẽn mà không gây rớt gói.     |
|                                                                                                   |
|  KỊCH BẢN 5: KHẢ NĂNG MỞ RỘNG & TẢI ĐỒNG THỜI CAO ĐỘ (SCALABILITY & CONCURRENCY STRESS)           |
|  - Tăng số lượng luồng đồng thời từ 1,000 lên 10,000 luồng.                                       |
|  - Mục tiêu: Khảo sát dung lượng bảng TCAM, bộ nhớ RAM Ryu Controller và hiện tượng rò rỉ bộ nhớ.|
+───────────────────────────────────────────────────────────────────────────────────────────────────+
```

---

## 4. HỆ THỐNG CHỈ SỐ KPI HỌC THUẬT & CÔNG THỨC TOÁN HỌC

### 4.1. Thời gian Hoàn thành Luồng Chuẩn hóa (Normalized Flow Completion Time - NormFCT)
Để so sánh công bằng giữa các luồng có kích thước khác nhau, FCT được chuẩn hóa theo thời gian lý tưởng không tải:
$$\text{Ideal FCT}(s) = RTT_{\text{base}} + \frac{s}{C_{\text{host}}}$$
$$\text{NormFCT} = \frac{\text{Actual FCT}(s)}{\text{Ideal FCT}(s)}$$
- **Mice Flow FCT ($s < 100\text{ KB}$):** Đánh giá Mean FCT và **Tail Latency ($P_{95}, P_{99}$)**. Mục tiêu: Giảm thiểu độ trễ đuôi để bảo vệ SLA ứng dụng Web RPC.
- **Elephant Flow FCT ($s \ge 100\text{ KB}$):** Đánh giá tốc độ truyền tải trung bình.

### 4.2. Hiệu suất Băng thông Mặt cắt Bisection (Bisection Bandwidth Efficiency $\eta$)
Đo lường mức độ khai thác tài nguyên phần cứng của mạng đa tầng Clos:
$$\eta = \frac{\sum_{e \in \text{Bisection}} \text{Throughput}_e}{\text{Total Bisection Capacity}} \times 100\%$$
- *Kỳ vọng:* Đạt $\eta > 85\%$ dưới tải nặng (vượt trội so với ECMP thường chỉ đạt $55\% - 65\%$ do xung đột băm).

### 4.3. Chỉ số Công bằng Tải Liên kết (Jain's Fairness Index $\mathcal{J}$)
Đánh giá mức độ san phẳng lưu lượng giữa $m$ liên kết Uplink song song:
$$\mathcal{J}(U_1, U_2, \dots, U_m) = \frac{\left(\sum_{i=1}^m U_i\right)^2}{m \sum_{i=1}^m U_i^2} \in \left[\frac{1}{m}, \ 1\right]$$
Trong đó $U_i$ là tỷ lệ sử dụng của liên kết $i$. Giá trị $\mathcal{J} \to 1.0$ thể hiện lưu lượng được phân bổ hoàn hảo không có liên kết nào bị quá tải hay bỏ đói.

### 4.4. Tỷ lệ Mất gói Mạng Toàn cục (Packet Loss Rate $P_{\text{loss}}$)
$$P_{\text{loss}} = \frac{\sum_{sw} \text{Tx\_Dropped}_{sw} + \text{Rx\_Dropped}_{sw}}{\sum_{sw} \text{Tx\_Packets}_{sw}} \times 100\%$$
- *Kỳ vọng:* Nhờ cơ chế ECN Marking Data Plane ($K=30\text{KB}$), tỷ lệ rớt gói giảm thiểu tối đa, đạt mức tiệm cận $0\%$.

---

## 5. THIẾT KẾ CẤU TRÚC MÃ NGUỒN TRONG `evaluate/`

Thư mục [`evaluate/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/evaluate/) được tổ chức thành các kịch bản thực nghiệm tự động hóa:

```
evaluate/
├── __init__.py
├── run_all_benchmarks.py      # Kịch bản Master tự động kích hoạt tuần tự 5 kịch bản và thu thập dữ liệu
├── scenario_1_saturation.py   # Kịch bản 1: Thử thách áp lực tải bão hòa 50% - 95%
├── scenario_2_data_shift.py   # Kịch bản 2: Dịch chuyển phân phối tải đột ngột giữa Web, Cache, Hadoop
├── scenario_3_link_failure.py # Kịch bản 3: Ngắt liên kết đột ngột và đo thời gian phục hồi Fail-Open
├── scenario_4_incast_burst.py # Kịch bản 4: Bơm bão xung đột biến TCP Incast 16-to-1
├── scenario_5_scalability.py  # Kịch bản 5: Đo kiểm tài nguyên TCAM và CPU/RAM dưới tải 10,000 luồng
├── baseline_ecmp_runner.py    # Kịch bản chạy thực nghiệm đối chứng ECMP chuẩn
├── metrics_calculator.py      # Module tính toán FCT, Tail Latency p95/p99, Jain's Index, Bisection BW
└── plot_academic_figures.py   # Script xuất toàn bộ biểu đồ học thuật 300 DPI định dạng PDF/PNG
```

---

## 6. QUY CHUẨN XUẤT BẢN BIỂU ĐỒ HỌC THUẬT (300 DPI PLOTS)

Hàm `generate_publication_plots()` xuất bản 5 đồ thị chuẩn LaTeX:
1. **Đồ thị CDF Phân vị FCT của Luồng Chuột:** Minh chứng việc cắt giảm Tail Latency $P_{99}$ từ $15\text{ ms} \to 1.8\text{ ms}$.
2. **Đồ thị Cột Bisection Bandwidth Efficiency:** So sánh trực quan giữa ECMP ($62\%$), Hedera ($74\%$), Presto ($81\%$) và SDN-AI ($89\%$).
3. **Đồ thị Chuỗi Thời gian Đứt cáp (Failover Timeline):** Thể hiện thời gian khôi phục thông lượng tức thì trong $<50\text{ ms}$ khi Spine c1 bị ngắt.
4. **Biểu đồ Hộp (Boxplot) Phân bố Tải Liên kết:** Minh chứng độ lệch chuẩn tải của SDN-AI co hẹp tối đa xung quanh mức trung bình.
5. **Đồ thị Tương quan ECN CE Marking vs Packet Loss:** Khẳng định ECN Data Plane ghìm hàng đợi thành công mà không gây rớt gói.

---

## 7. TIÊU CHÍ ĐÁNH GIÁ & NGHIỆM THU HỌC THUẬT (ACCEPTANCE GATES)

- [ ] **Tự động hóa $100\%$:** Kịch bản `run_all_benchmarks.py` thực thi trọn vẹn 5 kịch bản mà không cần can thiệp thủ công.
- [ ] **Mức cải thiện FCT Luồng Chuột:** Giảm tối thiểu $25\%$ Mean FCT và giảm tối thiểu $50\%$ Tail Latency $P_{99}$ so với ECMP.
- [ ] **Mức cải thiện Goodput Luồng Voi:** Tăng tối thiểu $35\%$ thông lượng hữu ích Goodput cho các luồng Voi lớn.
- [ ] **Tính Ổn định của Cơ chế Fail-Open:** Khi cố tình ngắt Controller hoặc AI engine, mạng tự động quay về chế độ ECMP Data Plane cơ bản với thời gian gián đoạn $\Delta t = 0\text{ ms}$.
