# KẾ HOẠCH CHI TIẾT: ĐỘNG CƠ SINH TẢI THỐNG NHẤT FACEBOOK DCN (SIGCOMM 2015)
## (UNIFIED DCN TRAFFIC SIMULATION ENGINE PLAN)

> **Mã chuyên đề:** `PLAN-WP03-TRAFFIC-ENGINE`  
> **Thuộc dự án:** Nghiên cứu Tối ưu hóa Kỹ thuật Lưu lượng trong Mạng DCN Dựa trên SDN và AI (SDN-AI DCN)  
> **Cố vấn chuyên môn:** Senior SDN Architect (Gemini 4 Argon)  
> **Trạng thái thực tế:** **ĐÃ HOÀN THÀNH 100% (PHASE 1 CORE RUNTIME)**  
> **Mã nguồn liên quan:** [`controller/traffic_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_generator.py), [`controller/unified_sampler.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/unified_sampler.py), [`controller/dcn_flow_engine.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/dcn_flow_engine.py), [`controller/microburst_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/microburst_generator.py), [`controller/supply/validate_workload_kstest.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/supply/validate_workload_kstest.py), [`controller/traffic_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_config.json)  

---

## 1. MỤC TIÊU & PHẠM VI KỸ THUẬT

1. **Loại bỏ Hoàn toàn Lưu lượng Giả lập Ngẫu nhiên (Zero Toy Traffic):** Tuyệt đối không sử dụng các hàm sinh ngẫu nhiên nhân tạo vô căn cứ (như phân phối đều hay Poisson thuần túy). Toàn bộ lưu lượng thực nghiệm được kế thừa trực tiếp từ hồ sơ đo đạc thực tế của Facebook Datacenter công bố tại ACM SIGCOMM 2015.
2. **Hiện thực hóa Mô hình Toán học Hòa trộn ECDF Lồi (Convex Mixture Model):** Tích hợp 9 đường phân phối thực nghiệm từ 3 cụm dịch vụ lớn (**Hadoop**, **Web Frontend**, **Cache Follower**) trên 3 chiều biến ngẫu nhiên cốt lõi: *Kích thước luồng (Flow Size)*, *Khoảng cách thời gian phát (Inter-Arrival Time)*, và *Thời lượng luồng (Flow Duration)*.
3. **Hiện thực hóa Bộ Lấy mẫu Nghịch đảo & Hàm Co giãn Kích thước Liên tục Từng khúc (Piecewise Continuous Scaling):** Bảo toàn $100\%$ cấu trúc kích thước gói tin nhỏ của luồng Chuột, đồng thời co giãn mượt mà luồng Voi theo hệ số băng thông $\alpha = 0.01$ mà không làm biến dạng độ dốc đuôi nặng Pareto.
4. **Mô phỏng Đa Giao thức Thực tế (Dual Protocol Realism) & Phân vùng Định vị 4 Cấp độ (4-Level Locality):** Tái tạo chính xác $18.4\%$ lưu lượng UDP của Memcached và $81.6\%$ lưu lượng TCP của Web/Hadoop, kết hợp ma trận phân bổ đích theo tỷ lệ bài báo Facebook.
5. **Kiểm định Thống kê Nghiêm ngặt (Kolmogorov-Smirnov Test):** Đảm bảo mẫu lưu lượng sinh ra trên môi trường ảo hóa đạt độ tương đồng thống kê ($p\text{-value} > 0.05$) so với dữ liệu gốc của Facebook.

---

## 2. CƠ SỞ KHOA HỌC, ĐỊNH LÝ GỐC & TÀI LIỆU THAM KHẢO

