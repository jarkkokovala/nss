import settings

import sys
import socket
import struct
import time
import threading
import pickle
import urllib
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer

if len(sys.argv) < 2:
    print("Usage:", sys.argv[0], "<front #>")
    exit()

FRONT = int(sys.argv[1])
addrport = settings.INITIAL_FRONTS[FRONT]["address"]

players = {}
players_lock = threading.Lock()

print("Starting front #", FRONT, addrport)

def ping_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(addrport)
        s.settimeout(settings.FRONT_TIMEOUT)

        last_quorum_ping = time.time()

        while True:
            try:
                data, addr = s.recvfrom(1024)

                print(str(data), addr)
                if addr == settings.QUORUM_ADDRPORT:
                    if data == b"PING":
                        last_quorum_ping = time.time()
                        s.sendto(b"PONG", addr)
            except socket.timeout:
                print("Timed out listening")
            
            if time.time() - last_quorum_ping > settings.FRONT_TIMEOUT:
                print("Quorum silent, dying")
                break

class front_http_handler(BaseHTTPRequestHandler):
    def do_POST(self):
        protocol_version = "HTTP/1.1"

        query = urlparse(self.path)
        content_len = int(self.headers.get('Content-Length'))
        if content_len > 0:
            body = self.rfile.read(content_len)

        if query.path == "/player":
            player = pickle.loads(body)

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

    ping_listener_thread = threading.Thread(target=ping_listener)
    ping_listener_thread.start()

    front_http_server_thread.join()
    ping_listener_thread.join()

if __name__ == "__main__":
    main()