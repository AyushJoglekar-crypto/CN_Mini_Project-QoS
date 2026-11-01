#!/usr/bin/python3
import json
import socket
import struct
import time
import argparse

def main():
    parser = argparse.ArgumentParser(description="QoS Traffic Sender")
    parser.add_argument("--class_name", required=True, help="Traffic class (voice, video, bulk)")
    parser.add_argument("--target", required=True, help="Receiver IP address")
    parser.add_argument("--config", default="config/qos_config.json", help="Path to config file")
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = json.load(f)

    class_info = config['classes'].get(args.class_name.lower())
    if not class_info:
        print(f"[!] Unknown class name: {args.class_name}")
        return

    port = class_info['port']
    # Match the exact key 'target_rate_kbps' from your JSON file
    rate_kbps = class_info.get('target_rate_kbps', 512)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[*] Starting {args.class_name.upper()} sender -> {args.target}:{port} @ {rate_kbps} kbps", flush=True)

    seq = 0
    packet_size = 1024
    bytes_per_sec = (rate_kbps * 1000) / 8
    packets_per_sec = bytes_per_sec / packet_size if bytes_per_sec > 0 else 50
    interval = 1.0 / packets_per_sec if packets_per_sec > 0 else 0.02

    try:
        while True:
            send_time = time.time()
            header = struct.pack('!d Q', send_time, seq)
            payload = header + b'X' * (packet_size - len(header))
            
            sock.sendto(payload, (args.target, port))
            seq += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n[*] {args.class_name.upper()} sender stopped.", flush=True)

if __name__ == '__main__':
    main()
