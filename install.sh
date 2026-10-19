#!/bin/bash
# install.sh [numPlayers]
# Set up The Cult: create the cultmaster user, place the server files, create
# player users, and prepare the log directory. Run as a user with sudo.
#
#   sudo ./install.sh 6
#
# After install:
#   * become cultmaster and run the server:   python3 cultserver.py
#   * become each playerN and run the client:  python3 cultclient.py

set -u
NUM="${1:-6}"

# 1. Create the cultmaster user (owns the server, socket, and logs).
sudo adduser --disabled-password --gecos "" cultmaster

# 2. Copy the whole game into cultmaster's home.
sudo cp -r ./* /home/cultmaster/
sudo mkdir -p /home/cultmaster/log

# 3. Ownership + permissions.
#    The home dir is traversable (711) so a player process can reach the
#    socket file inside it, but cannot list the directory.
sudo chown -R cultmaster:cultmaster /home/cultmaster
sudo chmod 711 /home/cultmaster

#    The log directory holds the MASTER log (hidden roles/conversions) and
#    the PUBLIC log. We make the directory private to cultmaster so players
#    cannot read the master log -- this is the "moderator log" secrecy idea
#    carried over from Werewolves, done with plain filesystem permissions.
sudo chmod 700 /home/cultmaster/log

#    The server + source stay readable only by cultmaster.
sudo chmod 700 /home/cultmaster/cultserver.py
sudo chmod 644 /home/cultmaster/cultconfig

# 4. Create the player users and give them the client files.
cd /home/cultmaster
sudo python3 makeplayers.py "$NUM"

echo
echo "Install complete with $NUM players."
echo "Start the server:   sudo -u cultmaster bash -c 'cd /home/cultmaster && python3 cultserver.py'"
echo "Start a player:     su - player0 -c 'python3 /home/player0/cultclient.py'"
