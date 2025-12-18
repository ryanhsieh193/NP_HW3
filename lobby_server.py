# lobby_server.py
import socket
import threading
import json
import os
import sys
import subprocess
import struct
import shutil
import zipfile
from config import LOBBY_HOST, LOBBY_PORT, DB_HOST, DB_PORT, GAME_HOST, GAME_PORT

HOST = LOBBY_HOST
PORT = LOBBY_PORT

server_running = True
db_socket = None
game_server_process = None

# Global client connection tracking (username -> socket object)
client_connections = {}
connection_lock = threading.Lock()


def connect_db_server():
    global db_socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(5)  # Set connection timeout
        s.connect((DB_HOST, DB_PORT))
        print(f"[SYSTEM] Connected to DB server at {DB_HOST}:{DB_PORT}")
        s.settimeout(None)  # Remove timeout after successful connection
        db_socket = s
        return s
    except Exception as e:
        print(f"[ERROR] Cannot connect to DB server at {DB_HOST}:{DB_PORT}")
        print(f"[ERROR DETAIL] {type(e).__name__}: {e}")
        print(f"[ERROR] Cannot connect to DB server at {DB_HOST}:{DB_PORT}")
        print(f"[ERROR DETAIL] {type(e).__name__}: {e}")
        raise ConnectionError("DB Connection Failed")



def db_request(req_dict):
    global db_socket
    try:
        if db_socket is None:
            connect_db_server()

        # Send using length-prefix format (matching db_server.py)
        msg_json = json.dumps(req_dict)
        msg_bytes = msg_json.encode()
        length_prefix = struct.pack("!I", len(msg_bytes))
        db_socket.send(length_prefix + msg_bytes)

        # Set receive timeout to avoid indefinite waiting
        db_socket.settimeout(5)
        try:
            # Receive response length prefix (ensure 4 bytes are read)
            raw_len = b""
            while len(raw_len) < 4:
                chunk = db_socket.recv(4 - len(raw_len))
                if not chunk:
                    raise ConnectionResetError("DB server closed connection")
                raw_len += chunk

            resp_len = struct.unpack("!I", raw_len)[0]
            if resp_len <= 0 or resp_len > 65536:
                raise ValueError(f"Invalid response length: {resp_len}")

            resp_data = b""
            while len(resp_data) < resp_len:
                packet = db_socket.recv(resp_len - len(resp_data))
                if not packet:
                    raise ConnectionResetError(
                        "DB server closed connection during read"
                    )
                resp_data += packet
        finally:
            db_socket.settimeout(None)  # Restore blocking mode

        return json.loads(resp_data.decode())
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        print(f"[WARNING] DB connection lost: {e}. Reconnecting...")
        db_socket = None
        # Reconnect and retry once
        try:
            connect_db_server()
            msg_json = json.dumps(req_dict)
            msg_bytes = msg_json.encode()
            length_prefix = struct.pack("!I", len(msg_bytes))
            db_socket.send(length_prefix + msg_bytes)

            # Set receive timeout
            db_socket.settimeout(5)
            try:
                # Receive response length prefix
                raw_len = b""
                while len(raw_len) < 4:
                    chunk = db_socket.recv(4 - len(raw_len))
                    if not chunk:
                        raise ConnectionResetError("DB server closed connection")
                    raw_len += chunk

                resp_len = struct.unpack("!I", raw_len)[0]
                resp_data = b""
                while len(resp_data) < resp_len:
                    packet = db_socket.recv(resp_len - len(resp_data))
                    if not packet:
                        raise ConnectionResetError("DB server closed connection")
                    resp_data += packet
            finally:
                db_socket.settimeout(None)

            return json.loads(resp_data.decode())
        except Exception as retry_e:
            print(f"[ERROR] Failed to reconnect to DB: {retry_e}")
            return {"status": "error", "msg": "Database connection failed"}


