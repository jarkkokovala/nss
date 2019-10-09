import settings

import sys
import socket
import struct
import time
import threading

if len(sys.argv) < 2:
    print("Usage:", sys.argv[0], "<front #>")
    exit()

FRONT = int(sys.argv[1])
addrport = settings.FRONTS[FRONT]
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

def main():
    ping_listener_thread = threading.Thread(target=ping_listener)
    ping_listener_thread.start()

if __name__ == "__main__":
    main()