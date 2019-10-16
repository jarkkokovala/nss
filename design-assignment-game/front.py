# Front module: handles game mechanics and communication to the player
# Jarkko Kovala <jarkko.kovala@iki.fi>

import settings

import sys
import socket
import struct
import time
import threading
import random
import queue
import math
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

sections = {} # Map sections we handle
sections_lock = threading.Lock()

players = {} # Players currently connected
players_lock = threading.Lock()

print("Starting front #", FRONT, addrport)

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s_lock = threading.Lock()

resend_queue = queue.PriorityQueue() # Queue for resends to players
store_resend_queue = queue.PriorityQueue() # Queue for resends to store

# Attempt to send, generate packet loss for testing
# Caller must have s_lock
def try_send(s, packet, addr):
    if(random.randint(1, 100) > settings.PACKET_LOSS):
        s.sendto(packet, addr)

# Clean internal data from object for transfer
# Caller must have sections_lock
def clean_object(obj):
    if obj is None:
        return None
        
    obj = obj.copy()

    if "last_move" in obj:
        del obj["last_move"]
    
    return obj

# Clean internal data rom section for transfer
# Caller must have sections_lock
def clean_section(section):
    section = section.copy()

    if "store_buffer" in section:
        del section["store_buffer"]

    section["objects"] = section["objects"].copy()

    for obj in list(section["objects"]):
        if section["objects"][obj] is None:
            del section["objects"][obj]
        else:
            section["objects"][obj] = clean_object(section["objects"][obj])

    return section

# Clean internal data from player for sending
# Caller must have players_lock
def clean_player(player):
    player = player.copy()

    for x in ("pingcount", "rtt", "last_sent_ack", "recv_buffer", "send_buffer", "last_recvd_ack"):
        if x in player:
            del player[x]

    return player

# Up version number for object and send updates to everyone
# Caller must have sections_lock, players_lock
def update_object(section_id, id):
    global s, s_lock, resend_queue, store_resend_queue

    section = sections[section_id]
    obj = clean_object(section["objects"][id])

    section["version"] += 1
    version = section["version"]

    # First update store
    store_packet = b"UPDATE" + pickle.dumps((section_id, version, id, obj))
    with s_lock:
        try_send(s, store_packet, settings.STORE_ADDRPORT)
    sections[section_id]["store_buffer"][version] = store_packet
    store_resend_queue.put((time.time(), (section_id, version)))

    # Update all players
    for p in players:
        if players[p]["section"] == section_id and "send_buffer" in players[p]:
            packet = b"UPDATE" + pickle.dumps((version, id, obj))
            players[p]["send_buffer"][version] = packet

            with s_lock:
                try_send(s, packet, players[p]["addr"])
                resend_queue.put((time.time(), (p, version)))

# Update object location based, direction, speed, and time since last update
# Caller must have sections_lock
def move_object(obj):
    dir = math.radians(obj["direction"])
    cur_loc = obj["loc"]

    interval = time.time() - obj["last_move"]

    xloc = round(cur_loc[0] + interval * obj["speed"] * math.cos(dir), 3)
    yloc = round(cur_loc[1] + interval * obj["speed"] * math.sin(dir), 3)

    obj["loc"] = (xloc, yloc)
    obj["last_move"] = time.time()

# Notify quorum that player has moved sections/neighbors
# Caller must have sections_lock
def notify_quorum_of_move(obj, next_neighbor):
    quorum_conn = http.client.HTTPConnection(settings.QUORUM_ADDRPORT[0], settings.QUORUM_ADDRPORT[1])

    try:
        quorum_conn.request("POST", "/move", pickle.dumps((obj, next_neighbor)))

        response = quorum_conn.getresponse()
        quorum_conn.close()

        if response.status == 200:
            return True
    except OSError:
        pass

    return False

# Transfer player to another front
# Caller must have sections_lock, players_lock
def send_player_to_front(neighbor, section, id, ship):
    front_conn = http.client.HTTPConnection(neighbor[0], neighbor[1])

    player = clean_player(players[id])
    player["section"] = section

    try:
        front_conn.request("POST", "/move", pickle.dumps((player, ship)))

        response = front_conn.getresponse()
        front_conn.close()

        if response.status == 200:
            return True
    except OSError:
        pass

    return False

