# KẾ HOẠCH & ĐẶC TẢ KỸ THUẬT: SINH LƯU LƯỢNG DATACENTER THỐNG NHẤT

> **Tài liệu tham chiếu gốc:** _Inside the Social Network’s (Datacenter) Network_ (ACM SIGCOMM 2015)
> **Tập tin PDF phân tích:** [`Documents/Inside the Social Network’s (Datacenter) Network.pdf`](<file:///c:/Users/USER/Desktop/Document%20Analyzing/Documents/Inside%20the%20Social%20Network’s%20(Datacenter)%20Network.pdf>)
> **Phạm vi tài liệu:** Đặc tả kỹ thuật module **Sinh Lưu Lượng (Traffic Generation)** cho mạng DCN SDN Spine-Leaf. Bao gồm: Cơ chế hòa trộn ECDF thống nhất, mô hình 3 vùng locality, hệ công thức co giãn thứ nguyên tham số mở, kiến trúc tách rời (Decoupled Engine) giữa lưu lượng nền (`iperf3`) và luồng đột biến (`microburst`), cùng quy trình xác định ngưỡng Ground-Truth hướng dữ liệu (Data-Driven Thresholding).

---

## MỤC LỤC

1. [Bản Chất Lưu Lượng Thống Nhất](#1-bản-chất-lưu-lượng-thống-nhất)
2. [Dữ Liệu Cần Chuẩn Bị](#2-dữ-liệu-cần-chuẩn-bị)
   - [2.1. Dữ Liệu Số Hóa Thô Từ Biểu Đồ PDF Gốc](#21-dữ-liệu-số-hóa-thô-từ-biểu-đồ-pdf-gốc)
   - [2.2. Cơ Sở Toán Học Hòa Trộn Phân Phối Đa Biến](#22-cơ-sở-toán-học-hòa-trộn-phân-phối-đa-biến)
   - [2.3. Dữ Liệu Hồ Sơ Thống Nhất Xuất Ra](#23-dữ-liệu-hồ-sơ-thống-nhất-xuất-ra)
3. [Dữ Liệu Cần Scale &amp; Hệ Tham Số Mở (Configurable Parameters)](#3-dữ-liệu-cần-scale--hệ-tham-số-mở-configurable-parameters)
   - [3.1. Phân Loại Dữ Liệu Cần Scale](#31-phân-loại-dữ-liệu-cần-scale)
   - [3.2. Hệ Biến Số Đầu Vào Của Bộ Sinh Tải](#32-hệ-biến-số-đầu-vào-của-bộ-sinh-tải)
   - [3.3. Ma Trận Quy Đổi &amp; Co Giãn Tài Nguyên Phần Cứng Ảo Hóa (Hardware Resource Scaling Matrix)](#33-ma-trận-quy-đổi--co-giãn-tài-nguyên-phần-cứng-ảo-hóa-hardware-resource-scaling-matrix)
4. [Công Thức Scale &amp; Dẫn Chứng Khoa Học](#4-công-thức-scale--dẫn-chứng-khoa-học)
   - [4.1. Hệ số co giãn băng thông](#41-hệ-số-co-giãn-băng-thông-alpha)
   - [4.2. Tỷ lệ hạ tài nguyên CPU &amp; Hệ số giãn nhịp phát](#42-tỷ-lệ-hạ-tài-nguyên-phần-cứng-beta_textcpu--hệ-số-giãn-nhịp-phát-d_textarrival)
   - [4.3. Co giãn khoảng thời gian giữa các luồng](#43-công-thức-co-giãn-thời-gian-giữa-các-luồng-delta-t_textarrival)
   - [4.4. Co giãn kích thước luồng liên tục chống nghịch đảo (Piecewise Continuous Scaling)](#44-công-thức-co-giãn-kích-thước-luồng-liên-tục-chống-nghịch-đảo-piecewise-continuous-scaling)
   - [4.5. Thuật toán phân bổ 3 vùng Locality](#45-thuật-toán-xác-định-vùng-đích-3-nhánh-3-way-locality-routing-algorithm)
   - [4.6. Phân tách Module: Heavy Jitter / Ephemeral Microburst Injection](#46-phân-tách-module-heavy-jitter--ephemeral-microburst-injection)
   - [4.7. Quy trình 2 pha xác định ngưỡng Ground-Truth (Data-Driven Thresholding)](#47-quy-trình-2-pha-xác-định-ngưỡng-ground-truth-cho-classifier-data-driven-thresholding)
5. [Cách Thức Vận Hành Bộ Đôi Sinh Tải (Traffic Generation Architecture)](#5-cách-thức-vận-hành-bộ-đôi-sinh-tải-traffic-generation-architecture)
   - [5.1. Engine Chính: `traffic_generator.py` (Lưu lượng nền thống nhất iperf3)](#51-engine-chính-traffic_generatorpy-lưu-lượng-nền-thống-nhất-iperf3)
   - [5.2. Engine Phụ: `microburst_generator.py` (Bơm Heavy Jitter độc lập)](#52-engine-phụ-microburst_generatorpy-bơm-heavy-jitter-độc-lập)
6. [Cấu Trúc Tệp Tin Module Sinh Tải &amp; Huấn Luyện AI](#6-cấu-trúc-tệp-tin-module-sinh-tải--huấn-luyện-ai)

---

## 1. BẢN CHẤT LƯU LƯỢNG THỐNG NHẤT

Thay vì chia máy chủ thành các nhóm chức năng cứng nhắc (Web server, Cache node, Hadoop host) – vốn rất gượng ép trên các topo giả lập nhỏ (8–16 hosts), mô hình này coi **toàn bộ trung tâm dữ liệu là một thể thống nhất**:

- Mọi máy chủ đều là một **DCN Node** đồng nhất.
- Mỗi luồng sinh ra đều được lấy mẫu từ **Hồ sơ Phân phối Tích lũy Thống nhất (Unified ECDF)** hòa trộn toán học từ 3 workload tiêu biểu trong bài báo Facebook: **Hadoop**, **Frontend (Web)**, và **Cache**.
- Mô hình tách bạch rõ giữa **Lưu lượng nền tự nhiên (Background Workload)** do `iperf3` phụ trách và **Lưu lượng đột biến (Microburst)** do module chuyên dụng phụ trách.

---

## 2. DỮ LIỆU CẦN CHUẨN BỊ

### 2.1. Dữ Liệu Số Hóa Thô Từ Biểu Đồ PDF Gốc

Trích xuất tối thiểu $50 - 100$ điểm tọa độ thực nghiệm $(x, y)$ trực tiếp từ file PDF gốc [`Documents/Inside the Social Network’s (Datacenter) Network.pdf`](<file:///c:/Users/USER/Desktop/Document%20Analyzing/Documents/Inside%20the%20Social%20Network’s%20(Datacenter)%20Network.pdf>) để lưu thành **9 tập tin CSV thô độc lập** (cấu trúc 2 cột: `value`, `cdf`):

| Đại Lượng Đo Lường             | Biểu Đồ Bài Báo | Cụm Dịch Vụ & Đường Cong       | Vị Trí Trong PDF (Trang PDF / Trang In) | Tệp Tin Dữ Liệu Thô Xuất Ra      |
| :----------------------------- | :-------------- | :----------------------------- | :-------------------------------------: | :------------------------------- |
| **Flow Size**                  | Figure 6(c)     | Hadoop (đường ALL)             |         Trang 8 (Trang in 130)          | `raw_flow_size_hadoop.csv`       |
| **Flow Size**                  | Figure 6(a)     | Frontend (đường ALL)           |         Trang 8 (Trang in 130)          | `raw_flow_size_frontend.csv`     |
| **Flow Size**                  | Figure 6(b)     | Cache follower (đường ALL)     |         Trang 8 (Trang in 130)          | `raw_flow_size_cache.csv`        |
| **Flow Inter-Arrival Time**    | Figure 14       | Hadoop (đường Hadoop)          |         Trang 12 (Trang in 134)         | `raw_inter_arrival_hadoop.csv`   |
| **Flow Inter-Arrival Time**    | Figure 14       | Frontend (đường Web server)    |         Trang 12 (Trang in 134)         | `raw_inter_arrival_frontend.csv` |
| **Flow Inter-Arrival Time**    | Figure 14       | Cache follower (đường Cache-f) |         Trang 12 (Trang in 134)         | `raw_inter_arrival_cache.csv`    |
| **Flow Duration** _(đối soát)_ | Figure 7(c)     | Hadoop (đường ALL)             |         Trang 8 (Trang in 130)          | `raw_flow_duration_hadoop.csv`   |
| **Flow Duration** _(đối soát)_ | Figure 7(a)     | Frontend (đường ALL)           |         Trang 8 (Trang in 130)          | `raw_flow_duration_frontend.csv` |
| **Flow Duration** _(đối soát)_ | Figure 7(b)     | Cache follower (đường ALL)     |         Trang 8 (Trang in 130)          | `raw_flow_duration_cache.csv`    |

---

### 2.2. Cơ Sở Toán Học Hòa Trộn Phân Phối Đa Biến

#### A. Chuẩn hóa trọng số mẫu đại diện từ Table 3 ($55.4\% \to 100\%$):

Theo **Table 3 (Trang in 128, Trang PDF 6)**, 3 dịch vụ có dữ liệu ECDF thực nghiệm chiếm tỷ trọng mẫu $W_{\text{total}} = 23.7\% + 21.5\% + 10.2\% = \mathbf{55.4\%}$. Áp dụng phép chiếu chuẩn hóa xác suất:

$$
w_{\text{Hadoop}} = \frac{23.7\%}{55.4\%} = \mathbf{0.428 \ (42.8\%)}
$$

$$
w_{\text{Frontend}} = \frac{21.5\%}{55.4\%} = \mathbf{0.388 \ (38.8\%)}
$$

$$
w_{\text{Cache}} = \frac{10.2\%}{55.4\%} = \mathbf{0.184 \ (18.4\%)}
$$

#### B. Phép tổ hợp lồi trên đường cong "ALL":

Tạo lưới phân vị chuẩn $u \in [0.001, 0.999]$ (1.000 điểm) và áp dụng **Nội suy Logarit (Log-scale Interpolation)** để tính giá trị phân vị của hàm tích lũy thống nhất:

1. **Hàm Kích Thước Luồng Thống Nhất ($F_{\text{flow\_size}}^{\text{unified}}$):**

   $$
   F_{\text{flow\_size}}^{\text{unified}}(s) = 0.428 \cdot F_{\text{size, Hadoop}}^{\text{ALL}}(s) + 0.388 \cdot F_{\text{size, Frontend}}^{\text{ALL}}(s) + 0.184 \cdot F_{\text{size, Cache}}^{\text{ALL}}(s)
   $$

2. **Hàm Thời Gian Giữa Các Luồng Thống Nhất ($F_{\text{inter\_arrival}}^{\text{unified}}$):**

   $$
   F_{\text{inter\_arrival}}^{\text{unified}}(t) = 0.428 \cdot F_{\text{arr, Hadoop}}(t) + 0.388 \cdot F_{\text{arr, Frontend}}(t) + 0.184 \cdot F_{\text{arr, Cache}}(t)
   $$

3. **Hàm Thời Lượng Luồng Thống Nhất ($F_{\text{flow\_duration}}^{\text{unified}}$) — Thước đo đối soát:**

   $$
   F_{\text{flow\_duration}}^{\text{unified}}(d) = 0.428 \cdot F_{\text{dur, Hadoop}}^{\text{ALL}}(d) + 0.388 \cdot F_{\text{dur, Frontend}}^{\text{ALL}}(d) + 0.184 \cdot F_{\text{dur, Cache}}^{\text{ALL}}(d)
   $$

#### C. Cơ Sở & Cách Tính Tỷ Lệ Chọn Máy Đích (3 Vùng Locality):

Không gian máy đích được phân chia thành **3 vùng địa phương hóa độc lập**:

1. **Intra-Rack ($r_{\text{intra\_rack}}$):** Lưu lượng nội bộ tủ rack (Host nguồn và Host đích cùng cắm vào một switch Top-of-Rack / Access switch. Với kiến trúc mặc định **4 hosts/rack** — ví dụ giữa `h1_1` và `h1_2` trên rack 1 — gói tin chỉ chuyển mạch nội bộ tại switch `a1`, **không đi qua uplink và hoàn toàn không chạm vào switch tầng Aggregation/Core**).
2. **Extra-Rack ($r_{\text{extra\_rack}}$):** Lưu lượng xuyên rack nhưng vẫn nằm trong phạm vi Trung tâm dữ liệu (giữa các host thuộc rack khác nhau, ví dụ `h1_1` gửi sang `h3_2`). Gói tin **cạnh tranh băng thông uplink và bộ đệm tại switch Aggregation và Core**.
3. **Extra-Datacenter ($r_{\text{extra\_dc}}$):** Lưu lượng đi ra ngoài Trung tâm dữ liệu (tương ứng với host `inet` hoặc External Gateway trong mô hình Containernet).

**Bảng Tỷ Lệ Chuẩn Hóa Theo 3 Workload Đại Diện (Table 3 Facebook):**

$$
r_{\text{intra\_rack}} = \mathbf{0.072 \ (7.2\%)}, \quad r_{\text{extra\_rack}} = \mathbf{0.850 \ (85.0\%)}, \quad r_{\text{extra\_dc}} = \mathbf{0.078 \ (7.8\%)}
$$

_(Tổng xác suất điều kiện: $0.072 + 0.850 + 0.078 = 1.000$. Nếu thử nghiệm theo Cột ALL toàn mạng thì tỷ lệ tương ứng là: $12.9\% / 69.4\% / 17.7\%$)_.

---

### 2.3. Dữ Liệu Hồ Sơ Thống Nhất Xuất Ra

Sau khi hòa trộn toán học, bộ sinh tải chỉ cần nạp **3 tập tin hồ sơ phân phối duy nhất**:

1. `cdf_flow_size_unified.csv`: Dữ liệu phân vị dung lượng luồng thống nhất (Đầu vào sinh dữ liệu TCP).
2. `cdf_inter_arrival_unified.csv`: Dữ liệu phân vị thời gian nghỉ thống nhất (Đầu vào điều phối nhịp phát).
3. `cdf_flow_duration_unified.csv`: Dữ liệu thời lượng luồng thống nhất (Dùng để kiểm định Kolmogorov-Smirnov đối soát sau khi chạy).

---

## 3. DỮ LIỆU CẦN SCALE & HỆ THAM SỐ MỞ (CONFIGURABLE PARAMETERS)

### 3.1. Phân Loại Dữ Liệu Cần Scale

| Đại Lượng                                                                                           | Có Scale Không? | Bản Chất Co Giãn                                                                                | Nguyên Nhân Kỹ Thuật                                                                                                                                                                    |
| :-------------------------------------------------------------------------------------------------- | :-------------: | :---------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Băng thông máy chủ ($C_{\text{host}}$)**                                                          |     **CÓ**      | Tuyến tính theo tỷ số băng thông $\alpha$                                                       | Băng thông bài báo là $10\text{ Gbps}$, môi trường ảo hóa hạ xuống thang Mbps theo cấu hình thực tế.                                                                                    |
| **Thời gian giữa các luồng ($\Delta t_{\text{arrival}}$)**                                          |     **CÓ**      | Giãn thời gian theo tỷ lệ hạ tài nguyên phần cứng ($D_{\text{arrival}} = 1/\beta_{\text{CPU}}$) | Giảm tần suất gọi tiến trình tương ứng với năng lực CPU ảo hóa để chống bão hòa ngắt và bảo toàn độ tải CPU.                                                                            |
| **Luồng lớn / Heavy Hitters ($s > S_{\text{threshold}}$)**                                          |     **CÓ**      | Co nhỏ liên tục theo tỷ số $\alpha$                                                             | Tránh luồng chiếm dụng link hàng chục phút; thời gian truyền $T_{\text{trans}} = \frac{s \cdot \alpha}{C \cdot \alpha} = \frac{s}{C^{\text{paper}}}$ được bảo toàn tương đương thực tế. |
| **Luồng nhỏ / Small Flows ($s \le S_{\text{threshold}}$)**                                          |    **KHÔNG**    | Giữ nguyên $100\%$ kích thước ($S = s$)                                                         | Bảo toàn cấu trúc TCP Header ($40-60\text{B}$), gói MTU và pha Slow-Start ($IW10$). Thời lượng luồng tự động co giãn theo RTT của mạng ảo hóa.                                          |
| **Tỷ lệ 3 vùng chọn đích ($r_{\text{intra\_rack}}, r_{\text{extra\_rack}}, r_{\text{extra\_dc}}$)** |    **KHÔNG**    | Giữ nguyên bộ tỷ lệ thực nghiệm bài báo                                                         | Đảm bảo đúng tỷ lệ phân bổ luồng nội rack, xuyên rack và đi ra ngoài Internet.                                                                                                          |
| **Heavy Jitter / Ephemeral Microbursts**                                                            |     **CÓ**      | Tách riêng ra script độc lập (`microburst_generator.py`)                                        | Bơm tải đột biến ngắn ($< 10\text{ms}$) để kiểm thử hàng đợi OVS/ECN mà không làm nhiễu tiến trình sinh tải nền.                                                                        |

---

### 3.2. Hệ Biến Số Đầu Vào Của Bộ Sinh Tải

> [!IMPORTANT]
> **Toàn bộ các tham số dưới đây được thiết kế mở (Configurable Parameters):**
> Người dùng sẽ tự tính toán và chỉ định trong tệp cấu hình `traffic_config.json` hoặc tham số dòng lệnh trước khi chạy thực nghiệm. Các giá trị bên dưới là **giá trị đề xuất mẫu (Default / Recommended Baselines)**:

| Tên Biến         |    Đơn Vị    | Ý Nghĩa Kỹ Thuật                                                       | Tính Chất Quyết Định                         |    Giá Trị Mặc Định Mẫu    |
| :--------------- | :----------: | :--------------------------------------------------------------------- | :------------------------------------------- | :------------------------: |
| `C_host`         |     Mbps     | Băng thông link máy chủ trong mạng ảo hóa                              | **Người dùng tự chỉ định theo topo**         |   $20.0$ (hoặc $100.0$)    |
| `CPU_host`       | Cores / vCPU | Năng lực CPU cấp phát cho 1 máy chủ ảo                                 | **Người dùng tự chỉ định theo CPU máy thật** | $1.0$ (hoặc hạn ngạch CFS) |
| `S_threshold`    |    Bytes     | Ngưỡng phân tách luồng: các luồng lớn hơn ngưỡng này sẽ được scale nhỏ | **Để ngỏ [TBD] — Chọn sau khi phân tích**    | $51,200$ ($50\text{ KB}$)  |
| `r_intra_rack`   |    Tỷ lệ     | Xác suất chọn host đích cùng rack (Intra-Rack)                         | Chuẩn hóa (Mục 2.2)                          |     $0.072$ ($7.2\%$)      |
| `r_extra_rack`   |    Tỷ lệ     | Xác suất chọn host đích khác rack trong DCN (Extra-Rack)               | Chuẩn hóa (Mục 2.2)                          |     $0.850$ ($85.0\%$)     |
| `r_extra_dc`     |    Tỷ lệ     | Xác suất chọn đích ra ngoài Internet / Gateway (Extra-DC)              | Chuẩn hóa (Mục 2.2)                          |     $0.078$ ($7.8\%$)      |
| `p_burst`        |    Tỷ lệ     | Xác suất kích hoạt Microburst (chỉ dùng trong script riêng)            | Tham chiếu Facebook (Mục 5.3)                |     $0.020$ ($2.0\%$)      |
| `burst_size_min` |    Bytes     | Dung lượng tối thiểu của đợt burst                                     | Vượt ngưỡng đệm ECN ($K$)                    | $20,480$ ($20\text{ KB}$)  |
| `burst_size_max` |    Bytes     | Dung lượng tối đa của đợt burst                                        | Giới hạn phân khúc burst                     | $81,920$ ($80\text{ KB}$)  |
| `enable_ecn`     |   Boolean    | Kích hoạt ECN trên Switch và Host                                      | RFC 8257 (DCTCP) / RFC 3168                  |           `True`           |

- **Hằng số phần cứng tham chiếu từ bài báo Facebook:**
  - $C_{\text{host}}^{\text{paper}} = 10,000\text{ Mbps}$ ($10.0\text{ Gbps}$ Ethernet).
  - $CPU_{\text{host}}^{\text{paper}} = 16.0\text{ Cores}$ (Máy chủ Facebook tiêu chuẩn OCP Leopard: 2 socket Intel Xeon E5-2600, 16 physical cores).

---

### 3.3. Ma Trận Quy Đổi & Co Giãn Tài Nguyên Phần Cứng Ảo Hóa (Hardware Resource Scaling Matrix)

#### A. Cơ Sở Lý Thuyết: Tại Sao Không Thể Chia Cào Bằng Cùng Một Tỷ Lệ?
Trong lý thuyết mô phỏng hệ thống máy tính và mạng (Computer Systems Similitude & Network Emulation), **các thông số phần cứng ảo hóa bắt buộc phải được co giãn theo từng miền chức năng riêng biệt (Domain-Specific Similitude)**, tuyệt đối không được chia cào bằng cùng một tỷ lệ:
* *Nếu chia cào bằng theo tỷ lệ băng thông ($1/500$):*
  - MTU gói tin $1500\text{B} / 500 = 3\text{B}$ $\implies$ Phá vỡ cấu trúc TCP/IP (IP Header $20\text{B}$, TCP Header $20\text{B}$, Ethernet frame tối thiểu $64\text{B}$).
  - CPU máy chủ $16\text{ Cores} / 500 = 0.032\text{ Core}$ $\implies$ Container bị bóp nghẹt CFS scheduler, tiến trình Python và Linux kernel bị treo cứng.
  - RAM máy chủ $128\text{ GB} / 500 = 256\text{ MB}$ $\implies$ OVS và NFV Proxy bị kernel kích hoạt OOM Killer tiêu diệt ngay lập tức.
* *Do đó, hệ thống được phân lập thành 4 miền bảo toàn động học độc lập:*
  1. **Miền Truyền Dẫn Mạng (Tỷ số $\alpha = 1/500$):** Áp dụng cho Băng thông link và Dung lượng luồng Voi $\implies$ **Bảo toàn Thời gian hoàn thành luồng (Flow Completion Time - FCT)**.
  2. **Miền Tính Toán CPU (Tỷ số $1/16$):** Áp dụng cho CPU host ($16\text{ Cores} \to 1.0\text{ Core}$) và Giãn nhịp phát luồng ($D_{\text{arrival}} = 16.0$) $\implies$ **Bảo toàn Mật độ tải công việc trên mỗi đơn vị CPU Core**.
  3. **Miền Hàng Đợi Switch (Đồng dạng thời gian trữ đệm):** Áp dụng cho Bộ đệm OVS Queue $\implies$ **Bảo toàn Thời gian xả đệm line-rate ($\tau_{\text{buffer}} \approx 9.6\text{ ms} \text{ – } 10\text{ ms}$)**.
  4. **Miền Bộ Nhớ RAM (Working Set Size + Safety Margin):** Cấp phát trần $1024\text{ MB}$ ($1\text{ GB}$) dựa trên bộ nhớ tập làm việc thực tế ($\approx 150\text{MB} \text{ – } 450\text{MB}$) $\implies$ **Bảo toàn Tính ổn định của tiến trình, triệt tiêu lỗi sập OOM**.

---

#### B. Bảng Ma Trận Quy Đổi Co Giãn Tài Nguyên Phần Cứng

| Thiết bị & Thành phần | Phần cứng gốc Facebook (2014–2016) | Cấu hình thực tế Facebook | Cấu hình Container (Containernet) | Tỷ lệ co giãn (Scale Factor) | Cơ sở khoa học & Đại lượng bảo toàn |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Máy chủ nội bộ (`h1_1..h8_4`, 32 hosts)** | Facebook Winterfell v3 / Leopard v1 | Dual-Socket Intel Xeon E5-2600 v2 (16 physical cores), 64–128 GB RAM, 10GbE NIC | `dimage`: `dcn-host:latest`<br>`cpus`: $1.0\text{ Core}$ (`quota`: $100\text{k}$, `period`: $100\text{k}$)<br>`mem_limit`: $1024\text{m}$ ($1\text{ GB}$)<br>`memswap_limit`: $2048\text{m}$ | $1/16$ (CPU)<br>RSS (RAM) | Tiến trình `iperf3` đơn luồng chạy hết công suất chiếm đúng $100\%$ của $1.0\text{ Core}$. RAM an toàn gấp 5 lần nhu cầu thực tế ($150\text{MB}$). |
| **Máy chủ Internet (`inet`)** | External Gateway Server | Dual-Socket Xeon, 10GbE NIC | `dimage`: `dcn-host:latest`<br>`cpus`: $1.0\text{ Core}$<br>`mem_limit`: $1024\text{m}$ | $1/16$ (CPU) | Đóng vai trò External node nhận/phát tải ra ngoài DCN (7.8% locality). |
| **Switch ToR / Access (`a1..a8`)** | Facebook Wedge 40 (Top-of-Rack Switch) | Intel Atom C2550 (4 cores 2.4GHz), 8 GB RAM, Broadcom Trident II $12\text{ MB}$ Buffer | `dimage`: `dcn-ovs:latest`<br>`cpus`: $1.0\text{ Core}$ (`quota`: $100\text{k}$)<br>`mem_limit`: $1024\text{m}$ ($1\text{ GB}$)<br>`max_queue_size`: $1000\text{ pkts}$ | $1/4$ (CPU)<br>Bảo toàn $\tau_{\text{buf}}$ | $4\text{ cores}$ Atom C2550 thế hệ 2013 tương đương năng lực tính toán của $1.0\text{ core}$ CPU PC hiện đại (IPC chênh lệch 3–4 lần). Đủ RAM chứa OVS và NFV Proxy. |
| **Switch Aggregation (`ag1..ag4`)** | Facebook 6-pack (Cluster Switch - CSW) | Khung gầm Clos ghép từ 12 bo Wedge 40 (Trident II ASICs, 12MB Buffer/bo) | `dimage`: `dcn-ovs:latest`<br>`cpus`: $1.0\text{ Core}$<br>`mem_limit`: $1024\text{m}$ | $1/4$ (CPU) | Xử lý chuyển tiếp tầng phân tập (Aggregation Fabric), chịu tải các luồng liên rack (85.0% locality). |
| **Switch Core Spine (`c1, c2`)** | Facebook 6-pack (Fabric Switch - FSW) | Khung gầm Clos 12 bo Wedge 40 kết nối trục chính DCN Fabric | `dimage`: `dcn-ovs:latest`<br>`cpus`: $1.0\text{ Core}$<br>`mem_limit`: $1024\text{m}$ | $1/4$ (CPU) | Chuyển mạch đường trục kịch trần giữa các cụm Pod/Cluster. |
| **Băng thông Access $\leftrightarrow$ Host** | Cáp DAC SFP+ 10GbE xuống Server | $10,000\text{ Mbps}$ ($10\text{ Gbps}$) | $20.0\text{ Mbps}$ (hoặc $100.0\text{ Mbps}$) | $\alpha = 0.002$ ($1/500$) | Chuẩn hóa năng lực mạng theo máy trạm. Tỷ số $\alpha$ điều khiển toàn bộ hàm co giãn kích thước luồng. |
| **Băng thông Agg $\leftrightarrow$ Access** | Uplink 40GbE / Breakout 4x10GbE | $40\text{ Gbps}$ Uplink | $50.0\text{ Mbps}$ | $1/800$ | Duy trì tỷ lệ tập hợp (Oversubscription ratio 2.5:1) chuẩn Data Center. |
| **Băng thông Core $\leftrightarrow$ Agg** | Inter-switch Fabric 40GbE/100GbE | $40\text{ – }100\text{ Gbps}$ Fabric | $100.0\text{ Mbps}$ | $1/1000$ | Đảm bảo băng thông đường trục không bị nghẽn cục bộ trước khi chạm switch biên. |
| **Băng thông Core $\leftrightarrow$ Internet** | Border Gateway Uplink | $40\text{ – }100\text{ Gbps}$ Edge | $100.0\text{ Mbps}$ | $1/1000$ | Cung cấp luồng ra Internet cho node `inet` thông suốt. |
| **Bộ đệm Switch (Buffer Delay)** | Broadcom SmartBuffer $12\text{ MB}$ | $\tau_{\text{buf}} = \frac{12\text{MB} \times 8}{10\text{Gbps}} = 9.6\text{ ms}$ | $1000\text{ packets}$ ($\approx 1.5\text{ MB}$) trên link $20\text{M}$ | Bảo toàn $\tau_{\text{buf}} \approx 10\text{ms}$ | Bảo toàn thời gian xả đệm line-rate. Tái hiện hiện tượng tắc nghẽn và drop gói khi xảy ra TCP Incast / Microburst. |
| **Khoảng cách nhịp phát ($\Delta t$)** | Inter-arrival time thực tế Facebook | $10.5\text{ }\mu\text{s} \to 714\text{ ms}$ (từ 16 cores) | $\Delta t_{\text{scaled}} = \Delta t^{\text{paper}} \times 16.0$ | $\times 16.0$ ($D_{\text{arrival}}$) | **Bảo toàn mật độ tải luồng trên mỗi đơn vị CPU Core.** Máy ảo 1 core xử lý nhịp phát thưa hơn 16 lần tương đương chính xác 16 cores xử lý dồn dập. |
| **Dung lượng Luồng Voi** | $s > S_{\text{threshold}}$ (P90 Pareto) | $124\text{ KB} \to 543\text{ MB}$ (Hadoop, Web) | $S_{\text{scaled}} = S_{\text{th}} + (s - S_{\text{th}}) \cdot \alpha$ | $\times 0.002$ phần đuôi | **Bảo toàn thời gian chiếm dụng link (FCT):** Luồng voi truyền trên link 20M kết thúc cùng thời gian với luồng gốc truyền trên link 10G. |
| **Dung lượng Luồng Chuột** | $s \le S_{\text{threshold}}$ (DNS, ACK, HTTP) | $64\text{ Bytes} \to 124\text{ KB}$ | Giữ nguyên $100\%$ ($S = s$) | $1.0$ (Không scale) | **Bảo toàn cấu trúc MTU $1500\text{B}$ và gói tin nhỏ**, không làm méo mó các gói tin điều khiển của giao thức mạng. |

---

#### C. Cơ Chế Tham Chiếu Chống Lệch Pha Giữa 2 File Cấu Hình
Để đảm bảo các thông số tài nguyên và băng thông luôn đồng bộ $100\%$ khi người dùng thay đổi môi trường thử nghiệm:
* [`controller/topology_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/topology_config.json) đóng vai trò **Gốc phần cứng & Mạng (Master)**: Khai báo toàn bộ cấu hình container cgroups (`cpus`, `cpu_quota`, `mem_limit`) và băng thông liên kết (`access_host`, `core_agg`, `agg_access`).
* [`controller/traffic_config.json`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/traffic_config.json) đóng vai trò **Mô hình phụ tải**: Tự động tham chiếu sang `topology_config.json` qua cú pháp JSON Pointer:
  - `"C_host_mbps": "ref:topology_config.json#/links/bandwidth_mbps/access_host"`
  - `"C_paper_mbps": "ref:topology_config.json#/system_info/hardware_reference/server_nic_speed_mbps"`
  - `"CPU_host_cores": "ref:topology_config.json#/hosts/resources/cpus"`
  - `"CPU_paper_cores": "ref:topology_config.json#/system_info/hardware_reference/server_physical_cores"`
* Bộ lấy mẫu toán học [`controller/unified_sampler.py`](file:///c:/Users/USER/Desktop/SDN%20KLTN/controller/unified_sampler.py) tự động giải mã các tham chiếu này khi nạp vào bộ nhớ. Người dùng chỉ cần sửa đổi cấu hình tại `topology_config.json`, toàn bộ hệ thống sinh tải và bộ tính toán $\alpha, D_{\text{arrival}}$ sẽ tự động thích ứng ngay lập tức.

---

## 4. CÔNG THỨC SCALE & DẪN CHỨNG KHOA HỌC

### 4.1. Hệ số co giãn băng thông ($\alpha$):

$$
\alpha = \frac{C_{\text{host}}}{C_{\text{host}}^{\text{paper}}} = \frac{C_{\text{host}}}{10,000}
$$

_(Ví dụ: Nếu topo dùng $C_{\text{host}} = 20\text{ Mbps} \implies \alpha = 0.002$; nếu dùng $100\text{ Mbps} \implies \alpha = 0.01$)\_.

---

### 4.2. Tỷ lệ hạ tài nguyên phần cứng ($\beta_{\text{CPU}}$) & Hệ số giãn nhịp phát ($D_{\text{arrival}}$):

$$
\beta_{\text{CPU}} = \frac{CPU_{\text{host}}}{CPU_{\text{host}}^{\text{paper}}} = \frac{CPU_{\text{host}}}{16.0}
$$

$$
D_{\text{arrival}} = \frac{1}{\beta_{\text{CPU}}} = \frac{CPU_{\text{host}}^{\text{paper}}}{CPU_{\text{host}}}
$$

---

### 4.3. Công thức co giãn thời gian giữa các luồng ($\Delta t_{\text{arrival}}$):

$$
\Delta t_{\text{arrival}} = \Delta t_{\text{arrival}}^{\text{paper}} \times D_{\text{arrival}} = \Delta t_{\text{arrival}}^{\text{paper}} \times \frac{CPU_{\text{host}}^{\text{paper}}}{CPU_{\text{host}}}
$$

- **Cơ sở khoa học:**
  - _Mininet-HiFi (Handigol et al., ACM SIGCOMM 2012 - Stanford University):_ Năng suất xử lý ngắt gói tin và tiến trình mạng tỷ lệ thuận với hạn ngạch CPU. Tần suất phát sinh luồng $\lambda$ phải hạ tương ứng với CPU ảo để tránh nghẽn hàng đợi nội tại của máy chủ ảo (Host Processing Bottleneck).
  - _Lý thuyết Hàng đợi & Bảo toàn Độ tải CPU (Kleinrock 1975):_ Giữ nguyên hệ số tải CPU $\rho_{\text{CPU}} = \lambda / \mu$ giữa hệ thống thực tế và hệ thống giả lập.

---

### 4.4. Công thức co giãn kích thước luồng liên tục chống nghịch đảo (Piecewise Continuous Scaling):

Để tránh triệt để lỗi **Nghịch đảo kích thước (Size Inversion Anomaly)** — hiện tượng luồng lớn sau khi scale bị nhỏ hơn luồng nhỏ do nhân $\alpha$ đột ngột, công thức scale được xây dựng dưới dạng **hàm ghép liên tục (Piecewise Linear Continuous Function)**:

$$
S_{\text{scaled}}(s) = \begin{cases}
s & \text{khi } s \le S_{\text{threshold}} \quad (\text{Mice Flows}) \\
S_{\text{threshold}} + (s - S_{\text{threshold}}) \times \alpha & \text{khi } s > S_{\text{threshold}} \quad (\text{Elephant Flows})
\end{cases}
$$

- **Đặc tính kỹ thuật xuất sắc:**
  - Khi $s \le S_{\text{threshold}}$: Kích thước được bảo toàn $100\%$, giữ nguyên cấu trúc gói tin MTU và pha TCP Slow-Start ($IW10$).
  - Khi $s > S_{\text{threshold}}$: Hàm số tăng dần liên tục, đảm bảo với mọi $s_2 > s_1$ thì luôn có $S_{\text{scaled}}(s_2) > S_{\text{scaled}}(s_1)$. Luồng lớn luôn luôn lớn hơn luồng nhỏ.
  - Phần vượt ngưỡng được thu nhỏ theo $\alpha$, giúp luồng Voi không chiếm dụng kênh truyền quá lâu mà vẫn bảo toàn thời gian truyền tương quan thực tế.

---

### 4.5. Thuật toán xác định vùng đích 3 nhánh (3-Way Locality Routing Algorithm):

Khi một host nguồn phát sinh luồng dữ liệu mới, việc chọn máy đích tuân theo phân phối đa thức bằng biến ngẫu nhiên $U_r \sim \text{Uniform}(0, 1)$:

$$
\text{Vùng đích} = \begin{cases}
\text{Host ngẫu nhiên CÙNG switch Access (Intra-rack)} & \text{khi } U_r \le 0.072 \ (7.2\%) \\
\text{Host ngẫu nhiên KHÁC switch Access trong DCN (Extra-rack)} & \text{khi } 0.072 < U_r \le 0.922 \ (85.0\%) \\
\text{Cổng Gateway / Internet Sink Node (Extra-Datacenter)} & \text{khi } U_r > 0.922 \ (7.8\%)
\end{cases}
$$

---

### 4.6. Phân tách Module: Heavy Jitter / Ephemeral Microburst Injection

Thay vì gộp chung vào tiến trình phát sinh tải liên tục, **Heavy Jitter được tách riêng thành một script độc lập: `microburst_generator.py`**:

- **Mục đích:** Kích hoạt có chủ đích khi cần kiểm thử cơ chế ECN tại OVS Data-Plane, kiểm tra dung lượng hàng đợi, hoặc tạo stress test ngẫu nhiên.
- **Đặc trưng luồng burst:**
  - Dung lượng: $S_{\text{burst}} \sim \text{Log-Uniform}(20\text{ KB}, 80\text{ KB})$.
  - Cơ chế phát: Dùng **Socket Python non-blocking** (thay vì `iperf3`) để đẩy sạch dữ liệu ở tốc độ Full Line-rate trong vòng $1.5\text{ – }6.0\text{ ms}$.
  - Socket flags: `TCP_NODELAY = 1` (tắt Nagle), gắn nhãn TOS `ECT(0) = 0x02`.
- **Tự ghi nhận Client-side Ground Truth:** Script tự lưu bản ghi gồm `[timestamp, src, dst, bytes, real_duration_ms, is_burst=True]` để không bị phụ thuộc vào chu kỳ polling $1.0\text{s}$ của Ryu Telemetry.

---

### 4.7. Quy trình 2 pha xác định ngưỡng Ground-Truth cho Classifier (Data-Driven Thresholding)

Để đảm bảo tính khoa học và tránh thiên kiến tiên nghiệm (a priori bias), **ngưỡng phân loại Elephant Flow được để ngỏ [TBD]** và được xác định thông qua quy trình 2 pha:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHA 1: THU THẬP TẬP DỮ LIỆU THỰC NGHIỆM THÔ (RAW TELEMETRY COLLECTION)      │
│ • Chạy traffic_generator.py sinh tải tự nhiên theo ECDF Facebook.           │
│ • management_plane.py ghi nhận đầy đủ 10 features (sbytes, dur, Sload,...). │
│ • Tạm thời để trống cột label (hoặc gán nhãn tạm).                          │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHA 2: PHÂN TÍCH PHÂN VỊ HẬU KỲ & CHỐT NGƯỠNG (POST-RUN THRESHOLD SELECTION) │
│ • Chạy script analyze_and_label_dataset.py.                                 │
│ • Vẽ biểu đồ Histogram & ECDF của 2 đại lượng: sbytes và Sload.             │
│ • Hệ thống tự động tính và hiển thị các mốc phân vị: P80, P90, P95, P99.   │
│ • NHẮC NGƯỜI DÙNG: Người dùng xem xét phân phối và chọn ngưỡng tối ưu.      │
│ • Script tự động cập nhật nhãn chuẩn Ground-Truth (1: Elephant, 0: Mice).   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. CÁCH THỨC VẬN HÀNH BỘ ĐÔI SINH TẢI (TRAFFIC GENERATION ARCHITECTURE)

Hệ thống sinh tải được module hóa thành **2 engine độc lập**:

```
                              KIẾN TRÚC SINH TẢI DCN
                                        │
        ┌───────────────────────────────┴───────────────────────────────┐
        ▼                                                               ▼
┌─────────────────────────────────┐           ┌─────────────────────────────────┐
│ 5.1. ENGINE LƯU LƯỢNG NỀN       │           │ 5.2. ENGINE HEAVY JITTER        │
│      (traffic_generator.py)     │           │      (microburst_generator.py)  │
├─────────────────────────────────┤           ├─────────────────────────────────┤
│ • Lấy mẫu s từ ECDF thống nhất  │           │ • Lấy mẫu 20KB - 80KB           │
│ • Scale liên tục: S_scaled      │           │ • Gửi Full Line-rate bằng Socket│
│ • Chọn đích theo 3 vùng locality│           │ • Gắn nhãn ECT(0) cho ECN       │
│ • Gửi đồng nhất: iperf3 -n      │           │ • Tự ghi log Client GroundTruth │
│ • time.sleep(Delta_t_scaled)    │           │ • Kích hoạt độc lập / stress test│
└─────────────────────────────────┘           └─────────────────────────────────┘
```

### 5.1. Engine Chính: `traffic_generator.py` (Lưu lượng nền thống nhất iperf3)

Toàn bộ các luồng trong lưu lượng nền (cả luồng nhỏ và luồng lớn) đều sử dụng **công cụ `iperf3` đồng nhất**:

1. **Lấy mẫu kích thước:** Sinh $u_1 \sim \text{Uniform}(0, 1) \implies s = F_{\text{flow\_size}}^{-1}(u_1)$.
2. **Co giãn kích thước:** Tính $S_{\text{scaled}} = S_{\text{scaled}}(s)$ theo công thức liên tục (Mục 4.4).
3. **Chọn đích:** Lấy mẫu $u_r \implies$ Chọn host đích theo 3 vùng Locality (Mục 4.5).
4. **Phát dữ liệu đồng nhất bằng `iperf3 -n`:**

   ```bash
   iperf3 -c {dst_ip} -p {port} -n {S_scaled}
   ```

   - _Ý nghĩa:_ Ứng dụng chỉ định nghĩa dung lượng cần truyền. Mạng mạng ảo hóa, thuật toán SDN routing và TCP Congestion Control sẽ **tự nhiên quyết định thời gian hoàn tất luồng (FCT) và thông lượng**.

5. **Điều phối nhịp phát:** Lấy mẫu $u_3 \implies \Delta t_{\text{arrival}} \implies$ Thực thi `time.sleep(\Delta t_{\text{arrival}} \times D_{\text{arrival}})`.

---

### 5.2. Engine Phụ: `microburst_generator.py` (Bơm Heavy Jitter độc lập)

- Chạy song song hoặc chạy theo kịch bản đo kiểm định kỳ.
- Sử dụng raw/stream socket Python để bơm burst $20\text{ – }80\text{ KB}$ trong thời gian siêu ngắn ($< 10\text{ ms}$).
- Phục vụ việc quan sát cơ chế đánh dấu cờ CE (Congestion Experienced) của ECN tại hàng đợi switch OVS.

---

## 6. CẤU TRÚC TỆP TIN MODULE SINH TẢI & HUẤN LƯYỆN AI

```
controller/
├── traffic_config.json                      # Cấu hình mở: Băng thông, CPU, ngưỡng scale
├── raw_digitized/                          # Dữ liệu số hóa thô từ PDF bài báo Facebook
│   ├── flow_size/
│   │   ├── raw_flow_size_hadoop.csv        # Tọa độ thô Fig. 6c (đường ALL)
│   │   ├── raw_flow_size_frontend.csv      # Tọa độ thô Fig. 6a (đường ALL)
│   │   └── raw_flow_size_cache.csv         # Tọa độ thô Fig. 6b (đường ALL)
│   ├── inter_arrival/
│   │   ├── raw_inter_arrival_hadoop.csv    # Tọa độ thô Fig. 14 (Hadoop)
│   │   ├── raw_inter_arrival_frontend.csv  # Tọa độ thô Fig. 14 (Frontend)
│   │   └── raw_inter_arrival_cache.csv     # Tọa độ thô Fig. 14 (Cache)
│   └── flow_duration/
│       ├── raw_flow_duration_hadoop.csv    # Tọa độ thô Fig. 7c (đường ALL)
│       ├── raw_flow_duration_frontend.csv  # Tọa độ thô Fig. 7a (đường ALL)
│       └── raw_flow_duration_cache.csv     # Tọa độ thô Fig. 7b (đường ALL)
│
├── cdf_profiles/                           # 3 hồ sơ phân phối HỢP NHẤT DUY NHẤT
│   ├── cdf_flow_size_unified.csv           # Hồ sơ Flow Size thống nhất (Input sinh tải)
│   ├── cdf_inter_arrival_unified.csv       # Hồ sơ Flow Inter-Arrival thống nhất (Input điều nhịp)
│   └── cdf_flow_duration_unified.csv       # Hồ sơ Flow Duration thống nhất (Dùng đối soát KS-Test)
│
├── digitize_raw_plots.py                   # Script hỗ trợ số hóa tọa độ từ ảnh biểu đồ
├── blend_cdfs.py                           # Script hòa trộn 9 file raw thành 3 file CDF thống nhất
├── unified_sampler.py                      # Module nạp CDF và lấy mẫu ngẫu nhiên (Log-interpolation)
├── traffic_generator.py                    # Engine CHÍNH: Vòng lặp sinh tải nền bằng iperf3 -n
├── microburst_generator.py                 # Engine PHỤ: Bơm Heavy Jitter / Microburst độc lập
└── analyze_and_label_dataset.py            # Script phân tích phân vị P90/P95 và gán nhãn Ground-Truth
```
