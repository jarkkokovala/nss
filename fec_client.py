#!/usr/bin/env python3

import sys
import socket
import struct
import random
import time

# Forward error correction client, sends data as UDP packets
# Arguments: packet loss probability as a percentage and FEC method (triple redundancy or XOR)

DEST_IP = "127.0.0.1" # Destination IP address
DEST_PORT = 12345 # Destination UDP address
DATA_FILE = "E.txt" # Source file where to read data to be sent
PAYLOAD_SIZE = 100 # How many bytes of payload to send in a packet

if len(sys.argv) < 3 or sys.argv[2] not in ("triple", "xor"):
    print("Usage:", sys.argv[0], " <packet loss percentage> {triple|xor}")
    exit()

PACKET_LOSS = int(sys.argv[1]) # Packet loss probability (percentage 0-100)
METHOD = sys.argv[2] # FEC method ("triple" or "xor")

count = 0 # Packet counter
drops = 0 # How many packets have been dropped so far

# Construct and try to send a packet simulating packet loss
# Arguments: socket where to send and payload to send
def try_send(s, payload):
    global count
    global drops

    if(random.randint(1, 100) > PACKET_LOSS): # Randomly drop packets
        # Construct packet: 4 bytes for packet id plus payload
        packet = struct.pack("!l", count) + payload

        s.sendto(packet, (DEST_IP, DEST_PORT))
        time.sleep(0.001) # Don't send too fast
    else:
        drops += 1
    
    count += 1

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s, open(DATA_FILE, "rb") as f:
        sent = 0
        data = f.read(PAYLOAD_SIZE)

        # Read from data file until no more data.
        while data:
            if METHOD == "triple":
                # Triple redundancy: just send three copies of packet
                for i in range(3):
                    try_send(s, data)
                sent += 1
            else: # METHOD == "xor"
                # XOR: send two packets plus xor of the two packets
                # First packet
                try_send(s, data)
                sent += 1

                # Second packet (if there is any more data)
                data2 = f.read(PAYLOAD_SIZE)
                if(data2):
                    try_send(s, data2)
                    sent += 1

                    # Calculate XOR of the previous two and send
                    xor = bytes(x ^ y for x, y in zip(data, data2))
                    try_send(s, xor)
                else:
                    break
    
            data = f.read(PAYLOAD_SIZE)

        print("Sent", sent, "payloads in", count, "packets with", drops, "drops")

if __name__ == "__main__":
    main()