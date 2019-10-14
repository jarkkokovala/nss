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

            return section
        else:
            return None
    except OSError:
        return None

def player_listener(s, s_lock, cmd_queue):
    global front, front_seq
    session = None
    section = None
    last_ack = -1
    last_front_msg = 0
    outbound_cmds = {}
    resend_queue = queue.PriorityQueue()
    current_rtt = settings.PLAYER_INITIAL_RTT

    while True:
        with front_lock:
            while not front:
                if not session:
                    session = login_blackbox()
                
                with s_lock:
                    front = get_front(s, session)
                    last_front_msg = time.time()
                
                last_ack = -1
                outbound_cmds = {}
                resend_queue = queue.PriorityQueue()

            while not section:
                section = get_section(front, session)
        
        try:
            with s_lock:
                s.settimeout(current_rtt)

            data, addr = s.recvfrom(1024)
            print(data, addr)

            if data == b"FRONT!":
                with front_lock:
                    section = None
                    front = None
            elif data[:4] == b"PING":
                with s_lock:
                    s.sendto(b"PONG " + data[5:], addr)
            else:
                with front_lock:
                    if addr != front:
                        raise Exception

                last_front_msg = time.time()

                if data[:3] == b"ACK":
                    seq = struct.unpack_from("!l", data[3:])[0]

                    if seq in outbound_cmds:
                        del outbound_cmds[seq]
                    
                    while last_ack < seq and last_ack not in outbound_cmds:
                        last_ack += 1
        except socket.timeout:
            if time.time() - last_front_msg > settings.FRONT_TIMEOUT:
                with front_lock:
                    print("Lost front to timeout")
                    section = None
                    front = None
            pass
        except Exception:
            pass
        except:
            break

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

        try:
            timestamp, seq = resend_queue.get(False)

            if timestamp is not None and seq in outbound_cmds:
                if time.time() + current_rtt >= timestamp:
                    with front_lock, s_lock:
                        s.sendto(outbound_cmds[seq], front)
                    timestamp = time.time()

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

            print("Sending command", packet)

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