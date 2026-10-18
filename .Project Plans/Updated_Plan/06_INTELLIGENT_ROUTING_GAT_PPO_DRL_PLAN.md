# KẾ HOẠCH CHI TIẾT: ĐỊNH TUYẾN ĐA ĐƯỜNG THÔNG MINH BẰNG GAT KẾT HỢP PPO DRL
## (INTELLIGENT MULTIPATH ROUTING VIA GAT & PPO DRL PLAN)

> **Mã chuyên đề:** `PLAN-WP06-INTELLIGENT-ROUTING`  
> **Thuộc dự án:** Nghiên cứu Tối ưu hóa Kỹ thuật Lưu lượng trong Mạng DCN Dựa trên SDN và AI (SDN-AI DCN)  
> **Cố vấn chuyên môn:** Senior SDN Architect (Gemini 4 Argon)  
> **Trạng thái thực tế:** **SẴN SÀNG TRIỂN KHAI (PHASE 2 & 3 WORK PACKAGE)**  
> **Thư mục mã nguồn:** [`ml_engine/routing/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/ml_engine/routing/)  

---

## 1. MỤC TIÊU & BÀI TOÁN KHOA HỌC

1. **Bài toán Kỹ thuật Lưu lượng Thích ứng (Adaptive Traffic Engineering - TE):** Giải quyết nhược điểm băm tĩnh của ECMP khi gặp mạng bất đối xứng tải hoặc khi xuất hiện đồng thời nhiều luồng Voi lớn bằng cách tính toán ma trận tỷ lệ phân tải tối ưu $\vec{w}$ qua các đường dẫn song song.
2. **Biểu diễn Cấu trúc Đồ thị Tô-pô bằng Mạng Chú ý Đồ thị (Graph Attention Network - GAT):** Thay vì làm phẳng dữ liệu thành vector 1 chiều làm mất quan hệ không gian, GAT nhúng trực tiếp đồ thị mạng $\mathcal{G} = (\mathcal{V}, \mathcal{E})$ thành các vector nhúng (Node Embeddings) phản ánh tương quan nghẽn giữa các switch lân cận trong thời gian $< 2.0\text{ ms}$.
3. **Tối ưu hóa Ma trận Phân tải Đa đường bằng Học tăng cường Sâu (PPO DRL):** Sử dụng thuật toán Proximal Policy Optimization huấn luyện chính sách tác tử điều phối liên tục, tối đa hóa thông lượng Bisection Bandwidth, triệt tiêu rớt gói và san phẳng tỷ lệ sử dụng liên kết (Link Fairness).
4. **Xây dựng Môi trường Chuẩn Gymnasium DCN (`drl-gym-environment`):** Đóng gói toàn bộ tô-pô mạng Containernet và telemetry thành môi trường Gymnasium có giao diện `step(action)` và `reset()` chuẩn mực phục vụ huấn luyện và kiểm thử.

---

## 2. CƠ SỞ KHOA HỌC, ĐỊNH LÝ GỐC & TÀI LIỆU THAM KHẢO

- **[Mạng Chú ý Đồ thị & Biểu diễn Topo Mạng]** P. Veličković, G. Cucurull, A. Casanova, A. Romero, P. Liò, Y. Bengio, *"Graph Attention Networks"*, International Conference on Learning Representations (ICLR), 2018; ứng dụng vào định tuyến mạng: K. Rusek, et al., *"RouteNet: Leveraging Graph Neural Networks for Network Modeling and Optimization in SDN"*, IEEE Journal on Selected Areas in Communications (JSAC), Vol. 38, No. 10, 2020. *(Cơ chế nhúng đồ thị bất biến hoán vị và tính hệ số chú ý cạnh động).*
- **[Thuật toán PPO & Vùng Tin cậy Cắt xén]** J. Schulman, F. Wolski, P. Dhariwal, A. Radford, O. Klimov (OpenAI), *"Proximal Policy Optimization Algorithms"*, arXiv:1707.06347, 2017; kế thừa định lý cải tiến chính sách an toàn: S. Kakade, J. Langford, *"Approximately Optimal Approximate Reinforcement Learning"*, ICML 2002. *(Cơ chế Clipped Surrogate Objective tạo chặn dưới bi quan, loại bỏ dao động rung giật tuyến đường).*
- **[Ước lượng Ưu thế Tổng quát GAE]** J. Schulman, P. Moritz, S. Levine, M. I. Jordan, P. Abbeel (UC Berkeley), *"High-Dimensional Continuous Control Using Generalized Advantage Estimation"*, ICLR 2016. *(Cân bằng tối ưu giữa độ chệch và phương sai của gradient chính sách).*
- **[Chỉ số Công bằng Jain & 5 Tiên đề Tài nguyên]** R. K. Jain, D.-M. W. Chiu, W. R. Hawe, *"A Quantitative Measure of Fairness and Discrimination for Resource Allocation in Shared Computer Systems"*, DEC Research Report TR-301, 1984; D.-M. Chiu, R. Jain, *"Analysis of the Increase and Decrease Algorithms for Congestion Avoidance in Computer Networks"*, Computer Networks and ISDN Systems, 1989. *(Chứng minh toán học 5 tiên đề công bằng: Scale invariance, Symmetry, Continuity, Boundedness, Monotonicity).*

---

## 3. MÔ HÌNH TOÁN HỌC QUÁ TRÌNH QUYẾT ĐỊNH MARKOV (MDP FORMULATION)

Bài toán điều phối được mô hình hóa thành một Quá trình Quyết định Markov: $\mathcal{M} = \langle \mathcal{S}, \mathcal{A}, \mathcal{P}, \mathcal{R}, \gamma \rangle$.

### 3.1. Không gian Trạng thái (State Space $\mathcal{S}$) qua GAT Graph Embedding
Mạng DCN được biểu diễn dưới dạng đồ thị có hướng $\mathcal{G} = (\mathcal{V}, \mathcal{E})$:
- **Đặc trưng Đỉnh (Node Feature Matrix $X_v \in \mathbb{R}^{|V| \times d_v}$):**
  $$X_v = [\text{DPID}, \ \text{Switch Tier}, \ \text{Queue Occupancy \%}, \ \text{TCAM Active Rules}, \ \text{CPU \%}]^T$$
- **Đặc trưng Cạnh (Edge Feature Matrix $E_{uv} \in \mathbb{R}^{|E| \times d_e}$):**
  $$E_{uv} = [\text{Capacity } C_e, \ \text{Current Throughput } B_e, \ \text{Utilization } U_e = B_e / C_e, \ \text{ECN CE Rate}, \ \text{Drop Rate}]^T$$
- **Cơ chế Lan truyền Chú ý Đồ thị (Graph Attention Layer):**
  Hệ số chú ý $\alpha_{ij}$ giữa switch $i$ và switch $j$ lân cận:
  $$\alpha_{ij} = \frac{\exp\left(\text{LeakyReLU}\left(\vec{a}^T [W \vec{h}_i \,\|\, W \vec{h}_j \,\|\, W_e \vec{e}_{ij}]\right)\right)}{\sum_{k \in \mathcal{N}_i} \exp\left(\text{LeakyReLU}\left(\vec{a}^T [W \vec{h}_i \,\|\, W \vec{h}_k \,\|\, W_e \vec{e}_{ik}]\right)\right)}$$
  Vector nhúng mới của đỉnh $i$:
  $$\vec{h}'_i = \sigma\left(\sum_{j \in \mathcal{N}_i} \alpha_{ij} W \vec{h}_j\right)$$
  Sau 2 lớp GATConv, đồ thị được tổng hợp qua phép Readout thành vector trạng thái toàn cục:
  $$\vec{s}_t = \text{GlobalMeanPool}(\{\vec{h}'_v\}) \in \mathbb{R}^{128}$$

---

### 3.2. Không gian Hành động (Action Space $\mathcal{A}$)
Tại mỗi chu kỳ điều khiển $\Delta t = 2.0\text{s}$, Agent xuất ra vector tỷ lệ phân chia lưu lượng liên tục (Continuous Splitting Weights) trên $K$ đường dẫn khả thi (qua các Core/Spine switches):
$$\vec{a}_t = [w_1, w_2, \dots, w_K]^T \in \mathbb{R}^K, \quad \text{thỏa mãn } \sum_{k=1}^K w_k = 1 \ \text{và } w_k \ge 0$$
Vector $\vec{a}_t$ được chuẩn hóa thông qua tầng kích hoạt **Softmax** tại lớp output của mạng Policy Actor:
$$w_k = \frac{\exp(z_k)}{\sum_{j=1}^K \exp(z_j)}$$
*(Ví dụ: $\vec{w} = [0.45, 0.30, 0.15, 0.10]$ chỉ định Ingress NFV Proxy rải $45\%$ khối dữ liệu qua Core 1, $30\%$ qua Core 2,...)*.

---

### 3.3. Thuật toán Cập nhật Chính sách PPO (Proximal Policy Optimization)
Mạng Actor-Critic được tối ưu hóa bằng hàm mục tiêu Clipped Surrogate Objective:
$$L^{\text{CLIP}}(\theta) = \hat{\mathbb{E}}_t \left[ \min\left( r_t(\theta) \hat{A}_t, \, \text{clip}(r_t(\theta), 1-\epsilon, 1+\epsilon) \hat{A}_t \right) \right]$$
Trong đó:
- Tỷ số xác suất hành động: $r_t(\theta) = \frac{\pi_\theta(\vec{a}_t | \vec{s}_t)}{\pi_{\theta_{\text{old}}}(\vec{a}_t | \vec{s}_t)}$.
- Ngưỡng cắt xén: $\epsilon = 0.2$ (ngăn chặn chính sách thay đổi quá đột ngột, triệt tiêu hiện tượng Route Flapping).
- Ước lượng Ưu thế: $\hat{A}_t$ được tính toán qua thuật toán Generalized Advantage Estimation ($\text{GAE}(\gamma=0.99, \ \lambda=0.95)$).

---

### 3.4. Hàm Phần thưởng Đa Mục tiêu (Multi-Objective Reward Function)
Hàm phần thưởng $R_t$ cân bằng đồng thời 4 mục tiêu kỹ thuật mạng:
$$R_t = \lambda_1 \cdot \left(\frac{\text{Throughput}_{\text{total}}}{\text{Capacity}_{\text{bisection}}}\right) - \lambda_2 \cdot \max_{e \in \mathcal{E}}(U_{e, t}) - \lambda_3 \cdot \left(\frac{\text{Packet Drops}_t}{\text{Total Packets}_t}\right) + \lambda_4 \cdot \mathcal{J}_t$$
Trong đó:
- $\lambda_1 = 2.0$: Thưởng cho việc tối đa hóa thông lượng chuyển giao hữu ích.
- $\lambda_2 = 1.5$: Phạt nặng liên kết có tải cao nhất (Max Link Utilization - tắc nghẽn cổ chai).
- $\lambda_3 = 5.0$: Phạt cực nặng hiện tượng rớt gói.
- $\lambda_4 = 1.0$: Thưởng cho sự công bằng tải giữa các liên kết qua **Chỉ số Công bằng Jain (Jain's Fairness Index $\mathcal{J}_t$)**:
  $$\mathcal{J}(U_1, U_2, \dots, U_m) = \frac{\left(\sum_{i=1}^m U_i\right)^2}{m \sum_{i=1}^m U_i^2} \in [0, 1]$$

---

## 4. THIẾT KẾ MÔI TRƯỜNG GYMNASIUM DCN (`gym_dcn_env.py`)

Môi trường tuân thủ chuẩn Gymnasium API của Farama Foundation:
```python
import gymnasium as gym
from gymnasium import spaces

class DCNGymEnv(gym.Env):
    """Môi trường DRL Gymnasium điều phối lưu lượng DCN 2 Cụm Clos."""
    def __init__(self, topo_config_path, telemetry_api_url):
        super(DCNGymEnv, self).__init__()
        # Không gian hành động: Vector trọng số liên tục qua K=4 uplink paths
        self.action_space = spaces.Box(low=0.0, high=1.0, shape=(4,), dtype=np.float32)
        # Không gian quan sát: Đồ thị trạng thái nhúng (128 chiều)
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(128,), dtype=np.float32)

    def step(self, action):
        # 1. Chuẩn hóa action bằng Softmax (Tổng w_i = 1.0)
        norm_weights = np.exp(action) / np.sum(np.exp(action))
        
        # 2. Đẩy ma trận tỷ lệ sang NFV Proxy và Ryu Controller qua REST API
        self.apply_splitting_weights(norm_weights)
        
        # 3. Chờ chu kỳ telemetry (2 giây) và đọc trạng thái mạng mới
        new_state, metrics = self.fetch_telemetry_state()
        
        # 4. Tính toán phần thưởng đa mục tiêu
        reward = self.compute_reward(metrics)
        terminated = False
        truncated = False
        info = metrics
        return new_state, reward, terminated, truncated, info
