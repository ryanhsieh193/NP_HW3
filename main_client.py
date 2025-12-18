# main_client.py
import socket
import json
import getpass
import os
import shutil
import sys
import threading
import subprocess
import zipfile
import io
import time
from client_config import LOBBY_HOST, LOBBY_PORT

HOST = LOBBY_HOST
PORT = LOBBY_PORT

# --- 全域變數 (Player 用) ---
game_started = False
game_event = threading.Event()
game_process_event = threading.Event()
game_info = {}
listen_socket = None

# ============================
#      共用工具函式
# ============================

def send_and_recv(sock, msg, silent=False):
    try:
        if not silent: pass # print(f"[DEBUG] Sending: {msg}")
        sock.send(json.dumps(msg).encode())
        if not silent: pass # print("[DEBUG] Waiting for response...")
        while True:


            data = sock.recv(1024).decode()
            if not data:
                raise ConnectionResetError("Server closed connection")

            try:
                temp_json = json.loads(data)
                # 忽略遊戲開始的廣播，避免干擾同步回應
                if temp_json.get("type") == "start_game":
                    continue
            except json.JSONDecodeError:
                pass
            break
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        if not silent:
            print(f"\n[ERROR] Connection Error: {e}")
        raise

    if silent:
        return data

    pass # print(f"[DEBUG] Received raw: {data}")
    
    # 統一顯示邏輯
    try:

        resp = json.loads(data)

        if "room_info" in resp:
            info = resp["room_info"]
            ready_status = [
                f"{u}({'ready' if info['ready'].get(u, False) else 'not ready'})"
                for u in info["members"]
            ]
            print("\n--- ROOM INFO ---")
            print(f"Room Name: {info.get('room_name', 'Unknown')}")
            print(f"Host: {info.get('host', 'Unknown')}")
            print(f"Members: {', '.join(ready_status)}")
            print(f"Game: {info.get('game_id', 'Unknown')}")
            print(f"Private: {'Yes' if info.get('private') else 'No'}")
            print(f"Open: {'Yes' if info.get('open') else 'No'}")
        elif "rooms" in resp:
            rooms = resp.get("rooms", [])
            if rooms:
                print("\n--- PUBLIC ROOMS ---")
                for i, room in enumerate(rooms, 1):
                    status = "Open" if room.get("open", False) else "Closed"
                    print(f"{i}. {room['name']} (Host: {room['host']}, {status})")
            else:
                print("\nNo public rooms available.")
        elif "users" in resp:
            users = resp.get("users", [])
            if users:
                print("\n--- ONLINE USERS ---")
                for i, user in enumerate(users, 1):
                    print(f"{i}. {user}")
            else:
                print("\nNo users online.")
        elif "invitations" in resp: # [新增] 支援邀請列表顯示
            invites = resp.get("invitations", [])
            # 這裡只做純資料回傳，顯示邏輯在 handle_invitations
        else:
            msg_text = resp.get("msg", data)
            status = resp.get("status", "unknown")
            if status == "error":
                print(f"\n[Server Error] {msg_text}")
            elif "success" in msg_text.lower() or status == "ok":
                print(f"\n[Server] ✓ {msg_text}")
            else:
                print(f"\n[Server] {msg_text}")
    except json.JSONDecodeError:
        print(f"\n[Server] {data}")
    return data

def get_yes_no(prompt):
    while True:
        choice = input(prompt).strip().lower()
        if choice == 'y': return True
        elif choice == 'n': return False
        print("\nInvalid input.\n")

# ============================
#      Developer 功能模組
# ============================

def zip_game(game_dir_path):
    if not os.path.exists(game_dir_path):
        print("Game directory not found.")
        return None
    if not os.path.exists(os.path.join(game_dir_path, "manifest.json")):
        print("Error: manifest.json not found in directory.")
        return None
    game_name = os.path.basename(os.path.normpath(game_dir_path))
    zip_filename = f"{game_name}" 
    print(f"Zipping {game_dir_path}...")
    output_path = shutil.make_archive(zip_filename, 'zip', game_dir_path)
    return output_path

