QUORUM_ADDRPORT = ( "127.0.0.1", 10000 )

LOGIN_ADDRPORT = ( "127.0.0.1", 10001 )

INITIAL_FRONTS = { 1 : { "address": ("127.0.0.1", 10100) } }
FRONT_TIMEOUT = 5

INITIAL_PLAYERS = { 1 : { "name": "Player #1", "front": 1 } }
PLAYER_TIMEOUT = 1