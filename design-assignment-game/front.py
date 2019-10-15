import settings

import sys
import socket
import struct
import time
import threading
import random
import queue
import pickle
import urllib
import http.client
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

if len(sys.argv) < 2:
    print("Usage:", sys.argv[0], "<front #>")
    exit()

FRONT = int(sys.argv[1])
addrport = settings.INITIAL_FRONTS[FRONT]["address"]

STORE_MAGIC = -1

sections = settings.INITIAL_SECTIONS_FOR_FRONTS[FRONT]
sections_lock = threading.Lock()

players = {}
players_lock = threading.Lock()

print("Starting front #", FRONT, addrport)

def try_send(s, packet, addr):
    if(random.randint(1, 100) > settings.PACKET_LOSS):
        s.sendto(packet, addr)

# Caller must have sections_lock, players_lock
def update_object(section_id, id, s, s_lock, resend_queue, store_resend_queue):
    section = sections[section_id]
    obj = section["objects"][id]

    section["version"] += 1
    version = section["version"]

    store_packet = b"UPDATE" + pickle.dumps((section_id, version, id, obj))
    with s_lock:
        try_send(s, store_packet, settings.STORE_ADDRPORT)
    sections[section_id]["store_buffer"][version] = store_packet
    store_resend_queue.put((time.time(), (section_id, version)))

    for p in players:
        if players[p]["section"] == section_id:
            packet = b"UPDATE" + pickle.dumps((version, id, obj))
            players[p]["send_buffer"][version] = packet

            with s_lock:
                try_send(s, packet, players[p]["addr"])
                resend_queue.put((time.time(), (p, version)))

def clean_section(section):
    section = section.copy()

    if "store_buffer" in section:
        del section["store_buffer"]

    return section

# Caller must have sections_lock
def store_section(section_id):
    store_conn = http.client.HTTPConnection(settings.STORE_ADDRPORT[0], settings.STORE_ADDRPORT[1])
    data = pickle.dumps((section_id, clean_section(sections[section_id]), FRONT, addrport))

    try:
        store_conn.request("POST", "/map", data)

        response = store_conn.getresponse()
        store_conn.close()

        if response.status == 200:
            sections[section_id]["store_buffer"] = {}
            return True
    except OSError:
        pass
    
    return False

# Caller must have sections_lock, players_lock
def player_command(player, cmd, s, s_lock, resend_queue, store_resend_queue):
    id = player["id"]

    if cmd == b"NOP":
        print("NOP from", player["name"])
        update_object(player["section"], id, s, s_lock, resend_queue, store_resend_queue)

def front_listener(s, s_lock):
    last_quorum_ping = time.time()
    resend_queue = queue.PriorityQueue()
    store_resend_queue = queue.PriorityQueue()
    next_timeout = 1

    while True:
        try:
            data, addr = s.recvfrom(1024)

            if addr == settings.QUORUM_ADDRPORT:
                if data == b"PING":
                    last_quorum_ping = time.time()
                    with s_lock:
                        try_send(s, b"PONG", addr)
            elif addr == settings.STORE_ADDRPORT:
                if data[:3] == b"ACK":
                    section, version = struct.unpack_from("!ll", data[3:])

                    with sections_lock:
                        if section in sections and version in sections[section]["store_buffer"]:
                            del sections[section]["store_buffer"][version]
            else:
                with sections_lock, players_lock:
                    player = None

                    for p in players:
                        if players[p]["addr"] == addr:
                            player = players[p]
                            break
         
                    if player:
                        if data[:4] == b"PONG":
                            player["pingcount"] = 0
                            rtt = time.time() - struct.unpack("!d", data[4:])[0]
                            player["rtt"] = rtt
                        elif data[:3] == b"ACK":
                            version = struct.unpack_from("!l", data[3:])[0]
                            cur_version = sections[player["section"]]["version"]

                            if version < sections[player["section"]]["version"] and version + 1 in player["send_buffer"]:
                                with s_lock:
                                    try_send(s, player["send_buffer"][version + 1], addr)
                            
                            for seq in list(player["send_buffer"]):
                                if seq < version:
                                    del player["send_buffer"][seq]
                            
                            while player["last_recvd_ack"] < cur_version and player["last_recvd_ack"] not in player["send_buffer"]:
                                player["last_recvd_ack"] += 1

                        elif data[:4] == b"QUIT":
                            print("Player", player["id"], "quit")
                            del players[player["id"]]
                        else:
                            seq = struct.unpack_from("!l", data)[0]
                            payload = data[4:]

                            with s_lock:
                                try_send(s, b"ACK" + struct.pack("!l", seq), addr)

                            if seq > player["last_sent_ack"] and seq not in player["recv_buffer"]:
                                player["recv_buffer"][seq] = payload
                            
                            while player["last_sent_ack"]+1 in player["recv_buffer"]:
                                player_command(player, payload, s, s_lock, resend_queue, store_resend_queue)
                                del player["recv_buffer"][player["last_sent_ack"]+1]
                                player["last_sent_ack"] += 1
                    else:
                        with s_lock:
                            try_send(s, b"FRONT!", addr)
        except socket.timeout:
            pass
            
        if time.time() - last_quorum_ping > settings.FRONT_TIMEOUT:
            print("Quorum silent, dying")
            sys.exit(0)

        next_timeout = 1

        try:
            while True:
                timestamp, (player, version) = resend_queue.get(False)

                with players_lock:
                    if player in players and version > players[player]["last_recvd_ack"]:
                        to_next_resend = timestamp + 2 * players[player]["rtt"] - time.time()

                        if to_next_resend < 0 and version in players[player]["send_buffer"]:
                            with s_lock:
                                try_send(s, players[player]["send_buffer"][version], players[player]["addr"])
                            timestamp = time.time()
                            resend_queue.put((timestamp, (player, version)))
                            next_timeout = min(2 * players[player]["rtt"], next_timeout)
                        else:
                            resend_queue.put((timestamp, (player, version)))
                            next_timeout = min(to_next_resend, next_timeout)
                            break
        except queue.Empty:
            pass

        try:
            while True:
                timestamp, (section_id, version) = store_resend_queue.get(False)

                with sections_lock:
                    if section_id in sections and version in sections[section_id]["store_buffer"]:
                        to_next_resend = timestamp + settings.STORE_RESEND_TIMEOUT - time.time()

                        if to_next_resend < 0:
                            with s_lock:
                                try_send(s, sections[section_id]["store_buffer"][version], settings.STORE_ADDRPORT)
                            timestamp = time.time()
                            store_resend_queue.put((timestamp, (section_id, version)))
                            next_timeout = min(settings.STORE_RESEND_TIMEOUT, next_timeout)
                        else:
                            store_resend_queue.put((timestamp, (section_id, version)))
                            next_timeout = min(to_next_resend, next_timeout)
                            break
        except queue.Empty:
            pass
    
