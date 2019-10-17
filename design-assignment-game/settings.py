# Global settings used for modules
# Jarkko Kovala <jarkko.kovala@iki.fi>

SECTION_XSIZE = 100
SECTION_YSIZE = 100

QUORUM_ADDRPORT = ( "127.0.0.1", 10000 )

LOGIN_ADDRPORT = ( "127.0.0.1", 10001 )

STORE_ADDRPORT = ( "127.0.0.1", 10002 )

INITIAL_FRONTS = { 
        1 : { "address": ("127.0.0.1", 10101) },
        2 : { "address": ("127.0.0.1", 10102) },
        3 : { "address": ("127.0.0.1", 10103) },
        4 : { "address": ("127.0.0.1", 10104) }
    }
FRONT_TIMEOUT = 5

INITIAL_SECTIONS_FOR_FRONTS = { 
        1 : {   
                1 : { "version": 0, 
                    "e-neighbor": (INITIAL_FRONTS[2]["address"], 2),
                    "s-neighbor": (INITIAL_FRONTS[3]["address"], 3),
                    "name": "Section #1",
                    "objects": { 
                        1 : { "name" : "Player #1 ship", "loc": (1, 1), "speed": 0, "direction": 90 },
                        100 : { "name" : "Planet #1", "loc": (0, 0), "speed": 0 }
                    }
                }
            },
        2 : {
                2 : { "version": 0,
                    "w-neighbor": (INITIAL_FRONTS[1]["address"], 1),
                    "s-neighbor": (INITIAL_FRONTS[4]["address"], 4),
                    "name": "Section #2",
                    "objects": {
                        2 : { "name" : "Player #2 ship", "loc": (10, 10), "speed": 0, "direction": 180 }
                    }
                }
            },
        3 : {   
                3 : { "version": 0, 
                    "n-neighbor": (INITIAL_FRONTS[1]["address"], 1),
                    "e-neighbor": (INITIAL_FRONTS[4]["address"], 4),
                    "name": "Section #3",
                    "objects": { 
                    }
                }
            },
        4 : {   
                4 : { "version": 0, 
                    "n-neighbor": (INITIAL_FRONTS[2]["address"], 2),
                    "w-neighbor": (INITIAL_FRONTS[3]["address"], 3),
                    "name": "Section #4",
                    "objects": { 
                    }
                }
            }
    }

INITIAL_PLAYERS = { 
        1 : { "name": "Player #1", "id": 1, "front": 1, "section": 1 },
        2 : { "name": "Player #2", "id": 2, "front": 2, "section": 2 }
    }

PLAYER_INITIAL_RTT = 1

PLAYER_TIMEOUT = 1

STORE_RESEND_TIMEOUT = 1

PACKET_LOSS = 0
