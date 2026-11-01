import json
import socket
import threading
import time
from ryu.base import app_manager #Ryu SDN Controller is used here
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types

class QoSController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(QoSController, self).__init__(*args, **kwargs)
        with open('config/qos_config.json', 'r') as f:
            self.config = json.load(f)
        
        self.policy_mode = "dynamic"
        self.congested = False
        self.clear_polls = 0
        self.datapaths = {}
        self.mac_to_port = {}
        self.lock = threading.Lock()
        
        # Start background control server and stats polling monitor
        threading.Thread(target=self.start_control_server, daemon=True).start()
        threading.Thread(target=self.monitor_loop, daemon=True).start()

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofproto = dp.ofproto
        parser = dp.ofproto_parser
        self.datapaths[dp.id] = dp

        # Table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions, table_id=0)

        if dp.id == 1:
            self.install_qos_rules(dp)

    def add_flow(self, datapath, priority, match, actions, table_id=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority, match=match, instructions=inst, table_id=table_id)
        datapath.send_msg(mod)

    def install_qos_rules(self, datapath):
        parser = datapath.ofproto_parser
        for cls_name, info in self.config['classes'].items():
            port = info['port']
            dscp = info['dscp']
            queue_id = info['queue_id'] if self.policy_mode != "best_effort" else 0

            match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=port)
            actions = [
                parser.OFPActionSetField(ip_dscp=dscp),
                parser.OFPActionSetQueue(queue_id),
                parser.OFPActionOutput(port=4)  # FIXED: Output to port 4 (h4 receiver)
            ]
            self.add_flow(datapath, priority=200, match=match, actions=actions, table_id=0)
        self.logger.info(f"[*] Installed QoS Rules | Mode: {self.policy_mode}")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofproto = dp.ofproto
        parser = dp.ofproto_parser
        
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
            
        dst = eth.dst
        src = eth.src
        dpid = dp.id
        
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port
        
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD
            
        actions = [parser.OFPActionOutput(out_port)]
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(dp, 1, match, actions, table_id=0)
            
        data = msg.data
        out = parser.OFPPacketOut(datapath=dp, buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)

    def monitor_loop(self):
        while True:
            time.sleep(self.config['monitoring_interval_sec'])
            with self.lock:
                if self.policy_mode == "dynamic" and self.datapaths:
                    dp = list(self.datapaths.values())[0]
                    parser = dp.ofproto_parser
                    req = parser.OFPPortStatsRequest(dp, 0, ofproto_v1_3.OFPP_ANY)
                    dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        for stat in ev.msg.body:
            if stat.port_no == 2:
                tx_bytes = stat.tx_bytes
                current_util = (tx_bytes * 8) / (self.config['monitoring_interval_sec'] * 1000000)
                if current_util > 8.5:
                    if not self.congested:
                        self.logger.warning(f"[!] Congestion detected ({current_util:.2f} Mbps). Activating QoS queues.")
                        self.congested = True
                        self.clear_polls = 0
                        self.update_queues(active=True)
                else:
                    if self.congested:
                        self.clear_polls += 1
                        if self.clear_polls >= self.config['clear_polls_threshold']:
                            self.logger.info("[*] Link clear. Reverting to best effort.")
                            self.congested = False
                            self.update_queues(active=False)

    def update_queues(self, active):
        for dp_id, dp in self.datapaths.items():
            if dp_id == 1:
                parser = dp.ofproto_parser
                for cls_name, info in self.config['classes'].items():
                    q_id = info['queue_id'] if active else 0
                    match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=info['port'])
                    actions = [
                        parser.OFPActionSetField(ip_dscp=info['dscp'] if active else 0),
                        parser.OFPActionSetQueue(q_id),
                        parser.OFPActionOutput(port=4)  # FIXED: Output to port 4 (h4 receiver)
                    ]
                    self.add_flow(dp, priority=200, match=match, actions=actions, table_id=0)

    def start_control_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(('0.0.0.0', self.config['control_port']))
        while True:
            data, addr = server.recvfrom(1024)
            try:
                msg = json.loads(data.decode())
                cmd = msg.get("type") or msg.get("command")
                resp = {"status": "success"}
                if cmd in ["set_policy", "SET_POLICY"]:
                    with self.lock:
                        self.policy_mode = msg.get("mode")
                        active = (self.policy_mode != "best_effort")
                        self.update_queues(active)
                    resp["message"] = f"Policy updated to {self.policy_mode}"
                elif cmd in ["get_status", "GET_STATUS"]:
                    resp["mode"] = self.policy_mode
                    resp["congested"] = self.congested
                server.sendto(json.dumps(resp).encode(), addr)
            except Exception as e:
                server.sendto(json.dumps({"status": "error", "message": str(e)}).encode(), addr)