def front_sender(s, s_lock):
    print("Starting front sender")
    while True:
        with players_lock:
            for player in players:
                players[player]["pingcount"] += 1

                with s_lock:
                    try_send(s, b"PING" + struct.pack("!dd", players[player]["rtt"], time.time()), players[player]["addr"])

        time.sleep(1)

        with players_lock:
            for player in list(players):
                if players[player]["pingcount"] >= 5:
                    del players[player]
                    print("Player", player, "timed out")

class front_http_handler(BaseHTTPRequestHandler):
    def do_GET(self):
        protocol_version = "HTTP/1.1"

        query = urlparse(self.path)
        vars = parse_qs(query.query)

        if query.path == "/map":
            if "player" in vars and "session" in vars:
                player = int(vars["player"][0])
                session = vars["session"][0]

                with sections_lock, players_lock:
                    if player in players and players[player]["session"] == session:
                        section = players[player]["section"]
                        print("Giving section", section, "to player", player)
                        print(sections[section])

                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(pickle.dumps(clean_section(sections[section])))

                        players[player]["send_buffer"] = {}
                        players[player]["last_recvd_ack"] = sections[section]["version"]
            else:
                self.send_response(400)
                self.end_headers()

    def do_POST(self):
        protocol_version = "HTTP/1.1"

        query = urlparse(self.path)
        content_len = int(self.headers.get('Content-Length'))
        if content_len > 0:
            body = self.rfile.read(content_len)

        if query.path == "/player":
            player = pickle.loads(body)
            id = next(iter(player))
            player[id]["pingcount"] = 0
            player[id]["rtt"] = settings.PLAYER_INITIAL_RTT
            player[id]["last_sent_ack"] = -1 # last consecutively acked packet
            player[id]["recv_buffer"] = {} # list of received packet id's after last_sent_ack

            print("Adding player", player)
            with sections_lock, players_lock:
                players.update(player)
            
            self.send_response(200)
            self.end_headers()
        else:
            self.send_error(404)
            self.end_headers()

def front_http_server():
    httpd = HTTPServer(addrport, front_http_handler)

    try:
        print("Starting HTTP server at", addrport)
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

    httpd.server_close()

def main():
    with sections_lock:
        for section in sections:
            while not store_section(section):
                continue

    front_http_server_thread = threading.Thread(target=front_http_server)
    front_http_server_thread.start()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s_lock = threading.Lock()

        s.bind(addrport)
        s.settimeout(settings.FRONT_TIMEOUT)

        front_listener_thread = threading.Thread(target=front_listener, args=(s, s_lock))
        front_listener_thread.start()

        front_sender_thread = threading.Thread(target=front_sender, args=(s, s_lock))
        front_sender_thread.start()

        front_listener_thread.join()
        front_sender_thread.join()

    front_http_server_thread.join()

if __name__ == "__main__":
    main()