# Update movement for all objects in section
# Caller must have sections_lock, players_lock
def move_all_in_section(section):
    for obj in sections[section]["objects"]:
        if sections[section]["objects"][obj] is not None and sections[section]["objects"][obj]["speed"] > 0:
            move_object(sections[section]["objects"][obj])

            xloc, yloc = sections[section]["objects"][obj]["loc"]
            next_neighbor = None

            # Check if player is outside section boundary and find possible neighbor
            if xloc > settings.SECTION_XSIZE/2:
                if "e-neighbor" in sections[section]:
                    next_neighbor = sections[section]["e-neighbor"]
                    xloc -= settings.SECTION_XSIZE
                else:
                    sections[section]["objects"][obj]["loc"] = (settings.SECTION_XSIZE/2, yloc)
            elif xloc < -settings.SECTION_XSIZE/2:
                if "w-neighbor" in sections[section]:
                    next_neighbor = sections[section]["w-neighbor"]
                    xloc += settings.SECTION_XSIZE
                else:
                    sections[section]["objects"][obj]["loc"] = (-settings.SECTION_XSIZE/2, yloc)
            elif yloc > settings.SECTION_YSIZE/2:
                if "n-neighbor" in sections[section]:
                    next_neighbor = sections[section]["n-neighbor"]
                    yloc -= settings.SECTION_YSIZE
                else:
                    sections[section]["objects"][obj]["loc"] = (xloc, settings.SECTION_YSIZE/2)
            elif yloc < -settings.SECTION_YSIZE/2:
                if "s-neighbor" in sections[section]:
                    next_neighbor = sections[section]["s-neighbor"]
                    yloc += settings.SECTION_YSIZE
                else:
                    sections[section]["objects"][obj]["loc"] = (xloc, -settings.SECTION_YSIZE/2)
            
            # If there is a neighbor, send player there
            if next_neighbor is not None:
                print("Next neighbor", next_neighbor, addrport)
                new_obj = clean_object(sections[section]["objects"][obj])
                new_obj["loc"] = (xloc, yloc)
                new_obj["last_move"] = time.time()

                if next_neighbor[0] == addrport: # Neighbor is us, just move sections
                        print("Moving player to another section")
                        if notify_quorum_of_move(obj, next_neighbor):
                            sections[section]["objects"][obj] = None
                            sections[next_neighbor[1]]["objects"][obj] = new_obj
                            update_object(next_neighbor[1], obj)

                            # If player is logged in, clean connection
                            if obj in players:
                                players[obj]["section"] = next_neighbor[1]

                                with s_lock:
                                    s.sendto(b"FRONT:" + pickle.dumps(addrport), players[obj]["addr"])
                                players[obj]["pingcount"] = 0
                                players[obj]["rtt"] = settings.PLAYER_INITIAL_RTT
                                players[obj]["last_sent_ack"] = -1 # last consecutively acked packet
                                players[obj]["recv_buffer"] = {}
                                if "send_buffer" in players[obj]:
                                    del players[obj]["send_buffer"]
                        else:
                            print("Quorum failed")
                else: # Send player to another front
                    print("Transferring player to front", next_neighbor[0], "section", next_neighbor[1])
                    
                    if send_player_to_front(next_neighbor[0], next_neighbor[1], obj, new_obj):
                        sections[section]["objects"][obj] = None
                        if obj in players:
                            with s_lock:
                                s.sendto(b"FRONT:" + pickle.dumps(next_neighbor[0]), players[obj]["addr"])
                            del players[obj]
                    else:
                        print("Transfer failed")

            update_object(section, obj)

# Transfer section data to store
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

