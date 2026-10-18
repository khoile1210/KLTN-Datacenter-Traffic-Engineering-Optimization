# KẾ HOẠCH CHI TIẾT: TẦNG HỌC MÁY - PHÂN LOẠI LUỒNG VOI/CHUỘT SỚM (PHASE 2)
## (AI EARLY FLOW CLASSIFIER PLAN)

> **Mã chuyên đề:** `PLAN-WP05-AI-CLASSIFIER`  
> **Thuộc dự án:** Nghiên cứu Tối ưu hóa Kỹ thuật Lưu lượng trong Mạng DCN Dựa trên SDN và AI (SDN-AI DCN)  
> **Cố vấn chuyên môn:** Senior SDN Architect (Gemini 4 Argon)  
> **Trạng thái thực tế:** **SẴN SÀNG TRIỂN KHAI (PHASE 2 WORK PACKAGE)**  
> **Thư mục mã nguồn:** [`ml_engine/classifier/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/ml_engine/classifier/), [`results/traffic_flow_dataset_with_paths.csv`](file:///c:/Users/USER/Desktop/SDN%20KLTN/results/traffic_flow_dataset_with_paths.csv)  

---

## 1. MỤC TIÊU & BÀI TOÁN KHOA HỌC

1. **Bài toán Phân loại Luồng Sớm (Early Flow Classification Problem):** Nhận diện chính xác một luồng dữ liệu là **Luồng Voi (Elephant Flow)** chỉ dựa vào các gói tin đầu đời ($N \le 10\text{ gói}$) hoặc trong khoảng thời gian quan sát cực ngắn ($t_{\text{observe}} \le 10\text{ ms}$), trước khi luồng kịp bùng nổ làm tràn bộ đệm switch.
2. **Ngân sách Độ trễ Suy luận Siêu thấp (Sub-millisecond Inference Latency Budget):** Thời gian tiền xử lý đặc trưng và suy luận mô hình phải đạt:
   $$t_{\text{inference}} < 1.0\text{ ms/luồng}$$
   Đảm bảo Controller kịp thời cài đặt luật OpenFlow Priority 1000 bẻ hướng luồng Voi vào NFV Proxy trước khi xảy ra xung đột băm trên các đường truyền ECMP.
3. **Phân biệt Chính xác giữa Luồng Voi Bền vững và Microburst:** Tuyệt đối không nhầm lẫn xung đột biến ngắn (Microburst $20-80\text{KB}, <10\text{ms}$) với Luồng Voi bền vững, vì Microburst đã được ghìm bằng ECN Data Plane Reflex.
4. **Chỉ số Chất lượng Học máy Khắt khe:** Đạt $\text{Macro F1-Score} > 92\%$ và $\text{Recall (Elephant)} > 95\%$ trên tập dữ liệu kiểm thử thực tế mô phỏng lưu lượng Facebook DCN.

---

## 2. CƠ SỞ KHOA HỌC, ĐỊNH LÝ GỐC & TÀI LIỆU THAM KHẢO

- **[Tối ưu hóa Gradient Cấp 2 trong Cây Quyết định]** J. H. Friedman (Stanford University), *"Greedy Function Approximation: A Gradient Boosting Machine"*, Annals of Statistics, 2001; kết hợp T. Chen, C. Guestrin (University of Washington), *"XGBoost: A Scalable Tree Boosting System"*, ACM SIGKDD 2016. *(Cơ sở toán học khai triển chuỗi Taylor bậc 2 quanh nghiệm hiện tại để tìm nghiệm đóng giải tích cho trọng số nút lá).*
- **[LightGBM & Phân tách Dựa trên Lược đồ]** G. Ke, Q. Meng, T. Finley, T. Wang, W. Chen, W. Ma, Q. Ye, T.-Y. Liu (Microsoft Research), *"LightGBM: A Highly Efficient Gradient Boosting Decision Tree"*, Advances in Neural Information Processing Systems (NeurIPS 2017). *(Kỹ thuật GOSS - Gradient-based One-Side Sampling và EFB - Exclusive Feature Bundling cho phép suy luận siêu tốc $< 1\text{ms}$).*
- **[Nhận diện Luồng Voi Sớm trong SDN]** T. V. Phan, et al., *"An Efficient Elephant Flow Detection with CostSensitive in SDN"*, EAI INISCOM, 2015; và L. Peng, et al., *"Machine Learning for Early Flow Classification in SDN"*, IEEE Communications Letters. *(Nguyên lý trích xuất đặc trưng trong $N \le 10$ gói đầu tiên của phiên truyền).*

---

## 3. THIẾT KẾ MÔ HÌNH HỌC MÁY & QUY TRÌNH HUẤN LUYỆN

### 3.1. So sánh Lựa chọn Thuật toán: LightGBM / XGBoost vs. Deep Neural Networks
Trong các hệ thống mạng điều khiển thời gian thực (SDN), độ trễ suy luận là yếu tố sống còn:

| Tiêu chí Đánh giá | Mạng Nơ-ron Sâu (DNN / MLP / LSTM) | Thuật toán Cây Tăng cường (XGBoost / LightGBM) | Quyết định Lựa chọn |
| :--- | :---: | :---: | :---: |
| **Độ trễ suy luận CPU ($t_{\text{infer}}$)** | $5.0\text{ ms} - 15.0\text{ ms}$ (Quá chậm cho SDN) | **$0.15\text{ ms} - 0.40\text{ ms}$ (Đạt chuẩn $<1\text{ms}$)** | **Chọn LightGBM/XGBoost** |
| **Độ chính xác trên Dữ liệu Bảng (Tabular)**| Trung bình (Dễ overfit trên vector đặc trưng) | **Xuất sắc (Tối ưu hóa phân vị và tương quan phi tuyến)** | **Chọn LightGBM/XGBoost** |
| **Dung lượng Mô hình & Bộ nhớ RAM** | $50\text{ MB} - 200\text{ MB}$ | **$< 3\text{ MB}$ (Nhẹ, nạp trực tiếp vào RAM Controller)**| **Chọn LightGBM/XGBoost** |
| **Khả năng Giải thích (Interpretability)** | Hộp đen (Black-box) | **Rõ ràng (Feature Importance qua SHAP values)** | **Chọn LightGBM/XGBoost** |

---

### 3.2. Không gian Vector Đặc trưng Đầu vào (Input Feature Space $\vec{x}$)
Mô hình tiếp nhận vector đặc trưng 11 chiều trích xuất từ tầng Telemetry:
$$\vec{x} = \left[ dur, \ sbytes, \ dbytes, \ Spkts, \ Dpkts, \ Sload, \ Dload, \ smeansz, \ dmeansz, \ Ratio, \ locality \right]^T \in \mathbb{R}^{11}$$
- Các đặc trưng tỷ lệ tốc độ ($Sload, Dload$) phản ánh tốc độ bơm lưu lượng tức thời. Luồng Voi thường có $smeansz \to 1460\text{ Bytes}$ (Full MTU) và $Ratio \gg 1$.
- Chuẩn hóa dữ liệu bằng `RobustScaler` để triệt tiêu ảnh hưởng của các giá trị ngoại lai (Outliers) trong phân phối đuôi dài Pareto.

---

### 3.3. Định nghĩa Nhãn Ground-Truth Dựa trên Phân vị Pareto & Chuẩn Presto
Theo hồ sơ phân phối thực nghiệm của bài báo Facebook SIGCOMM 2015 và kiến trúc Presto SIGCOMM 2015, ngưỡng phân tách luồng Voi/Chuột được xác lập tại $S_{\text{threshold}} = 65,536\text{ Bytes}$ ($64\text{ KB}$, ứng với phân vị $P_{83}$):
$$y = \begin{cases} 1 \ (\text{Elephant Flow}), & \text{khi } sbytes + dbytes \ge 65,536\text{ Bytes} \ (64\text{ KB}) \\ 0 \ (\text{Mice Flow}), & \text{khi } sbytes + dbytes < 65,536\text{ Bytes} \end{cases}$$
- **Xử lý Mất cân bằng Mẫu (Class Imbalance):**
  Trong mạng thực tế, số lượng luồng Chuột chiếm $81.06\%$, trong khi luồng Voi chiếm $18.94\%$. Đề tài áp dụng kỹ thuật cân bằng trọng số lớp (Class Weighting):
  $$w_{\text{Elephant}} = \frac{N_{\text{total}}}{2 \cdot N_{\text{Elephant}}}, \quad w_{\text{Mice}} = \frac{N_{\text{total}}}{2 \cdot N_{\text{Mice}}}$$
  kết hợp hàm mất mát Focal Loss / Weighted Cross-Entropy để phạt nặng các trường hợp bỏ sót luồng Voi.

---

## 4. QUY TRÌNH TÍCH HỢP VÀO VÒNG LẶP ĐIỀU KHIỂN RYU

Hệ thống phân loại được đóng gói thành một tiến trình dịch vụ nhẹ hoặc module nhúng trong Ryu Controller:

```
[ GÓI TIN ĐẦU LƯỜNG TỚI ACCESS SWITCH ]
               │
               ▼ (Packet-In / Table 0 Priority 50)
[ RYU CONTROLLER: packet_in_handler() ]
               │
               ▼ (Trích xuất 5-tuple & Snapshot 10 Features ban đầu)
[ LIGHTGBM CLASSIFIER INFERENCE SERVICE (< 0.5ms) ]
               │
        ┌──────┴──────┐
        ▼             ▼
   [ DỰ ĐOÁN = 0 ] [ DỰ ĐOÁN = 1 ]
   (Luồng Chuột)    (Luồng Voi Bền vững)
        │             │
        │             ▼
        │     [ GỬI FLOWMOD PRIORITY 1000 ]
        │     Match 5-tuple -> Action: Output(proxy-int)
        │             │
        ▼             ▼
[ TABLE 1 ECMP ] [ CHUYỂN TIẾP VÀO NFV PROXY CẮT 64KB ]
```

---

## 5. THIẾT KẾ CẤU TRÚC MÃ NGUỒN TRONG `ml_engine/classifier/`

Thư mục [`ml_engine/classifier/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/ml_engine/classifier/) sẽ được triển khai với các module sau:

