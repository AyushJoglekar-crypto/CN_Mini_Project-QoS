#!/usr/bin/python3
import os
import time
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink
from mininet.cli import CLI

class QOSTopo(Topo):
    def build(self):
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, protocols='OpenFlow13')
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, protocols='OpenFlow13')
        
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01') # Voice
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02') # Video
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:03')   # Bulk
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04') # Receiver
        nat0 = self.addHost('nat0', ip='10.0.0.254/24', mac='00:00:00:00:00:FE')

        # Switch s1 ports: 
        # port 1 -> h1
        # port 2 -> h2
        # port 3 -> h3
        # port 4 -> s2 (bottleneck link)
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)
        
        # 10 Mbps bottleneck link between s1 and s2 (s1-eth4 links to s2)
        self.addLink(s1, s2, bw=10, max_queue_size=100)
        
        self.addLink(s2, h4)
        self.addLink(s2, nat0)

def setup_htb_queues():
    print("[*] Waiting for OVS interfaces to initialize...")
    time.sleep(1.5)  # Allow interfaces to settle
    print("[*] Configuring Linux HTB Queues on s1-eth4 (10 Mbps Bottleneck)...")
    
    # Queue IDs aligned with your qos_config.json:
    # Queue 0 (Bulk), Queue 1 (Video), Queue 2 (Voice)
    cmd = """
    ovs-vsctl set port s1-eth4 qos=@newqos -- \
    --id=@newqos create qos type=linux-htb other-config:max-rate=10000000 queues=0=@q0,1=@q1,2=@q2 -- \
    --id=@q0 create queue other-config:min-rate=1000000 other-config:priority=2 -- \
    --id=@q1 create queue other-config:min-rate=4000000 other-config:priority=1 -- \
    --id=@q2 create queue other-config:min-rate=3000000 other-config:priority=0
    """
    os.system(cmd)

def run_demo():
    topo = QOSTopo()
    # Fixed controller port to standard Ryu port 6633
    net = Mininet(topo=topo, link=TCLink, controller=None)
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)
    net.start()
    
    setup_htb_queues()
    
    print("[*] Testing reachability...")
    net.pingAll()
    
    print("\n[+] --- Mininet Topology & HTB Queues Ready for Deliverable 2 ---")
    CLI(net)
    net.stop()

if __name__ == '__main__':
    run_demo()
