## Điều phối lưu lượng thông mình (Intelligent Traffic Scheduling):

### Graph Attention Network (GAT) - Deep Q-Network (DQN)

##### Bước 1: Topology Discovery

- Controller sử dụng giao thức LLDP (Link Layer Discovery Protocol) và **ARP Snooping/Packet-In** để thăm dò toàn bộ kiến trúc mạng. Đây là dữ liệu cho **edge_index**.

##### Bước 2: Path Calculation: Tính toán các đường khả thi

- Khi có một luồng dữ liệu phát sinh (nguồn $\rightarrow$ đích), Controller chạy thuật toán định tuyến cơ bản (K-Shortest Paths) để tìm ra tất cả các con đường khả thi. (Ví dụ tìm ra 3 con đường)

##### Bước 3: Action Mapping

- Controller gom **3** con đường vừa tìm được vào 1 danh sách (List) với chiều dài = 3.

##### Bước 4: GAT - DQN

- Lấy dữ liệu về trạng thái môi trường mạng từ Controller thông qua `OFPPortStatsRequest` và `OFPFlowStatsRequest`.
- Dữ liệu được trích xuất thành đầu vào GAT có dạng:
  - **_edge_index_**: $[[source, destination]]$ $\rightarrow$ Ví dụ: $[[0, 1, 2 ,3], [2, 3, 1, 0]]$.
  - **_edge_attr_**: $[[att0_1, att0_2, att0_3],[att1_1, att1_2, att1_3],...]$.
  - **_node_attr_**: $[[node0_{cpu}, node0_{ram}, node0_{\%flowtable}, node0_{role}], [node1_{cpu}, node1_{ram}, node1_{\%flowtable}, node1_{role}],...]$.
- DQN nhận vector trạng thái và đánh giá xem đi đường nào (0, 1 hay 2) sẽ mang lại hiệu quả cao nhất (ít nghẽn nhất).
- Output của DQN sẽ là một mảng Q-value, ví dụ: [3.2, 7.5, -1.0].

##### Bước 5: Phiên dịch và Thực thi (Execution)

- Controller cài đặt OpenFlow Rules dựa trên Action $A_t$ mà AI vừa chọn tại trạng thái mạng $S_t$. Các luồng dữ liệu bắt đầu đi theo đường mới.
- Hệ thống chờ một khoảng thời gian ngắn
- Controller lại dùng `OFPPortStatsRequest` để lấy số liệu mạng hiện tại. Đây chính là trạng thái mới $S_{t+1}$.
- Tính toán Reward:
  $$
  R_t = \alpha \cdot U_{\text{throughput}} - \beta \cdot D_{\text{latency}} - \gamma \cdot P_{\text{loss}} - \delta \cdot C_{\text{penalty}}
  $$
- Lưu trữ và Huấn luyện - Store & Train: Hệ thống đóng gói bộ 4 giá trị $(S_t, A_t, R_t, S_{t+1})$ ném vào một bộ nhớ đệm (Replay Buffer). Định kỳ, AI sẽ bốc ngẫu nhiên một chùm dữ liệu từ Replay Buffer để chạy lan truyền ngược ()Backpropagation) cập nhật trọng số cho DQN và GAT.

##### Đánh giá

- Thông lượng (Throughput - $U_{\text{throughput}}$): Chỉ số này đo lường tổng lượng dữ liệu được truyền tải thành công và an toàn từ nguồn đến đích trong một khoảng thời gian nhất định. Thông lượng càng cao chứng tỏ mô hình AI đã học được cách phân bổ luồng dữ liệu vào các liên kết (links) đang rảnh rỗi, khai thác tối đa băng thông vật lý của mạng SDN.
- Độ trễ mạng (Latency - $D_{\text{latency}}$): Đây là thời gian cần thiết để một gói tin đi từ nút nguồn đến nút đích. Trong bài toán điều phối, độ trễ bị ảnh hưởng bởi số bước nhảy (hop count) và thời gian chờ tại hàng đợi của các Switch. AI chọn đường tốt sẽ giúp chỉ số này duy trì ở mức thấp nhất.
- Tỷ lệ mất gói (Packet Loss - $P_{\text{loss}}$): Chỉ số này thể hiện phần trăm số gói tin bị rớt hoặc loại bỏ trong quá trình truyền tải. Nếu AI điều phối dữ liệu đi vào một Switch đang bị tràn bảng băm (TCAM) hoặc một đường link đang bị tấn công DDoS làm quá tải băng thông, tỷ lệ mất gói sẽ tăng vọt.
- Chi phí/Điểm phạt (Penalty - $C_{\text{penalty}}$): Đây là một hằng số linh hoạt dùng để phạt mô hình khi đưa ra các quyết định kém tối ưu. Bạn có thể đánh giá chỉ số này thông qua việc đo lường mức độ tiêu hao tài nguyên (CPU, RAM, % flowtable) của các Node trên đường đi, đảm bảo AI không dồn traffic vào một thiết bị đang kiệt quệ tài nguyên.

