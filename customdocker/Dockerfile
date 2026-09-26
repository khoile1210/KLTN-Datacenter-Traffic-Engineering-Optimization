#Host-Dockerfile
FROM ubuntu:22.04

# Tránh các prompt hỏi múi giờ khi cài đặt
ENV DEBIAN_FRONTEND=noninteractive

# Cài đặt các công cụ mạng cần thiết
RUN apt-get update && apt-get install -y \
    iputils-ping \
    iperf \
    iperf3 \
    tcpdump \
    iproute2 \
    net-tools \
    python3 \
    python3-pip \
    python3-scapy \
    && rm -rf /var/lib/apt/lists/*

CMD ["/bin/bash"]