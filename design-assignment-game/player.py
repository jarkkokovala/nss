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

def login_blackbox():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

# Caller must protect s with lock
def get_front(s, session):
    packet = pickle.dumps({"id" : PLAYER, "session": session})
    s.sendto(b"FRONT?" + packet, settings.LOGIN_ADDRPORT)

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

# Caller must have front_lock
def get_section(front, session):
    front_conn = http.client.HTTPConnection(front[0], front[1])

    try:
        front_conn.request("GET", "/map?player=" + str(PLAYER) + "&session=" + session)

        response = front_conn.getresponse()
        front_conn.close()

        if response.status == 200:
            section = pickle.loads(response.read())
            print("Got new section", section)

            for o in section["objects"]:
                section["objects"][o]["version"] = section["version"]

            return section
        else:
            return None
    except OSError:
        return None

def flush_commands(cmd_queue, outbound_cmds, resend_queue):
    try:
        while True:
            seq, packet, timestamp = cmd_queue.get(False)

            if seq is not None:
                outbound_cmds[seq] = packet
                resend_queue.put((timestamp, seq))
            else:
                break
    except queue.Empty:
        pass

def display_object(objects, o):
    obj = objects[o]

    if o == PLAYER:
        print("Your ship \"", end='')
    else:
        print("You see \"", end='')
    
    print(obj["name"] + "\"", "at", obj["loc"], end='')

    if obj["speed"] == 0:
        print(" (stationary)")
    else:
        print(" moving at direction", obj["direction"], "with speed", obj["speed"])

def display_map(section):
    print("You are in", section["name"])

    for o in section["objects"]:
        display_object(section["objects"], o)

def player_listener(s, s_lock, cmd_queue):
    global front, front_seq
    session = None
    section = None
    last_ack = -1
    last_front_msg = 0
    outbound_cmds = {}
    resend_queue = queue.PriorityQueue()
    recvd_updates = []
    last_acked_version = -1
    current_rtt = settings.PLAYER_INITIAL_RTT
    next_listen_timeout = current_rtt

    while True:
        with front_lock:
            while not front:
                if not session:
                    session = login_blackbox()
                
                with s_lock:
                    front = get_front(s, session)
                    last_front_msg = time.time()
                
                if front:
                    last_ack = -1
                    outbound_cmds = {}
                    resend_queue = queue.PriorityQueue()
                    recv_updates = []
                    section = None

            while not section:
                section = get_section(front, session)
                if section:
                    last_acked_version = section["version"]
                    display_map(section)
        
        try:
            with s_lock:
                s.settimeout(next_listen_timeout)

            data, addr = s.recvfrom(1024)
            print(data, addr)

            if data == b"FRONT!":
                with front_lock:
                    front = None
            else:
                with front_lock:
                    if addr != front:
                        print("Unknown sender", addr)
                        raise Exception

                last_front_msg = time.time()

                if data[:4] == b"PING":
                    current_rtt, timestamp = struct.unpack("!dd", data[4:])

                    with s_lock:
                        if(random.randint(1, 100) > settings.PACKET_LOSS):
                            s.sendto(b"PONG" + struct.pack("!d", timestamp), addr)
                elif data[:3] == b"ACK":
                    seq = struct.unpack_from("!l", data[3:])[0]

                    flush_commands(cmd_queue, outbound_cmds, resend_queue)

                    if seq in outbound_cmds:
                        print("ACK for", seq)
                        del outbound_cmds[seq]
                    else:
                        print("Duplicate ACK", seq)
                    
                    with front_lock:
                        if seq < front_seq:
                            while last_ack < seq and last_ack not in outbound_cmds:
                                last_ack += 1
                elif data[:6] == b"UPDATE":
                    version, obj, data = pickle.loads(data[6:])

                    if version > last_acked_version:
                        if version not in recvd_updates:
                            recvd_updates.append(version)
                        while last_acked_version + 1 in recvd_updates:
                            recvd_updates.remove(version)
                            last_acked_version += 1

                    with s_lock:
                        s.sendto(b"ACK" + struct.pack("!l", last_acked_version), addr)

                    if section["objects"][obj]["version"] < version:
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
        except:
            break

        flush_commands(cmd_queue, outbound_cmds, resend_queue)

        next_listen_timeout = current_rtt

        try:
            timestamp, seq = resend_queue.get(False)

            if seq in outbound_cmds:
                to_next_resend = (timestamp + 2 * current_rtt) - time.time()

                if to_next_resend <= 0:
                    with front_lock, s_lock:
                        if front:
                            print("Resend", seq, "at", time.time())
                            s.sendto(outbound_cmds[seq], front)
                    timestamp = time.time()
                else:
                    next_listen_timeout = min(to_next_resend, next_listen_timeout)

                resend_queue.put((timestamp, seq))
        except queue.Empty:
            pass

class Command_sender:
    def __init__(self, s, s_lock, cmd_queue):
        self.s = s
        self.s_lock = s_lock
        self.cmd_queue = cmd_queue
    
    def send(self, data):
        global front_seq

        with front_lock:
            packet = struct.pack("!l", front_seq) + data

            print("Sending command", front_seq, packet)

            with self.s_lock:
                if(random.randint(1, 100) > settings.PACKET_LOSS):
                    self.s.sendto(packet, front)
            
            print("Putting in command queue")
            self.cmd_queue.put((front_seq, packet, time.time()))
            front_seq += 1

def player_command(s, s_lock, cmd_queue):
    sender = Command_sender(s, s_lock, cmd_queue)

    help = "Commands: n - nop, q - quit, ? - help"
    print(help)

    while True:
        print("> ", end='')
        cmd = input().lower()

        if cmd == "n":
            sender.send(b"NOP")
        elif cmd == "q":
            print("Bye!")
            break
        elif cmd == "?":
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

        with s_lock:
            s.close()

        player_listener_thread.join()

if __name__ == "__main__":
    main()