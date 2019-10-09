import settings

import sys
import socket
import pickle
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

fronts = [ ]
for front in settings.FRONTS:
    fronts.append({ "address" : front, "pingcount" : 0})
fronts_lock = threading.Lock()

def fail_front(front):
    print("Front", front["address"], "failed")
    with fronts_lock:
        fronts.remove(front)

def front_pinger(s):
    while True:
        for front in fronts:
            if front["pingcount"] > 4:
                    fail_front(front)
            s.sendto(b"PING", front["address"])

            with fronts_lock:
                front["pingcount"] += 1
        time.sleep(1)

def front_pong_listener(s):
    while True:
        data, addr = s.recvfrom(1024)
        if data == b"PONG":
            for front in fronts:
                if front["address"] == addr:
                    with fronts_lock:
                        front["pingcount"] = 0

class quorum_http_handler(BaseHTTPRequestHandler):
    def do_GET(self):

        print("HTTP GET", self.path)
        query = urlparse(self.path)
        vars = urllib.parse.parse_qs(query)

        if query.path == "/front":
            self.send_response(200)
            self.send_header("Content-type: application/octet-stream")
            self.end_headers
            self.wfile.write(pickle.dumps(fronts[0]["address"]))
            return
        else:
            self.send_response(404)
            self.send_header("Content-type", "text/plain")
            self.end_headers
            self.wfile.write(b"404 not found\n")
            return

def front_http_server():
    httpd = HTTPServer(settings.QUORUM_ADDRPORT, quorum_http_handler)
    try:
        print("Starting HTTP server at", settings.QUORUM_ADDRPORT)
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    
    httpd.server_close()

def main():
    front_http_server_thread = threading.Thread(target=front_http_server)
    front_http_server_thread.start()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(settings.QUORUM_ADDRPORT)
        
        front_pinger_thread = threading.Thread(target=front_pinger, args=(s,))
        front_pinger_thread.start()

        front_pong_listener_thread = threading.Thread(target=front_pong_listener, args=(s,))
        front_pong_listener_thread.start()

        front_pinger_thread.join()
        front_pong_listener_thread.join()

    front_http_server_thread.join()

if __name__ == "__main__":
    main()