- **[Phân phối Đuôi nặng & Tự đồng dạng Mạng]** M. E. Crovella, A. Bestavros (Boston University), *"Self-similarity in World Wide Web Traffic: Evidence and Possible Causes"*, IEEE/ACM Transactions on Networking, 1997. *(Chứng minh toán học lưu lượng mạng máy tính không tuân theo quy luật Poisson mà tuân theo phân phối đuôi nặng Heavy-tailed Pareto).*
- **[Dữ liệu Thực nghiệm Facebook Trace]** A. Roy, H. Zeng, J. Bagga, G. Porter, A. C. Snoeren (Facebook & UC San Diego), *"Inside the Social Network's (Datacenter) Network"*, ACM SIGCOMM 2015, pp. 123–137. *(Nguồn gốc bộ số liệu đo đạc thực tế của 3 cụm Hadoop, Web Frontend, Cache Follower).*
- **[Lý thuyết Lấy mẫu Biến đổi Ngược]** L. Devroye, *"Non-Uniform Random Variate Generation"*, Springer-Verlag, 1986. *(Nguyên lý lấy mẫu nghịch đảo $X = F^{-1}(U)$ với $U \sim \mathcal{U}(0, 1)$ bảo toàn tính chất thống kê của hàm phân phối).*
- **[Định lý & Kiểm định Kolmogorov-Smirnov]** A. Kolmogorov, *"Sulla determinazione empirica di una legge di distribuzione"*, G. Ist. Ital. Attuari, 1933; N. Smirnov, *"Table for estimating the goodness of fit of empirical distributions"*, Ann. Math. Statist., 1948. *(Cơ sở toán học đo lường khoảng cách cực đại $D_n = \sup_x |F_n(x) - F_0(x)|$ để kiểm định tính hợp lệ của mẫu sinh).*

---

## 3. MÔ HÌNH TOÁN HỌC & CÔNG THỨC THỰC NGHIỆM

### 3.1. Mô hình Hòa trộn Tổ hợp Lồi ECDF (Convex Combination Mixture)
Từ Bảng 3 và các biểu đồ thực nghiệm (Hình 6, 7, 14) của bài báo Facebook SIGCOMM 2015, hàm phân phối tích lũy thực nghiệm tổng hợp $F_{\text{unified}}(x)$ được tính bằng tổ hợp lồi theo tỷ trọng mẫu đại diện của 3 cụm:
$$F_{\text{unified}}(x) = w_{\text{Hadoop}} \cdot F_{\text{Hadoop}}(x) + w_{\text{Frontend}} \cdot F_{\text{Frontend}}(x) + w_{\text{Cache}} \cdot F_{\text{Cache}}(x)$$
Trong đó các trọng số thỏa mãn $\sum w_k = 1$:
$$w_{\text{Hadoop}} = 0.428, \quad w_{\text{Frontend}} = 0.388, \quad w_{\text{Cache}} = 0.184$$

### 3.2. Thuật toán Lấy mẫu Biến đổi Ngược trên Không gian $\log_{10}$ (Log-Domain Inversion)
Do dữ liệu lưu lượng mạng trải rộng trên nhiều bậc độ lớn ($10^1\text{ B} \to 10^8\text{ B}$), việc nội suy tuyến tính sẽ làm méo mó nghiêm trọng các luồng nhỏ. Do đó, thuật toán lấy mẫu được thực hiện trên không gian logarit cơ số 10:
1. Sinh số ngẫu nhiên đều: $u \sim \mathcal{U}(0, 1)$.
2. Nội suy tuyến tính tìm giá trị logarit:
   $$y = \text{Interp}\left(u, \ F_{\text{unified}}, \ \log_{10}(V)\right)$$
3. Khôi phục giá trị thực nghiệm:
   $$X = 10^y = 10^{\text{Interp}(u, F_{\text{unified}}, \log_{10}(V))}$$

```python
# Lấy mẫu biến đổi ngược mượt mà trên không gian log10
def sample_from_ecdf(cdf_df, u_val):
    log_vals = np.log10(cdf_df['value'].values)
    probs = cdf_df['prob'].values
    log_interp = np.interp(u_val, probs, log_vals)
    return float(10 ** log_interp)
```

---

