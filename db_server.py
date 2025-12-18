# db_server.py
import socket
import json
import struct
import threading
import os
import time

DB_HOST = "0.0.0.0"
DB_PORT = 10003

DB_FILE = "db.json"
server_running = True

lock = threading.Lock()
# [Modified] Added "Games" to store uploaded game information
DB_TEMPLATE = {"User": {}, "Developer": {}, "Room": {}, "GameLog": {}, "Games": {}}


def load_db():
    """Load the database from the JSON file."""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                # Ensure the old DB has the "Games" field
                if "Games" not in data:
                    data["Games"] = {}
                return data
            except json.JSONDecodeError:
                print("[DB SERVER] Invalid JSON file. Resetting database.")
                return DB_TEMPLATE.copy()
    else:
        return DB_TEMPLATE.copy()


def save_db():
    """Save the current state of the database to the JSON file."""
    with lock:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=4, ensure_ascii=False)


db = load_db()


# Helper: Receive message with 4-byte length prefix
def recv_msg(sock):
    raw_len = sock.recv(4)
    if not raw_len:
        return None
    msg_len = struct.unpack("!I", raw_len)[0]
    if msg_len <= 0 or msg_len > 65536:
        return None
    data = b""
    while len(data) < msg_len:
        packet = sock.recv(msg_len - len(data))
        if not packet:
            return None
        data += packet
    return data.decode()


# Helper: Send message with 4-byte length prefix
def send_msg(sock, message):
    msg_bytes = message.encode()
    sock.sendall(struct.pack("!I", len(msg_bytes)) + msg_bytes)