def upload_game(sock, game_dir, username):
    # 1. Select / Input Game Directory
    if not game_dir:
        if os.path.exists("games"):
            projects = [d for d in os.listdir("games") if os.path.isdir(os.path.join("games", d))]
            if projects:
                print("\nAvailable Local Projects:")
                for i, p in enumerate(projects, 1):
                    # Try to read name from manifest
                    p_name = p
                    try:
                        with open(os.path.join("games", p, "manifest.json"), 'r') as f:
                            p_name = json.load(f).get("name", p)
                    except: pass
                    print(f"{i}. {p_name} ({p})")
                
                sel = input("Select project (number) or enter path: ").strip()
                if sel.isdigit():
                    idx = int(sel) - 1
                    if 0 <= idx < len(projects):
                        game_dir = os.path.join("games", projects[idx])
                else:
                    game_dir = sel
        if not game_dir:
            game_dir = input("Enter game directory path: ").strip()
            
    if not os.path.exists(game_dir):
        print("Directory not found.")
        return

    # 2. Check Manifest / New Game Logic
    manifest_path = os.path.join(game_dir, "manifest.json")
    manifest = {}
    
    is_new = False
    if not os.path.exists(manifest_path):
        print(f"\n[Info] 'manifest.json' not found in {game_dir}.")
        is_new = get_yes_no("Is this a new game? (y/n): ")
        if not is_new:
            print("Upload aborted. Missing manifest.")
            return
    else:
        try:
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            # Version Auto-Increment Logic
            cur_ver = manifest.get("version", "1.0.0")
            print(f"\nCurrent Version: {cur_ver}")
            if get_yes_no("Is this an update? (Auto-increment version) (y/n): "):
                try:
                    parts = list(map(int, cur_ver.split('.')))
                    if len(parts) == 3:
                        parts[2] += 1
                        new_ver = ".".join(map(str, parts))
                        manifest["version"] = new_ver
                        print(f"Version bumped to: {new_ver}")
                        # Update manifest file
                        with open(manifest_path, 'w') as f:
                            json.dump(manifest, f, indent=4)
                    else: print("Version format not x.y.z, skipping auto-increment.")
                except: print("Version parse error, skipping auto-increment.")
        except Exception as e:
            print(f"Error reading manifest: {e}")
            return

    # 3. Metadata Input for New Game
    if is_new:
        print("\n--- Enter Game Metadata ---")
        game_id = os.path.basename(os.path.normpath(game_dir)).lower().replace(" ", "_")
        manifest["game_id"] = input(f"Game ID [{game_id}]: ").strip() or game_id
        manifest["name"] = input("Game Display Name: ").strip()
        manifest["description"] = input("Description: ").strip()
        manifest["type"] = input("Type (cli/gui) [gui]: ").strip() or "gui"
        manifest["version"] = "1.0.0"
        
        # Players
        try:
            manifest["min_players"] = int(input("Min Players [1]: ").strip() or "1")
            manifest["max_players"] = int(input("Max Players [2]: ").strip() or "2")
        except:
             manifest["min_players"] = 1
             manifest["max_players"] = 2
             
        # Entries
        manifest["client_entry"] = input("Client Script [game_client.py]: ").strip() or "game_client.py"
        manifest["server_entry"] = input("Server Script [game_server.py]: ").strip() or "game_server.py"

        # Write manifest
        try:
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=4)
            print("[Success] manifest.json created.")
        except Exception as e:
            print(f"Failed to write manifest: {e}")
            return

    # 4. Proceed with Zip and Upload (Original Logic)
    zip_path = zip_game(game_dir)
    if not zip_path: return

    file_size = os.path.getsize(zip_path)
    file_name = os.path.basename(zip_path)
    print(f"Uploading {file_name} ({file_size} bytes)...")

    req = {
        "cmd": "upload_game",
        "file_name": file_name,
        "file_size": file_size,
        "user": username 
    }
    sock.send(json.dumps(req).encode())
    
    ack = sock.recv(1024).decode()
    if "READY" not in ack:
        print(f"Server rejected upload: {ack}")
        os.remove(zip_path)
        return

    with open(zip_path, 'rb') as f:
        while True:
            bytes_read = f.read(4096)
            if not bytes_read: break
            sock.sendall(bytes_read)
    
    print("File sent. Waiting for confirmation...")
    resp = json.loads(sock.recv(1024).decode())
    if resp['status'] == 'ok':
        print(f"SUCCESS: {resp['msg']}")
    else:
        print(f"FAILED: {resp.get('msg')}")
    os.remove(zip_path)


