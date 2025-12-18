# Online Game Platform (Network Programming HW3)

A multiplayer game platform supporting **GUI (Pygame)** and **CLI (Command Line)** games, complete with a developer ecosystem, version control, and social features.

## Prerequisites

* **OS**: Windows (Recommended for best CLI window management)
* **Python**: 3.8+
* **Libraries**:

    ```bash
    pip install pygame
    ```

---

## Quick Start (Initialization)

Before testing, please execute these scripts to clean the environment and generate test assets.

1. **Open a terminal in the project root.**

2. **Clean previous data** (Database, Repositories, Logs):

    ```bash
    python clean_env.py
    ```

3. **Generate Test Games** (Creates `guess_num_v1` and `guess_num_v2`):

    ```bash
    python prepare_demo.py
    ```

---

## System Launch Order

Please open **3 separate terminals** and run the following commands in order:

### Terminal 1: Database Server

```bash
python db_server.py
```

### Terminal 2: Lobby Server

```bash
python lobby_server.py
```

### Terminal 3,4,5: Main Client

```bash
python main_client.py
```

---

## Demo Walkthrough

### Scenario A: Developer Workflow (Uploading a Game)

1. On Client, select `2. Developer Mode`
2. Register a new account (e.g., dev1 / 123)
3. Login
4. Select 3. Upload/Update Project
5. Enter the path for Version 1.0: `games/guess_num_v1`

### Scenario B: Player Workflow (Downloading & Playing)

1. Open a new Client (or logout from Dev)
2. Select `1. Player Mode`
3. Register a player account (e.g. p1 / 123)
4. Login
5. Select `3. View game store`
6. You should see: `1. Guess Number (v1.0.0) - [Download]`
7. Enter `1` to download. Status changes to `[Installed]`
8. eturn to Main Menu.
9. Select `1. Create a room` -> Select Game -> Enter Room Name
10. Inside the room: Select `6. Ready (Input y)` and Select `7. Start game`
11. Result: A new console window pops up running the game
12. Note: Type quit in the game window to close it

### Scenario C: Version Control & Auto-Update

1. Switch back to Developer (Terminal 3).
2. Select `3. Upload/Update Project`

3. Enter the path for Version 1.1 (Extreme Edition):Plaintext
4. games/guess_num_v2
Result: Upload success. (Server checks version: 1.1.0 > 1.0.0).

5. Switch back to Player.

6. Go to `3. View game store`

7. You should see: `1. Guess Number (v1.1.0) - [Update v1.1.0]`

8. Try to Play without Updating (Soft Lock Test):

9. Go to Room -> Try to Ready.
Result: System detects version mismatch and asks: `Update now? (y/n)`.

10. Select `y` to update.

11. Start Game.
Result: Game window title now shows `"Guess Number v1.1 (EXTREME)"`

### Scenario D: Reviews & Ratings

1. On Player Client, go to `3. View game store`.

2. Select the game to view details.

3. You will see the Description, Author, and Rating.

4. Select `2. Write a Review`.

5. Enter `Rating (1-5)` and a `Comment`.

6. Result: The review appears immediately in the details page.

### Scenario E: Multiplayer (Invitation & Tetris)

1. You can launch **3+ separate main_client.py instances**.

2. P1: Create Room -> 2. Invite player (Invite P2 and P3).

3. P2 & P3: Main Menu -> 6. Manage invitations -> Accept.

4. All: Ready -> Start.

5. Result: Tetris game launches. You will see 2 small opponent boards on the right side if 3 players are playing.

### Scenario F: Delete Game (Developer Only)

1. Switch back to Developer.
2. Select `4. Remove Game`.
3. Enter the `Game ID` (e.g., `guess_num_v1`).
4. Confirm with `y`.
5. Result: Game is removed from Store and Database.

