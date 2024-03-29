# Store saves map sections for fronts to be retrieved if necessary
# Jarkko Kovala <jarkko.kovala@iki.fi>

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
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

sections = {} # The map sections
sections_lock = threading.Lock()

fronts = {} # The fronts
fronts_lock = threading.Lock()

addrport = settings.STORE_ADDRPORT

# Attempt to send, generate packet loss for testing
def try_send(s, packet, addr):
    if(random.randint(1, 100) > settings.PACKET_LOSS):
        s.sendto(packet, addr)

# Update an object
def update_object(section, version, obj_id, obj):
    section["version"] = version

    if obj == None: # Object was removed
        print("Removing object", obj_id, "from section", section["name"], "ver", version)
        del section["objects"][obj_id]
    else:
        print("Updating object", obj_id, "in section", section["name"], "ver", version)
        section["objects"][obj_id] = obj

# Clean internal data from map section for sending
def clean_section(section):
    section = section.copy()

    for x in ("recv_buffer", "last_ack", "front"):
        if x in section:
            del section[x]

    return section

# HTTP request handler for store
class store_http_handler(BaseHTTPRequestHandler):
    def do_GET(self):
        protocol_version = "HTTP/1.1"

        query = urlparse(self.path)
        vars = parse_qs(query.query)

        if query.path == "/map": # Request to retrieve a map section
            section = int(vars["section"][0])

            with sections_lock:
                if section in sections:
                    print("Section", section, "requested, sending")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(pickle.dumps((clean_section(sections[section]), {})))
                else:
                    print("Section", section, "requested but we don't have it")
                    self.send_response(404)
                    self.end_headers()

    def do_POST(self):
        protocol_version = "HTTP/1.1"

        query = urlparse(self.path)
        content_len = int(self.headers.get('Content-Length'))
        if content_len > 0:
            body = self.rfile.read(content_len)

        if query.path == "/map": # Request to store a map section
            section_id, section, front_id, front = pickle.loads(body)

            print("Storing section", section_id, "for front", front_id)

            with sections_lock, fronts_lock:
                sections[section_id] = section
                sections[section_id]["front"] = front_id
                sections[section_id]["recv_buffer"] = {}
                sections[section_id]["last_ack"] = section["version"]
                fronts[front_id] = front
            
            self.send_response(200)
            self.end_headers()

# UDP listener thread for store
def store_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(settings.STORE_ADDRPORT)

        while True:
            data, addr = s.recvfrom(1024)

            if data[:6] == b"UPDATE": # Update for an object
                with sections_lock, fronts_lock:
                    section, version, obj_id, obj = pickle.loads(data[6:])

                    if fronts[sections[section]["front"]] == addr: # Check if it was the correct front
                        # If we haven't received this then store in buffer
                        if version > sections[section]["last_ack"] and version not in sections[section]["recv_buffer"]:
                            sections[section]["recv_buffer"][version] = (obj_id, obj)

                        # Acknowledge the update
                        try_send(s, b"ACK" + struct.pack("!ll", section, version), addr)
                    
                        # Process received updates consecutively
                        while sections[section]["last_ack"] + 1 in sections[section]["recv_buffer"]:
                            seq = sections[section]["last_ack"] + 1
                            obj_id, obj = sections[section]["recv_buffer"].pop(seq)
                            update_object(sections[section], seq, obj_id, obj)
                            sections[section]["last_ack"] += 1

# HTTP server thread for store                    
def store_http_server():
    httpd = HTTPServer(addrport, store_http_handler)

    try:
        print("Starting HTTP server at", addrport)
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

    httpd.server_close()

def main():
    # First store initial section data from settings
    for front in settings.INITIAL_SECTIONS_FOR_FRONTS:
        for section in settings.INITIAL_SECTIONS_FOR_FRONTS[front]:
            print("Adding initial section", section)
            sections[section] = settings.INITIAL_SECTIONS_FOR_FRONTS[front][section]
            print(sections[section])

    store_http_server_thread = threading.Thread(target=store_http_server)
    store_http_server_thread.start()

    store_listener_thread = threading.Thread(target=store_listener)
    store_listener_thread.start()

    store_http_server_thread.join()
    store_listener_thread.join()

if __name__ == "__main__":
    main()
