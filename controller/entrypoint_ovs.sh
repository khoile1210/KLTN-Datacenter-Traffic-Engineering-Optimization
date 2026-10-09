#!/usr/bin/env bash
set -e

# Tên switch OVS (lấy từ biến môi trường SW_NAME hoặc hostname)
SW_NAME=${SW_NAME:-$(hostname)}
DPID=${DPID:-""}
CONTROLLER_IP=${CONTROLLER_IP:-"127.0.0.1"}
CONTROLLER_PORT=${CONTROLLER_PORT:-"6653"}
OF_VERSION=${OF_VERSION:-"OpenFlow13"}
ENABLE_PROXY_INT=${ENABLE_PROXY_INT:-"true"}
PROXY_INT_IP=${PROXY_INT_IP:-""}

echo "[*] Khởi động Open vSwitch daemon trên Switch: ${SW_NAME}..."
/etc/init.d/openvswitch-switch start || /usr/share/openvswitch/scripts/ovs-ctl start

# Đợi ovsdb và ovs-vswitchd sẵn sàng
sleep 1

echo "[*] Cấu hình OVS Bridge cho ${SW_NAME}..."
if ! ovs-vsctl br-exists "${SW_NAME}"; then
    ovs-vsctl add-br "${SW_NAME}"
fi

# Gán DPID nếu được chỉ định
if [ -n "${DPID}" ]; then
    ovs-vsctl set bridge "${SW_NAME}" other-config:datapath-id="${DPID}"
    echo "[+] Đã gán DPID=${DPID} cho ${SW_NAME}"
fi

# Cấu hình OpenFlow 1.3 và Fail-mode Secure
ovs-vsctl set bridge "${SW_NAME}" protocols="${OF_VERSION}"
ovs-vsctl set-fail-mode "${SW_NAME}" secure

# Kết nối Controller
echo "[*] Kết nối tới Ryu Controller tại ${CONTROLLER_IP}:${CONTROLLER_PORT}..."
ovs-vsctl set-controller "${SW_NAME}" tcp:${CONTROLLER_IP}:${CONTROLLER_PORT}

# Bật cổng nội bộ proxy-int nếu là Access Leaf Switch (hoặc cờ ENABLE_PROXY_INT=true)
if [ "${ENABLE_PROXY_INT}" = "true" ]; then
    if ! ovs-vsctl list-ports "${SW_NAME}" | grep -q "proxy-int"; then
        echo "[+] Tạo cổng nội bộ NFV Proxy: proxy-int trên ${SW_NAME}..."
        ovs-vsctl add-port "${SW_NAME}" proxy-int -- set Interface proxy-int type=internal
        ip link set dev proxy-int up
        if [ -n "${PROXY_INT_IP}" ]; then
            ip addr add "${PROXY_INT_IP}" dev proxy-int || true
        fi
    fi
fi

echo "[+] Switch ${SW_NAME} đã sẵn sàng vận hành."

# Giữ container chạy ở chế độ foreground
exec tail -f /var/log/openvswitch/ovs-vswitchd.log 2>/dev/null || exec /bin/bash
