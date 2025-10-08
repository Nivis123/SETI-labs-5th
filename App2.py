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
MAX_MESSAGE_LENGTH = 500

def is_ipv6(address):
    try:
        return ipaddress.ip_address(address).version == 6
    except ValueError:
        raise ValueError(f"Invalid multicast address: {address}")

def get_local_ip(family, group, port, interface_ip=None):
    if interface_ip:
        return interface_ip
    
    s = socket.socket(family, socket.SOCK_DGRAM)
    try:
        s.connect((group, port))
        ip = s.getsockname()[0]
    except Exception as e:
        print(f"Error getting local IP: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        s.close()
    return ip

def create_message(type_value, data):
    length = len(data)
    if length > MAX_MESSAGE_LENGTH - 3:
        raise ValueError("Message length exceeds maximum allowed")
    return struct.pack("!BH", type_value, length) + data

def main(multicast_group, interface_ip=None):
    ipv6 = is_ipv6(multicast_group)
    family = socket.AF_INET6 if ipv6 else socket.AF_INET
    group = multicast_group
    port = MULTICAST_PORT
    addr_info = (group, port)

    local_ip = get_local_ip(family, group, port, interface_ip)
    print(f"Using local IP: {local_ip}")

    ALIVE_MESSAGE = create_message(0, b"Kirill!")
    DEAD_MESSAGE = create_message(1, b"Kirill!")

    server_sock = socket.socket(family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.settimeout(3)  

    bind_addr = '' if ipv6 else ''
    server_sock.bind((bind_addr, port))

    if ipv6:
        if interface_ip:
            interface_index = socket.if_nametoindex(interface_ip) if not interface_ip.replace('.', '').isdigit() else int(interface_ip)
            mreq = struct.pack("16sI", socket.inet_pton(socket.AF_INET6, group), interface_index)
        else:
            mreq = struct.pack("16sI", socket.inet_pton(socket.AF_INET6, group), 0)
        server_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq)
    else:
        if interface_ip:
            mreq = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton(interface_ip))
        else:
            mreq = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton("0.0.0.0"))
        server_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    client_sock = socket.socket(family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    if ipv6:
        if interface_ip:
            client_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, socket.inet_pton(socket.AF_INET6, interface_ip))
        client_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
        client_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 0)
    else:
        if interface_ip:
            client_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip))
        client_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        client_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)

    peers = {}
    peers_lock = threading.Lock()

    previous_live = set()
    running = True

    def sender():
        while running:
            try:
                client_sock.sendto(ALIVE_MESSAGE, addr_info)
            except Exception as e:
                print(f"Error sending heartbeat: {e}", file=sys.stderr)
            time.sleep(HEARTBEAT_INTERVAL)

    def receiver():
        while running:
            try:
                data, addr = server_sock.recvfrom(MAX_MESSAGE_LENGTH)
                if len(data) >= 3:  
                    t = data[0]
                    msg_len = struct.unpack('!H', data[1:3])[0]
                    msg = data[3:3+msg_len]
                    if len(data) == 3 + msg_len and msg_len <= MAX_MESSAGE_LENGTH - 3:
                        if t == 0:
                            with peers_lock:
                                peers[addr[0]] = time.time()
                            print(f"Received alive from {addr[0]} at {time.ctime()}")
                            print(str(msg))
                        elif t == 1:
                            with peers_lock:
                                if addr[0] in peers:
                                    del peers[addr[0]]
                            print(f"Peer {addr[0]} disconnected at {time.ctime()}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving message: {e}", file=sys.stderr)

    def checker():
        nonlocal previous_live
        while running:
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

    sender_thread = threading.Thread(target=sender, daemon=True)
    receiver_thread = threading.Thread(target=receiver, daemon=True)
    checker_thread = threading.Thread(target=checker, daemon=True)

    sender_thread.start()
    receiver_thread.start()
    checker_thread.start()

    print(f"Started discovery on multicast group {multicast_group} (IPv{'6' if ipv6 else '4'})")
    print(f"Using interface: {local_ip}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        running = False
        print("Shutting down...")
        try:
            client_sock.sendto(DEAD_MESSAGE, addr_info)
            print("Sent disconnect message to peers")
        except Exception as e:
            print(f"Error sending disconnect message: {e}", file=sys.stderr)
        server_sock.close()
        client_sock.close()
        sender_thread.join(timeout=1)
        receiver_thread.join(timeout=1)
        checker_thread.join(timeout=1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multicast discovery application")
    parser.add_argument("multicast_group", help="Multicast group address (IPv4 or IPv6)")
    parser.add_argument("--interface", "-i", help="Specific interface IP to use")
    args = parser.parse_args()
    main(args.multicast_group, args.interface)
#python App2.py 239.0.0.1 --interface 10.217.247.104