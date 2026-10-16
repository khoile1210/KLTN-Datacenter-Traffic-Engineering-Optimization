# BẢNG THEO DÕI TIẾN ĐỘ & CHECKLIST CÔNG VIỆC: SINH LƯU LƯỢNG DATACENTER

> **Dự án:** Research on Traffic Engineering Optimization in Data Center Networks Based on Software-Defined Network and Artificial Intelligence  
> **Tài liệu tham chiếu:** [`.Project Plans/UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md`](<file:///c:/Users/USER/Desktop/SDN%20KLTN/.Project%20Plans/UNIFIED_DCN_TRAFFIC_SIMULATION_MASTER_PLAN.md>)  
> **Mục tiêu:** Theo dõi chi tiết từng đầu việc từ số hóa ECDF Facebook, xây dựng các module sinh tải, thu thập telemetry cho đến phân tích phân vị và chốt ngưỡng gán nhãn Dataset cho mô hình AI.  
> **Trạng thái cập nhật:** 2026-10-16 (Khởi tạo lộ trình)

---

## I. TỔNG QUAN TIẾN ĐỘ THỰC HIỆN (PROGRESS OVERVIEW)

| Giai Đoạn | Tên Giai Đoạn | Trạng Thái | Số Đầu Việc | Tệp Tin Đầu Ra Chính |
| :---: | :--- | :---: | :---: | :--- |
| **GĐ 1** | Số Hóa 9 Biểu Đồ Thô Từ PDF Facebook | ⏳ Chờ dữ liệu | 0/3 | `controller/raw_digitized/*.csv` (9 files) |
| **GĐ 2** | Hòa Trộn Phân Phối ECDF Thống Nhất | ⏹ Chưa bắt đầu | 0/2 | `controller/cdf_profiles/*.csv` (3 files) |
| **GĐ 3** | Xây Dựng Bộ Lấy Mẫu Toàn Cục (Unified Sampler) | ⏹ Chưa bắt đầu | 0/2 | `controller/unified_sampler.py` |
| **GĐ 4** | Xây Dựng Engine Sinh Tải Nền (`iperf3 -n`) | ⏹ Chưa bắt đầu | 0/3 | `controller/traffic_generator.py` |
| **GĐ 5** | Xây Dựng Module Heavy Jitter Độc Lập | ⏹ Chưa bắt đầu | 0/2 | `controller/microburst_generator.py` |
| **GĐ 6** | Thực Nghiệm Thu Thập Dữ Liệu Thô (10 Features) | ⏹ Chưa bắt đầu | 0/2 | `results/traffic_flow_dataset_raw.csv` |
| **GĐ 7** | Phân Tích Phân Vị & Chốt Ngưỡng Ground-Truth | ⏹ Chưa bắt đầu | 0/2 | `controller/analyze_and_label_dataset.py` |
| **GĐ 8** | Kiểm Định Thống Kê Học Thuật (KS-Test) | ⏹ Chưa bắt đầu | 0/2 | `results/chart_validation_kstest.png` |

---

## II. CHI TIẾT TỪNG GIAI ĐOẠN & ĐẦU VIỆC (TASK BREAKDOWN)

### Giai Đoạn 1: Số Hóa 9 Biểu Đồ Thô Từ PDF Facebook

*Mục tiêu: Trích xuất tọa độ $(x, y)$ từ các biểu đồ thực nghiệm của bài báo Facebook (SIGCOMM 2015).*

- [ ] **TASK-1.1: Trích xuất 3 tệp tọa độ Flow Size (Figure 6):**
  - [ ] `controller/raw_digitized/flow_size/raw_flow_size_hadoop.csv` (Fig. 6c - đường ALL)
  - [ ] `controller/raw_digitized/flow_size/raw_flow_size_frontend.csv` (Fig. 6a - đường ALL)
  - [ ] `controller/raw_digitized/flow_size/raw_flow_size_cache.csv` (Fig. 6b - đường ALL)
  - *Tiêu chuẩn nghiệm thu (DoD):* Mỗi file chứa tối thiểu 50–100 điểm tọa độ `(value, cdf)`, đơn điệu tăng ngặt từ $0.0 \to 1.0$.

- [ ] **TASK-1.2: Trích xuất 3 tệp tọa độ Inter-Arrival Time (Figure 14):**
  - [ ] `controller/raw_digitized/inter_arrival/raw_inter_arrival_hadoop.csv` (Fig. 14 - Hadoop)
  - [ ] `controller/raw_digitized/inter_arrival/raw_inter_arrival_frontend.csv` (Fig. 14 - Web server)
  - [ ] `controller/raw_digitized/inter_arrival/raw_inter_arrival_cache.csv` (Fig. 14 - Cache-f)
  - *Tiêu chuẩn nghiệm thu (DoD):* Tọa độ thời gian $\Delta t$ tính bằng giây, xác suất từ $0.0 \to 1.0$.

- [ ] **TASK-1.3: Trích xuất 3 tệp tọa độ Flow Duration dùng đối soát (Figure 7):**
  - [ ] `controller/raw_digitized/flow_duration/raw_flow_duration_hadoop.csv` (Fig. 7c - ALL)
  - [ ] `controller/raw_digitized/flow_duration/raw_flow_duration_frontend.csv` (Fig. 7a - ALL)
  - [ ] `controller/raw_digitized/flow_duration/raw_flow_duration_cache.csv` (Fig. 7b - ALL)
  - *Tiêu chuẩn nghiệm thu (DoD):* Đầy đủ 9 tệp tin CSV thô đặt đúng cây thư mục `controller/raw_digitized/`.

---

### Giai Đoạn 2: Hòa Trộn Phân Phối ECDF Thống Nhất

*Mục tiêu: Áp dụng phép tổ hợp lồi có trọng số mẫu ($42.8\%$ Hadoop, $38.8\%$ Frontend, $18.4\%$ Cache).*

- [ ] **TASK-2.1: Lập trình script hòa trộn `blend_cdfs.py`:**
  - Viết module đọc 9 file CSV thô, tạo lưới phân vị $u \in [0.001, 0.999]$ (1.000 điểm).
  - Áp dụng nội suy logarit (Log-scale Interpolation) cho Flow Size và Flow Duration.
  - Tính tổng có trọng số theo công thức Mục 2.2 của Master Plan.
  - *Tệp thực thi:* `controller/blend_cdfs.py`

- [ ] **TASK-2.2: Xuất 3 hồ sơ phân phối ECDF thống nhất:**
  - [ ] `controller/cdf_profiles/cdf_flow_size_unified.csv`
  - [ ] `controller/cdf_profiles/cdf_inter_arrival_unified.csv`
  - [ ] `controller/cdf_profiles/cdf_flow_duration_unified.csv`
  - *Tiêu chuẩn nghiệm thu (DoD):* 3 file CSV có đúng 1.000 dòng phân vị chuẩn, xác suất tích lũy tăng ngặt từ $0.001 \to 0.999$.

---

### Giai Đoạn 3: Xây Dựng Bộ Lấy Mẫu Toàn Cục (Unified Sampler)

*Mục tiêu: Module toán học chịu trách nhiệm nạp hồ sơ ECDF và thực hiện nghịch đảo lấy mẫu kèm scale.*

- [ ] **TASK-3.1: Xây dựng tệp cấu hình tham số mở `traffic_config.json`:**
  - Định nghĩa các biến cấu hình: `C_host_mbps`, `CPU_host_cores`, `r_intra_rack`, `r_extra_rack`, `r_extra_dc`.
  - Để ngỏ giá trị `S_threshold_bytes: null` (sẽ được cập nhật sau khi phân tích).
  - *Tệp cấu hình:* `controller/traffic_config.json`

- [ ] **TASK-3.2: Lập trình lớp `UnifiedCdfSampler` trong `unified_sampler.py`:**
  - Nạp 3 file CDF thống nhất từ `cdf_profiles/`.
  - Cài đặt hàm `sample_flow_size()`: Lấy mẫu $u \sim \text{Uniform}(0, 1) \to s$, sau đó áp dụng **hàm scale liên tục chống nghịch đảo**:
    $$S_{\text{scaled}} = \begin{cases} s & s \le S_{\text{threshold}} \\ S_{\text{threshold}} + (s - S_{\text{threshold}}) \cdot \alpha & s > S_{\text{threshold}} \end{cases}$$
  - Cài đặt hàm `sample_inter_arrival()`: Giãn thời gian $\Delta t = \Delta t^{\text{paper}} \times D_{\text{arrival}}$.
  - Cài đặt hàm `sample_destination(src_host)`: Phân bổ ngẫu nhiên theo 3 vùng Locality ($7.2\% / 85.0\% / 7.8\%$).
  - *Tệp thực thi:* `controller/unified_sampler.py`

---

### Giai Đoạn 4: Xây Dựng Engine Sinh Tải Nền (`iperf3 -n`)

*Mục tiêu: Nâng cấp `traffic_generator.py` phát sinh lưu lượng nền thống nhất bằng `iperf3`.*

- [ ] **TASK-4.1: Đồng nhất cơ chế phát dữ liệu qua `iperf3 -n {S_scaled}`:**
  - Loại bỏ các lệnh ping lẻ tẻ và các tham số áp đặt thời gian cứng (`-t`, `-b`).
  - Thống nhất mọi luồng (cả Mice và Elephant) đều gửi đúng dung lượng $S_{\text{scaled}}$ bytes bằng lệnh:
    ```bash
    iperf3 -c {dst_ip} -p {port} -n {S_scaled}
    ```
  - Để hạ tầng mạng và giao thức TCP tự quyết định thời gian truyền và thông lượng thực tế.

- [ ] **TASK-4.2: Tích hợp vòng lặp điều phối nhịp phát phi phong tỏa:**
  - Kiểm soát số lượng luồng đồng thời (tránh cạn kiệt socket buffer trên máy ảo).
  - Áp dụng `time.sleep(Delta_t_scaled)` giữa các lượt phát sinh luồng.
  - Hỗ trợ dừng an toàn và dọn sạch tiến trình khi bấm `Ctrl + C`.

- [ ] **TASK-4.3: Kiểm thử độc lập vòng lặp sinh tải trên Containernet:**
  - Chạy thử 3–5 phút trên topo Spine-Leaf để đảm bảo không bị lỗi `server busy` và không gây nghẽn CPU.
  - *Tệp hoàn thiện:* `controller/traffic_generator.py`

---

### Giai Đoạn 5: Xây Dựng Module Heavy Jitter Độc Lập

*Mục tiêu: Tạo công cụ bơm Microburst tức thời $(< 10\text{ms})$ để kiểm thử ECN và hàng đợi switch.*

- [ ] **TASK-5.1: Lập trình `microburst_generator.py` bằng Python Socket:**
  - Sử dụng socket TCP trực tiếp với cờ `TCP_NODELAY = 1` và IP TOS `ECT(0) = 0x02`.
  - Lấy mẫu kích thước burst $20\text{ KB} \to 80\text{ KB}$.
  - Gửi dữ liệu ở tốc độ Full Line-rate kịch trần, kết thúc trong $1.5\text{ – }6\text{ ms}$.
  - Hỗ trợ chế độ Incast: Gửi dồn đồng loạt từ nhiều host về 1 host/rack mục tiêu.

- [ ] **TASK-5.2: Tự ghi nhận nhật ký Ground-Truth phía Client:**
  - Ghi trực tiếp ra file: `results/microburst_client_ground_truth.csv`.
  - Lưu các trường: `timestamp`, `src_ip`, `dst_ip`, `burst_bytes`, `duration_ms`, `is_burst=True`.
  - Khắc phục hoàn toàn việc lệch chu kỳ lấy mẫu 1.0s của Ryu Telemetry.
  - *Tệp thực thi:* `controller/microburst_generator.py`

---

### Giai Đoạn 6: Thực Nghiệm Thu Thập Dữ Liệu Thô (10 Features)

*Mục tiêu: Chạy đồng thời hệ thống mạng, bộ sinh tải và tầng quản trị để thu thập dataset thô.*

- [ ] **TASK-6.1: Khởi động toàn diện hệ thống DCN:**
  - Terminal 1: Ryu Controller (`controller.py`).
  - Terminal 2: Containernet Topo (`spine_leaf_topo.py`).
  - Terminal 3: Management Plane (`management_plane.py`).
  - Terminal 4: Background Traffic Generator (`traffic_generator.py`).

- [ ] **TASK-6.2: Thu thập Dataset thô trong 15–30 phút:**
  - Thu thập tối thiểu $5,000 - 10,000$ bản ghi Bi-flow đối xứng với đầy đủ 10 features và đường đi hop-by-hop.
  - *Tệp kết quả:* `results/traffic_flow_dataset_with_paths.csv`

---

### Giai Đoạn 7: Phân Tích Phân Vị & Chốt Ngưỡng Ground-Truth

*Mục tiêu: Quy trình 2 pha dựa trên dữ liệu thực tế để chọn ngưỡng phân tách luồng Voi/Chuột tối ưu.*

- [ ] **TASK-7.1: Xây dựng script phân tích phân vị `analyze_and_label_dataset.py`:**
  - Đọc file dataset thô vừa thu thập.
  - Vẽ biểu đồ Histogram và đường phân phối thực nghiệm ECDF của 2 đại lượng: `sbytes` (dung lượng) và `Sload` (tốc độ).
  - Tự động tính toán các mốc phân vị: $P80, P90, P95, P99$.
  - Xuất ra màn hình bảng khuyến nghị ngưỡng phân tách Elephant Flow.

- [ ] **TASK-7.2: Nhắc nhở người dùng lựa chọn ngưỡng & Gán nhãn Dataset chuẩn:**
  - 🔔 **ĐIỂM DỪNG QUYẾT ĐỊNH CỦA NGƯỜI DÙNG:** Người dùng xem xét biểu đồ phân vị và chốt giá trị `ELEPHANT_BYTES_THRESHOLD` và `ELEPHANT_RATE_THRESHOLD`.
  - Script tự động quét lại dataset, gán nhãn chuẩn Ground-Truth (`label = 1` cho Elephant, `label = 0` cho Mice).
  - Xuất tệp Dataset sẵn sàng cho huấn luyện mô hình Machine Learning: `results/final_labeled_flow_dataset.csv`.

---

### Giai Đoạn 8: Kiểm Định Thống Kê Học Thuật (KS-Test)

*Mục tiêu: Chứng minh tính khoa học và độ tương đồng phân phối để đưa vào Luận văn Tốt nghiệp.*

- [ ] **TASK-8.1: Thực hiện kiểm định Kolmogorov-Smirnov (KS-Test):**
  - Chạy hàm `scipy.stats.ks_2samp()` so sánh ECDF thực nghiệm đo được trên testbed với ECDF gốc từ bài báo Facebook.
  - Đạt tiêu chuẩn học thuật khi $p\text{-value} > 0.05$ (không có sự khác biệt có ý nghĩa thống kê).

- [ ] **TASK-8.2: Xuất biểu đồ so sánh chồng hình (Overlay Plot):**
  - Vẽ đồ thị so sánh đường nét đứt (Dữ liệu bài báo Facebook) và đường nét liền (Dữ liệu thực nghiệm Mininet).
  - *Tệp đồ thị xuất ra:* `results/chart_facebook_workload_validation.png`

---

## III. BẢNG THEO DÕI CÁC ĐIỂM QUYẾT ĐỊNH CỦA NGƯỜI DÙNG (USER DECISION LOG)

| STT | Điểm Quyết Định | Trạng Thái Hiện Tại | Tùy Chọn Của Người Dùng | Ghi Chú Kỹ Thuật |
| :---: | :--- | :---: | :--- | :--- |
| **1** | Băng thông máy chủ thực tế (`C_host`) | ⏳ Chờ quyết định | $20\text{ Mbps}$ (theo topo hiện tại) hoặc nâng lên $100\text{ Mbps}$ | Quyết định tỷ số scale $\alpha$ trong `traffic_config.json`. |
| **2** | Cung cấp ảnh/file PDF của 9 biểu đồ | ⏳ Chờ cung cấp | Gửi file PDF hoặc ảnh cắt của Fig. 6, 7, 14 | Điều kiện tiên quyết để bắt đầu Giai đoạn 1. |
| **3** | Chốt ngưỡng Elephant Flow Ground-Truth | ⏳ Để ngỏ hậu kỳ | Chọn mốc phân vị sau khi chạy `analyze_and_label_dataset.py` | Tránh gán nhãn tiên nghiệm khi chưa có dữ liệu thực nghiệm. |
