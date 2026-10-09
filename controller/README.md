# Ryu apps (topo_discovery, telemetry_poller, flow_manager)

```
Ryu apps (topo_discovery, telemetry_poller, flow_manager)
```

### Installation

```

#!/usr/bin/env bash
set -e

# ==========================================
# 1. HỆ THỐNG CƠ BẢN VÀ DOCKER
# ==========================================
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y git ansible aptitude python3-pip python3-venv docker.io build-essential

# Kích hoạt Docker daemon và phân quyền user
sudo systemctl daemon-reload
sudo systemctl enable --now docker
sudo usermod -aG docker $USER

# Nâng cấp công cụ build Python
sudo python3 -m pip install --upgrade packaging setuptools

# ==========================================
# 2. CÀI ĐẶT MININET & CONTAINERNET
# ==========================================
cd ~
[ ! -d "containernet" ] && git clone https://github.com/containernet/containernet.git

# Chạy Ansible playbook build Open vSwitch và Mininet Core
cd ~/containernet/ansible
sudo ansible-playbook -i "localhost," -c local install.yml

# Cài đặt Containernet package vào Python
cd ~/containernet
sudo python3 -m pip install -e . --no-build-isolation

# Kéo image Docker Ubuntu mẫu
sudo docker pull ubuntu:trusty

# ==========================================
# 3. CÀI ĐẶT VÀ VÁ RYU CONTROLLER (PYTHON 3.10)
# ==========================================
cd ~/containernet
[ ! -d "ryu" ] && git clone https://github.com/faucetsdn/ryu.git
cd ryu

# Vá setup.py của Ryu
sed -i 's/ryu.hooks.save_orig()/# ryu.hooks.save_orig()/g' setup.py
sudo python3 -m pip install .

# Nâng cấp eventlet và greenlet tương thích Python 3.10
sudo python3 -m pip install eventlet==0.33.3 "greenlet<3.0"

# Tự động map collections.abc sang collections khi nạp môi trường Python
sudo python3 -c '
content = """import collections
import collections.abc

for name in dir(collections.abc):
    if not name.startswith("_"):
        setattr(collections, name, getattr(collections.abc, name))
"""
with open("/usr/local/lib/python3.10/dist-packages/sitecustomize.py", "w") as f:
    f.write(content)
'

# Vá trực tiếp các gọi hàm cũ trong thư viện dns, ryu, tinyrpc
sudo find /usr/local/lib/python3.10/dist-packages/dns \
          /usr/local/lib/python3.10/dist-packages/ryu \
          /usr/local/lib/python3.10/dist-packages/tinyrpc \
          -type f -name "*.py" -exec sed -i \
  -e 's/collections\.MutableMapping/collections.abc.MutableMapping/g' \
  -e 's/collections\.Mapping/collections.abc.Mapping/g' \
  -e 's/collections\.Iterable/collections.abc.Iterable/g' \
  -e 's/collections\.Callable/collections.abc.Callable/g' \
  -e 's/from collections import MutableMapping/from collections.abc import MutableMapping/g' \
  -e 's/from collections import Mapping/from collections.abc import Mapping/g' \
  -e 's/from collections import Iterable/from collections.abc import Iterable/g' \
  -e 's/from collections import Callable/from collections.abc import Callable/g' \
  {} + 2>/dev/null || true


pip3 install psutil requests pandas networkx
pip3 install numpy pandas matplotlib seaborn
```

### Build Docker Images

```bash
# 1. Build image Docker Host (dcn-host:latest)
docker build -t dcn-host:latest -f Dockerfile .

# 2. Build image Docker OVS Switch nhúng NFV Proxy (dcn-ovs:latest)
docker build -t dcn-ovs:latest -f Dockerfile.ovs .
```

### Run

```bash
# Terminal 1: Run Controller (Ryu OF1.3)
ryu-manager --observe-links controller.py ryu.app.ofctl_rest ryu.app.rest_topology --ofp-tcp-listen-port 6653

# Terminal 2: Run Topology Spine-Leaf
sudo python3 spine_leaf_topo.py

(containernet>) pingall

# Terminal 3: Run Management Plane (Thu thập 10 Features + Full Hop-by-Hop Paths)
python3 management_plane.py

# Terminal 4: Sinh tải luồng Voi và Chuột liên tục (Đa kênh iperf3)
sudo python3 traffic_generator.py

# Terminal 5: Phân tích kết quả sau khi thu thập
python3 analyze_csv_result.py
```

### Xử lý khi bị treo Terminal / Dọn dẹp:

```bash
# 1. Tiêu diệt toàn bộ tiến trình Mininet, Ryu, iperf3 và Python
sudo killall -9 containernet mn ryu-manager python3 iperf3 2>/dev/null

# 2. Xóa sạch các Docker Container do Mininet/Containernet khởi tạo
docker rm -f $(docker ps -a -q --filter "name=mn.") 2>/dev/null

# 3. Dọn dẹp card mạng ảo (veth pairs) và cấu hình OVS còn sót lại
sudo mn -c

# 4. Đặt lại trạng thái terminal nếu bị lỗi phông/ẩn chữ
stty sane && reset
```

### Collect CSV

```powershell
scp -i '.\sshkey.pem' ubuntu@35.187.226.188:/home/ubuntu/dcn/controller/results/*.csv .\controller\results\
```