##### Điểm phạt C_Penalty

Trong công thức hàm phần thưởng (Reward Function) của mô hình GAT-DQN mà bạn đang xây dựng, giá trị $C_{\text{penalty}}$ (Chi phí/Điểm phạt) đóng vai trò là một "chiếc phanh" nhằm ngăn chặn AI đưa ra những quyết định định tuyến tuy mang lại băng thông cao nhưng lại vắt kiệt sức của các thiết bị mạng. Dưới đây là chi tiết về cơ sở dữ liệu và cách tính toán chỉ số này:1. $C_{\text{penalty}}$ dựa vào đâu?Dựa trên thiết kế đầu vào của mạng Graph Attention Network (GAT) trong đồ án của bạn, $C_{\text{penalty}}$ được tính toán trực tiếp dựa trên trạng thái tài nguyên của các Switch (nút mạng) nằm trên con đường mà AI vừa quyết định chọn. Cụ thể, nó lấy dữ liệu từ ma trận node\*attr mà Controller thu thập được: $CPU$: Mức độ sử dụng vi xử lý của Switch.$RAM$: Mức độ tiêu thụ bộ nhớ của Switch.$\% Flowtable$: Tỷ lệ chiếm dụng bộ nhớ TCAM (bảng luồng) của Switch. Nếu chỉ số này quá cao, Switch sẽ không thể nhận thêm luật định tuyến mới, dẫn đến rớt mạng. 2. $C*{\text{penalty}}$ được tính như thế nào?Vì hệ thống cần đánh giá sức chịu đựng của toàn bộ con đường, $C_{\text{penalty}}$ thường được tính bằng cách kiểm tra xem có bất kỳ thiết bị nào trên tuyến đường đó đang bị quá tải hay không. Có 2 cách phổ biến để thiết lập công thức tính toán trong code Python của bạn:Cách 1: Tính theo hàm ngưỡng (Threshold Step Function) - Khuyên dùngCách này đơn giản và hiệu quả. Bạn đặt ra một ngưỡng an toàn (ví dụ: 80%). Nếu AI chọn một con đường đi qua một Switch có CPU, RAM hoặc Flowtable vượt quá 80%, nó sẽ bị phạt một điểm số rất lớn. Nếu tất cả đều dưới 80%, điểm phạt bằng 0.

$$
C_{\text{penalty}} =  \begin{cases}  100 & \text{nếu } \max(CPU_i, RAM_i, \%Flowtable_i) > 0.8 \text{ với mọi nút } i \in \text{Path} \\ 0 & \text{nếu ngược lại} \end{cases}
$$

Cách 2: Tính theo tổng trọng số tuyến tính (Weighted Sum)Nếu bạn muốn mô hình AI cảm nhận được sự "tăng dần" của mức độ tiêu hao tài nguyên để từ đó né tránh từ sớm, bạn có thể tính $C_{\text{penalty}}$ là tổng mức sử dụng tài nguyên trung bình (hoặc tối đa) của các nút trên đường đi, nhân với các hệ số trọng lượng (weights).Gọi $N$ là tập hợp các Switch trên đường đi mà AI vừa chọn. Đối với mỗi Switch $i$, điểm phạt cục bộ $c_i$ được tính bằng:

$$
c_i = w_1 \cdot CPU_i + w_2 \cdot RAM_i + w_3 \cdot \%Flowtable_i
$$

(Trong đó $w_1, w_2, w_3$ là các hằng số trọng lượng do bạn tự cấu hình, ví dụ $w_3$ nên đặt cao nhất vì tràn Flowtable rất nguy hiểm trong SDN).Khi đó, tổng điểm phạt của toàn hệ thống sẽ lấy giá trị tệ nhất (tối đa) trên con đường đó:

$$
C_{\text{penalty}} = \max_{i \in N} (c_i)
$$

Hoặc lấy giá trị trung bình:

$$
C_{\text{penalty}} = \frac{1}{\vert{}N\vert{}} \sum_{i \in N} c_i
$$

Tóm lại: Khi đưa vào phương trình tổng $R_t$, nếu con đường AI chọn có một Switch đang "hấp hối" (RAM 99%, CPU 95%), giá trị $C_{\text{penalty}}$ sẽ tăng vọt. Nhờ dấu trừ ($- \delta \cdot C_{\text{penalty}}$) trong công thức hàm Reward, tổng điểm thưởng $R_t$ sẽ bị kéo xuống mức âm, ép mạng nơ-ron DQN phải tự điều chỉnh trọng số (Backpropagation) để lần sau "né" cái Switch đang quá tải đó ra.