# Process a command from a player
# Caller must have sections_lock, players_lock
def player_command(player, cmd):
    id = player["id"]
    ship = sections[player["section"]]["objects"][id]

    # Update player's movement first if their ship is moving
    if ship["speed"] > 0:
        move_object(ship)

    if cmd == b"NOP": # Do nothing
        print("NOP from", player["name"])
    if cmd[:5] == b"SPEED": # Change speed
        speed = struct.unpack_from("!h", cmd[5:])[0]

        if ship["speed"] == 0 and speed > 0:
            ship["last_move"] = time.time()

        ship["speed"] = speed

        if speed == 0:
            print(player["name"], "stopped")
            if "last_move" in ship:
                del ship["last_move"]
        else:
            print(player["name"], "changed speed to", speed)
    if cmd[:3] == b"DIR": # Change direction
        dir = struct.unpack_from("!h", cmd[3:])[0]

        ship["direction"] = dir
        print(player["name"], "changed direction to", dir)

    # Update map version and send updates
    update_object(player["section"], id)

# UDP listener thread for front
def front_listener():
    global s, s_lock, resend_queue, store_resend_queue

    last_quorum_ping = time.time()
    last_move = time.time()
    next_timeout = 1

    while True:
        try:
            data, addr = s.recvfrom(1024)

            if addr == settings.QUORUM_ADDRPORT:
                if data == b"PING": # Keepalive from quorum
                    last_quorum_ping = time.time()
                    with s_lock:
                        try_send(s, b"PONG", addr)
            elif addr == settings.STORE_ADDRPORT:
                if data[:3] == b"ACK": # ACK from store
                    section, version = struct.unpack_from("!ll", data[3:])

                    with sections_lock:
                        if section in sections and version in sections[section]["store_buffer"]:
                            del sections[section]["store_buffer"][version]
            else: # Other packets will be player messages
                with sections_lock, players_lock:
                    player = None

                    for p in players:
                        if players[p]["addr"] == addr and "send_buffer" in players[p]:
                            player = players[p]
                            break
         
                    if player:
                        if data[:4] == b"PONG": # Player keepalive reply
                            player["pingcount"] = 0
                            rtt = time.time() - struct.unpack("!d", data[4:])[0]
                            player["rtt"] = rtt
                        elif data[:3] == b"ACK": # Player packet acknowledgement
                            version = struct.unpack_from("!l", data[3:])[0]
                            cur_version = sections[player["section"]]["version"]

                            # Fast resend if received ack older than version
                            if version < sections[player["section"]]["version"] and version + 1 in player["send_buffer"]:
                                with s_lock:
                                    try_send(s, player["send_buffer"][version + 1], addr)
                            
                            # Clean send_buffer based on consecutive acks received
                            for seq in list(player["send_buffer"]):
                                if seq <= version:
                                    del player["send_buffer"][seq]
                            
                            # Update ack counter
                            while player["last_recvd_ack"] < cur_version and player["last_recvd_ack"] not in player["send_buffer"]:
                                player["last_recvd_ack"] += 1

                        elif data[:4] == b"QUIT": # Player quit
                            print("Player", player["id"], "quit")
                            del players[player["id"]]
                        else: # All else is player commands
                            seq = struct.unpack_from("!l", data)[0]
                            payload = data[4:]

                            with s_lock: # ACK the command
                                try_send(s, b"ACK" + struct.pack("!l", seq), addr)

                            # Insert command to buffer
                            if seq > player["last_sent_ack"] and seq not in player["recv_buffer"]:
                                player["recv_buffer"][seq] = payload
                            
                            # Executive consecutive commands from buffer
                            while player["last_sent_ack"]+1 in player["recv_buffer"]:
                                player_command(player, payload)
                                del player["recv_buffer"][player["last_sent_ack"]+1]
                                player["last_sent_ack"] += 1
                    else: # Unknown player, tell them to find another front
                        with s_lock:
                            try_send(s, b"FRONT!", addr)
        except socket.timeout:
            pass
            
        # Quorum timeout
        if time.time() - last_quorum_ping > settings.FRONT_TIMEOUT:
            print("Quorum silent, dying")
            sys.exit(0)

        next_timeout = 1

        # Process resends from queue
        try:
            while True:
                timestamp, (player, version) = resend_queue.get(False)

                with players_lock:
                    if player in players and "send_buffer" in players[player] and version > players[player]["last_recvd_ack"]:
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

        # Process store resends from queue
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

        # Try to move everything at least once a second
        if time.time() - last_move > 1:
            with sections_lock, players_lock:
                for section in sections:
                    move_all_in_section(section)
            last_move = time.time()
    
