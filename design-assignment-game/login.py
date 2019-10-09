import settings

import sys
import socket
import pickle
import threading
import http.client
from urllib.parse import urlencode

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(settings.LOGIN_ADDRPORT)

        while True:
            data, addr = s.recvfrom(1024)

            if data[:5] == "FRONT":
                client = pickle.loads(data[5:])
                client["addr"] = addr

                while True:
                    try:
                        quorum_conn = http.client.HTTPConnection(settings.QUORUM_ADDRPORT[0], settings.QUORUM_ADDRPORT[1])
                        quorum_conn.request("GET", "/front", urlencode(client))
                        response = quorum_conn.getresponse()

                        if response.status == 200:
                            s.sendto(b"FRONT" + response.read(), addr)
                            break
                    except OSError:
                        pass

if __name__ == "__main__":
    main()