def remove_game(sock, username):
    """Developer: Remove a game from the store (Interactive)"""
    print("\n--- Remove Game ---")
    try:
        data = send_and_recv(sock, {"cmd": "get_store_list"}, silent=True)
        resp = json.loads(data)
        all_games = resp.get("games", [])
        
        # Filter games owned by this user
        my_games = [g for g in all_games if g.get("uploader") == username]
        
        if not my_games:
            print("You have no uploaded games to remove.")
            return

        print("\nSelect a game to remove:")
        for i, g in enumerate(my_games, 1):
            print(f"{i}. {g['name']} ({g['game_id']}) - v{g['version']}")
        print("c. Cancel")

        choice = input("Enter choice: ").strip()
        if choice.lower() == 'c': return
        
        if not choice.isdigit():
            print("Invalid input.")
            return
            
        idx = int(choice) - 1
        if 0 <= idx < len(my_games):
            target_game = my_games[idx]
            game_id = target_game["game_id"]
            
            confirm = input(f"Are you sure you want to permanently delete '{target_game['name']}' ({game_id})? (y/n): ")
            if confirm.lower() == 'y':
                req = {"cmd": "delete_game", "game_id": game_id, "user": username}
                send_and_recv(sock, req)
        else:
            print("Invalid selection.")

    except Exception as e:
        print(f"[Error] Remove failed: {e}")


# --- [新增] 建立新專案 ---
def create_new_project():
    print("\n--- Create New Game Project ---")
    game_name = input("Enter Game Name (e.g. Super Tank): ")
    game_id = input("Enter Game ID (e.g. super_tank_01): ")
    
    target_dir = os.path.join("games", game_id)
    if os.path.exists(target_dir):
        print(f"[Error] Directory {target_dir} already exists.")
        return

    if not os.path.exists("template"):
        print("[Error] 'template' folder missing. Cannot scaffold.")
        return

    try:
        shutil.copytree("template", target_dir)
        
        # 修改 manifest.json
        manifest_path = os.path.join(target_dir, "manifest.json")
        with open(manifest_path, "r") as f:
            data = json.load(f)
        
        data["game_id"] = game_id
        data["name"] = game_name
        
        with open(manifest_path, "w") as f:
            json.dump(data, f, indent=4)
            
        print(f"[Success] Project created at {target_dir}")
    except Exception as e:
        print(f"[Error] Create failed: {e}")

# --- [新增] 本地測試 (Dry Run) ---
def run_local_test():
    print("\n--- Local Test (Dry Run) ---")
    if not os.path.exists("games"):
        print("No 'games' directory found.")
        return

    # 列出本地專案
    projects = [d for d in os.listdir("games") if os.path.isdir(os.path.join("games", d))]
    if not projects:
        print("No projects found in games/.")
        return

    for i, p in enumerate(projects, 1):
        print(f"{i}. {p}")
    
    sel = input("Select project to test: ")
    if not sel.isdigit(): return
    idx = int(sel) - 1
    if idx < 0 or idx >= len(projects): return
    
    game_id = projects[idx]
    base_dir = os.path.join("games", game_id)
    manifest_path = os.path.join(base_dir, "manifest.json")
    
    if not os.path.exists(manifest_path):
        print("No manifest.json found.")
        return

    with open(manifest_path, "r") as f:
        manifest = json.load(f)
    
    server_script = manifest.get("server_entry")
    client_script = manifest.get("client_entry")

    print(f"\n[Test] Launching {manifest.get('name')} locally...")
    print("Press Ctrl+C in this terminal to stop the test.")

    procs = []
    try:
        # 1. 啟動 Server
        print("[Test] Starting Server...")
        srv_proc = subprocess.Popen([sys.executable, server_script], cwd=base_dir)
        procs.append(srv_proc)
        time.sleep(1) # 等 server 起來

        creation_flags = 0
        if os.name == 'nt':
            creation_flags = subprocess.CREATE_NEW_CONSOLE

        # 2. 啟動 Client 1
        print("[Test] Starting Client 1...")
        env1 = os.environ.copy()
        env1["GAME_PLAYER"] = "Dev_P1"
        env1["SDL_VIDEO_WINDOW_POS"] = "100,100"
        c1 = subprocess.Popen([sys.executable, client_script], env=env1, cwd=base_dir, creationflags=creation_flags)
        procs.append(c1)

        # 3. 啟動 Client 2
        print("[Test] Starting Client 2...")
        env2 = os.environ.copy()
        env2["GAME_PLAYER"] = "Dev_P2"
        env2["SDL_VIDEO_WINDOW_POS"] = "600,100"
        c2 = subprocess.Popen([sys.executable, client_script], env=env2, cwd=base_dir, creationflags=creation_flags)
        procs.append(c2)

        # 等待直到有人關閉
        c1.wait()
        c2.wait()
    except KeyboardInterrupt:
        print("\n[Test] Stopping test...")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        print("[Test] Environment cleaned up.")

