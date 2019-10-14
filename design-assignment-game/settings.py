QUORUM_ADDRPORT = ( "127.0.0.1", 10000 )

LOGIN_ADDRPORT = ( "127.0.0.1", 10001 )

INITIAL_FRONTS = { 
        1 : { "address": ("127.0.0.1", 10100) } 
    }
FRONT_TIMEOUT = 5

INITIAL_SECTIONS_FOR_FRONTS = { 
        1 : { 1 : { "version": 0, 
                    "name": "Section #1",
                    "objects": { 
                        1 : { "name" : "Player #1 ship", "loc": (1, 1), "speed": 0, "direction": 90 },
                        2 : { "name" : "Planet #1", "loc": (0, 0), "speed": 0 }
                    }
            } } 
    }

INITIAL_PLAYERS = { 
        1 : { "name": "Player #1", "id": 1, "front": 1, "section": 1 } 
    }

PLAYER_INITIAL_RTT = 1

PLAYER_TIMEOUT = 1

PACKET_LOSS = 25