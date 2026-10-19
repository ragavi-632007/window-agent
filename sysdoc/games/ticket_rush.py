#!/usr/bin/env python3
"""
Support Bot: Ticket Rush
Terminal arcade runner — dodge incoming tickets & bugs!

Controls:
  SPACE / UP  -> Jump (double-jump allowed!)
  P           -> Pause
  Q           -> Quit
  R           -> Restart (on game over)
"""

import curses
import random
import time
import sys


# ─── Color pair IDs ───────────────────────────────────────────────────────────
C_BOT   = 1
C_OBS   = 2
C_GOLD  = 3
C_CYAN  = 4
C_WHITE = 5
C_MAG   = 6
C_DARK  = 7
C_FLASH = 8


# ─── ASCII art ────────────────────────────────────────────────────────────────
SPLASH = r"""
   _____ _   _ _____  ____   ___  ____  _____   ____   __  _____
  / ____| | | |  __ \|  _ \ / _ \|  _ \|_   _| |  _ \ / / |_   _|
 | (___ | | | | |__) | |_) | | | | |_) | | |   | |_) / /_   | |
  \___ \| | | |  ___/|  __/| | | |  _ <  | |   |  _ < '_ \  | |
  ____) | |_| | |    | |   | |_| | |_) |_| |_  | |_) | (_) || |
 |_____/ \___/|_|    |_|    \___/|____/|_____| |____/ \___/|___|

         ████████╗██╗ ██████╗██╗  ██╗███████╗████████╗
            ██╔══╝██║██╔════╝██║ ██╔╝██╔════╝╚══██╔══╝
            ██║   ██║██║     █████╔╝ █████╗     ██║
            ██║   ██║██║     ██╔═██╗ ██╔══╝     ██║
            ██║   ██║╚██████╗██║  ██╗███████╗   ██║
            ╚═╝   ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝   ╚═╝

          R U S H   —  D o d g e  t h e  T i c k e t s !
"""

BOT_RUN = [
    r" _____ ",
    r"|o BOT|",
    r"|_____|",
    r"  | |  ",
    r" / \ / ",
]
BOT_RUN2 = [
    r" _____ ",
    r"|o BOT|",
    r"|_____|",
    r"  | |  ",
    r" \  /\ ",
]
BOT_JUMP = [
    r" _____ ",
    r"|^ BOT|",
    r"|_____|",
    r"  /\  ",
    r" /  \ ",
]

BOT_W = 7

OBS_DEFS = [
    (r" /\/\ ",  r"|BUG! |", "BUG",    False),
    (r" #### ",  r"|ERR! |", "ERR",    False),
    (r" /oo\ ",  r"|MAD! |", "MAD",    False),
    (r" /--\ ",  r"|SPAM |", "SPAM",   False),
    (r" /!!\ ",  r"|CRIT |", "CRIT",   False),
    (r"<BUG!>",  r"~~~~~~",  "FLYBUG", True),
    (r"<ERR!>",  r"~~~~~~",  "FLYERR", True),
]

COLLECT_CHAR = "[✓OK]"
COLLECT_W    = 5


def make_obs(w, ground_y, speed):
    defn = random.choice(OBS_DEFS)
    is_fly = defn[3]
    y = (ground_y - 4) if is_fly else (ground_y - 1)
    return {
        "x":      float(w - 2),
        "y":      y,
        "top":    defn[0],
        "bot":    defn[1],
        "label":  defn[2],
        "flying": is_fly,
        "w":      max(len(defn[0]), len(defn[1])),
    }


def make_collect(w, ground_y):
    return {"x": float(w - 4), "y": ground_y - 5}


