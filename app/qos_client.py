#!/usr/bin/python3
import json
import socket
import argparse

def main():
    parser = argparse.ArgumentParser(description="QoS Controller Control Client")
    parser.add_argument("--action", choices=["set_policy", "get_status"], required=True, help="Action to perform")
    parser.add_argument("--mode", choices=["dynamic", "best_effort", "static"], default="dynamic", help="Policy mode to set")
    parser.add_argument("--controller_ip", default="127.0.0.1", help="Controller IP address")
    parser.add_argument("--config", default="config/qos_config.json", help="Path to config file")
    args = parser.parse_args()

    # Load control port from config
    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
        control_port = config.get('control_port', 5555)
    except Exception:
        control_port = 5555

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    if args.action == "set_policy":
        payload = {"command": "set_policy", "mode": args.mode}
    else:
        payload = {"command": "get_status"}

    try:
        sock.sendto(json.dumps(payload).encode(), (args.controller_ip, control_port))
        sock.settimeout(2.0)
        data, _ = sock.recvfrom(1024)
        response = json.loads(data.decode())
        print(f"[*] Response from Ryu controller: {response}", flush=True)
    except socket.timeout:
        print("[!] Error: Controller did not respond (timeout). Ensure qos_controller.py is running.", flush=True)
    except Exception as e:
        print(f"[!] Error communicating with controller: {e}", flush=True)

if __name__ == '__main__':
    main()
