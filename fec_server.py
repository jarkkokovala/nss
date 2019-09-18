#!/usr/bin/env python3

import socket
import sys
import struct
import time

# Forward error correction server, receives data as UDP packets
# Argument: FEC method (triple redundancy or XOR)

LISTEN_IP = "127.0.0.1" # IP address where we listen
LISTEN_PORT = 12345 # UDP port where we listen
TIMEOUT = 5 # Timeout after we assume there will be no more packets in the stream
PAYLOAD_SIZE = 100 # How many bytes of payload we receive in each packet
DATA_FILE = "E.txt" # Data file to compare received data

if len(sys.argv) < 2 or sys.argv[1] not in ("triple", "xor"):
    print("Usage:", sys.argv[0], "{triple|xor}")
    exit()

METHOD = sys.argv[1] # FEC method ("triple" or "xor")

# Try to 
# Arguments: receive buffer, packet id of the first packet in the buffer, file for comparing data
def try_decode(buffer, window_start, f):
    ret = 0

    if METHOD == "triple":
        # Triple redundancy: just check through buffer, if there is a packet we're done
        for item in buffer:
            if item:
                # Compare against datafile to be sure everything worked
                f.seek(int(window_start/3) * PAYLOAD_SIZE)

                if item == f.read(PAYLOAD_SIZE):
                    ret += 1

                break
    else: # METHOD == "xor"
        # XOR: If packet is missing try to reconstruct from another packet and xor packet
        # If first packet is missing and we have second and third, reconstruct
        if not buffer[0] and (buffer[1] and buffer[2]):
            buffer[0] = bytes(x ^ y for x, y in zip(buffer[1], buffer[2]))
        
        # If second packet is missing and we have first and third, reconstruct
        if not buffer[1] and (buffer[0] and buffer[2]):
            buffer[1] = bytes(x ^ y for x, y in zip(buffer[0], buffer[2]))
        
        # If we now have first packet, compare against datafile
        if buffer[0]:
            f.seek((window_start - int(window_start/3)) * PAYLOAD_SIZE)
            if buffer[0] == f.read(PAYLOAD_SIZE):
                ret += 1
        
        # If we now have second packet, compare against datafile
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
                # Listen for packets
                data, addr = s.recvfrom(1024)
                sys.stdout.write('.')
                sys.stdout.flush()
            except socket.timeout:
                # If no packets have been received in TIMEOUT seconds flush buffer and start over
                print("\nTimeout with", 3 - buffer.count(0), "packets in buffer")
                if(buffer.count(0) < 3):
                    payload_count += try_decode(buffer, window_start, f)
                    buffer = [0, 0, 0]
                print("Received", payload_count, "payloads succesfully in", recv_count, "packets since last check")
                recv_count = 0
                payload_count = 0
                continue

            # We have packet
            recv_count += 1
            # Extract packet id from the first 4 bytes
            id = struct.unpack_from("!l", data)[0]

            # Extract payload
            payload = data[4:]
            # Location of received packet in window
            modulus = id % 3

            # If we received packet smaller than current window, assume we have started over
            if id < window_start:
                window_start = 0

            # If we received packet outside current window (window_start + 2), flush buffer
            if (id - window_start) > 2:
                payload_count += try_decode(buffer, window_start, f)
                buffer = [0, 0, 0]
                window_start = id - modulus

            # Insert packet in buffer
            buffer[modulus] = payload

            # If we received packet at window end, flush buffer
            if modulus == 2:
                payload_count += try_decode(buffer, window_start, f)
                buffer = [0, 0, 0]
                window_start = id + 1

if __name__ == "__main__":
    main()