def new_state(w, h):
    ground_y = h - 5
    return {
        "w": w, "h": h,
        "ground_y":      ground_y,
        "player_x":      6,
        "player_y":      float(ground_y - 4),
        "vel_y":         0.0,
        "on_ground":     True,
        "jumps_left":    2,
        "score":         0,
        "lives":         3,
        "hit_flash":     0,
        "obstacles":     [],
        "collectibles":  [],
        "frame":         0,
        "spawn_timer":   0,
        "spawn_interval": 48,
        "speed":         2.0,
        "game_over":     False,
        "paused":        False,
        "anim_frame":    0,
        "distance":      0.0,
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def safe(stdscr, y, x, text, attr=0):
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h or x >= w or x < 0:
        return
    clip = min(len(text), w - x - 1)
    if clip <= 0:
        return
    try:
        stdscr.addstr(y, x, text[:clip], attr)
    except curses.error:
        pass


def center(stdscr, y, text, attr=0):
    _, w = stdscr.getmaxyx()
    x = max(0, w // 2 - len(text) // 2)
    safe(stdscr, y, x, text, attr)


def draw_bot(stdscr, px, py, jumping, anim, flash, colors):
    frames = BOT_JUMP if jumping else (BOT_RUN if anim % 8 < 4 else BOT_RUN2)
    attr = colors["flash"] if flash > 0 else colors["bot"]
    for i, line in enumerate(frames):
        safe(stdscr, py + i, px, line, attr)


def draw_obs(stdscr, obs, colors):
    x = int(obs["x"])
    y = obs["y"]
    safe(stdscr, y,     x, obs["top"], colors["obs"])
    safe(stdscr, y + 1, x, obs["bot"], colors["obs"])


def draw_collect(stdscr, col, colors, frame):
    x = int(col["x"])
    y = col["y"]
    if (frame // 4) % 2 == 0:
        safe(stdscr, y, x, COLLECT_CHAR, colors["cyan"])
    else:
        safe(stdscr, y, x, COLLECT_CHAR, colors["gold"])


def check_collision(px, py, obs):
    bx1, bx2 = px, px + BOT_W - 1
    by1, by2 = py, py + 3
    ox1 = int(obs["x"])
    ox2 = ox1 + obs["w"] - 1
    oy1, oy2 = obs["y"], obs["y"] + 1
    return (bx1 < ox2 and bx2 > ox1) and (by1 < oy2 + 1 and by2 > oy1 - 1)


def check_collect(px, py, col):
    bx1, bx2 = px, px + BOT_W - 1
    cx1, cx2 = int(col["x"]), int(col["x"]) + COLLECT_W
    return (bx1 < cx2 and bx2 > cx1) and abs((py + 1) - col["y"]) <= 3


# ─── Screens ──────────────────────────────────────────────────────────────────

def splash_screen(stdscr, colors):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    lines = SPLASH.strip("\n").split("\n")
    start = max(1, h // 2 - len(lines) // 2 - 3)
    for i, line in enumerate(lines):
        x = max(0, w // 2 - len(line) // 2)
        safe(stdscr, start + i, x, line, colors["mag"])
    center(stdscr, start + len(lines) + 1,
           "─── Dodge BUG  ERR  MAD  SPAM  CRIT  tickets! ───", colors["gold"])
    center(stdscr, start + len(lines) + 2,
           "Collect  [✓OK]  for +50 bonus points  |  Double-jump unlocked!", colors["cyan"])
    center(stdscr, start + len(lines) + 4,
           "[ SPACE / UP ] Jump    [ P ] Pause    [ Q ] Quit", colors["white"])
    center(stdscr, start + len(lines) + 6,
           "======  Press  SPACE  to  START  ======", colors["mag"] | curses.A_BLINK)
    stdscr.nodelay(False)
    while True:
        key = stdscr.getch()
        if key in (ord(' '), ord('\n'), curses.KEY_UP):
            break
        if key in (ord('q'), ord('Q')):
            return False
    stdscr.nodelay(True)
    return True


def game_over_screen(stdscr, score, high_score, colors):
    h, w = stdscr.getmaxyx()
    lines = [
        "╔═══════════════════════════════════════╗",
        "║   💥  SYSTEM OVERLOADED!  💥          ║",
        "║                                       ║",
       f"║   SCORE     : {score:>8}              ║",
       f"║   HIGH SCORE: {high_score:>8}              ║",
        "║                                       ║",
        "║    [ R ] Restart   │   [ Q ] Quit     ║",
        "╚═══════════════════════════════════════╝",
    ]
    sy = h // 2 - len(lines) // 2
    for i, line in enumerate(lines):
        center(stdscr, sy + i, line, colors["obs"] | curses.A_BOLD)


def hud(stdscr, s, high_score, colors):
    w = s["w"]
    safe(stdscr, 0, 0, "─" * w, colors["white"])
    title = " ◄ SUPPORT BOT: TICKET RUSH ► "
    safe(stdscr, 0, w // 2 - len(title) // 2, title, colors["mag"] | curses.A_BOLD)
    score_str = f" SCORE: {s['score']:>8} "
    best_str  = f" BEST: {high_score:>8} "
    lives_str = " LIVES: " + ("♥ " * s["lives"]) + ("♡ " * max(0, 3 - s["lives"])) + " "
    safe(stdscr, 1, 1, score_str, colors["gold"] | curses.A_BOLD)
    safe(stdscr, 1, w // 2 - len(best_str) // 2, best_str, colors["white"])
    safe(stdscr, 1, w - len(lives_str) - 1, lives_str, colors["obs"] | curses.A_BOLD)
    spd = min(8, int(s["speed"]))
    bar = "SPD [" + "█" * spd + "░" * (8 - spd) + "]"
    safe(stdscr, 2, 1, bar, colors["cyan"])
    lvl = min(5, 1 + int(s["score"] // 400))
    safe(stdscr, 2, w - 14, f" LEVEL: {lvl} ", colors["gold"])
    h = s["h"]
    safe(stdscr, h - 2, 0, "─" * w, colors["white"])
    hint = " SPACE/↑ Jump (x2!)  │  P Pause  │  Q Quit  │  [✓OK]+50pts "
    safe(stdscr, h - 1, 1, hint, colors["white"])


def draw_ground(stdscr, s, colors):
    gy = s["ground_y"]
    w  = s["w"]
    safe(stdscr, gy, 0, "═" * w, colors["white"])
    offset = int(s["distance"]) % 4
    dots = ("· " * (w // 2 + 2))
    safe(stdscr, gy + 1, 0, dots[offset: offset + w], colors["dark"])


# ─── Main game loop ───────────────────────────────────────────────────────────

def run_game(stdscr):
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_BOT,   curses.COLOR_GREEN,   -1)
    curses.init_pair(C_OBS,   curses.COLOR_RED,     -1)
    curses.init_pair(C_GOLD,  curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_CYAN,  curses.COLOR_CYAN,    -1)
    curses.init_pair(C_WHITE, curses.COLOR_WHITE,   -1)
    curses.init_pair(C_MAG,   curses.COLOR_MAGENTA, -1)
    curses.init_pair(C_DARK,  curses.COLOR_WHITE,   -1)
    curses.init_pair(C_FLASH, curses.COLOR_WHITE,   curses.COLOR_RED)

    colors = {
        "bot":   curses.color_pair(C_BOT)   | curses.A_BOLD,
        "obs":   curses.color_pair(C_OBS)   | curses.A_BOLD,
        "gold":  curses.color_pair(C_GOLD)  | curses.A_BOLD,
        "cyan":  curses.color_pair(C_CYAN)  | curses.A_BOLD,
        "white": curses.color_pair(C_WHITE),
        "mag":   curses.color_pair(C_MAG)   | curses.A_BOLD,
        "dark":  curses.color_pair(C_DARK),
        "flash": curses.color_pair(C_FLASH) | curses.A_BOLD,
    }

    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(33)

    if not splash_screen(stdscr, colors):
        return

    h, w = stdscr.getmaxyx()
    s = new_state(w, h)
    high_score = 0

    GRAVITY  = 18.0   # lower gravity = higher, floatier arc
    JUMP_VEL = -13.0  # stronger launch = ~4.7 row peak clearance
    last_t   = time.time()

    while True:
        now = time.time()
        dt  = min(now - last_t, 0.1)
        last_t = now

        key = stdscr.getch()

        if key in (ord('q'), ord('Q')):
            break

        if key in (ord('p'), ord('P')) and not s["game_over"]:
            s["paused"] = not s["paused"]

        if s["game_over"]:
            if key in (ord('r'), ord('R')):
                high_score = max(high_score, s["score"])
                h2, w2 = stdscr.getmaxyx()
                s = new_state(w2, h2)
                last_t = time.time()
                continue

        if not s["paused"] and not s["game_over"]:
            if key in (ord(' '), curses.KEY_UP, ord('w'), ord('W')):
                if s["jumps_left"] > 0:
                    s["vel_y"]       = JUMP_VEL
                    s["on_ground"]   = False
                    s["jumps_left"] -= 1

            s["vel_y"]    += GRAVITY * dt
            s["player_y"] += s["vel_y"] * dt

            ground_top = float(s["ground_y"] - 4)
            if s["player_y"] >= ground_top:
                s["player_y"]   = ground_top
                s["vel_y"]      = 0.0
                s["on_ground"]  = True
                s["jumps_left"] = 2

            s["spawn_timer"] += 1
            if s["spawn_timer"] >= int(s["spawn_interval"]):
                s["spawn_timer"] = 0
                s["obstacles"].append(make_obs(s["w"], s["ground_y"], s["speed"]))
                if random.random() < 0.40:
                    s["collectibles"].append(make_collect(s["w"], s["ground_y"]))
                s["spawn_interval"] = max(18, s["spawn_interval"] - 0.4)
                s["speed"]          = min(7.5, s["speed"] + 0.07)

            spd = s["speed"]
            for obs in s["obstacles"]:
                obs["x"] -= spd
            for col in s["collectibles"]:
                col["x"] -= spd
            s["obstacles"]    = [o for o in s["obstacles"]    if o["x"] > -12]
            s["collectibles"] = [c for c in s["collectibles"] if c["x"] > -8]

            px = s["player_x"]
            py = int(s["player_y"])

            for obs in s["obstacles"][:]:
                if check_collision(px, py, obs):
                    s["obstacles"].remove(obs)
                    s["lives"]    -= 1
                    s["hit_flash"] = 10
                    if s["lives"] <= 0:
                        s["game_over"] = True
                        high_score     = max(high_score, s["score"])

            for col in s["collectibles"][:]:
                if check_collect(px, py, col):
                    s["collectibles"].remove(col)
                    s["score"] += 50

            if not s["game_over"]:
                s["score"]      += 1
                s["distance"]   += spd
                s["frame"]      += 1
                s["anim_frame"] += 1
                if s["hit_flash"] > 0:
                    s["hit_flash"] -= 1

        stdscr.erase()
        draw_ground(stdscr, s, colors)
        hud(stdscr, s, max(high_score, s["score"]), colors)
        draw_bot(stdscr, s["player_x"], int(s["player_y"]),
                 not s["on_ground"], s["anim_frame"], s["hit_flash"], colors)
        for obs in s["obstacles"]:
            draw_obs(stdscr, obs, colors)
        for col in s["collectibles"]:
            draw_collect(stdscr, col, colors, s["frame"])

        if s["paused"] and not s["game_over"]:
            lines = [
                "┌──────────────────────────────┐",
                "│  ⏸  TICKET QUEUE PAUSED  ⏸  │",
                "│       Press P to resume      │",
                "└──────────────────────────────┘",
            ]
            sy = s["h"] // 2 - 2
            for i, line in enumerate(lines):
                center(stdscr, sy + i, line, colors["gold"])

        if s["game_over"]:
            game_over_screen(stdscr, s["score"], max(high_score, s["score"]), colors)

        stdscr.refresh()

    stdscr.clear()
    center(stdscr, stdscr.getmaxyx()[0] // 2 - 1,
           "Thanks for playing Support Bot: Ticket Rush!", colors["mag"])
    center(stdscr, stdscr.getmaxyx()[0] // 2,
           f"Final High Score: {max(high_score, s['score'])}", colors["gold"])
    stdscr.nodelay(False)
    stdscr.getch()