```

---

## 5. THIẾT KẾ CẤU TRÚC MÃ NGUỒN TRONG `ml_engine/routing/`

Thư mục [`ml_engine/routing/`](file:///c:/Users/USER/Desktop/SDN%20KLTN/ml_engine/routing/) bao gồm:

```
ml_engine/routing/
├── __init__.py
├── gym_dcn_env.py             # Lớp môi trường Gymnasium DCN tích hợp Containernet & Telemetry API
├── gat_embedding_model.py     # Mô hình Mạng Chú ý Đồ thị GAT (PyTorch Geometric GATConv)
├── ppo_agent.py               # Thuật toán Actor-Critic PPO với Clipped Objective & GAE
├── train_drl_agent.py         # Kịch bản huấn luyện tương tác thời gian thực với mạng Containernet
├── reward_functions.py        # Các hàm tính toán phần thưởng Bisection BW, Drops và Jain's Index
├── evaluate_policy.py         # Kịch bản đối sánh hiệu năng (So sánh đường hội tụ PPO vs ECMP tĩnh)
├── routing_service.py         # Tiến trình phục vụ suy luận thời gian thực cho Ryu Controller
└── saved_checkpoints/         # Thư mục lưu trữ checkpoint trọng số nơ-ron (.pt, .onnx)
```

---

## 6. TIÊU CHÍ KIỂM ĐỊNH & NGHIỆM THU HỌC THUẬT (ACCEPTANCE GATES)

- [ ] **Hội tụ Chính sách (Policy Convergence):** Đường cong Reward trung bình tăng trưởng ổn định và đạt trạng thái hội tụ phẳng sau $100 - 300$ episodes huấn luyện.
- [ ] **San phẳng Tải Liên kết:** Dưới tải bão hòa $80\% - 95\%$, chỉ số Jain's Fairness Index của các liên kết Uplink đạt $\mathcal{J} > 0.90$ (vượt trội so với ECMP chỉ đạt $\approx 0.65$).
- [ ] **Thời gian Suy luận Nhanh:** Thời gian tính toán GAT + PPO hoàn thành trong $t_{\text{step}} < 2.5\text{ ms}$, hoàn toàn đáp ứng chu kỳ điều phối $2.0\text{ giây}$ của Controller.
- [ ] **Bảo toàn Tính Toàn vẹn:** Tỷ lệ rớt gói toàn mạng giảm tối thiểu $30\%$ so với định tuyến ECMP tĩnh.
