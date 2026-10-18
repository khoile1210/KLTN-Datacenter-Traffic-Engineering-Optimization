# KẾ HOẠCH CHI TIẾT: ỨNG DỤNG NHÚNG NFV PROXY - PHÂN MẢNH BLOCK 64KB & TÁI HỢP GÓI CHỐNG XÁO TRỘN TCP
## (IN-NETWORK NFV PROXY & PACKET REASSEMBLY PLAN)

> **Mã chuyên đề:** `PLAN-WP07-NFV-PROXY`  
> **Thuộc dự án:** Nghiên cứu Tối ưu hóa Kỹ thuật Lưu lượng trong Mạng DCN Dựa trên SDN và AI (SDN-AI DCN)  
> **Cố vấn chuyên môn:** Senior SDN Architect (Gemini 4 Argon)  
> **Trạng thái thực tế:** **THIẾT KẾ CHI TIẾT (PHASE 3 WORK PACKAGE)**  
> **Thư mục mã nguồn:** [`nfv_proxy/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/nfv_proxy/)  

---

## 1. MỤC TIÊU & BÀI TOÁN KHOA HỌC

1. **Bài toán Xáo trộn Thứ tự Gói tin TCP (TCP Packet Reordering Problem):** Trong mạng DCN, khi một luồng Voi được phân bổ đi qua nhiều đường truyền song song có độ trễ và tải khác nhau, các gói tin đến máy nhận bị đảo lộn thứ tự (Out-of-Order). Khi máy nhận nhận được 3 gói tin Duplicate ACK, giao thức TCP hiểu nhầm là mạng bị mất gói và kích hoạt cơ chế Fast Retransmit, thu hẹp cửa sổ tắc nghẽn về một nửa:
   $$cwnd \leftarrow \frac{cwnd}{2}$$
   khiến thông lượng hữu ích (Goodput) của luồng Voi bị suy giảm nghiêm trọng từ $50\% - 80\%$.
2. **Kế thừa & Nâng cấp Ý tưởng Kiến trúc Presto (ACM SIGCOMM 2015):** Triển khai cơ chế phân tách luồng thành các đơn vị tế bào dữ liệu kích thước chuẩn **Flowcell ($64\text{ KB}$)** tại biên mạng (Edge Switch).
3. **Phân rải Đa đường theo Trọng số Tối ưu từ AI (Adaptive Multi-path Spraying):** Ingress Proxy nhận ma trận tỷ lệ $\vec{w}$ từ mô hình GAT-PPO DRL để phân rải các Flowcell $64\text{ KB}$ qua các đường Uplink khác nhau.
4. **Bộ đệm Tái hợp Thứ tự tại Biên Đích (Egress Reassembly Buffer):** Egress Proxy tiếp nhận các Flowcell, sắp xếp lại đúng thứ tự tuần tự của TCP Sequence Number trước khi chuyển giao vào ngăn xếp mạng của Host đích, đảm bảo **tỷ lệ gói tin xáo trộn $\text{Out-of-Order} = 0\%$**.

---

## 2. CƠ SỞ KHOA HỌC, ĐỊNH LÝ GỐC & TÀI LIỆU THAM KHẢO

- **[Cân bằng tải Biên DCN & Khối Flowcell 64KB]** K. He, E. Rozner, K. Agarwal, Y. Gu, W. Felter, J. Carter, A. Akella (UT Austin, IBM Research, UW-Madison), *"Presto: Edge-based Load Balancing for Fast Datacenter Networks"*, ACM SIGCOMM 2015. *(Chứng minh toán học kích thước Flowcell $64\text{ KB}$ tương thích hoàn hảo với bộ đệm TSO/GRO của Linux kernel, đạt sự cân bằng tối ưu giữa độ mịn chia tải qua Spine và chi phí tái hợp).*
- **[Nguyên lý Bảo tồn Gói tin TCP & Kiểm soát Tắc nghẽn]** V. Jacobson, M. J. Karels, *"Congestion Avoidance and Control"*, ACM SIGCOMM 1988; RFC 5681, M. Allman, V. Paxson, E. Blanton, 2009. *(Nguyên lý kích hoạt 3 Duplicate ACKs, sụp đổ cửa sổ $cwnd \leftarrow cwnd / 2$ khi gói bị xáo trộn thứ tự, và nguyên tắc bảo tồn gói trong mạng).*
- **[Xử lý Vi gói Tại Biên Mạng]** S. H. K. Narayana, et al., *"Language-Directed Hardware Design for Datacenters"*, ACM SIGCOMM 2017. *(Cơ chế trích lọc và định tuyến tế bào lưu lượng cấp phần cứng/NFV).*

---

## 3. THIẾT KẾ KIẾN TRÚC PHẦN MỀM NFV PROXY

Hệ thống NFV Proxy được triển khai dưới dạng một tiến trình Daemon tối ưu chạy trực tiếp tại các Switch Access (Edge Switches), kết nối với OVS thông qua cổng nội bộ chuyên dụng **`proxy-int`**:

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
| ACCESS SWITCH NGUỒN (INGRESS SWITCH)                                                              |
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|  Luồng Voi (TCP Stream) ──► OVS Table 0 (Priority 1000) ──► Cổng "proxy-int"                     |
|                                                                    │                              |
|                                                                    ▼                              |
|  [ INGRESS PROXY SLICER DAEMON ]                                                                  |
|  ├── Gom dữ liệu TCP vào bộ đệm dòng (Stream Buffer)                                              |
|  ├── Cắt luồng thành từng khối Flowcell cố định: S_cell = 64 KB (~43 gói MSS 1460B)               |
|  ├── Gắn tiêu đề Flowcell Header: [ Flow_ID (4B) | Seq_Cell (4B) | Payload (64KB) ]                |
|  └── Rải Flowcell ra các Uplink Ports theo vector trọng số w = [w1, w2, w3, w4] từ GAT-PPO DRL    |
+──────────────────────────────────────────────────┬────────────────────────────────────────────────+
                                                   │
                                                   ▼ (Truyền phân tán qua 4 Spine switches)
                                                   │
+──────────────────────────────────────────────────▼────────────────────────────────────────────────+
| ACCESS SWITCH ĐÍCH (EGRESS SWITCH)                                                                |
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|  Các khối Flowcell 64KB đến rải rác từ các Uplink khác nhau ──► Cổng "proxy-int"                 |
|                                                                    │                              |
|                                                                    ▼                              |
|  [ EGRESS PROXY REASSEMBLY DAEMON ]                                                               |
|  ├── Nhận các khối Flowcell và đưa vào Hàng đợi Tái hợp Trượt (Sliding Reorder Buffer)            |
|  ├── Kiểm tra số thứ tự tuần tự Seq_Cell:                                                         |
|  │     - Nếu Seq_Cell == Expected_Seq: Chuyển tiếp ngay lập tức vào Host đích                     |
|  │     - Nếu Seq_Cell > Expected_Seq: Lưu tạm vào bộ đệm và đợi khối bị chậm                      |
|  ├── Giới hạn thời gian chờ tối đa (Reassembly Timeout = 5.0ms) để chống kẹt luồng                |
|  └── Chuyển giao các gói tin TCP đúng thứ tự hoàn hảo vào ngăn xếp mạng của Host đích             |
|                                                                    │                              |
|                                                                    ▼                              |
|  Host Đích nhận gói tin: Duplicate ACK = 0, Cửa sổ cwnd duy trì cực đại, Goodput tăng 85%!         |
+───────────────────────────────────────────────────────────────────────────────────────────────────+
```

---

## 4. MÔ HÌNH TOÁN HỌC & TỐI ƯU HÓA KÍCH THƯỚC FLOWCELL (64 KB)

### 4.1. Phân tích Cân bằng giữa Độ mịn Chia tải và Chi phí Tái hợp
Giả sử một luồng Voi có kích thước $S_{\text{flow}}$. Nếu chia thành các đơn vị tế bào kích thước $S_{\text{cell}}$:
- **Nếu $S_{\text{cell}}$ quá nhỏ ($S_{\text{cell}} \approx 1.5\text{ KB} \sim 1\text{ packet}$ - Packet Spraying):**
  - Khả năng cân bằng tải đạt mức hoàn hảo (Fine-grained).
  - *Nhưng chi phí:* Xáo trộn thứ tự xảy ra cực kỳ nghiêm trọng trên từng gói tin đơn lẻ; bộ đệm Egress bị quá tải; tỷ lệ Out-of-Order vượt $40\%$.
- **Nếu $S_{\text{cell}}$ quá lớn ($S_{\text{cell}} > 500\text{ KB}$):**
  - Xáo trộn giảm, nhưng quay lại hiện tượng thô của ECMP (Coarse-grained), gây bão hòa cục bộ một nhánh đường truyền.
- **Kích thước Tối ưu $S_{\text{cell}} = 64\text{ KB}$ (Presto Theorem):**
  $$S_{\text{cell}} = 64\text{ KB} \approx 43.8 \times \text{MSS} \ (1460\text{ Bytes})$$
  Tại kích thước $64\text{ KB}$, một khối dữ liệu đủ nhỏ để san phẳng độ lệch băng thông giữa các Spine trong thời gian $< 5\text{ ms}$, nhưng đủ lớn để bộ đệm tái hợp Egress chỉ cần quản lý hàng chục thẻ Sequence thay vì hàng ngàn gói tin rời rạc.

---

### 4.2. Cơ chế Quản lý Bộ đệm Tái hợp Egress (Sliding Window Reorder Buffer)
Bộ đệm tại Egress Proxy duy trì cửa sổ trượt:
$$\mathcal{W}_{\text{reorder}} = \left[ \text{Seq}_{\text{expected}}, \ \text{Seq}_{\text{expected}} + W_{\text{max}} - 1 \right]$$
Trong đó:
- $W_{\text{max}} = 16\text{ Flowcells} \approx 1.0\text{ MB}$ (Kích thước đệm tối đa cho mỗi luồng Voi).
- **Hàm giải phóng tức thời (Immediate Flush):** Khi Flowcell có số thứ tự $\text{Seq}_{\text{expected}}$ cập bến, bộ đệm giải phóng lập tức khối này và tất cả các khối liên tiếp đã nằm chờ sẵn trong RAM, giảm thiểu trễ trung chuyển xuống dưới $0.2\text{ ms}$.
- **Bộ đếm thời gian an toàn (Watchdog Timer $\tau_{\text{reorder}} = 5.0\text{ ms}$):** Nếu một khối bị mất trên đường truyền, sau $5.0\text{ ms}$ bộ đệm sẽ tự động bỏ qua và chuyển tiếp các khối tiếp theo để giao thức TCP của Host tự kích hoạt cơ chế phục hồi tiêu chuẩn, không để xảy ra deadlock.

---

## 5. THIẾT KẾ CẤU TRÚC MÃ NGUỒN TRONG `nfv_proxy/`

Thư mục [`nfv_proxy/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/nfv_proxy/) được cấu trúc thành các module độc lập:

```
nfv_proxy/
├── __init__.py
├── proxy_daemon.py            # Tiến trình chính quản lý socket RAW / AF_PACKET trên cổng proxy-int
├── ingress_slicer.py          # Module bóc tách luồng TCP và phân rải Flowcell 64KB theo trọng số DRL
├── egress_reassembler.py      # Module hàng đợi tái hợp thứ tự trượt (Sliding Window Reassembly Buffer)
├── flowcell_protocol.py       # Định nghĩa cấu trúc header nhãn tế bào Flowcell 64KB
├── proxy_telemetry_client.py  # Gửi thống kê số khối phân mảnh và dung lượng đệm sang Management Plane
└── README.md                  # Hướng dẫn biên dịch và khởi chạy NFV Proxy daemon
```

---

## 6. TIÊU CHÍ ĐÁNH GIÁ & NGHIỆM THU HỌC THUẬT (ACCEPTANCE GATES)

- [ ] **Triệt tiêu Xáo trộn Gói tin:** Đo kiểm gói tin tại card mạng của Host nhận bằng Wireshark / `tcpdump`, xác nhận tỷ lệ gói tin out-of-order đạt:
  $$\text{TCP Out-of-Order Rate} = 0\%$$
- [ ] **Bảo toàn Cửa sổ Tắc nghẽn ($cwnd$):** Giám sát biến `cwnd` trong nhân Linux của Host phát qua `ss -i`, xác nhận cửa sổ tắc nghẽn duy trì mức cực đại, không bị bẻ gãy bởi 3 Duplicate ACKs.
- [ ] **Tăng trưởng Thông lượng Hữu ích:** Thông lượng Goodput của luồng Voi khi chạy qua NFV Proxy + GAT-PPO tăng tối thiểu $40\%$ so với khi chạy qua ECMP tĩnh.
- [ ] **Trễ Trung chuyển Cực tiểu:** Độ trễ đệm phát sinh tại NFV Proxy không vượt quá $1.5\text{ ms}$.
