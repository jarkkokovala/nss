#!/usr/bin/env python3

import socket
import threading
import time

class client_thread(threading.Thread):
    def __init__(self, s, addr):
        threading.Thread.__init__(self)
        self.s = s

    def run(self):
        with self.s as s:
            for x in range(1, 6):
                msg = "Hello " + str(time.time()) + "\n"
                s.send(msg.encode())
                time.sleep(3)
            s.send("Bye!\n".encode())

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 12345))
    while True:
        s.listen()
        client, addr = s.accept()
        thread = client_thread(client, addr)
        thread.start()