```
ml_engine/classifier/
├── dataset_loader.py          # Nạp dataset từ results/traffic_flow_dataset_with_paths.csv, làm sạch và lọc dữ liệu
├── feature_engineering.py     # Chuẩn hóa RobustScaler, trích xuất 10 features Bi-flow, mã hóa locality
├── train_classifier.py        # Kịch bản huấn luyện XGBoost và LightGBM với Bayesian Hyperparameter Optimization
├── evaluate_model.py          # Xuất báo cáo F1-Score, Confusion Matrix, ROC-AUC curve và thời gian suy luận
├── export_model.py            # Đóng gói mô hình sang định dạng ONNX và C++ header/pickle tối ưu hóa
├── flow_classifier_api.py     # Lớp giao diện suy luận Python thời gian thực phục vụ Ryu Controller
└── models/                    # Thư mục lưu trữ trọng số mô hình đã huấn luyện (.pkl, .onnx)
```

---

## 6. TIÊU CHÍ ĐÁNH GIÁ & NGHIỆM THU HỌC THUẬT (METRICS & GATES)

### 6.1. Bộ Chỉ số Đánh giá Chất lượng Mô hình
- **Độ thu hồi luồng Voi ($\text{Recall}_{\text{Elephant}} \ge 95\%$):**
  $$\text{Recall} = \frac{TP}{TP + FN}$$
  *Ý nghĩa:* Tuyệt đối không để lọt luồng Voi chạy vào đường ECMP thông thường làm nghẽn hàng đợi.
- **Độ chính xác luồng Chuột ($\text{Precision}_{\text{Mice}} \ge 95\%$):**
  $$\text{Precision} = \frac{TN}{TN + FN}$$
  *Ý nghĩa:* Không bẻ nhầm luồng Chuột vào NFV Proxy gây lãng phí tài nguyên CPU và bộ nhớ đệm tái hợp.
- **Điểm F1 tổng thể ($\text{Macro F1-Score} \ge 92\%$):**
  $$F_1 = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$$

### 6.2. Kiểm định Ngân sách Độ trễ (Latency Verification)
- Đo đạc thời gian suy luận trên CPU Intel Core i7 / AMD Ryzen (không cần GPU rời):
  $$t_{\text{preprocess}} + t_{\text{inference}} \le 0.8\text{ ms} \quad (\text{Thỏa mãn ngân sách } < 1.0\text{ ms})$$
