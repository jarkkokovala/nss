#!/usr/bin/env python3

import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect(("127.0.0.1", 12345))

    while True:
        data = s.recv(1024)
        if not data:
            break
        print(data.decode())