import settings

import sys
import socket
import pickle
import time
import threading
import urllib
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

fronts = settings.INITIAL_FRONTS
for id in fronts:
    fronts[id]["pingcount"] = 0
    fronts[id]["failed"] = False
fronts_lock = threading.Lock()

section_neighbors = {}
section_neighbors_lock = threading.Lock()

players = settings.INITIAL_PLAYERS
players_lock = threading.Lock()

# Caller must have fronts_lock
def fail_front(id):
    print("Front", id, "failed")

    fronts[id]["failed"] = True

def front_pinger(s):
    while True:
        with fronts_lock:
            for id in fronts:
                front = fronts[id]

                if not front["failed"] and front["pingcount"] > 4:
                    fail_front(id)

                s.sendto(b"PING", front["address"])

                front["pingcount"] += 1
        time.sleep(1)

def front_pong_listener(s):
    while True:
        data, addr = s.recvfrom(1024)
        if data == b"PONG":
            with fronts_lock:
                for id in fronts:
                    front = fronts[id]

                    if front["address"] == addr:
                        front["pingcount"] = 0

                        if front["failed"]:
                            front["failed"] = False
                            print("Front", id, "back alive")

# caller must have fronts_lock and players_lock
def request_front_for_player(front, player):
    if not front["failed"]:
        addrport = front["address"]

        front_conn = http.client.HTTPConnection(addrport[0], addrport[1])
        try:
            print("Requesting front", addrport, "for player", next(iter(player.values()))["name"])

            front_conn.request("POST", "/player", pickle.dumps(player))

            response = front_conn.getresponse()
            front_conn.close()

            if response.status == 200:
                return True
        except OSError:
            pass

    return False

# Caller must have fronts_lock, players_lock
def request_front_for_section(front, source, section, neighbors):
    if not fronts[front]["failed"]:
        addrport = fronts[front]["address"]

        front_conn = http.client.HTTPConnection(addrport[0], addrport[1])

        try:
            print("Requesting front", addrport, "for section", section)

            front_conn.request("POST", "/map", pickle.dumps((source, section, neighbors)))

            response = front_conn.getresponse()
            front_conn.close()
            
            if response.status == 200:
                return True
        except OSError:
            pass
    return False

class quorum_http_handler(BaseHTTPRequestHandler):
    def do_POST(self):
        protocol_version = "HTTP/1.1"

        query = urlparse(self.path)
        content_len = int(self.headers.get('Content-Length'))
        if content_len > 0:
            body = self.rfile.read(content_len)

        if query.path == "/front":
            client = pickle.loads(body)

            with fronts_lock, players_lock:
                player = players[client["id"]]
                player["addr"] = client["addr"]
                player["session"] = client["session"]

                front = fronts[player["front"]]

                if request_front_for_player(front, { client["id"]: player } ):
                    print("Giving front", front, "to", player["name"], "at", client["addr"])

                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(pickle.dumps(front["address"]))
                else:
                    self.send_error(503)
                    self.end_headers()
        elif query.path == "/move":
            player, (front, section) = pickle.loads(body)

            for f in fronts:
                if fronts[f]["address"] == front:
                    new_front = f

            with players_lock:
                players[player]["front"] = front
                players[player]["section"] = section

            print("Player", player, "moved to front", front, "section", section)

            self.send_response(200)
            self.end_headers()
        else:
            self.send_error(404)
            self.end_headers()

def quorum_http_server():
    httpd = HTTPServer(settings.QUORUM_ADDRPORT, quorum_http_handler)

    try:
        print("Starting HTTP server at", settings.QUORUM_ADDRPORT)
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    
    httpd.server_close()

def get_neighbors(obj):
    neighbors = {}

    for n in ("e-neighbor", "w-neighbor", "n-neighbor", "s-neighbor"):
        if n in obj:
            neighbors[n] = obj[n]
    
    return neighbors

def main():
    for front in settings.INITIAL_SECTIONS_FOR_FRONTS:
        for section in settings.INITIAL_SECTIONS_FOR_FRONTS[front]:
            neighbors = get_neighbors(settings.INITIAL_SECTIONS_FOR_FRONTS[front][section])

            section_neighbors[section] = neighbors

            while not request_front_for_section(front, settings.STORE_ADDRPORT, section, neighbors):
                time.sleep(1)
                continue

    quorum_http_server_thread = threading.Thread(target=quorum_http_server)
    quorum_http_server_thread.start()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(settings.QUORUM_ADDRPORT)
        
        front_pinger_thread = threading.Thread(target=front_pinger, args=(s,))
        front_pinger_thread.start()

        front_pong_listener_thread = threading.Thread(target=front_pong_listener, args=(s,))
        front_pong_listener_thread.start()

        front_pinger_thread.join()
        front_pong_listener_thread.join()

    quorum_http_server_thread.join()

if __name__ == "__main__":
    main()