#!/bin/bash
# uninstall.sh [numPlayers]
# Remove The Cult: delete player users, the cultmaster user, and their homes.
#
#   sudo ./uninstall.sh 6

NUM="${1:-6}"

# Remove player users and their home directories.
for i in $(seq 0 $((NUM-1))); do
    sudo userdel -r "player$i" 2>/dev/null
    sudo groupdel "player$i" 2>/dev/null
done

# Remove the cultmaster user and home.
sudo userdel -r cultmaster 2>/dev/null
sudo groupdel cultmaster 2>/dev/null

echo "Uninstall complete."
