import settings

import sys
import random
import string
import socket
import pickle
import threading

if len(sys.argv) < 2:
    print("Usage:", sys.argv[0], "<player #>")
    exit()

PLAYER = int(sys.argv[1])

def login_blackbox():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(settings.PLAYER_TIMEOUT)
        session = None
        front = None

        while True:
            if not session:
                session = login_blackbox()
            while not front:
                packet = pickle.dumps({"id" : PLAYER, "session": session})
                s.sendto(b"FRONT?" + packet, settings.LOGIN_ADDRPORT)

                try:
                    data, addr = s.recvfrom(1024)
                except socket.timeout:
                    print("Timed out waiting for a front")
                    continue

                if data[:6] == b"FRONT:":
                    front = pickle.loads(data[6:])
                    print("Got new front", front)

if __name__ == "__main__":
    main()