def handle_client(conn, addr):
    print(f"[CONNECTED] {addr}")
    current_user = None
    current_role = "player"
    is_listener = False  # Flag to indicate if this is a listener thread connection

    while True:
        try:
            # Use longer timeout for listener thread to avoid frequent timeouts
            if is_listener:
                conn.settimeout(30)  # 30 seconds for listener
            else:
                conn.settimeout(None)  # No timeout for main connection

            data = conn.recv(1024).decode()
            if not data:
                break
            # print(f"[DEBUG] Received from {addr}: {data}")


            
            # Parse only the first valid JSON object
            try:
                msg = json.loads(data)
            except json.JSONDecodeError as e:
                print(f"[ERROR] {addr}: JSON parse failed - {e}")
                print(f"[DEBUG] Received data: {data[:100]}")
                if not is_listener:  # Only respond for non-listener connections
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "Invalid JSON format"}
                        ).encode()
                    )
                continue

            cmd = msg.get("cmd")

            # Handle listener thread connection
            if cmd == "_listener":
                # This connection is used to listen for game start notifications
                username = msg.get("user")
                is_listener = True  # Mark as listener
                if username:
                    with connection_lock:
                        client_connections[f"{username}_listener"] = conn
                    print(f"[SYSTEM] Listener thread connected for user {username}")
                
                # Listener thread enters infinite listening loop
                # Use blocking receive (no timeout) to wait for broadcasts
                conn.settimeout(None)
                while True:
                    try:
                        data = conn.recv(1024).decode()
                        if not data:
                            # Connection closed
                            print(f"[SYSTEM] Listener thread for {username} disconnected")
                            break
                        
                        try:
                            l_msg = json.loads(data)
                            if l_msg.get("cmd") == "set_ready":
                                ready = l_msg.get("ready")
                                db_request({"cmd": "set_ready", "user": username, "ready": ready})
                                # No response needed to client here, listener only expects start_game
                        except json.JSONDecodeError:
                            pass
                        
                    except (ConnectionResetError, OSError):
                        # Normal disconnection
                        print(f"[SYSTEM] Listener thread for {username} disconnected (connection closed)")
                        break
                    except Exception as e:
                        print(f"[WARNING] Listener thread exception: {e}")
                        break
                # Listener loop ended, cleanup connection
                break

            elif cmd == "register":
                username = msg["username"]
                password = msg["password"]
                role = msg.get("role", "player")
                resp = db_request(
                    {"cmd": "create", "user": username, "password": password, "role": role}
                )
                if resp["status"] == "ok":
                    conn.send(
                        json.dumps({"status": "ok", "msg": "Register success"}).encode()
                    )
                    current_role = role
                else:
                    conn.send(
                        json.dumps(
                            {
                                "status": "error",
                                "msg": resp.get("msg", "Register failed"),
                            }
                        ).encode()
                    )

            elif cmd == "login":
                username = msg["username"]
                password = msg["password"]
                role = msg.get("role", "player")
                resp = db_request({"cmd": "read", "user": username, "role": role})
                if resp["status"] == "error":
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "Login failed: user not found"}
                        ).encode()
                    )
                elif resp.get("online", False):
                    conn.send(
                        json.dumps(
                            {
                                "status": "error",
                                "msg": "Login failed: already logged in",
                            }
                        ).encode()
                    )
                elif resp["password"] != password:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "Login failed: wrong password"}
                        ).encode()
                    )
                else:
                    current_user = username
                    current_role = role
                    db_request({"cmd": "set_online", "user": username, "online": True, "role": role})
                    # Record client connection
                    with connection_lock:
                        client_connections[username] = conn
                    conn.send(
                        json.dumps({"status": "ok", "msg": "Login success"}).encode()
                    )

            elif cmd == "logout":
                if current_user:
                    db_request({"cmd": "leave_room", "user": current_user})
                    db_request({"cmd": "clear_invitations", "user": current_user})
                    db_request({"cmd": "set_online", "user": current_user, "online": False, "role": current_role})
                    # Remove client connection record
                    with connection_lock:
                        if current_user in client_connections:
                            del client_connections[current_user]
                    current_user = None
                    conn.send(
                        json.dumps({"status": "ok", "msg": "Logout success"}).encode()
                    )
                else:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "You are not logged in"}
                        ).encode()
                    )

            elif cmd == "list":
                online_only = msg.get("online_only", False)
                resp = db_request({"cmd": "list", "online_only": online_only})
                users = resp.get("users", [])
                conn.send(
                    json.dumps(
                        {"status": "ok", "msg": "User list", "users": users}
                    ).encode()
                )

            elif cmd == "create_room":
                room_name = msg.get("room_name")
                private = msg.get("private", False)
                game_id = msg.get("game_id")
                if not current_user:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "You must login first."}
                        ).encode()
                    )
                else:
                    resp = db_request(
                        {
                            "cmd": "create_room",
                            "room_name": room_name,
                            "host": current_user,
                            "private": private,
                            "game_id": game_id,
                        }
                    )
                    if resp["status"] == "ok":
                        conn.send(
                            json.dumps(
                                {
                                    "status": "ok",
                                    "msg": f"Room '{room_name}' created successfully.",
                                }
                            ).encode()
                        )
                    else:
                        conn.send(
                            json.dumps(
                                {
                                    "status": "error",
                                    "msg": f"Failed to create room: {resp.get('msg')}",
                                }
                            ).encode()
                        )

            elif cmd == "list_rooms":
                resp = db_request({"cmd": "list_rooms"})
                if resp["status"] == "ok":
                    rooms = resp.get("rooms", [])
                    conn.send(
                        json.dumps(
                            {"status": "ok", "msg": "Room list", "rooms": rooms}
                        ).encode()
                    )
                else:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "Failed to fetch room list."}
                        ).encode()
                    )

            elif cmd == "join_room":
                if not current_user:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "You must login first."}
                        ).encode()
                    )
                else:
                    room_name = msg.get("room_name")
                    resp = db_request(
                        {
                            "cmd": "join_room",
                            "room_name": room_name,
                            "user": current_user,
                        }
                    )
                    if resp["status"] == "ok":
                        conn.send(
                            json.dumps(
                                {
                                    "status": "ok",
                                    "msg": f"Joined room '{room_name}' successfully.",
                                }
                            ).encode()
                        )
                    else:
                        conn.send(
                            json.dumps(
                                {
                                    "status": "error",
                                    "msg": f"Failed to join room: {resp.get('msg')}",
                                }
                            ).encode()
                        )

            elif cmd == "leave_room":
                if not current_user:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "You must login first."}
                        ).encode()
                    )
                else:
                    resp = db_request({"cmd": "leave_room", "user": current_user})
                    if resp["status"] == "ok":
                        conn.send(
                            json.dumps(
                                {
                                    "status": "ok",
                                    "msg": resp.get("msg", "Left room successfully"),
                                }
                            ).encode()
                        )
                    else:
                        conn.send(
                            json.dumps(
                                {
                                    "status": "error",
                                    "msg": f"Failed to leave room: {resp.get('msg')}",
                                }
                            ).encode()
                        )

            elif cmd == "get_user_room":
                user = msg.get("user")
                resp = db_request({"cmd": "get_user_room", "user": user})
                conn.send(json.dumps(resp).encode())

            elif cmd == "get_room_info":
                user = msg.get("user")
                resp = db_request({"cmd": "get_user_room", "user": user})
                room_name = resp.get("room_name")
                if room_name:
                    room_resp = db_request(
                        {"cmd": "get_room_info", "room_name": room_name}
                    )
                    conn.send(json.dumps(room_resp).encode())
                else:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "User not in any room"}
                        ).encode()
                    )

            elif cmd == "invite_player":
                if not current_user:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "You must login first."}
                        ).encode()
                    )
                else:
                    resp = db_request({"cmd": "list", "online_only": True})
                    users = resp.get("users", [])
                    room_resp = db_request(
                        {"cmd": "get_user_room", "user": current_user}
                    )
                    room_name = room_resp.get("room_name")
                    if room_name:
                        filtered = [u for u in users if u != current_user]
                        conn.send(
                            json.dumps(
                                {
                                    "status": "ok",
                                    "available_users": filtered,
                                    "room_name": room_name,
                                }
                            ).encode()
                        )
                    else:
                        conn.send(
                            json.dumps(
                                {"status": "error", "msg": "You are not in a room"}
                            ).encode()
                        )

            elif cmd == "manage_invitations":
                if not current_user:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "You must login first."}
                        ).encode()
                    )
                else:
                    resp = db_request({"cmd": "get_invitations", "user": current_user})
                    conn.send(json.dumps(resp).encode())

            elif cmd == "invite":
                if not current_user:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "You must login first."}
                        ).encode()
                    )
                else:
                    target_user = msg.get("user")
                    room_name = msg.get("room_name")
                    resp = db_request(
                        {"cmd": "invite", "user": target_user, "room_name": room_name}
                    )
                    conn.send(json.dumps(resp).encode())

            elif cmd == "respond_invitation":
                if not current_user:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "You must login first."}
                        ).encode()
                    )
                else:
                    room_name = msg.get("room_name")
                    accept = msg.get("accept", False)
                    resp = db_request(
                        {
                            "cmd": "respond_invitation",
                            "user": current_user,
                            "room_name": room_name,
                            "accept": accept,
                        }
                    )
                    conn.send(json.dumps(resp).encode())

            elif cmd == "set_ready":
                if not current_user:
                    conn.send(
                        json.dumps(
                            {"status": "error", "msg": "You must login first."}
                        ).encode()
                    )
                else:
                    ready = msg.get("ready")
                    resp = db_request(
                        {"cmd": "set_ready", "user": current_user, "ready": ready}
                    )
                    conn.send(json.dumps(resp).encode())

            elif cmd == "start_game":
                if not current_user:
                    conn.send(json.dumps({"status":"error","msg":"You must login first."}).encode())
                    continue

                room_info = db_request({"cmd":"get_user_room","user":current_user})
                room_name = room_info.get("room_name")
                if not room_name:
                    conn.send(json.dumps({"status":"error","msg":"You are not in any room."}).encode())
                    continue

                room_data = db_request({"cmd":"get_room_info","room_name":room_name})
                room_info = room_data.get("room_info", {})

                # Check host identity
                if room_info.get("host") != current_user:
                    conn.send(json.dumps({"status":"error","msg":"Only the host can start the game."}).encode())
                    continue
                
                # --- [Modified] Read Manifest first to get min_players ---
                game_id = room_info.get("game_id")
                if not game_id:
                    conn.send(json.dumps({"status":"error","msg":"Room has no game assigned."}).encode())
                    continue

                game_dir = os.path.join("games_repo", game_id)
                manifest_path = os.path.join(game_dir, "manifest.json")
                
                if not os.path.exists(manifest_path):
                     conn.send(json.dumps({"status":"error","msg":"Game files missing on server."}).encode())
                     continue
                
                try:
                    with open(manifest_path, 'r') as f:
                        manifest = json.load(f)
                except Exception as e:
                    conn.send(json.dumps({"status":"error","msg":f"Bad manifest: {e}"}).encode())
                    continue

                # Read min_players from manifest, default to 2
                min_players = manifest.get("min_players", 2)
                
                # --- [Modified] Dynamic player count check ---
                current_players = len(room_info.get("members", []))
                if current_players < min_players:
                    conn.send(json.dumps({
                        "status":"error",
                        "msg":f"Need at least {min_players} players to start (Current: {current_players})."
                    }).encode())
                    continue
                # ----------------------------------------------

                # Check ready status
                not_ready = [u for u in room_info.get("members", []) if not room_info.get("ready", {}).get(u, False)]
                if not_ready:
                    conn.send(json.dumps({"status":"error","msg":f"Cannot start game, not ready: {', '.join(not_ready)}"}).encode())
                    continue

                server_script = manifest.get("server_entry")
                if not server_script:
                     conn.send(json.dumps({"status":"error","msg":"Invalid game manifest (no server_entry)."}).encode())
                     continue

                print(f"[SYSTEM] Launching Game Server for room '{room_name}' ({game_id})...")
                
                try:
                    # Launch child process
                    proc = subprocess.Popen([sys.executable, server_script], cwd=game_dir)
                except Exception as e:
                    print(f"[ERROR] Failed to launch game server: {e}")
                    conn.send(json.dumps({"status":"error","msg":"Failed to launch game server."}).encode())
                    continue

                # Broadcast game start info
                players = room_info.get("members", [])
                game_start_msg = json.dumps({
                    "type": "start_game",
                    "game_host": GAME_HOST,
                    "game_port": GAME_PORT,
                    "room_name": room_name,
                    "game_id": game_id,
                    "players": players,
                })

                with connection_lock:
                    for p in players:
                        listener_key = f"{p}_listener"
                        if listener_key in client_connections:
                            try:
                                client_connections[listener_key].send(game_start_msg.encode())
                            except Exception as e:
                                print(f"[ERROR] Notify {p} failed: {e}")
                                if listener_key in client_connections:
                                    del client_connections[listener_key]

                conn.send(json.dumps({"status": "ok", "msg": "Game started"}).encode())

            elif cmd == "upload_game":
                # 1. Read Header Info
                file_name = msg.get("file_name")
                file_size = msg.get("file_size")
                
                # Tell Client ready to receive
                conn.send("READY".encode())

                # 2. Receive File
                save_path = os.path.join("games_repo", file_name)
                received_size = 0
                
                # Ensure games_repo exists
                if not os.path.exists("games_repo"):
                    os.makedirs("games_repo")

                with open(save_path, 'wb') as f:
                    while received_size < file_size:
                        # Calculate remaining size to avoid over-reading
                        chunk_size = min(4096, file_size - received_size)
                        data_chunk = conn.recv(chunk_size)
                        if not data_chunk:
                            break
                        f.write(data_chunk)
                        received_size += len(data_chunk)
                
                print(f"[SYSTEM] Received {file_name} from {addr}")

                # 3. Validation and Registration (Modified: unzip to permanent dir)
                try:
                    # Read zip content without extracting first
                    with zipfile.ZipFile(save_path, 'r') as zip_ref:
                        # Find manifest.json
                        if "manifest.json" not in zip_ref.namelist():
                             conn.send(json.dumps({"status": "error", "msg": "Invalid Game: No manifest.json found."}).encode())
                             continue
                        
                        with zip_ref.open("manifest.json") as mf:
                            manifest = json.load(mf)
                    
                    game_id = manifest.get("game_id")
                    new_version = manifest.get("version", "0.0.0")
                    if not game_id:
                         conn.send(json.dumps({"status": "error", "msg": "Manifest missing 'game_id'"}).encode())
                         continue

                    # 1. Define old game directory path
                    current_game_dir = os.path.join("games_repo", game_id)
                    old_manifest_path = os.path.join(current_game_dir, "manifest.json")
                    
                    # 2. If old file exists, read its version
                    if os.path.exists(old_manifest_path):
                        try:
                            with open(old_manifest_path, 'r') as f:
                                old_manifest = json.load(f)
                            old_version = old_manifest.get("version", "0.0.0")
                            
                            # 3. Compare versions: If new <= old, reject upload
                            if new_version <= old_version:
                                msg = f"Upload rejected: Version {new_version} is not greater than server version {old_version}."
                                print(f"[SYSTEM] {msg}")
                                conn.send(json.dumps({"status": "error", "msg": msg}).encode())
                                
                                # Important: Delete received zip and skip extraction
                                os.remove(save_path) 
                                continue 
                        except:
                            # If reading old file fails, proceed to overwrite
                            pass

                    # --- [Critical] Extract to games_repo/{game_id} ---
                    game_dir = os.path.join("games_repo", game_id)
                    if os.path.exists(game_dir):
                        shutil.rmtree(game_dir) # Overwrite old version
                    os.makedirs(game_dir)
                    
                    with zipfile.ZipFile(save_path, 'r') as zip_ref:
                        zip_ref.extractall(game_dir)

                    # Add file info
                    manifest["file_name"] = file_name
                    manifest["file_size"] = file_size
                    manifest["uploader"] = current_user or "anonymous"

                    # Write to DB
                    db_resp = db_request({
                        "cmd": "update_game_info", 
                        "game_id": game_id,
                        "info": manifest
                    })
                    
                    if db_resp["status"] == "ok":
                        msg = f"Game '{manifest.get('name')}' v{manifest.get('version')} uploaded & installed."
                        conn.send(json.dumps({"status": "ok", "msg": msg}).encode())
                    else:
                        conn.send(json.dumps({"status": "error", "msg": "DB update failed"}).encode())

                except Exception as e:
                    print(f"[ERROR] Upload process failed: {e}")
                    conn.send(json.dumps({"status": "error", "msg": str(e)}).encode())

            elif cmd == "get_store_list":
                resp = db_request({"cmd": "get_store_list"})
                conn.send(json.dumps(resp).encode())
            
            elif cmd == "delete_game":
                game_id = msg.get("game_id")
                # 1. Verify ownership via DB
                store_resp = db_request({"cmd": "get_store_list"})
                games = store_resp.get("games", [])
                target_game = next((g for g in games if g["game_id"] == game_id), None)
                
                if not target_game:
                    conn.send(json.dumps({"status": "error", "msg": "Game not found"}).encode())
                elif target_game.get("uploader") != current_user:
                     conn.send(json.dumps({"status": "error", "msg": "Permission denied: You are not the owner."}).encode())
                else:
                    # 2. Remove from DB
                    db_resp = db_request({"cmd": "delete_game", "game_id": game_id})
                    if db_resp["status"] == "ok":
                        # 3. Remove files from server
                        file_name = target_game.get("file_name")
                        # 4. Remove file from games_repo
                        zip_path = os.path.join("games_repo", file_name)
                        game_dir = os.path.join("games_repo", game_id)
                        
                        try:
                            if os.path.exists(zip_path): os.remove(zip_path) # Though we delete zip after extract, check just in case
                            if os.path.exists(game_dir): shutil.rmtree(game_dir)
                            conn.send(json.dumps({"status": "ok", "msg": f"Game {game_id} deleted."}).encode())
                        except Exception as e:
                             conn.send(json.dumps({"status": "error", "msg": f"DB deleted but file error: {e}"}).encode())
                    else:
                        conn.send(json.dumps(db_resp).encode())

            
            elif cmd == "download_game":
                game_id = msg.get("game_id")
                # 1. Query DB for filename
                store_resp = db_request({"cmd": "get_store_list"})
                games = store_resp.get("games", [])
                target_game = next((g for g in games if g["game_id"] == game_id), None)
                
                if not target_game:
                    conn.send(json.dumps({"status": "error", "msg": "Game not found"}).encode())
                    continue
                    
                file_name = target_game.get("file_name")
                file_path = os.path.join("games_repo", file_name)
                
                if not os.path.exists(file_path):
                    conn.send(json.dumps({"status": "error", "msg": "Game file missing on server"}).encode())
                    continue
                    
                file_size = os.path.getsize(file_path)
                
                # 2. Send Header
                header = {
                    "status": "ok",
                    "file_name": file_name,
                    "file_size": file_size,
                    "game_info": target_game
                }
                conn.send(json.dumps(header).encode())
                
                # Wait for Client Ready
                ack = conn.recv(1024).decode()
                if "READY" not in ack:
                    print(f"[SYSTEM] Download cancelled by client")
                    continue
                    
                # 3. Send File
                print(f"[SYSTEM] Sending {file_name} to {addr}...")
                with open(file_path, 'rb') as f:
                    while True:
                        bytes_read = f.read(4096)
                        if not bytes_read:
                            break
                        conn.sendall(bytes_read)
                print(f"[SYSTEM] Sent {file_name} complete.")

            elif cmd == "get_game_details":
                game_id = msg.get("game_id")
                resp = db_request({"cmd": "get_game_details", "game_id": game_id})
                conn.send(json.dumps(resp).encode())

            elif cmd == "add_review":
                # Forward all parameters
                resp = db_request(msg) 
                conn.send(json.dumps(resp).encode())

            elif cmd == "exit":
                if current_user:
                    db_request(
                        {"cmd": "set_online", "user": current_user, "online": False}
                    )
                    db_request({"cmd": "leave_room", "user": current_user})
                    # Remove client connection record
                    with connection_lock:
                        if current_user in client_connections:
                            del client_connections[current_user]
                    current_user = None
                conn.send(json.dumps({"status": "ok", "msg": "Goodbye!"}).encode())
                break

            else:
                conn.send(
                    json.dumps({"status": "error", "msg": "Unknown command"}).encode()
                )

        except Exception as e:
            print(f"[ERROR] {addr}: {e}")
            break

    # Cleanup client connection
    if current_user:
        with connection_lock:
            if current_user in client_connections:
                del client_connections[current_user]
            # Also cleanup listener connection
            listener_key = f"{current_user}_listener"
            if listener_key in client_connections:
                del client_connections[listener_key]
        db_request({"cmd": "set_online", "user": current_user, "online": False, "role": current_role})
        db_request({"cmd": "leave_room", "user": current_user})

    conn.close()
    print(f"[DISCONNECTED] {addr}")


def admin_console(server_socket):
    global server_running
    while True:
        cmd = input()
        if cmd.strip().lower() in ("shutdown", "s"):
            print("[SYSTEM] Shutting down server...")
            server_running = False
            server_socket.close()
            os._exit(0)


def main():
    _ = connect_db_server()  # Test DB connection
    global server_running
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[SYSTEM] Server listening on {HOST}:{PORT}")

    resp = db_request({"cmd": "list"})
    if resp["status"] == "ok":
        print(f"[SYSTEM] {len(resp['users'])} registered users loaded.")
    else:
        print("[SYSTEM] Failed to load user list.")

    print("Type 'shutdown' to safely close the server.")

    threading.Thread(target=admin_console, args=(server,), daemon=True).start()

    try:
        while server_running:
            try:
                conn, addr = server.accept()
                threading.Thread(target=handle_client, args=(conn, addr)).start()
            except OSError:
                break
    finally:
        pass


if __name__ == "__main__":
    main()