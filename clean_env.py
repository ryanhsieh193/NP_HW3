import os
import shutil
import time
import stat
import sys

def kill_python_processes():
    """強制結束除了自己以外的所有 python.exe 進程"""
    current_pid = os.getpid()
    print(f"[System] Killing all Python processes (except PID {current_pid})...")
    
    # 強制殺死程序
    os.system(f'taskkill /F /FI "PID ne {current_pid}" /IM python.exe 2>nul')
    
    # [關鍵] 增加等待時間，讓 Windows 有時間釋放檔案鎖定
    print("[System] Waiting for Windows to release file locks...")
    time.sleep(2) 

def on_rm_error(func, path, exc_info):
    """
    處理 Windows 無法刪除唯讀檔案的錯誤。
    如果刪除失敗，嘗試更改權限後再刪一次。
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
        print(f"   -> [Force Deleted] {path}")
    except Exception as e:
        print(f"   -> [Skip] Still cannot delete {path}: {e}")

def remove_folder(path):
    if os.path.exists(path):
        print(f"[Deleting] Folder: {path}...")
        try:
            # onerror 參數用於處理權限問題
            shutil.rmtree(path, onerror=on_rm_error)
            print(f"[Deleted] Folder: {path}")
        except Exception as e:
            print(f"[Error] Failed to delete {path}: {e}")

def remove_file(path):
    if os.path.exists(path):
        try:
            os.chmod(path, stat.S_IWRITE) # 確保有寫入權限
            os.remove(path)
            print(f"[Deleted] File: {path}")
        except Exception as e:
            print(f"[Error] Failed to delete {path}: {e}")

def main():
    print("=== ULTRA CLEAN ENVIRONMENT ===")
    
    # 1. 殺死進程
    kill_python_processes()

    # 2. 定義要刪除的 "舊垃圾" 檔案清單
    garbage_files = [
        "db.json",
        "store_client.py",
        "developer_client.py",
        "test_launcher.py",
        "game_client.py", # 如果有殘留
        "game_server.py", # 如果有殘留
    ]

    # 3. 定義要刪除的資料夾
    garbage_folders = [
        "games_repo",       # Server 端的倉庫
        "downloads",        # Client 端的下載
        "__pycache__",
        "games/__pycache__",
        "others"
    ]

    # 執行刪除檔案
    for f in garbage_files:
        remove_file(f)

    # 執行刪除資料夾
    for d in garbage_folders:
        remove_folder(d)

    print("\n=== Environment Reset Complete! ===")
    print("Garbage files should be gone now.")

if __name__ == "__main__":
    main()