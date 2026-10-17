from mininet.net import Containernet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import info, setLogLevel
from mininet.link import TCLink

def create_spine_leaf_topology():
    setLogLevel('info')

    info('*** Khởi tạo mạng Containernet\n')
    net = Containernet(controller=None)

    info('*** Thêm Ryu Remote Controller\n')
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    info('*** Thêm các Spine Switches (Lớp Core)\n')
    spines = []
    for i in range(1, 4):
        s = net.addSwitch(f's{i}', cls=OVSSwitch, protocols='OpenFlow13')
        spines.append(s)

    info('*** Thêm các Leaf Switches (Lớp Access)\n')
    leaves = []
    for i in range(1, 5):
        l = net.addSwitch(f'l{i}', cls=OVSSwitch, protocols='OpenFlow13')
        leaves.append(l)

    info('*** Thêm các Docker Hosts và công cụ mạng (Mặc định 1 rack = 4 hosts)\n')
    hosts = {}
    for i in range(1, 5):
        for h in range(1, 5):
            h_name = f'h{i}_{h}'
            idx = (i - 1) * 4 + h
            hosts[h_name] = net.addDocker(h_name, ip=f'10.0.0.{idx}/24', dimage="dcn-host:latest")

    # Thêm inet (đóng vai trò Guest từ Internet)
    inet = net.addDocker('inet', ip='10.0.0.100/24', dimage="dcn-host:latest")

    info('*** Tạo liên kết (Links) giữa Spine và Leaf (Full Mesh)\n')
    for spine in spines:
        net.addLink(spine, inet, cls=TCLink, bw=200, delay='10ms', loss=0.5, max_queue_size=1000)
        
        for leaf in leaves:
            net.addLink(spine, leaf, cls=TCLink, bw=1000, delay='0.1ms', loss=0, max_queue_size=5000)

    info('*** Tạo liên kết giữa Host và Leaf (Mỗi Leaf nối 4 hosts)\n')
    for i in range(1, 5):
        leaf = leaves[i - 1]
        for h in range(1, 5):
            h_name = f'h{i}_{h}'
            net.addLink(hosts[h_name], leaf, cls=TCLink, bw=100, delay='1ms', loss=0, max_queue_size=1000)
    

    info('*** Khởi động mạng SDN\n')
    net.start()

    info('*** Bật giao diện CLI\n')
    CLI(net)

    info('*** Dừng mạng\n')
    net.stop()

if __name__ == '__main__':
    create_spine_leaf_topology()