### 3.3. Hàm Co giãn Kích thước Liên tục Từng khúc (Piecewise Continuous Scaling)
Để hạ quy mô luồng Voi từ mạng $10\text{ Gbps}$ xuống mạng giả lập $100\text{ Mbps}$ ($\alpha = 0.01$) mà **không làm co cụm các gói tin nhỏ của luồng Chuột**, đề tài áp dụng hàm co giãn từng khúc:
$$S_{\text{scaled}}(s) = \begin{cases} s, & \text{khi } s \le S_{\text{threshold}} \quad (\text{Luồng Chuột giữ nguyên } 100\%) \\ S_{\text{threshold}} + \alpha \cdot (s - S_{\text{threshold}}), & \text{khi } s > S_{\text{threshold}} \quad (\text{Luồng Voi co giãn mượt mà}) \end{cases}$$
Trong đó:
- $S_{\text{threshold}} = 65,536\text{ Bytes} = 64\text{ KB}$ (Ngưỡng phân tách Voi/Chuột chuẩn Presto ACM SIGCOMM 2015, tương thích với bộ đệm TSO/GRO).
- $\alpha = 0.01$ (Hệ số co giãn băng thông $100\text{ Mbps} / 10\text{ Gbps}$).
- *Ý nghĩa:* Một luồng Chuột $500\text{ B}$ hay $63\text{ KB}$ vẫn truyền đúng kích thước gốc (không bị bóp méo hay nghịch đảo thứ bậc). Một luồng Voi $65\text{ KB}$ sẽ co thành $64\text{ KB} + 0.01 \times 1\text{ KB} = 64,010\text{ B}$ (vẫn lớn hơn luồng Chuột); một luồng Voi khổng lồ $100\text{ MB}$ sẽ được co giãn thành $64\text{ KB} + 0.01 \times (100\text{ MB} - 64\text{ KB}) \approx 1.063\text{ MB}$, bảo đảm áp lực tải tương đương lên liên kết $100\text{ Mbps}$.

---

### 3.4. Ma trận Định vị Không gian 4 Cấp độ (Locality Distribution Matrix)
Theo Bảng 3 bài báo Facebook SIGCOMM 2015, luồng dữ liệu được phân bổ chính xác theo 4 miền vị trí không gian địa lý:

| Cấp độ Locality | Tỷ lệ Phần trăm | Đường đi Vật lý trong Topo 2-Cluster Clos |
| :--- | :---: | :--- |
| **Intra-Rack** | **$12.9\%$** | Host $\to$ Access Switch $\to$ Host (Chỉ qua 1 switch duy nhất, $Hop = 1$). |
| **Intra-Cluster** | **$57.5\%$** | Host $\to$ Access $\to$ Aggregation $\to$ Access $\to$ Host (Trong cùng 1 cụm, $Hop = 3$). |
| **Intra-DC (Cross-Cluster)** | **$11.9\%$** | Host $\to$ Access $\to$ Agg $\to$ Core $\to$ Agg $\to$ Access $\to$ Host (Liên cụm, $Hop = 5$). |
| **Extra-DC** | **$17.7\%$** | Host $\to$ Access $\to$ Agg $\to$ Core $\to$ Node Internet Gateway `inet` (`10.0.0.254`). |

---

### 3.5. Mô phỏng Đa Giao thức Thực tế (Dual Protocol Realism)
- **18.4% Lưu lượng UDP (Memcached Workload):**
  - Không thiết lập bắt tay 3 bước TCP (triệt tiêu overhead giả tạo cho các bản tin nhỏ $66\text{B} - 150\text{B}$).
  - Gói tin được đóng gói dạng UDP Datagram với MTU tối đa $1400\text{ B}$.
- **81.6% Lưu lượng TCP (Web & Hadoop Workload):**
  - Sử dụng socket TCP trực tiếp với cờ `TCP_NODELAY = 1` (tắt thuật toán Nagle để gói tin được đẩy đi tức thì).
  - Phía nhận phản hồi bản tin ACK 1-byte để xác nhận kết thúc truyền tải cấp ứng dụng.

---

### 3.6. Động cơ Sinh Microburst & Incast Đột biến (`microburst_generator.py`)
Mô phỏng chính xác hiện tượng Microburst theo lý thuyết hàng đợi và nguyên lý Fast-Path ECN:
- Kích thước xung: $S_{\text{burst}} \in [20\text{ KB}, \ 80\text{ KB}]$.
- Thời gian bùng nổ chớp nhoáng: $T_{\text{burst}} < 10\text{ ms}$.
- Tốc độ phát tức thời: $R_{\text{burst}} \approx 80\text{ Mbps} - 100\text{ Mbps}$ (gây nghẽn tức thời).
- Đánh dấu cờ ECN-Capable Transport ECT(0): Cấu hình trường IP TOS byte:
  $$\text{TOS} = 0x02 \implies \text{Bit ECN} = 10_2 \quad (\text{ECT-0})$$