def developer_menu(sock, username):
    while True:
        print(f"\n--- DEVELOPER MENU ({username}) ---")
        print("1. Create New Project (from Template)") # [新增]
        print("2. Test Project Locally")                # [新增]
        print("3. Upload/Update Project")
        print("4. Remove Game")
        print("5. Logout")
        print("6. Exit")
        
        choice = input("Enter choice: ")
        
        if choice == "1":
            create_new_project()
        elif choice == "2":
            run_local_test()
        elif choice == "3":
            upload_game(sock, None, username)


        elif choice == "4":
            remove_game(sock, username)
        elif choice == "5":
            send_and_recv(sock, {"cmd": "logout"}, silent=True)
            return
        elif choice == "6":

            try:
                send_and_recv(sock, {"cmd": "logout"}, silent=True)
            except:
                pass
            sock.close()
            sys.exit()
        else:
            print("Invalid choice.")

# ============================
#      Player 功能模組
# ============================

def ensure_download_dir(username):
    base = os.path.join("downloads", username)
    if not os.path.exists(base): os.makedirs(base)
    return base

def download_game(sock, game_id, username):
    print(f"\n[System] Requesting download for {game_id}...")
    req = {"cmd": "download_game", "game_id": game_id}
    sock.send(json.dumps(req).encode())
    
    header_data = sock.recv(1024).decode()
    try:
        header = json.loads(header_data)
    except:
        print("[Error] Invalid header")
        return

    if header["status"] != "ok":
        print(f"[Error] Server refused: {header.get('msg')}")
        return

    file_size = header["file_size"]
    game_name = header["game_info"].get("name", game_id)
    print(f"[System] Downloading {game_name} ({file_size} bytes)...")
    
    sock.send("READY".encode())

    received_size = 0
    buffer = io.BytesIO()
    while received_size < file_size:
        chunk_size = min(4096, file_size - received_size)
        data = sock.recv(chunk_size)
        if not data: break
        buffer.write(data)
        received_size += len(data)
        sys.stdout.write(f"\rProgress: {int(received_size/file_size*100)}%")
        sys.stdout.flush()
    
    print("\n[System] Extracting...")
    user_download_dir = ensure_download_dir(username)
    game_install_dir = os.path.join(user_download_dir, game_id)
    
    if os.path.exists(game_install_dir): shutil.rmtree(game_install_dir)
    os.makedirs(game_install_dir)
    
    try:
        with zipfile.ZipFile(buffer) as zf:
            zf.extractall(game_install_dir)
        print(f"[System] Installed at {game_install_dir}")
    except Exception as e:
        print(f"[Error] Install failed: {e}")

