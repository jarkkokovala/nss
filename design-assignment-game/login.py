# Login module: handles login requests for player
# Jarkko Kovala <jarkko.kovala@iki.fi>

import settings

import sys
import socket
import pickle
import threading
import http.client

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(settings.LOGIN_ADDRPORT)

        # Listen for UDP forever
        while True:
            data, addr = s.recvfrom(1024)

            if data[:6] == b"FRONT?":
                client = pickle.loads(data[6:])
                client["addr"] = addr

                # TODO (after real player login has been implemented)
                # check that request game from valid session
                # and get player id from session data instead
                # of trusting client

                try:
                    print("Asking for front for", client)

                    # Get front from quorum
                    addrport = settings.QUORUM_ADDRPORT
                    quorum_conn = http.client.HTTPConnection(addrport[0], addrport[1])
                    quorum_conn.request("POST", "/front", pickle.dumps(client))
                    response = quorum_conn.getresponse()
                    quorum_conn.close()

                    if response.status == 200: # If OK, send to player
                        s.sendto(b"FRONT:" + response.read(), addr)

                except OSError:
                    pass

if __name__ == "__main__":
    main()
