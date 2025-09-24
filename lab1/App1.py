import socket
import struct
import time
import threading
import argparse
import ipaddress
import sys
import signal

MULTICAST_PORT = 5000
REGISTRATION_TIMEOUT = 3
RESPONSE_TIMEOUT = 10
ALIVE_MESSAGE = struct.pack("!B", 0) 

def get_name():
    return f"{socket.gethostname()}:{MULTICAST_PORT}".encode()[:500]

def is_ipv6(address):
    try:
        ip = ipaddress.ip_address(address)
        if not ip.is_multicast:
            raise ValueError(f"Not a multicast address: {address}")
        return ip.version == 6
    except ValueError as e:
        raise ValueError(f"Invalid multicast address: {address}") from e

def handler(sig, frame):
    global sock
    print("Shutting down...")
    if sock:
        sock.sendto(struct.pack("!BH", 1, len(get_name())) + get_name(), addr_info) 
        sock.close()
    sys.exit(0)

def main(multicast_group):
    global sock, addr_info
    ipv6 = is_ipv6(multicast_group)
    family = socket.AF_INET6 if ipv6 else socket.AF_INET
    addr_info = (multicast_group, MULTICAST_PORT)

    sock = socket.socket(family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    if ipv6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 0)
    else:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)

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
        name = get_name()
        msg = struct.pack("!BH", 0, len(name)) + name  
        while True:
            try:
                sock.sendto(msg, addr_info)
                time.sleep(REGISTRATION_TIMEOUT)  
            except Exception as e:
                print(f"Error sending heartbeat: {e}", file=sys.stderr)

    def receiver():
        sock.settimeout(RESPONSE_TIMEOUT)  
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if len(data) >= 3:  # Минимум Type + Length
                    type_val = struct.unpack("!B", data[:1])[0]
                    length = struct.unpack("!H", data[1:3])[0]
                    if len(data[3:]) == length and length <= 500:
                        peer_ip = addr[0]
                        with peers_lock:
                            peers[peer_ip] = time.time()
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving message: {e}", file=sys.stderr)

    def checker():
        nonlocal previous_live
        while True:
            time.sleep(REGISTRATION_TIMEOUT)
            current_time = time.time()
            live_peers = set()
            with peers_lock:
                to_remove = [ip for ip, last in peers.items() if current_time - last > RESPONSE_TIMEOUT]
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

    signal.signal(signal.SIGINT, handler)
    while True:
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multicast discovery application")
    parser.add_argument("multicast_group", help="Multicast group address (IPv4 or IPv6)")
    args = parser.parse_args()
    main(args.multicast_group)