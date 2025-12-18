import os
import shutil
import json

# --- Server Template ---
# 修改點：把 send 分開送 改成 合併送
SERVER_TEMPLATE = """# -*- coding: utf-8 -*-
import socket, threading, random, os, sys, time

HOST = "0.0.0.0"
PORT = int(os.environ.get("GAME_PORT", 60001))
RANGE_MAX = {range_max}
VERSION_NAME = "{ver_name}"

def handle(conn):
    print("Player connected.")
    try:
        low = 1
        high = RANGE_MAX
        target = random.randint(low, high)
        
        # [初始訊息] Welcome + 第一次提示
        # 注意：結尾不要換行，因為 Client 的 input() 會自己停在那
        conn.send(f"Welcome to {{VERSION_NAME}}!\\nGuess ({{low}}-{{high}}): ".encode())
        
        while True:
            d = conn.recv(1024).decode().strip()
            if not d: break
            
            if not d.isdigit(): 
                # 錯誤提示 + 重複顯示範圍
                conn.send(f"Numbers only!\\nGuess ({{low}}-{{high}}): ".encode())
                continue
                
            g = int(d)
            
            if g == target:
                conn.send(f"BINGO! The number was {{target}}.\\nGame Over.".encode())
                break
            elif g < target:
                if g >= low: low = g + 1
                # [回應] 判定結果 + 下一次提示 (合併傳送)
                conn.send(f"Too Low!\\nGuess ({{low}}-{{high}}): ".encode())
            elif g > target:
                if g <= high: high = g - 1
                # [回應] 判定結果 + 下一次提示 (合併傳送)
                conn.send(f"Too High!\\nGuess ({{low}}-{{high}}): ".encode())
                
    except Exception as e:
        print(e)
    finally:
        try: conn.close()
        except: pass
        print("Game Over. Shutting down in 3s...")
        threading.Timer(3.0, lambda: os._exit(0)).start()

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try: s.bind((HOST, PORT))
    except: return
    s.listen()
    print(f"Server ({{VERSION_NAME}}) on {{PORT}}")
    threading.Timer(60.0, lambda: os._exit(0)).start()
    while True:
        try:
            c, _ = s.accept()
            threading.Thread(target=handle, args=(c,)).start()
        except: break

if __name__ == "__main__": main()
"""

def create_v1():
    src = "template"
    dst = os.path.join("games", "guess_num_v1")
    
    if not os.path.exists(src):
        print("[Error] 'template' folder missing.")
        return False

    if os.path.exists(dst): shutil.rmtree(dst)
    shutil.copytree(src, dst)
    
    # Manifest v1
    manifest_path = os.path.join(dst, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["game_id"] = "guess_num_01"
    data["name"] = "Guess Number"
    data["version"] = "1.0.0"
    data["min_players"] = 1
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    # Server v1 (範圍 1-100)
    code = SERVER_TEMPLATE.format(range_max=100, ver_name="Guess Number v1.0 (Standard)")
    with open(os.path.join(dst, "game_server.py"), "w", encoding="utf-8") as f:
        f.write(code)
    
    print(f"[Created] {dst} (v1.0.0)")
    return True

def create_v2():
    src = "template" # 直接從 template 複製最新版 client
    dst = os.path.join("games", "guess_num_v2")
    
    if os.path.exists(dst): shutil.rmtree(dst)
    shutil.copytree(src, dst)
    
    # Manifest v2
    manifest_path = os.path.join(dst, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["game_id"] = "guess_num_01"
    data["name"] = "Guess Number"
    data["version"] = "1.1.0"
    data["min_players"] = 1
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    # Server v2 (範圍 1-1000)
    code = SERVER_TEMPLATE.format(range_max=1000, ver_name="Guess Number v1.1 (EXTREME 1-1000)")
    with open(os.path.join(dst, "game_server.py"), "w", encoding="utf-8") as f:
        f.write(code)

    print(f"[Created] {dst} (v1.1.0)")

if __name__ == "__main__":
    if create_v1():
        create_v2()
    print("\nReady for Demo!")