def show_game_details(sock, username, game_id):
    """顯示遊戲詳情與評論頁面"""
    while True:
        try:
            # 獲取詳情
            data = send_and_recv(sock, {"cmd": "get_game_details", "game_id": game_id}, silent=True)
            resp = json.loads(data)
            
            if resp.get("status") != "ok":
                print(f"[Error] {resp.get('msg')}")
                return

            info = resp.get("game_info", {})
            reviews = info.get("reviews", [])
            
            # 計算平均分
            avg_rating = 0
            if reviews:
                total = sum(r["rating"] for r in reviews)
                avg_rating = total / len(reviews)
            
            os.system('cls' if os.name == 'nt' else 'clear')
            print("\n=================================")
            print(f"   {info.get('name')} (v{info.get('version')})")
            print("=================================")
            print(f"Description: {info.get('description', 'No description.')}")
            print(f"Author:      {info.get('uploader', 'Unknown')}")
            print(f"Rating:      ★ {avg_rating:.1f}  ({len(reviews)} reviews)")
            print("-" * 33)
            print("REVIEWS:")
            if not reviews:
                print("  No reviews yet.")
            else:
                # 只顯示最近 5 筆
                for r in reviews[-5:]:
                    stars = "★" * r['rating']
                    print(f"  {r['user']:<10}: {stars:<5} | {r['comment']}")
            print("=================================")
            
            # 檢查本地狀態 (用來顯示 Download 還是 Update)
            local_path = os.path.join("downloads", username, game_id)
            local_manifest = os.path.join(local_path, "manifest.json")
            btn_text = "Download"
            if os.path.exists(local_manifest):
                try:
                    with open(local_manifest, 'r') as f:
                        lv = json.load(f).get("version", "0.0.0")
                    if info.get("version") > lv:
                        btn_text = "Update"
                    else:
                        btn_text = "Re-install" # 或 Installed
                except: pass

            print(f"1. {btn_text} Game")
            print("2. Write a Review")
            print("3. Back to Store")
            
            sel = input("Choice: ")
            
            if sel == "1":
                download_game(sock, game_id, username)
                print("\n[System] Installation complete.")
                input("Press Enter to return to Main Menu...")
                return "back_to_main"
            
            elif sel == "2":
                # 寫評論
                while True:
                    try:
                        r_str = input("Rating (1-5): ")
                        rating = int(r_str)
                        if 1 <= rating <= 5:
                            break
                        print("Please enter 1-5.")
                    except: pass
                
                comment = input("Comment: ")
                send_and_recv(sock, {
                    "cmd": "add_review",
                    "game_id": game_id,
                    "user": username,
                    "rating": rating,
                    "comment": comment
                })
                print("Review submitted!")
                time.sleep(1)
                
            elif sel == "3":
                return # 回上一層
                
        except Exception as e:
            print(f"[Error] {e}")
            return

def view_store(sock, username):
    """瀏覽商城列表"""
    while True:
        try:
            data = send_and_recv(sock, {"cmd": "get_store_list"}, silent=True)
            resp = json.loads(data)
            games = resp.get("games", [])
            
            print("\n=== GAME STORE ===")
            print("0. Back to Main Menu") 
            print("-" * 20)

            if not games:
                print("No games available.")
            else:
                for i, g in enumerate(games, 1):
                    print(f"{i}. {g['name']} (v{g['version']})")
            
            print("-" * 20)
            sel = input("Select a game to view details (Enter number): ")
            if sel == "0": break
            
            if sel.isdigit():
                idx = int(sel) - 1
                if 0 <= idx < len(games):
                    target_game = games[idx]
                    result = show_game_details(sock, username, target_game['game_id'])
                    if result == "back_to_main":
                        break
                else:
                    print("Invalid selection.")
            else:
                print("Invalid input.")
        except Exception as e:
            print(f"[Error] Store error: {e}")
            break

def check_user_room(sock, username):
    try:
        sock.send(json.dumps({"cmd": "get_user_room", "user": username}).encode())
        data = sock.recv(1024).decode()
        if not data: return None
        return json.loads(data).get("room_name")
    except: return None

def handle_invitations(sock, username):
    try:
        sock.send(json.dumps({"cmd": "manage_invitations"}).encode())
        data = sock.recv(1024).decode()
        invitations = json.loads(data).get("invitations", [])

        if not invitations:
            print("\nNo pending invitations.")
            return

        print(f"\nYou have {len(invitations)} pending invitations:")
        for i, room in enumerate(invitations, 1):
            print(f"{i}. {room}")

        sel = input("Enter invitation number to respond (or Enter to skip): ")
        if sel.isdigit():
            idx = int(sel) - 1
            if 0 <= idx < len(invitations):
                room_name = invitations[idx]
                choice = get_yes_no(f"Accept invitation to {room_name}? (y/n): ")
                sock.send(json.dumps({
                    "cmd": "respond_invitation",
                    "user": username,
                    "room_name": room_name,
                    "accept": choice 
                }).encode())
                
                resp_data = sock.recv(1024).decode()
                try:
                    print(f"\n[Server] {json.loads(resp_data).get('msg', resp_data)}")
                except:
                    print(f"\n[Server] {resp_data}")
            else:
                print("Invalid selection.")
    except Exception as e:
        print(f"[ERROR] Manage invitations failed: {e}")

