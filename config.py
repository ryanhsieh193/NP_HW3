# Server 綁定的位址 (在遠端機器上跑通常設為 0.0.0.0)
LOBBY_HOST = "0.0.0.0"
LOBBY_PORT = 60001 # 或者是你設定的 Port

DB_HOST = "127.0.0.1" # DB 和 Lobby 在同一台機器，所以用 localhost
DB_PORT = 10003

# 這是給 Client 連線用的 Public IP (助教電腦連過來用的)
# 如果你在學校伺服器，這裡要填伺服器的 Public IP
# 但 Server bind 時通常不需要這個變數，主要是 Client 需要
GAME_HOST = "linux1.cs.nycu.edu.tw" 
GAME_PORT = 60002