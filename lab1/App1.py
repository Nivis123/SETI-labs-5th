import socket
import struct
import time
import threading
import argparse
import ipaddress
import sys


MULTICAST_PORT = 5000
HEARTBEAT_INTERVAL = 5
PEER_TIMEOUT = 15
ALIVE_MESSAGE = b"alive"

def is_ipv6(address):
    try:
        return ipaddress.ip_address(address).version == 6
    except ValueError:
        raise ValueError(f"Invalid multicast address: {address}")

def main(multicast_group):
    ipv6 = is_ipv6(multicast_group)
    family = socket.AF_INET6 if ipv6 else socket.AF_INET
    addr_info = (multicast_group, MULTICAST_PORT)

    sock = socket.socket(family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)#____

    if ipv6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 1)  # Выключен!!!
    else:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)  # Выключен!!!!

    if ipv6:
        sock.bind(('', MULTICAST_PORT))
    else:
        sock.bind(('', MULTICAST_PORT))

    if ipv6:
        mreq = struct.pack("16sI", socket.inet_pton(socket.AF_INET6, multicast_group), 0)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq)
    else:
        mreq = struct.pack("4s4s", socket.inet_aton(multicast_group), socket.inet_aton("0.0.0.0"))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    peers = {}
    peers_lock = threading.Lock()

    previous_live = set()

    def sender():
        while True:
            try:
                sock.sendto(ALIVE_MESSAGE, addr_info)
            except Exception as e:
                print(f"Error sending heartbeat: {e}", file=sys.stderr)
            time.sleep(HEARTBEAT_INTERVAL)

    def receiver():
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                peer_ip = addr[0]
                print(f"Received from {peer_ip}: {data} at {time.ctime()}")
                if data == ALIVE_MESSAGE:
                    with peers_lock:
                        peers[peer_ip] = time.time()
            except Exception as e:
                print(f"Error receiving message: {e}", file=sys.stderr)
    def checker():
        nonlocal previous_live
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            current_time = time.time()
            live_peers = set()
            with peers_lock:
                to_remove = [ip for ip, last in peers.items() if current_time - last > PEER_TIMEOUT]
                for ip in to_remove:
                    del peers[ip]
                live_peers = set(peers.keys())

            if live_peers != previous_live:
                if live_peers:
                    print("Live copies:")
                    for ip in sorted(live_peers):
                        print(f"- {ip}")
                else:
                    print("No live copies detected.")
                print() 
                previous_live = live_peers.copy()

    threading.Thread(target=sender, daemon=True).start()
    threading.Thread(target=receiver, daemon=True).start()
    threading.Thread(target=checker, daemon=True).start()

    print(f"Started discovery on multicast group {multicast_group} (IPv{'6' if ipv6 else '4'})")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multicast discovery application")
    parser.add_argument("multicast_group", help="Multicast group address (IPv4 or IPv6)")
    args = parser.parse_args()
    main(args.multicast_group)

    #python3 App1.py ff02::1