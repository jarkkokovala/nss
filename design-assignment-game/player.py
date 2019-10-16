# Player module is the user interface for the player
# Jarkko Kovala <jarkko.kovala@iki.fi>

import settings

import sys
import time
import random
import string
import socket
import pickle
import struct
import threading
import queue
import http.client

if len(sys.argv) < 2:
    print("Usage:", sys.argv[0], "<player #>")
    exit()

PLAYER = int(sys.argv[1])
front = None
front_seq = 0
front_lock = threading.Lock() # Protects front and front_seq

# Log in and return session key
def login_blackbox():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

# Attempt to send, generate packet loss for testing
def try_send(s, packet, addr):
    if(random.randint(1, 100) > settings.PACKET_LOSS):
        s.sendto(packet, addr)

# Fetch a front for us
def get_front(s, session):
    global front_seq

    packet = pickle.dumps({"id" : PLAYER, "session": session})
    try_send(s, b"FRONT?" + packet, settings.LOGIN_ADDRPORT)

    try:
        s.settimeout(settings.PLAYER_TIMEOUT)
        data, addr = s.recvfrom(1024)
    except socket.timeout:
        print("Timed out waiting for a front")
        return None

    if data[:6] == b"FRONT:":
        front = pickle.loads(data[6:])

        print("Got new front", front)

        return front
    else:
        return None

# Fetch a section for us
# Caller must have front_lock
def get_section(front, session):
    front_conn = http.client.HTTPConnection(front[0], front[1])

    try:
        front_conn.request("GET", "/map?player=" + str(PLAYER) + "&session=" + session)

        response = front_conn.getresponse()
        front_conn.close()

        if response.status == 200:
            section = pickle.loads(response.read())
            print("Got new section.")

            for o in section["objects"]:
                section["objects"][o]["version"] = section["version"]

            return section
        else:
            return None
    except OSError:
        return None

# Retrieve all commands from queue and put in outbound and resend
def flush_commands(cmd_queue, outbound_cmds, resend_queue):
    try:
        while True:
            seq, packet, timestamp = cmd_queue.get(False)

            if seq is not None:
                if packet == b"QUIT":
                    return False

                outbound_cmds[seq] = packet
                resend_queue.put((timestamp, seq))
            else:
                break
    except queue.Empty:
        pass

    return True

# UI for displaying an object
def display_object(objects, o):
    obj = objects[o]

    if o == PLAYER:
        print("Your ship \"", end='')
    else:
        print("You see \"", end='')
    
    print(obj["name"] + "\" [#" + str(o) + "]", "at", obj["loc"], end='')

    if "direction" in obj:
        print(", heading", obj["direction"], "deg", end='')

    if obj["speed"] == 0:
        print(" (stationary)")
    else:
        print(", moving at speed", obj["speed"])

# UI for displaying map section
def display_map(section):
    print("You are in", section["name"])

    for o in section["objects"]:
        display_object(section["objects"], o)

