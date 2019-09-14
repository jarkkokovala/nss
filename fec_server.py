#!/usr/bin/env python3

import socket
import sys
import struct
import time

LISTEN_IP = "127.0.0.1"
LISTEN_PORT = 12345
TIMEOUT = 5
PAYLOAD_SIZE = 100
DATA_FILE = "E.txt"

if len(sys.argv) < 2 or sys.argv[1] not in ("triple", "xor"):
    print("Usage:", sys.argv[0], "{triple|xor}")
    exit()

METHOD = sys.argv[1]

def try_decode(buffer, window_start, f):
    ret = 0

    if METHOD == "triple":
        for item in buffer:
            if item:
                f.seek(int(window_start/3) * PAYLOAD_SIZE)

                if item == f.read(PAYLOAD_SIZE):
                    ret += 1

                break
    else: # METHOD == "xor"
        if not buffer[0] and (buffer[1] and buffer[2]):
            buffer[0] = bytes(x ^ y for x, y in zip(buffer[1], buffer[2]))
        
        if not buffer[1] and (buffer[0] and buffer[2]):
            buffer[1] = bytes(x ^ y for x, y in zip(buffer[0], buffer[2]))
        
        if buffer[0]:
            f.seek((window_start - int(window_start/3)) * PAYLOAD_SIZE)
            if buffer[0] == f.read(PAYLOAD_SIZE):
                ret += 1
        
        if buffer[1]:
            f.seek(((window_start - int(window_start/3)) + 1) * PAYLOAD_SIZE)
            if buffer[1] == f.read(PAYLOAD_SIZE):
                ret += 1
    
    return ret

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s, open(DATA_FILE, "rb") as f:
        s.bind((LISTEN_IP, LISTEN_PORT))
        s.settimeout(TIMEOUT)
        recv_count = 0
        payload_count = 0
        buffer = [0, 0, 0]
        window_start = 0

        print("Listening for udp packets at", LISTEN_IP, "port", LISTEN_PORT)
        while True:
            try:
                data, addr = s.recvfrom(1024)
                sys.stdout.write('.')
                sys.stdout.flush()
            except socket.timeout:
                print("\nTimeout with", 3 - buffer.count(0), "packets in buffer")
                if(buffer.count(0) < 3):
                    payload_count += try_decode(buffer, window_start, f)
                    buffer = [0, 0, 0]
                print("Received", payload_count, "payloads succesfully in", recv_count, "packets since last check")
                recv_count = 0
                payload_count = 0
                continue

            recv_count += 1
            id = struct.unpack_from("!l", data)[0]

            payload = data[4:]
            modulus = id % 3

            if id < window_start:
                window_start = 0

            if (id - window_start) > 2:
                payload_count += try_decode(buffer, window_start, f)
                buffer = [0, 0, 0]
                window_start = id - modulus

            buffer[modulus] = payload

            if modulus == 2:
                payload_count += try_decode(buffer, window_start, f)
                buffer = [0, 0, 0]
                window_start = id + 1

if __name__ == "__main__":
    main()