# Front UDP sender thread (pinger)
def front_sender():
    global s, s_lock

    print("Starting front sender")
    while True:
        # Ping all players
        with players_lock:
            for player in players:
                players[player]["pingcount"] += 1

                with s_lock:
                    try_send(s, b"PING" + struct.pack("!dd", players[player]["rtt"], time.time()), players[player]["addr"])

        time.sleep(1)

        # Check for timeouts
        with players_lock:
            for player in list(players):
                if players[player]["pingcount"] >= 5:
                    del players[player]
                    print("Player", player, "timed out")

# HTTP request handler
class front_http_handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global s, s_lock
        protocol_version = "HTTP/1.1"

        query = urlparse(self.path)
        vars = parse_qs(query.query)

        if query.path == "/map": # Request for map data
            if "player" in vars and "session" in vars:
                player = int(vars["player"][0])
                session = vars["session"][0]

                with sections_lock, players_lock:
                    if player in players and players[player]["session"] == session:
                        section = players[player]["section"]

                        move_all_in_section(section)

                        print("Giving section", section, "to player", player)

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

        if query.path == "/player": # Request to initialize a player connection
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
        elif query.path == "/map": # Request to fetch a map section
            source, section, neighbors = pickle.loads(body)

            print("Told to fetch section", section, "from", source)

            with sections_lock, players_lock:
                conn = http.client.HTTPConnection(source[0], source[1])

                try:
                    conn.request("GET", "/map?section=" + str(section))

                    response = conn.getresponse()
                   
                    conn.close()

                    if response.status == 200:
                        new_section, new_players = pickle.loads(response.read())
                        for x in ("e-neighbor", "w-neighbor", "n-neighbor", "s-neighbor"):
                            if x in neighbors:
                                new_section[x] = neighbors[x]
                        for player in new_players:
                            players[player] = new_players[player]
                            players[player]["pingcount"] = 0
                            players[player]["rtt"] = settings.PLAYER_INITIAL_RTT
                            players[player]["last_sent_ack"] = -1
                            players[player]["recv_buffer"] = {}
                        sections[section] = new_section
                        store_section(section)

                        self.send_response(200)
                    else:
                        self.send_response(503)
                except OSError:
                    self.send_response(503)
            self.end_headers()
        elif query.path == "/neighbors": # Request to update neighbors for section
            section, neighbors = pickle.loads(body)

            print("Updating neighbors for section", section, neighbors)
            with sections_lock:
                for n in neighbors:
                    sections[section][n] = neighbors[n]
            
            self.send_response(200)
            self.end_headers()
        elif query.path == "/move": # Request to receive a player from another front
            player, ship = pickle.loads(body)
            id = player["id"]
            section = player["section"]

            print("Receiving player", id)

            player["pingcount"] = 0
            player["rtt"] = settings.PLAYER_INITIAL_RTT
            player["last_sent_ack"] = -1
            player["recv_buffer"] = {}
            ship["last_move"] = time.time()

            with sections_lock, players_lock:
                if notify_quorum_of_move(id, (addrport, section)):
                    sections[section]["objects"][id] = ship
                    players[id] = player

                    update_object(section, id)
                    self.send_response(200)
                    print("Received player", id)
                else:
                    self.send_response(503)
            
            self.end_headers()
        else:
            self.send_error(404)
            self.end_headers()

# Front HTTP server thread
def front_http_server():
    httpd = HTTPServer(addrport, front_http_handler)

    try:
        print("Starting HTTP server at", addrport)
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

    httpd.server_close()

def main():
    global s, s_lock

    with s_lock:
        s.bind(addrport)
        s.settimeout(settings.FRONT_TIMEOUT)

    front_http_server_thread = threading.Thread(target=front_http_server)
    front_http_server_thread.start()

    front_listener_thread = threading.Thread(target=front_listener)
    front_listener_thread.start()

    front_sender_thread = threading.Thread(target=front_sender)
    front_sender_thread.start()

    front_listener_thread.join()
    front_sender_thread.join()

    front_http_server_thread.join()

if __name__ == "__main__":
    main()