# Player UDP listener thread
def player_listener(s, s_lock, cmd_queue):
    global front, front_seq
    session = None
    section = None
    last_ack = -1 # Last ACK consecutively received
    last_front_msg = 0 # Last time front spoke to us
    outbound_cmds = {} # Commands still to be acked by front
    resend_queue = queue.PriorityQueue() # Resend queue to front
    recvd_updates = [] # Receive buffer from front
    last_acked_version = -1 # Last ACK consecutively sent
    current_rtt = settings.PLAYER_INITIAL_RTT
    next_listen_timeout = current_rtt

    while True:
        with front_lock:
            # First get a front if we don't have it
            while not front:
                if not session:
                    session = login_blackbox()
                
                with s_lock:
                    front = get_front(s, session)
                    last_front_msg = time.time()
                
                if front:
                    front_seq = 0
                    last_ack = -1
                    outbound_cmds = {}
                    resend_queue = queue.PriorityQueue()
                    recv_updates = []
                    section = None

            # Get section if we don't have it
            while not section:
                section = get_section(front, session)
                if section:
                    last_acked_version = section["version"]
                    display_map(section)
        
        try:
            # Listen for packets
            with s_lock:
                s.settimeout(next_listen_timeout)

            data, addr = s.recvfrom(1024)

            if data == b"FRONT!": # We're talking to the wrong front
                with front_lock:
                    front = None
            else:
                with front_lock:
                    if addr != front: # We received packet from someone we don't know
                        print("Unknown sender", addr)
                        raise Exception

                last_front_msg = time.time()

                if data[:4] == b"PING": # Front keepalive
                    current_rtt, timestamp = struct.unpack("!dd", data[4:])

                    with s_lock:
                        try_send(s, b"PONG" + struct.pack("!d", timestamp), addr)
                elif data[:3] == b"ACK": # Front ack
                    seq = struct.unpack_from("!l", data[3:])[0]

                    # Flush commands from queue
                    if not flush_commands(cmd_queue, outbound_cmds, resend_queue):
                        break # Command is to quit

                    # Remove acked command from outbound buffer
                    if seq in outbound_cmds:
                        del outbound_cmds[seq]
                    else:
                        print("Duplicate ACK", seq)
                    
                    # Calculate last consecutively received ack
                    with front_lock:
                        if seq < front_seq:
                            while last_ack < seq and last_ack not in outbound_cmds:
                                last_ack += 1
                elif data[:6] == b"FRONT:": # Command to change fronts
                    front = pickle.loads(data[6:])

                    last_front_msg = time.time()
                    front_seq = 0
                    last_ack = -1
                    outbound_cmds = {}
                    resend_queue = queue.PriorityQueue()
                    recv_updates = []
                    section = None
                elif data[:6] == b"UPDATE": # Update from front
                    version, obj, data = pickle.loads(data[6:])

                    # Add to receive buffer if a new update
                    if version > last_acked_version:
                        if version not in recvd_updates:
                            recvd_updates.append(version)
                        # Update last consecutive ack counter and clean buffer
                        while last_acked_version + 1 in recvd_updates:
                            recvd_updates.remove(version)
                            last_acked_version += 1

                    with s_lock: # Acknowledge the update
                        try_send(s, b"ACK" + struct.pack("!l", last_acked_version), addr)

                    # Process the update
                    if obj not in section["objects"] or section["objects"][obj]["version"] < version:
                        if data == None:
                            # Object is gone
                            print(section["objects"][obj]["name"], "[#" + str(obj) + "] left the section")
                            del section["objects"][obj]
                        else:
                            section["objects"][obj] = data
                            section["objects"][obj]["version"] = version

                            display_object(section["objects"], obj)

        except socket.timeout:
            if time.time() - last_front_msg > settings.FRONT_TIMEOUT:
                with front_lock:
                    print("Lost front to timeout")
                    front = None
            pass
        except Exception:
            pass

        if not flush_commands(cmd_queue, outbound_cmds, resend_queue):
            break # Command was to quit

        next_listen_timeout = current_rtt

        # Process resend queue
        try:
            timestamp, seq = resend_queue.get(False)

            if seq in outbound_cmds:
                to_next_resend = timestamp + 2 * current_rtt - time.time()

                if to_next_resend <= 0:
                    with front_lock, s_lock:
                        if front:
                            print("Resend", seq, "at", time.time())
                            try_send(s, outbound_cmds[seq], front)
                    timestamp = time.time()
                    next_listen_timeout = min(2 * current_rtt, next_listen_timeout)
                else:
                    next_listen_timeout = min(to_next_resend, next_listen_timeout)

                resend_queue.put((timestamp, seq))
        except queue.Empty:
            pass

# Class for sending player commands
class Command_sender:
    def __init__(self, s, s_lock, cmd_queue):
        self.s = s
        self.s_lock = s_lock
        self.cmd_queue = cmd_queue
    
    def send(self, data):
        global front_seq

        if data == b"QUIT":
            with front_lock, self.s_lock:
                try_send(self.s, b"QUIT", front)
            self.cmd_queue.put((front_seq, b"QUIT", time.time()))
        else:
            with front_lock:
                packet = struct.pack("!l", front_seq) + data

                with self.s_lock:
                    try_send(self.s, packet, front)
                
                self.cmd_queue.put((front_seq, packet, time.time()))
                front_seq += 1

# Thread for reading commands from user
def player_command(s, s_lock, cmd_queue):
    sender = Command_sender(s, s_lock, cmd_queue)

    help = "Commands: s <0-10> - change speed, d <0-360> - change direction, n - nop, q - quit, ? - help"
    print(help)

    while True:
        print("> ", end='')
        cmd = input().lower()

        if len(cmd) > 2:
            param = cmd[2:]
        else:
            param = "0"

        if cmd[:1] == "n": # Do nothing
            sender.send(b"NOP")
        elif cmd[:1] == "s" and int(param) >= 0 and int(param) <= 10: # Change speed
            sender.send(b"SPEED" + struct.pack("!h", int(param)))
        elif cmd[:1] == "d" and int(param) >= 0 and int(param) <= 360: # Change direction
            sender.send(b"DIR" + struct.pack("!h", int(param)))
        elif cmd[:1] == "q": # Quit
            sender.send(b"QUIT")
            print("Bye!")
            break
        elif cmd[:1] == "?": # Help
            print(help)
        elif cmd == "":
            continue
        else:
            print("Unknown command. ? for help")

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s_lock = threading.Lock()
        
        session = None
        section = None
        front = None
        cmd_queue = queue.Queue()

        player_command_thread = threading.Thread(target=player_command, args=(s, s_lock, cmd_queue))
        player_command_thread.start()

        player_listener_thread = threading.Thread(target=player_listener, args=(s, s_lock, cmd_queue))
        player_listener_thread.start()

        player_command_thread.join()
        player_listener_thread.join()

        with s_lock:
            s.close()

if __name__ == "__main__":
    main()
