#!/usr/bin/env python3

import sys
import socket
import struct
import random
import time

DEST_IP = "127.0.0.1"
DEST_PORT = 12345
DATA_FILE = "E.txt"
PAYLOAD_SIZE = 100

if len(sys.argv) < 3 or sys.argv[2] not in ("triple", "xor"):
    print("Usage:", sys.argv[0], " <packet loss percentage> {triple|xor}")
    exit()

PACKET_LOSS = int(sys.argv[1])
METHOD = sys.argv[2]

count = 0
drops = 0

def try_send(s, payload):
    global count
    global drops

    if(random.randint(1, 100) > PACKET_LOSS):
        packet = struct.pack("!l", count) + payload

        s.sendto(packet, (DEST_IP, DEST_PORT))
        time.sleep(0.001)
    else:
        drops += 1
    
    count += 1

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s, open(DATA_FILE, "rb") as f:
        sent = 0
        data = f.read(PAYLOAD_SIZE)

        while data:
            if METHOD == "triple":
                for i in range(3):
                    try_send(s, data)
                sent += 1
            else: # METHOD == "xor"
                try_send(s, data)
                sent += 1

                data2 = f.read(PAYLOAD_SIZE)
                if(data2):
                    try_send(s, data2)
                    sent += 1

                    xor = bytes(x ^ y for x, y in zip(data, data2))
                    try_send(s, xor)
                else:
                    break
    
            data = f.read(PAYLOAD_SIZE)

        print("Sent", sent, "payloads in", count, "packets with", drops, "drops")

if __name__ == "__main__":
    main()