# Client Handler
def handle_client(conn, addr):
    print(f"[DB CONNECTED] {addr}")
    try:
        while True:
            # Receive data using length-prefix protocol
            raw_len = b""
            while len(raw_len) < 4:
                chunk = conn.recv(4 - len(raw_len))
                if not chunk:
                    return  # Connection closed
                raw_len += chunk

            msg_len = struct.unpack("!I", raw_len)[0]
            if msg_len <= 0 or msg_len > 65536:
                print(f"[ERROR] Invalid message length: {msg_len}")
                break

            data = b""
            while len(data) < msg_len:
                packet = conn.recv(msg_len - len(data))
                if not packet:
                    return  # Connection closed
                data += packet

            msg = json.loads(data.decode())
            # print(f"[DB DEBUG] Received: {msg}") 
 


            cmd = msg.get("cmd")
            response = {"status": "error", "msg": "Unknown command"}
            role = msg.get("role", "player")
            target_table = "Developer" if role == "developer" else "User"

            if cmd == "create":
                user = msg.get("user")
                password = msg.get("password")
                if user in db[target_table]:
                    response = {"status": "error", "msg": f"{role.capitalize()} account exists"}
                else:
                    # Create account
                    db[target_table][user] = {"password": password, "online": False}
                    if role == "developer":
                        db[target_table][user]["owned_games"] = []  # Reserved field
                    save_db()
                    response = {"status": "ok"}

            elif cmd == "read":
                user = msg.get("user")
                if user in db[target_table]:
                    response = {
                        "status": "ok",
                        "password": db[target_table][user]["password"],
                        "online": db[target_table][user].get("online", False),
                    }
                else:
                    response = {"status": "error", "msg": "Account not found"}

            elif cmd == "set_online":
                user = msg.get("user")
                online = msg.get("online", False)
                if user in db[target_table]:
                    db[target_table][user]["online"] = online
                    save_db()
                    response = {"status": "ok"}
                else:
                    response = {"status": "error", "msg": "User not found"}

            elif cmd == "list":
                online_only = msg.get("online_only", False)
                users = list(db["User"].keys())
                if online_only:
                    users = [u for u in users if db["User"][u].get("online", False)]
                response = {"status": "ok", "users": users}

            # --- Store Related Commands ---
            elif cmd == "update_game_info":
                try:
                    # 1. Safety check: Ensure 'Games' table exists
                    if "Games" not in db:
                        print("[DB] 'Games' table missing, creating new one...")
                        db["Games"] = {}

                    game_id = msg.get("game_id")
                    new_info = msg.get("info")

                    if not game_id or not new_info:
                        print("[DB Error] Missing game_id or info")
                        response = {"status": "error", "msg": "Missing data"}
                    else:
                        # 2. Ensure the game entry exists
                        if game_id not in db["Games"]:
                            db["Games"][game_id] = {}

                        # 3. Preserve existing reviews
                        existing_reviews = db["Games"][game_id].get("reviews", [])

                        # 4. Update info
                        db["Games"][game_id] = new_info
                        db["Games"][game_id]["reviews"] = existing_reviews

                        save_db()
                        print(f"[DB] Updated info for {game_id}")
                        response = {"status": "ok"}
                except Exception as e:
                    print(f"[DB EXCEPTION] update_game_info failed: {e}")
                    response = {"status": "error", "msg": str(e)}

            # Get detailed game info (including reviews)
            elif cmd == "get_game_details":
                game_id = msg.get("game_id")
                if game_id in db["Games"]:
                    game_data = db["Games"][game_id]
                    response = {"status": "ok", "game_info": game_data}
                else:
                    response = {"status": "error", "msg": "Game not found"}

            # Add a review
            elif cmd == "add_review":
                game_id = msg.get("game_id")
                user = msg.get("user")
                rating = msg.get("rating")
                comment = msg.get("comment")

                if game_id in db["Games"]:
                    if "reviews" not in db["Games"][game_id]:
                        db["Games"][game_id]["reviews"] = []

                    reviews_list = db["Games"][game_id]["reviews"]

                    # --- Check if already reviewed, update if so (Upsert) ---
                    found = False
                    for r in reviews_list:
                        if r["user"] == user:
                            r["rating"] = int(rating)
                            r["comment"] = comment
                            r["time"] = time.time()  # Update timestamp
                            found = True
                            msg_str = "Review updated"
                            break

                    if not found:
                        review_entry = {
                            "user": user,
                            "rating": int(rating),
                            "comment": comment,
                            "time": time.time()
                        }
                        reviews_list.append(review_entry)
                        msg_str = "Review added"
                    # -----------------------------------------------

                    save_db()
                    response = {"status": "ok", "msg": msg_str}
                else:
                    response = {"status": "error", "msg": "Game not found"}

            elif cmd == "get_store_list":
                # Return all uploaded games (metadata only)
                games_list = []
                for gid, info in db["Games"].items():
                    games_list.append(info)
                response = {"status": "ok", "games": games_list}

            elif cmd == "delete_game":
                game_id = msg.get("game_id")
                if game_id in db["Games"]:
                    del db["Games"][game_id]
                    save_db()
                    response = {"status": "ok", "msg": f"Game {game_id} deleted"}
                else:
                    response = {"status": "error", "msg": "Game not found"}


            elif cmd == "create_room":
                room_name = msg.get("room_name")
                host = msg.get("host")
                private = msg.get("private", False)
                game_id = msg.get("game_id")

                if room_name in db["Room"]:
                    response = {"status": "error", "msg": "Room already exists"}
                else:
                    db["Room"][room_name] = {
                        "host": host,
                        "private": private,
                        "game_id": game_id,
                        "max_players": msg.get("max_players", 2),
                        "open": True,
                        "members": [host],
                        "ready": {host: False},
                    }
                    save_db()
                    response = {"status": "ok"}

            elif cmd == "list_rooms":
                rooms = []
                for name, info in db["Room"].items():
                    if not info["private"]:
                        limit = info.get("max_players", 2)
                        full = len(info["members"]) >= limit
                        rooms.append(
                            {
                                "name": name,
                                "host": info["host"],
                                "open": info["open"] and not full,
                                "private": info["private"],
                            }
                        )
                response = {"status": "ok", "rooms": rooms}

            elif cmd == "join_room":
                room_name = msg.get("room_name")
                user = msg.get("user")
                if room_name not in db["Room"]:
                    response = {"status": "error", "msg": "Room not found"}
                else:
                    room = db["Room"][room_name]
                    limit = room.get("max_players", 2)
                    if len(room["members"]) >= limit:
                        response = {"status": "error", "msg": "Room is full"}
                    elif user in room["members"]:
                        response = {"status": "error", "msg": "Already in room"}
                    else:
                        room["members"].append(user)
                        room["ready"][user] = False
                        if len(room["members"]) >= limit:
                            room["open"] = False
                        save_db()
                        response = {"status": "ok"}

            elif cmd == "leave_room":
                user = msg.get("user")
                for rn, info in list(db["Room"].items()):
                    if user in info["members"]:
                        info["members"].remove(user)
                        if "ready" in info and user in info["ready"]:
                            del info["ready"][user]

                        if len(info["members"]) == 0:
                            del db["Room"][rn]
                        elif info["host"] == user:
                            info["host"] = info["members"][0]

                        if rn in db["Room"]:
                            db["Room"][rn]["open"] = True

                        save_db()
                        response = {"status": "ok", "msg": f"Left room {rn}"}
                        break
                else:
                    response = {"status": "error", "msg": "User not in any room"}

            elif cmd == "get_user_room":
                user = msg.get("user")
                room_found = None
                for rn, info in db["Room"].items():
                    if user in info.get("members", []):
                        room_found = rn
                        break
                response = {"status": "ok", "room_name": room_found}

            elif cmd == "get_room_info":
                room_name = msg.get("room_name")
                if room_name in db["Room"]:
                    info = db["Room"][room_name].copy()
                    info["room_name"] = room_name
                    response = {"status": "ok", "room_info": info}
                else:
                    response = {"status": "error", "msg": "Room not found"}

            elif cmd == "clear_invitations":
                user = msg.get("user")
                if user in db["User"]:
                    db["User"][user]["invitations"] = []
                    save_db()
                    response = {"status": "ok"}
                else:
                    response = {"status": "error", "msg": "User not found"}

            elif cmd == "get_invitations":
                user = msg.get("user")
                if user in db["User"]:
                    # Use .get() to avoid errors if field is missing in old data
                    invites = db["User"][user].get("invitations", [])
                    response = {"status": "ok", "invitations": invites}
                else:
                    response = {"status": "error", "msg": "User not found"}

            elif cmd == "invite":
                target_user = msg.get("user")
                room_name = msg.get("room_name")

                if target_user not in db["User"]:
                    response = {"status": "error", "msg": "Target user not found"}
                else:
                    # Ensure invitation list exists
                    if "invitations" not in db["User"][target_user]:
                        db["User"][target_user]["invitations"] = []

                    # Avoid duplicate invitations
                    if room_name not in db["User"][target_user]["invitations"]:
                        db["User"][target_user]["invitations"].append(room_name)
                        save_db()

                    response = {"status": "ok", "msg": f"Invitation sent to {target_user}"}

            elif cmd == "respond_invitation":
                user = msg.get("user")
                room_name = msg.get("room_name")
                accept = msg.get("accept")  # True or False

                if user in db["User"]:
                    # 1. Remove from invite list regardless of acceptance
                    user_invites = db["User"][user].get("invitations", [])
                    if room_name in user_invites:
                        user_invites.remove(room_name)
                        db["User"][user]["invitations"] = user_invites
                        save_db()

                    # 2. If accepted, execute join room logic
                    if accept:
                        if room_name not in db["Room"]:
                            response = {"status": "error", "msg": "Room no longer exists"}
                        else:
                            room = db["Room"][room_name]
                            if len(room["members"]) >= 2:
                                response = {"status": "error", "msg": "Room is full"}
                            elif user in room["members"]:
                                response = {"status": "error", "msg": "Already in room"}
                            else:
                                room["members"].append(user)
                                room["ready"][user] = False  # Default not ready
                                if len(room["members"]) >= 2:
                                    room["open"] = False  # Close room if full
                                save_db()
                                response = {"status": "ok", "msg": f"Joined room {room_name}"}
                    else:
                        response = {"status": "ok", "msg": "Invitation declined"}
                else:
                    response = {"status": "error", "msg": "User not found"}

            elif cmd == "set_ready":
                user = msg.get("user")
                ready = msg.get("ready")
                room_found = False

                # Find user's room
                for r_name, r_info in db["Room"].items():
                    if user in r_info["members"]:
                        r_info["ready"][user] = ready
                        room_found = True
                        save_db()
                        response = {"status": "ok", "msg": f"Set ready to {ready}"}
                        break

                if not room_found:
                    response = {"status": "error", "msg": "User not in any room"}

            else:
                # Fallback for unhandled commands (if any)
                if response["msg"] == "Unknown command" and cmd in ["invite", "manage_invitations", "respond_invitation", "set_ready", "start_game"]:
                    pass

            send_msg(conn, json.dumps(response))

    except Exception as e:
        if not isinstance(e, ConnectionResetError):
            print(f"[DB ERROR] {e}")
    finally:
        conn.close()
        print(f"[DB DISCONNECTED] {addr}")


def admin_console(server_socket):
    global server_running
    while True:
        cmd = input()
        if cmd.strip().lower() in ("shutdown", "s"):
            print("[DB SERVER] Saving user data...")
            save_db()
            print("[DB SERVER] Shutting down server...")
            server_running = False
            server_socket.close()
            os._exit(0)


def main():
    global db
    db = load_db()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((DB_HOST, DB_PORT))
    server.listen()
    print(f"[DB SERVER] Listening on {DB_HOST}:{DB_PORT}")

    threading.Thread(target=admin_console, args=(server,), daemon=True).start()

    while server_running:
        try:
            conn, addr = server.accept()
            threading.Thread(
                target=handle_client, args=(conn, addr), daemon=True
            ).start()
        except OSError:
            break


if __name__ == "__main__":
    main()