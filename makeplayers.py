#!/usr/bin/env python3
# makeplayers.py <numPlayers>
# Create playerN Linux users (player0 .. playerN-1), each with a random
# password, by calling mkplayer.sh. Mirrors the makeusers.py idea from the
# Werewolves reference code.

import os
import sys
import secrets
import string
import subprocess

num = int(sys.argv[1]) if len(sys.argv) > 1 else 6
alphabet = string.ascii_letters + string.digits

for i in range(num):
    password = "".join(secrets.choice(alphabet) for _ in range(12))
    subprocess.call(["bash", "./mkplayer.sh", str(i), password])