def invite_player(sock, username, current_room):
    resp = send_and_recv(sock, {"cmd": "invite_player", "user": username}, silent=True)
    try:
        users = json.loads(resp).get("available_users", [])
    except: users = []

    if not users:
        print("\nNo available users to invite.")
        return

    print("\nAvailable users to invite:")
    for i, u in enumerate(users, 1):
        print(f"{i}. {u}")

    sel = input("Enter user number to invite (or Enter to skip): ")
    if sel.isdigit():
        idx = int(sel) - 1
        if 0 <= idx < len(users):
            target_user = users[idx]
            send_and_recv(sock, {"cmd": "invite", "user": target_user, "room_name": current_room}, silent=True)
            print("\nInvitation sent.")
        else:
            print("Invalid selection.")
            time.sleep(1)

def listen_for_game_start(main_sock, username):
    global game_started, game_info, listen_socket
    try:
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_socket.connect((HOST, PORT))
        listen_socket.send(json.dumps({"cmd": "_listener", "user": username}).encode())
        listen_socket.settimeout(None)
    except Exception as e:
        print(f"[WARNING] Listener init failed: {e}")
        return

    while True:
        try:
            data = listen_socket.recv(1024).decode()
            if not data: break
            try:
                resp = json.loads(data)
                if resp.get("type") == "start_game":
                    game_info = resp
                    game_started = True
                    game_event.set()
                    game_id = game_info.get("game_id")
                    
                    base_dir = os.path.join("downloads", username, game_id)
                    manifest_path = os.path.join(base_dir, "manifest.json")
                    
                    if not os.path.exists(manifest_path):
                        print(f"[ERROR] Game {game_id} not installed.")
                        continue
                        
                    with open(manifest_path, 'r') as f:
                        manifest = json.load(f)
                    
                    client_script = manifest.get("client_entry")
                    if not client_script:
                        print(f"[ERROR] Manifest missing client_entry.")
                        continue
                    
                    players = game_info.get("players", [])
                    try:
                        idx = players.index(username)
                        pos_x = 100 + (idx * 700) 
                        os.environ['SDL_VIDEO_WINDOW_POS'] = f"{pos_x},100"
                    except: pass
                    
                    print(f"\n[SYSTEM] Launching {manifest.get('name')}...")
                    try:
                        env = subprocess.os.environ.copy()
                        env["GAME_ROOM"] = game_info.get("room_name", "")
                        env["GAME_HOST"] = game_info.get("game_host", "localhost")
                        env["GAME_PORT"] = str(game_info.get("game_port", 60001))
                        env["GAME_PLAYER"] = username
                        game_process_event.set()
                        
                        creation_flags = 0
                        if os.name == 'nt':
                            creation_flags = subprocess.CREATE_NEW_CONSOLE
                        
                        proc = subprocess.Popen(
                            [sys.executable, client_script],
                            env=env, 
                            cwd=base_dir,
                            creationflags=creation_flags
                        )
                        
                        def wait_for_game():
                            proc.wait()
                            game_process_event.clear()
                            print("\n[SYSTEM] Game has ended. Press [Enter] to refresh menu...")
                            try:
                                if listen_socket:
                                    listen_socket.send(json.dumps({
                                        "cmd": "set_ready", "user": username, "ready": False
                                    }).encode())
                            except: pass
                        threading.Thread(target=wait_for_game).start()
                    except Exception as e:
                        print(f"[ERROR] Launch failed: {e}")
                        game_process_event.clear()
            except json.JSONDecodeError: pass
        except (ConnectionResetError, OSError): break

    if listen_socket:
        try: listen_socket.close()
        except: pass