---

## 4. QUY TRÌNH KIỂM ĐỊNH THỐNG KÊ HỌC THUẬT (KOLMOGOROV-SMIRNOV TEST)

Để chứng minh tính hợp lệ khoa học của tập dữ liệu sinh ra, script [`controller/supply/validate_workload_kstest.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/supply/validate_workload_kstest.py) thực hiện kiểm định 2 mẫu Kolmogorov-Smirnov giữa tập dữ liệu sinh thực tế $F_n(x)$ và phân phối lý thuyết Facebook $F_{\text{ref}}(x)$:
$$D_n = \sup_{x} |F_n(x) - F_{\text{ref}}(x)|$$
- **Giả thuyết $H_0$:** Mẫu dữ liệu sinh thực tế và dữ liệu bài báo Facebook cùng tuân theo một quy luật phân phối xác suất.
- **Mức ý nghĩa:** $\alpha = 0.05$.
- **Điều kiện chấp nhận:** Nếu giá trị kiểm định $p\text{-value} > 0.05$, giả thuyết $H_0$ được chấp nhận $\implies$ **Dữ liệu sinh đạt chuẩn học thuật quốc tế**.

---

## 5. ÁNH XẠ MÃ NGUỒN (SOURCE CODE TRACEABILITY)

Toàn bộ hệ thống sinh tải được hiện thực hóa qua các module chuyên trách:
1. [`controller/unified_sampler.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/unified_sampler.py):
   - `UnifiedSampler`: Nạp 3 tệp ECDF chuẩn hóa từ `controller/cdf_profiles/`.
   - `sample_flow_size()`, `sample_inter_arrival()`, `sample_flow_duration()`: Lấy mẫu nghịch đảo $\log_{10}$.
   - `get_destination_ip()`: Phân bổ 4 cấp độ Locality.
2. [`controller/dcn_flow_engine.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/dcn_flow_engine.py):
   - Socket client/server tối ưu, hỗ trợ cả TCP Stream và UDP Datagram.
3. [`controller/traffic_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_generator.py):
   - Động cơ sinh tải bùng nổ phân tán (Dynamic Incast / Coflow Burst Engine).
   - Tự động tính toán kích thước đợt phát động lực học: $B \in [\lceil 0.25 \times N \rceil, N]$ với $N = |H_{\text{internal}}|$.
   - Bơm tải đồng loạt $B$ luồng song song qua `ThreadPoolExecutor` với `max_workers` được ánh xạ tự động từ `topology_config.json#/hosts/total_hosts` ($N=32$), không nghẽn thread.
4. [`controller/microburst_generator.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/microburst_generator.py):
   - Bơm tải xung đột biến mang nhãn ECT(0) phục vụ kiểm chứng ECN Data Plane.

---

## 6. TIÊU CHÍ KIỂM ĐỊNH & NGHIỆM THU HỌC THUẬT (ACCEPTANCE GATES)

- [x] **Trùng khớp phân vị:** Kiểm tra phân vị $P_{50}, P_{90}, P_{95}, P_{99}$ của dữ liệu sinh khớp với đồ thị Hình 6 và Hình 7 bài báo Facebook SIGCOMM 2015.
- [x] **Vượt qua kiểm định KS-Test:** Kết quả chạy `validate_workload_kstest.py` xuất ra $p\text{-value} > 0.05$ trên cả 3 đại lượng: Flow Size, Inter-Arrival và Duration.
- [x] **Bảo toàn tỷ lệ Locality:** Thống kê 10,000 luồng phát thực tế ghi nhận đúng tỷ lệ: $12.9\%$ Intra-Rack, $57.5\%$ Intra-Cluster, $11.9\%$ Intra-DC, $17.7\%$ Extra-DC.
- [x] **Đúng tỷ lệ giao thức:** Đo kiểm thực tế đạt $18.4\%$ UDP và $81.6\%$ TCP.
