import os
import shutil

DEPLOY_DIR = "deploy_package"
FILES_TO_COPY = [
    "db_server.py",
    "lobby_server.py",
    "config.py",
    "clean_env.py", 
    "prepare_demo.py",
    "template" # If scaffold needed
]
DIRS_TO_COPY = [
    "games"
]

if os.path.exists(DEPLOY_DIR):
    shutil.rmtree(DEPLOY_DIR)
os.makedirs(DEPLOY_DIR)

print(f"Packaging files into '{DEPLOY_DIR}'...")

for f in FILES_TO_COPY:
    if os.path.exists(f):
        if os.path.isdir(f):
            shutil.copytree(f, os.path.join(DEPLOY_DIR, f))
        else:
            shutil.copy(f, DEPLOY_DIR)
        print(f"Copied {f}")
    else:
        print(f"Warning: {f} not found.")

for d in DIRS_TO_COPY:
    if os.path.exists(d):
        shutil.copytree(d, os.path.join(DEPLOY_DIR, d))
        print(f"Copied directory {d}")

print("\nPackage created successfully!")
print(f"You can now upload the '{DEPLOY_DIR}' folder to your remote server.")