def main_menu(sock, username):
    room_name = None
    while True:
        try:
            if room_name is None:
                room_name = check_user_room(sock, username)
            in_room = room_name is not None

            print("\n--- PLAYER MENU ---")
            if in_room: print(f"Current location: Room {room_name}")
            else: print("Current location: Lobby")

            if not in_room:
                print("1. Create a room")
                print("2. Join room")
                print("3. View game store")
                print("4. List public rooms")
                print("5. List online users")
                print("6. Manage invitations")
                print("7. Logout")
                print("8. Exit")
            else:
                print("1. Leave room")
                print("2. Invite player")
                print("3. View room info")
                print("4. List online users")
                print("5. Manage invitations")
                print("6. Ready")
                print("7. Start game (host only)")
                print("8. Logout")
                print("9. Exit")
            
            choice = input("Enter choice: ")

            if not in_room:
                if choice == "1":
                    print("\nSelect a game for this room:")
                    try:
                        data = send_and_recv(sock, {"cmd": "get_store_list"}, silent=True)
                        games = json.loads(data).get("games", [])
                        if not games:
                            print("No games available.")
                            continue
                        for i, g in enumerate(games, 1):
                            print(f"{i}. {g['name']}")
                        
                        sel = input("Enter game number: ")
                        if not sel.isdigit() or int(sel) < 1 or int(sel) > len(games):
                            print("\nInvalid choice.\n")
                            time.sleep(0.5)
                            continue
                        
                        selected_game_id = games[int(sel)-1]["game_id"]
                        name = input("Enter room name: ")
                        private = get_yes_no("Private room? (y/n): ")
                        
                        data = send_and_recv(sock, {
                            "cmd": "create_room", "room_name": name, 
                            "private": private, "game_id": selected_game_id
                        })
                        if json.loads(data).get("status") == "ok":
                            room_name = name
                        else: room_name = None
                    except Exception as e:
                        print(f"[Error] Create room failed: {e}")
                        room_name = None

                elif choice == "2":
                    try:
                        data = send_and_recv(sock, {"cmd": "list_rooms"}, silent=True)
                        rooms = json.loads(data).get("rooms", [])
                        if not rooms:
                            print("\nNo public rooms.")
                            continue
                        print("\nAvailable Rooms:")
                        for i, r in enumerate(rooms, 1):
                            status = "Open" if r.get("open", False) else "Full"
                            print(f"{i}. {r['name']} (Host: {r['host']}, {status})")
                        
                        sel = input("Enter room number to join: ")
                        if sel.isdigit():
                            idx = int(sel) - 1
                            if 0 <= idx < len(rooms):
                                name = rooms[idx]['name']
                                data = send_and_recv(sock, {"cmd": "join_room", "room_name": name})
                                if json.loads(data).get("status") == "ok":
                                    room_name = name
                            else: print("Invalid room.")
                        else: print("Invalid input.")
                    except: pass

                elif choice == "3": view_store(sock, username)
                elif choice == "4": send_and_recv(sock, {"cmd": "list_rooms"})
                elif choice == "5": send_and_recv(sock, {"cmd": "list", "online_only": True})
                elif choice == "6": handle_invitations(sock, username)
                elif choice == "7": 
                    send_and_recv(sock, {"cmd": "logout"}, silent=True)
                    return
                elif choice == "8": 
                    send_and_recv(sock, {"cmd": "exit"}, silent=True)
                    sock.close()
                    sys.exit()
                else: print("Invalid choice.")
            
            else: # In Room
                if choice == "1":
                    send_and_recv(sock, {"cmd": "leave_room"})
                    room_name = None
                elif choice == "2": invite_player(sock, username, room_name)
                elif choice == "3": send_and_recv(sock, {"cmd": "get_room_info", "user": username})
                elif choice == "4": send_and_recv(sock, {"cmd": "list", "online_only": True})
                elif choice == "5": handle_invitations(sock, username)
                elif choice == "6":
                    try:
                        data = send_and_recv(sock, {"cmd": "get_room_info", "user": username}, silent=True)
                        info = json.loads(data).get("room_info", {})
                        game_id = info.get("game_id")
                        
                        store_data = send_and_recv(sock, {"cmd": "get_store_list"}, silent=True)
                        games_list = json.loads(store_data).get("games", [])
                        server_game_info = next((g for g in games_list if g["game_id"] == game_id), None)
                        
                        if not server_game_info:
                            print("[Error] Game not found on server.")
                            continue

                        server_ver = server_game_info.get("version", "0.0.0")

                        local_path = os.path.join("downloads", username, game_id)
                        local_manifest = os.path.join(local_path, "manifest.json")
                        local_ver = "0.0.0"
                        
                        if os.path.exists(local_manifest):
                            try:
                                with open(local_manifest, 'r') as f:
                                    local_ver = json.load(f).get("version", "0.0.0")
                            except: pass
                        
                        if local_ver < server_ver:
                            print(f"\n[System] VERSION MISMATCH")
                            print(f"Server version: v{server_ver}")
                            print(f"Your version:   v{local_ver}")
                            print("You must update the game to play.")
                            
                            do_update = get_yes_no("Update now? (y/n): ")
                            if do_update:
                                download_game(sock, game_id, username) # 呼叫下載函式進行更新
                                print("\n[Success] Update complete! You can now set ready.")
                                # 更新完不用 continue，讓他也許可以直接按 Ready，或者讓他重按一次比較保險
                            else:
                                print("You cannot ready without updating.")
                            
                            continue # 阻止發送 Ready 指令
                            
                    except Exception as e:
                        print(f"[Error] Version check failed: {e}")
                        continue
                    # ------------------------------------

                    # 如果版本檢查通過，才執行原本的 Ready 邏輯
                    state = get_yes_no("Ready? (y/n): ")
                    try:
                        send_and_recv(sock, {"cmd": "set_ready", "user": username, "ready": state})
                    except: pass
                elif choice == "7":
                    data = send_and_recv(sock, {"cmd": "start_game", "user": username})
                    if json.loads(data).get("status") == "ok":
                        print("Waiting for game start...")
                        if game_event.wait(timeout=5):
                            game_process_event.wait()
                            while game_process_event.is_set(): time.sleep(0.5)
                            print("\nWelcome back to lobby!")
                        else: print("Start timeout.")
                elif choice == "8":
                    send_and_recv(sock, {"cmd": "logout"}, silent=True)
                    return
                elif choice == "9":
                    send_and_recv(sock, {"cmd": "exit"}, silent=True)
                    sock.close()
                    sys.exit()
                else: print("Invalid choice.")
        except Exception as e:
            print(f"[ERROR] {e}")
            return

