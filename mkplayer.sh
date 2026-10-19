#!/bin/bash
# mkplayer.sh <N> <password>
# Create Linux user playerN and drop the client files into its home.
# Each player is its own Linux user so the server can authenticate them by
# UID via SO_PEERCRED.

echo "setting up user: player$1"

# Create the user with a home directory and a bash shell.
sudo /usr/sbin/useradd -c "player$1" -m -k /dev/null -s /bin/bash "player$1"

# Set the password non-interactively.
echo "player$1:$2" | sudo chpasswd

# Give the player a private copy of the client and the comms library.
sudo cp cultclient.py "/home/player$1/cultclient.py"
sudo cp cultnet.py    "/home/player$1/cultnet.py"
sudo chown "player$1:player$1" "/home/player$1/cultclient.py" "/home/player$1/cultnet.py"
sudo chmod 700 "/home/player$1/cultclient.py" "/home/player$1/cultnet.py"
