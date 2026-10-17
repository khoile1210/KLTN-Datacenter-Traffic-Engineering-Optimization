#!/usr/bin/env bash
# Tên file: build_images.sh
# Mô tả   : Script tiện ích tự động build toàn bộ Docker images cho Containernet
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================================================"
echo " BUILD DOCKER IMAGES CHO MẠNG SDN DATACENTER (CONTAINERNET)"
echo "================================================================================"

echo "[*] Bước 1: Build Docker Host image: dcn-host:latest..."
docker build -t dcn-host:latest -f "${SCRIPT_DIR}/Dockerfile.host" "${SCRIPT_DIR}"

echo "[*] Bước 2: Build Docker OVS Switch image: dcn-ovs:latest..."
docker build -t dcn-ovs:latest -f "${SCRIPT_DIR}/Dockerfile.ovs" "${SCRIPT_DIR}"

echo ""
echo "[+] HOÀN TẤT! Đã build thành công 2 Docker images:"
echo "    - dcn-host:latest : Dùng cho 8 host nội bộ (h1-h8) và 1 host Internet (inet)"
echo "    - dcn-ovs:latest  : Dùng cho các Switch OVS có nhúng NFV Proxy (proxy-int)"
echo "================================================================================"
