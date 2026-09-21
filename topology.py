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

    info('*** Thêm các Docker Hosts và công cụ mạng\n')
    hosts = []
    for i in range(1, 5):
        h = net.addDocker(f'h{i}', ip=f'10.0.0.{i}/24', dimage="sdn-host:latest")
        hosts.append(h)

    # Thêm h0 (đóng vai trò Guest từ Internet)
    h0 = net.addDocker(f'h0', ip=f'10.0.0.10/24', dimage="sdn-host:latest")

    info('*** Tạo liên kết (Links) giữa Spine và Leaf (Full Mesh)\n')
    for spine in spines:
        net.addLink(spine, h0, cls=TCLink, bw=200, delay='10ms', loss=0.5, max_queue_size=1000)
        
        for leaf in leaves:
            net.addLink(spine, leaf, cls=TCLink, bw=1000, delay='0.1ms', loss=0, max_queue_size=5000)

    info('*** Tạo liên kết giữa Host và Leaf\n')
    for i in range(4):
        net.addLink(hosts[i], leaves[i], cls=TCLink, bw=100, delay='1ms', loss=0, max_queue_size=1000)
    

    info('*** Khởi động mạng SDN\n')
    net.start()

    info('*** Bật giao diện CLI\n')
    CLI(net)

    info('*** Dừng mạng\n')
    net.stop()

if __name__ == '__main__':
    create_spine_leaf_topology()