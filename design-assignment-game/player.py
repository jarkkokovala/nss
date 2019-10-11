import settings

import sys
import random
import string
import socket
import pickle
import threading
import http.client

if len(sys.argv) < 2:
    print("Usage:", sys.argv[0], "<player #>")
    exit()

PLAYER = int(sys.argv[1])
front = None
front_lock = threading.Lock()

def login_blackbox():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

def get_front(s, session):
    packet = pickle.dumps({"id" : PLAYER, "session": session})
    s.sendto(b"FRONT?" + packet, settings.LOGIN_ADDRPORT)

    try:
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

def player_listener(s, s_lock):
    global front
    session = None
    section = None

    while True:
        with front_lock:
            while not front:
                if not session:
                    session = login_blackbox()
                
                front = get_front(s, session)
            while not section:
                section = get_section(front, session)
        
        try:
            data, addr = s.recvfrom(1024)
            print(data, addr)

            if data == b"FRONT!":
                with front_lock:
                    section = None
                    front = None
            elif data[:4] == b"PING":
                s.sendto(b"PONG " + data[5:], addr)
        except socket.timeout:
            pass


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s, threading.Lock() as s_lock:
        s.settimeout(settings.PLAYER_TIMEOUT)
        session = None
        section = None
        front = None

        player_listener_thread = threading.Thread(target=player_listener, args=(s, s_lock))
        player_listener_thread.start()

        player_listener_thread.join()

if __name__ == "__main__":
    main()