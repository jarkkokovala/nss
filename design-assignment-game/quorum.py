# Quorum knows which fronts are alive and which map sections and players they have
# Moves map sections in case of front failure
# Jarkko Kovala <jarkko.kovala@iki.fi>

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

fronts = settings.INITIAL_FRONTS # Dict of fronts we have
for id in fronts:
    fronts[id]["pingcount"] = 0
    fronts[id]["failed"] = False
fronts_lock = threading.Lock()

section_neighbors = {} # Neighbors for map sections
section_neighbors_lock = threading.Lock()

players = settings.INITIAL_PLAYERS # List of all players
players_lock = threading.Lock()

# Request a front to accept a player connection
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

# Request front to fetch a section
# Caller must have fronts_lock, players_lock
def request_front_for_section(front, source, section, neighbors):
    if not fronts[front]["failed"]:
        addrport = fronts[front]["address"]

        front_conn = http.client.HTTPConnection(addrport[0], addrport[1])

        try:
            print("Requesting front", addrport, "for section", section, "neighbors", neighbors)

            front_conn.request("POST", "/map", pickle.dumps((source, section, neighbors)))

            response = front_conn.getresponse()
            front_conn.close()
            
            if response.status == 200:
                return True
        except OSError:
            pass
    return False

# Update a front's neighbor information
def update_front_with_neighbors(front, section, neighbors):
    front_conn = http.client.HTTPConnection(fronts[front]["address"][0], fronts[front]["address"][1])

    try:
        print("Updating neighbors for section", section, "in front", front, neighbors)

        front_conn.request("POST", "/neighbors", pickle.dumps((section, neighbors)))

        response = front_conn.getresponse()
        front_conn.close()

        if response.status == 200:
            return True
    except OSError:
        pass
    
    return False

# Get list of neighbors from an object
def get_neighbors(obj):
    neighbors = {}

    for n in ("e-neighbor", "w-neighbor", "n-neighbor", "s-neighbor"):
        if n in obj:
            neighbors[n] = obj[n]
    
    return neighbors

# Find the front of a section
# Caller must have fronts_lock
def find_front_for_section(section):
    for front in fronts:
        if section in fronts[front]["sections"]:
            return front
    return None

# Find a front id by address and port
# Caller must have fronts_lock
def find_front_by_addrport(addrport):
    for front in fronts:
        if fronts[front]["address"] == addrport:
            return front
    return None

# Fail a front, move sections elsewhere and update neighbors
# Caller must have fronts_lock, players_lock
def fail_front(id):
    print("Front", id, "failed")

    new_front = None

    print("Failing front", id, "with sections", fronts[id]["sections"])

    # Try to find an available front
    for front in fronts:
        if front is not id and not fronts[front]["failed"]:
            new_front = front

    if new_front:
        print("New front:", new_front, "for sections", fronts[id]["sections"])

        with section_neighbors_lock:
            touched_sections = set()

            # Find sections that are neighbors to any sections in failed front
            for section in fronts[id]["sections"]:
                if "w-neighbor" in section_neighbors[section]:
                    section_neighbors[section_neighbors[section]["w-neighbor"][1]]["e-neighbor"] = (fronts[new_front]["address"], section)
                    touched_sections.add(section_neighbors[section]["w-neighbor"][1])
                if "e-neighbor" in section_neighbors[section]:
                    section_neighbors[section_neighbors[section]["e-neighbor"][1]]["w-neighbor"] = (fronts[new_front]["address"], section)
                    touched_sections.add(section_neighbors[section]["e-neighbor"][1])
                if "n-neighbor" in section_neighbors[section]:
                    section_neighbors[section_neighbors[section]["n-neighbor"][1]]["s-neighbor"] = (fronts[new_front]["address"], section)
                    touched_sections.add(section_neighbors[section]["n-neighbor"][1])
                if "s-neighbor" in section_neighbors[section]:
                    section_neighbors[section_neighbors[section]["s-neighbor"][1]]["n-neighbor"] = (fronts[new_front]["address"], section)
                    touched_sections.add(section_neighbors[section]["s-neighbor"][1])
            
            # Move all sections in failed front to new
            for section in fronts[id]["sections"]:
                if not request_front_for_section(new_front, settings.STORE_ADDRPORT, section, section_neighbors[section]):
                    print("Failed moving section")
                    return

                fronts[new_front]["sections"].add(section)

                if section in touched_sections:
                    touched_sections.remove(section)

            # Update neighbors for sections we haven't updated yet
            for section in touched_sections:
                front = find_front_for_section(section)

                if not fronts[front]["pingcount"] > 4: # Don't try to update a failing front
                    if not update_front_with_neighbors(find_front_for_section(section), section, section_neighbors[section]):
                        print("Updating neighbors failed.")
                        return
                else:
                    print("Not updating neighbors for section", section, "in failed front", front, "update was:", section_neighbors[section])

        # Move players to a new front
        for player in players:
            if players[player]["front"] == id:
                print("Player", player, "to new front")
                players[player]["front"] = new_front

        # Mark a front failed.
        # Only do this if failing process finished so we will retry in next iteration
        fronts[id]["sections"] = set()
        fronts[id]["failed"] = True
        print("Front", id, "failed.")
    else:
        print("Could not find an available front")

# HTTP request handler for quorum
class quorum_http_handler(BaseHTTPRequestHandler):
    def do_POST(self):
        protocol_version = "HTTP/1.1"

        query = urlparse(self.path)
        content_len = int(self.headers.get('Content-Length'))
        if content_len > 0:
            body = self.rfile.read(content_len)

        if query.path == "/front": # Request for a front for a player
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
        elif query.path == "/move": # Request to move player to another front or section
            player, (front, section) = pickle.loads(body)

            new_front = find_front_by_addrport(front)

            with players_lock:
                players[player]["front"] = new_front
                players[player]["section"] = section

            print("Player", player, "moved to front", new_front, "section", section)

            self.send_response(200)
            self.end_headers()
        else:
            self.send_error(404)
            self.end_headers()

# Quorum HTTP server thread
def quorum_http_server():
    httpd = HTTPServer(settings.QUORUM_ADDRPORT, quorum_http_handler)

    try:
        print("Starting HTTP server at", settings.QUORUM_ADDRPORT)
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    
    httpd.server_close()

# Thread to send keepalives to fronts
def front_pinger(s):
    while True:
        with fronts_lock:
            for id in fronts:
                front = fronts[id]

                # Check for any timeouts
                if not front["failed"] and front["pingcount"] > 4:
                    with players_lock:
                        fail_front(id)

                s.sendto(b"PING", front["address"])

                front["pingcount"] += 1
        time.sleep(1)

# Thread to listen for keepalives from fronts
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

def main():
    # Get initial front/section info from settings and tell fronts to fetch the data
    for front in settings.INITIAL_SECTIONS_FOR_FRONTS:
        fronts[front]["sections"] = set()

        for section in settings.INITIAL_SECTIONS_FOR_FRONTS[front]:
            neighbors = get_neighbors(settings.INITIAL_SECTIONS_FOR_FRONTS[front][section])

            section_neighbors[section] = neighbors
            fronts[front]["sections"].add(section)

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
