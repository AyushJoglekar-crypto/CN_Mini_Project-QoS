#!/usr/bin/python3
import json
import socket
import struct
import threading
import time
import argparse

def handle_receiver(port, class_name):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    print(f"[*] Receiver listening for {class_name.upper()} on port {port}...", flush=True)

    received = 0
    total_bytes = 0
    start_time = time.time()
    last_print = start_time

    while True:
        try:
            sock.settimeout(2.0)
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue

        arrival = time.time()
        total_bytes += len(data)
        received += 1
        latency = 0.0
        
        if len(data) >= 16:
            send_time, seq = struct.unpack('!d Q', data[:16])
            latency = (arrival - send_time) * 1000.0

        # Print aggregate metrics every 2 seconds cleanly
        if arrival - last_print >= 2.0:
            duration = arrival - start_time
            throughput = (total_bytes * 8) / (duration * 1000) if duration > 0 else 0
            print(f"[{class_name.upper()}] Throughput: {throughput:.2f} kbps | Latency: {latency:.2f} ms", flush=True)
            
            # Reset counters for the next window
            total_bytes = 0
            start_time = arrival
            last_print = arrival

def main():
    parser = argparse.ArgumentParser(description="QoS Traffic Receiver")
    parser.add_argument("--config", default="config/qos_config.json", help="Path to config file")
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = json.load(f)

    threads = []
    for cls_name, info in config['classes'].items():
        t = threading.Thread(target=handle_receiver, args=(info['port'], cls_name))
        t.daemon = True
        t.start()
        threads.append(t)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Receiver stopped.", flush=True)

if __name__ == '__main__':
    main()