# ============================
#      主程式入口
# ============================

def start_system():
    while True:
        print("\n=== GAME SYSTEM LAUNCHER ===")
        print("1. Player Mode (Play Games)")
        print("2. Developer Mode (Upload Games)")
        print("3. Exit")
        
        role_choice = input("Select Identity: ").strip()
        
        if role_choice == "3":
            sys.exit()
            
        if role_choice not in ["1", "2"]:
            print("Invalid selection.")
            continue
            
        role = "player" if role_choice == "1" else "developer"
        role_name = "Player" if role == "player" else "Developer"
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, PORT))
                print(f"\n[{role_name} Mode] Connected to Server.")
                
                while True:
                    print(f"\n--- {role_name.upper()} LOGIN ---")
                    print("1. Register")
                    print("2. Login")
                    print("3. Back to Launcher")
                    
                    auth_choice = input("Choice: ")
                    
                    if auth_choice == "1":
                        u = input("Username: ")
                        p = input("Password: ")
                        send_and_recv(s, {
                            "cmd": "register", 
                            "username": u, 
                            "password": p,
                            "role": role 
                        })

                    elif auth_choice == "2":
                        u = input("Username: ")
                        p = input("Password: ")
                        data = send_and_recv(s, {
                            "cmd": "login", 
                            "username": u, 
                            "password": p,
                            "role": role 
                        })
                        
                        if "success" in data.lower():
                            if role == "player":
                                listen_thread = threading.Thread(
                                    target=listen_for_game_start, args=(s, u), daemon=True
                                )
                                listen_thread.start()
                                main_menu(s, u)
                                game_event.clear()
                            else:
                                developer_menu(s, u)
                            
                            break # Logout後回到Launcher
                            
                    elif auth_choice == "3":
                        break
        except Exception as e:
            print(f"[Error] Connection failed: {e}")
            input("Press Enter to continue...")

if __name__ == "__main__":
    start_system()