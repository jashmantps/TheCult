#!/bin/bash
# rundemo.sh  --  run a self-playing demo game for screenshots, as ONE user,
# no install required. Starts the server plus 5 bot players against a local
# socket. Good for capturing a full game quickly; for the "real" multi-user
# setup use install.sh + cultconfig instead.
#
#   ./rundemo.sh            # server + 5 bots, local /tmp/cult.sock
#
# To screenshot a HUMAN player's view, run fewer bots and join yourself:
#   ./rundemo.sh 4          # 4 bots; then in another terminal:
#   python3 cultclient.py /tmp/cult.sock Me
#
set -u
NBOTS="${1:-5}"
CFG=democonfig
SOCK=/tmp/cult.sock

rm -f "$SOCK"
mkdir -p ./demo-log

echo "Starting server (democonfig)..."
python3 cultserver.py "$CFG" &
SRV=$!
sleep 2

NAMES=(alice bob carol dave erin frank grace heidi)
for i in $(seq 0 $((NBOTS-1))); do
  n="${NAMES[$i]}"
  python3 cultbot.py "$SOCK" "$n" "$((i+1))" &
  sleep 0.2
done

echo "Server PID $SRV. Waiting for the game to finish (Ctrl-C to stop early)..."
wait "$SRV"
pkill -f "cultbot.py $SOCK" 2>/dev/null
echo "Demo complete. See ./demo-log for the public and master logs."
