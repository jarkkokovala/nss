import settings

import sys
import socket
import struct
import time
import threading
import pickle
import urllib
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

if len(sys.argv) < 2:
    print("Usage:", sys.argv[0], "<front #>")
    exit()

FRONT = int(sys.argv[1])
addrport = settings.INITIAL_FRONTS[FRONT]["address"]

sections = settings.INITIAL_SECTIONS_FOR_FRONTS[FRONT]
sections_lock = threading.Lock()

players = {}
players_lock = threading.Lock()


print("Starting front #", FRONT, addrport)

def front_listener(s, s_lock):
    last_quorum_ping = time.time()

    while True:
        try:
            data, addr = s.recvfrom(1024)

            if addr == settings.QUORUM_ADDRPORT:
                if data == b"PING":
                    last_quorum_ping = time.time()
                    with s_lock:
                        s.sendto(b"PONG", addr)
            else:
                with players_lock:
                    player = None

                    for p in players:
                        if players[p]["addr"] == addr:
                            player = players[p]
                    
                    if player:
                        if data[:4] == b"PONG":
                            player["pingcount"] = 0
                            rtt = time.time() - struct.unpack("!d", data[5:])[0]
                            player["RTT"] = rtt
                    else:
                        with s_lock:
                            s.sendto(b"FRONT!", addr)
        except socket.timeout:
            print("Timed out listening")
            
        if time.time() - last_quorum_ping > settings.FRONT_TIMEOUT:
            print("Quorum silent, dying")
            sys.exit(0)

def front_sender(s, s_lock):
    print("Starting front sender")
    while True:
        with players_lock:
            for player in players:
                players[player]["pingcount"] += 1

                with s_lock:
                    s.sendto(b"PING " + struct.pack("!d", time.time()), players[player]["addr"])

        time.sleep(1)

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
                        self.wfile.write(pickle.dumps(sections[section]))
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
            player[id]["RTT"] = settings.PLAYER_INITIAL_RTT

            print("Adding player", player)
            with players_lock:
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