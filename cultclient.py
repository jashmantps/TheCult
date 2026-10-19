#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# cultclient.py  --  The Cult: player client
#
# Author: Abhishek Singh
# Course: CSE/CEN Advanced Operating Systems, ASU, Fall 2026
#
# A player runs this program. It connects to the server through cultnet.py
# and runs two threads:
#   * a receive thread that prints every message the server sends, and
#   * the main thread that reads what the player types and sends it.
#
# The client is deliberately thin: it does NOT know the rules. It only
# tags each typed line with a message "type" the server understands:
#       pitch <name>   -> {"type":"action", "text":"pitch <name>"}
#       check <name>   -> {"type":"action", "text":"check <name>"}
#       vote  <name>   -> {"type":"action", "text":"vote  <name>"}
#       anything else  -> {"type":"chat",   "text":"<line>"}
# The server decides, based on the player's hidden role and the current
# phase, what each message means. Identity is fixed by the kernel (the
# server reads the connecting UID via SO_PEERCRED), so a client cannot
# claim to be a different player no matter what it sends.
# ---------------------------------------------------------------------------

import os
import sys
import pwd
import time
import threading

import cultnet

# Where the server is listening. Overridable via argv[1] for local testing.
DEFAULT_SOCK = "/home/cultmaster/cult.sock"

# Words that are game ACTIONS rather than public chat.
ACTION_WORDS = ("pitch", "check", "vote")

running = True


def receiver(client):
    """Print everything the server sends until it closes or says 'close'."""
    global running
    while running:
        try:
            msg = client.recv()
        except OSError:
            break
        if msg is None:
            print("\n[Connection closed by server.]")
            running = False
            break
        text = msg.get("text", "")
        kind = msg.get("type", "info")
        if kind == "close":
            print("\n" + text)
            print("[Game over. You may close this terminal.]")
            running = False
            break
        elif kind == "role":
            print("\n*** %s" % text)
        elif kind == "cult":
            print("\n(cult) %s" % text)
        elif kind == "prompt":
            print("\n>> %s" % text)
        else:
            print(text)
        sys.stdout.flush()


def classify(line):
    """Turn a typed line into a (type, text) message for the server."""
    first = line.strip().split(" ", 1)[0].lower() if line.strip() else ""
    if first in ACTION_WORDS:
        return {"type": "action", "text": line.strip()}
    return {"type": "chat", "text": line.rstrip("\n")}


def main():
    global running
    sock_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOCK

    # Default display name = this Linux user's name, so the name on the
    # table lines up with the kernel-verified UID.
    try:
        myname = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        myname = "player%d" % os.getuid()
    # Allow an explicit name override as argv[2] (handy for demos).
    if len(sys.argv) > 2:
        myname = sys.argv[2]

    try:
        client = cultnet.CultClient(sock_path)
    except OSError as e:
        print("Could not connect to the Cult server at %s: %s"
              % (sock_path, e))
        sys.exit(1)

    # Announce ourselves with a JOIN message carrying our chosen name.
    client.send({"type": "join", "name": myname})

    rx = threading.Thread(target=receiver, args=(client,), daemon=True)
    rx.start()

    print("Connected as %s. Type to chat; actions: pitch/check/vote <name>."
          % myname)
    try:
        while running:
            try:
                line = input()
            except EOFError:
                break
            if not running:
                break
            if line.strip() == "":
                continue
            client.send(classify(line))
    except KeyboardInterrupt:
        pass
    finally:
        running = False
        client.close()
        time.sleep(0.1)


if __name__ == "__main__":
    main()
