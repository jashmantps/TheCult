#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# cultbot.py  --  The Cult: automated bot player (for testing & demos)
#
# Author: Abhishek Singh
#
# A bot connects exactly like a human (through cultnet.py) and reacts to the
# server's prompts: the Leader pitches a random valid target, the
# Investigator checks someone, and everyone votes. This lets a full game run
# without five live terminals, which is useful for testing the server logic
# and for producing a transcript to screenshot.
#
# Usage: cultbot.py <sock_path> <name> [seed]
# ---------------------------------------------------------------------------

import os
import sys
import time
import random
import threading

import cultnet

running = True


def parse_options(text, keyword):
    """Pull the 'Options: a, b, c' list out of a prompt line."""
    if "Options:" in text:
        tail = text.split("Options:", 1)[1]
    elif "Valid:" in text:
        tail = text.split("Valid:", 1)[1]
    else:
        return []
    parts = [x.strip().strip(".") for x in tail.split(",")]
    return [p for p in parts if p]


def main():
    global running
    sock_path = sys.argv[1]
    myname = sys.argv[2]
    if len(sys.argv) > 3:
        random.seed(int(sys.argv[3]))

    client = cultnet.CultClient(sock_path)
    client.send({"type": "join", "name": myname})

    state = {"role": None, "voted_this_vote": False, "known": []}

    def show(text, kind):
        # Mirror what a human client would print, so a bot's captured
        # output reads like a real player's terminal for screenshots.
        if kind == "role":
            print("*** %s" % text)
        elif kind == "cult":
            print("(cult) %s" % text)
        elif kind == "prompt":
            print(">> %s" % text)
        else:
            print(text)
        sys.stdout.flush()

    def think_and_act(text, kind):
        # Role discovery.
        if "Your role:" in text:
            state["role"] = text.split("Your role:")[1].split("~")[0].strip().lower()
            return

        # Night prompt to the Leader.
        if kind == "prompt" and "recruit" in text and state["role"] and \
           "leader" in state["role"]:
            opts = parse_options(text, "recruit")
            if opts:
                time.sleep(random.uniform(0.3, 1.0))
                client.send({"type": "action",
                             "text": "pitch %s" % random.choice(opts)})
            return

        # Night prompt to the Investigator.
        if kind == "prompt" and "investigate" in text and state["role"] and \
           "investigator" in state["role"]:
            opts = parse_options(text, "investigate")
            if opts:
                time.sleep(random.uniform(0.3, 1.0))
                client.send({"type": "action",
                             "text": "check %s" % random.choice(opts)})
            return

        # Day talk: say something innocuous when discussion opens.
        if "Discuss" in text:
            time.sleep(random.uniform(0.3, 1.2))
            lines = ["I think we should watch the quiet ones.",
                     "Anyone acting strange last night?",
                     "I'm just a humble townsperson.",
                     "Let's stay calm and think.",
                     "Something feels off about this group."]
            client.send({"type": "chat", "text": random.choice(lines)})
            return

        # A fresh vote window opens -> reset our per-vote flag and vote once.
        if "VOTE now" in text:
            state["voted_this_vote"] = False
            if not state["voted_this_vote"]:
                opts = parse_options(text, "vote")
                opts = [o for o in opts if o.lower() != myname.lower()]
                if opts:
                    time.sleep(random.uniform(0.2, 1.0))
                    client.send({"type": "action",
                                 "text": "vote %s" % random.choice(opts)})
                    state["voted_this_vote"] = True
            return

    def receiver():
        global running
        while running:
            try:
                msg = client.recv()
            except OSError:
                break
            if msg is None:
                running = False
                break
            kind = msg.get("type", "info")
            text = msg.get("text", "")
            show(text, kind)
            if kind == "close":
                running = False
                break
            try:
                think_and_act(text, kind)
            except Exception:
                pass

    rx = threading.Thread(target=receiver, daemon=True)
    rx.start()
    while running:
        time.sleep(0.2)
    client.close()


if __name__ == "__main__":
    main()
