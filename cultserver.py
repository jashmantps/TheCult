#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# cultserver.py  --  The Cult: game server (the "Prophet" / moderator)
#
# Author: Abhishek Singh
# Course: CSE/CEN Advanced Operating Systems, ASU, Fall 2026
#
# The Cult is a hidden-role social-deduction game with NO elimination.
# A hidden Cult Leader converts players one at a time each night.  Converted
# players secretly join a growing "cult channel" (a multicast group) while
# having to keep up appearances in the public day chat (a broadcast channel).
# The town tries to expose cultists by vote.  Nobody ever leaves the game,
# which keeps the socket lifecycle simple -- a connection staying open for
# the whole game is the normal case.
#
# Roles
#   Cult Leader   (1)      : each night sends a private pitch to one target;
#                            the target is converted unless protected.
#   Investigator  (N)      : each night privately checks one player and is
#                            told "cultist" or "not a cultist".
#   Skeptic       (N)      : immune to conversion (a failed pitch is silent
#                            to the town but the Leader learns it failed).
#   Townsfolk     (rest)   : ordinary players; chat and vote.
#
# Win conditions
#   Cult wins   : converted players (Leader + converts) are >= cultWinFraction
#                 of the living players (everyone is "living" -- see above).
#   Town wins   : the Leader is exposed by a day vote, OR maxRounds elapse
#                 without the cult reaching its threshold (survival).
#
# This file contains ZERO socket or framing code.  Every byte on the wire
# goes through cultnet.py:
#   unicast   via server.send(cid, obj)        -- pitches, role reveals,
#                                                  investigator results
#   multicast via server.multicast(cids, obj)  -- the cult channel
#   broadcast via server.broadcast(obj)        -- public chat, announcements,
#                                                  vote tallies
# ---------------------------------------------------------------------------

import os
import sys
import time
import random

import cultnet


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path="cultconfig"):
    cfg = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            cfg[key.strip()] = val.strip()
    return cfg


# ---------------------------------------------------------------------------
# A small record for each player at the table
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, cid, uid, name):
        self.cid = cid          # connection id (address for delivery)
        self.uid = uid          # kernel-verified Linux UID (identity)
        self.name = name        # display name
        self.role = "townsfolk" # leader / investigator / skeptic / townsfolk
        self.converted = False  # True once in the cult
        self.exposed = False    # True once publicly outed as a cultist

    def is_cultist(self):
        # The Leader counts as a cultist for win math; converts do too.
        return self.role == "leader" or self.converted


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------

class CultGame:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sock_path = cfg.get("sockPath", "/tmp/cult.sock")
        self.log_dir = cfg.get("logDir", ".")
        self.min_players = int(cfg.get("minPlayers", 5))
        self.join_time = int(cfg.get("joinTime", 60))
        self.night_time = int(cfg.get("nightTime", 30))
        self.day_talk_time = int(cfg.get("dayTalkTime", 45))
        self.day_vote_time = int(cfg.get("dayVoteTime", 30))
        self.max_rounds = int(cfg.get("maxRounds", 6))
        self.num_investigators = int(cfg.get("numInvestigators", 1))
        self.num_skeptics = int(cfg.get("numSkeptics", 1))
        self.cult_fraction = float(cfg.get("cultWinFraction", 0.5))
        self.random_roles = int(cfg.get("randomRoles", 1))

        self.server = None
        self.players = {}       # cid -> Player
        self.winner = None

        # Per-night scratch state
        self.phase = "lobby"    # lobby / night / day / over
        self.pitch_target = None       # cid the Leader chose this night
        self.invest_target = None      # cid the Investigator chose this night
        self.votes = {}                # voter_cid -> target_cid (day expose)

        self._open_logs()

    # -- logging --------------------------------------------------------

    def _open_logs(self):
        try:
            os.makedirs(self.log_dir, exist_ok=True)
        except OSError:
            pass
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.public_log_path = os.path.join(self.log_dir, "public-%s.log" % ts)
        self.master_log_path = os.path.join(self.log_dir, "master-%s.log" % ts)
        # The master log holds hidden info (roles, conversions) and is only
        # readable by the cultmaster user. The public log is the town-visible
        # transcript. We just open/append; install.sh sets directory perms.

    def log(self, text, public=False, master=True, show=True):
        stamp = "(%d) %s" % (int(time.time()), text)
        if show:
            print(stamp)
            sys.stdout.flush()
        if public:
            try:
                with open(self.public_log_path, "a") as f:
                    f.write(stamp + "\n")
            except OSError:
                pass
        if master:
            try:
                with open(self.master_log_path, "a") as f:
                    f.write(stamp + "\n")
            except OSError:
                pass

    # -- convenience addressing ----------------------------------------

    def living(self):
        """All players (nobody is ever eliminated in The Cult)."""
        return list(self.players.values())

    def cids(self):
        return list(self.players.keys())

    def name_of(self, cid):
        p = self.players.get(cid)
        return p.name if p else "?"

    def cid_by_name(self, name):
        for cid, p in self.players.items():
            if p.name.lower() == name.lower():
                return cid
        return None

    def cultists(self):
        return [p for p in self.players.values() if p.is_cultist()]

    def leader(self):
        for p in self.players.values():
            if p.role == "leader":
                return p
        return None

    def investigators(self):
        return [p for p in self.players.values() if p.role == "investigator"]

    # messaging wrappers around cultnet (keep the game readable) ---------

    def tell(self, cid, text, kind="info"):
        """Unicast a text line to one player."""
        self.server.send(cid, {"type": kind, "text": text})

    def announce(self, text, kind="info"):
        """Broadcast a text line to everyone."""
        self.log(text, public=True)
        self.server.broadcast({"type": kind, "text": text})

    def cult_whisper(self, text):
        """Multicast a line to the cult channel only."""
        members = [p.cid for p in self.cultists()]
        self.server.multicast(members, {"type": "cult", "text": text})

    # -- the main driver ------------------------------------------------

    def run(self):
        self.server = cultnet.CultServer(self.sock_path)
        self.log("The Cult server is listening on %s" % self.sock_path)
        self.log("Waiting up to %ds for at least %d players..."
                 % (self.join_time, self.min_players))

        self._lobby()
        if len(self.players) < self.min_players:
            self.log("Not enough players joined (%d). Shutting down."
                     % len(self.players))
            self.server.broadcast({"type": "info",
                                   "text": "Not enough players. Game cancelled."})
            self.server.close()
            return

        self._assign_roles()
        self.announce("=" * 48)
        self.announce("The Cult begins. There are %d souls in town."
                      % len(self.players))
        self.announce("Somewhere among you, a Cult Leader is recruiting...")
        self.announce("=" * 48)

        rnd = 1
        while self.phase != "over" and rnd <= self.max_rounds:
            self.announce("")
            self.announce("######## NIGHT %d ########" % rnd)
            self._night()
            if self._check_win(after="night", rnd=rnd):
                break

            self.announce("")
            self.announce("######## DAY %d ########" % rnd)
            self._day()
            if self._check_win(after="day", rnd=rnd):
                break
            rnd += 1

        if self.phase != "over":
            # Ran out of rounds with no cult victory -> town survives.
            self.winner = "Town survives! The cult never reached critical mass."
            self.phase = "over"

        self.announce("")
        self.announce("*** GAME OVER ***")
        self.announce(self.winner)
        self._reveal_all()
        self.server.broadcast({"type": "close", "text": "Thanks for playing."})
        self.log("Winner: %s" % self.winner)
        time.sleep(0.5)
        self.server.close()

    # -- lobby ----------------------------------------------------------

    def _lobby(self):
        deadline = time.time() + self.join_time
        while time.time() < deadline:
            for ev in self.server.poll(0.2):
                self._handle_lobby_event(ev)
            # Start early once we have enough and a short grace period passed.
            if len(self.players) >= self.min_players and \
               time.time() > deadline - (self.join_time - 5):
                # at least 5s elapsed and quota met -> start
                break
        # Drain any last joins.
        for ev in self.server.poll(0.1):
            self._handle_lobby_event(ev)

    def _handle_lobby_event(self, ev):
        if ev[0] == "connect":
            _c, cid, uid = ev
            # Name will be set from the player's JOIN message.
            self.players[cid] = Player(cid, uid, "player%d" % cid)
        elif ev[0] == "message":
            _m, cid, obj = ev
            p = self.players.get(cid)
            if p is None:
                return
            if obj.get("type") == "join":
                desired = str(obj.get("name", p.name))[:20].strip() or p.name
                # Avoid duplicate names so votes stay unambiguous.
                if self.cid_by_name(desired) not in (None, cid):
                    desired = "%s_%d" % (desired, cid)
                p.name = desired
                self.log("%s connected (uid=%d)" % (p.name, p.uid))
                self.tell(cid, "Welcome, %s. Waiting for the game to start."
                          % p.name)
        elif ev[0] == "disconnect":
            _d, cid = ev
            self.players.pop(cid, None)

    # -- role assignment ------------------------------------------------

    def _assign_roles(self):
        cids = self.cids()
        if not self.random_roles and os.path.exists("roles.txt"):
            self._assign_fixed()
        else:
            roles = ["leader"]
            roles += ["investigator"] * self.num_investigators
            roles += ["skeptic"] * self.num_skeptics
            roles += ["townsfolk"] * (len(cids) - len(roles))
            roles = roles[:len(cids)]
            random.shuffle(roles)
            for cid, role in zip(cids, roles):
                self.players[cid].role = role

        # Inform each player of their role privately (UNICAST).
        for p in self.players.values():
            self.tell(p.cid, "~~~ Your role: %s ~~~" % p.role.upper(),
                      kind="role")
            if p.role == "leader":
                self.tell(p.cid,
                          "Each night, type: pitch <name>  to recruit someone.")
            elif p.role == "investigator":
                self.tell(p.cid,
                          "Each night, type: check <name>  to investigate.")
            elif p.role == "skeptic":
                self.tell(p.cid, "You cannot be converted. Guard the town.")
            self.log("ROLE %s = %s" % (p.name, p.role))

    def _assign_fixed(self):
        wanted = {}
        with open("roles.txt") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    wanted[parts[0].lower()] = parts[1].lower()
        for p in self.players.values():
            p.role = wanted.get(p.name.lower(), "townsfolk")

    # -- night phase ----------------------------------------------------

    def _night(self):
        self.phase = "night"
        self.pitch_target = None
        self.invest_target = None

        leader = self.leader()
        if leader:
            targets = [p.name for p in self.living()
                       if not p.is_cultist()]
            self.tell(leader.cid,
                      "NIGHT: choose someone to recruit. Options: %s"
                      % ", ".join(sorted(targets)), kind="prompt")

        for inv in self.investigators():
            others = [p.name for p in self.living() if p.cid != inv.cid]
            self.tell(inv.cid,
                      "NIGHT: choose someone to investigate. Options: %s"
                      % ", ".join(sorted(others)), kind="prompt")

        # Let the current cult chat privately among themselves.
        self.cult_whisper("The cult is awake. Speak freely, %s."
                          % ", ".join(sorted(p.name for p in self.cultists())))
        self.announce("Night falls. The town sleeps while the cult stirs.")

        # Collect night actions for the configured duration.
        deadline = time.time() + self.night_time
        while time.time() < deadline:
            for ev in self.server.poll(0.2):
                self._handle_night_event(ev)

        # Resolve the Leader's pitch.
        self._resolve_pitch()

        # Resolve the Investigator's check(s).
        self._resolve_checks()

    def _handle_night_event(self, ev):
        if ev[0] == "message":
            _m, cid, obj = ev
            p = self.players.get(cid)
            if p is None:
                return
            text = str(obj.get("text", "")).strip()

            # Cult members chatting at night -> multicast within the cult.
            if obj.get("type") == "chat" and p.is_cultist():
                self.cult_whisper("[cult] %s: %s" % (p.name, text))
                return

            # Leader's recruitment choice.
            if obj.get("type") == "action" and p.role == "leader":
                cmd = text.split()
                if len(cmd) == 2 and cmd[0].lower() == "pitch":
                    tcid = self.cid_by_name(cmd[1])
                    if tcid is not None and not self.players[tcid].is_cultist():
                        self.pitch_target = tcid
                        self.tell(cid, "You will pitch %s tonight."
                                  % self.name_of(tcid))
                    else:
                        self.tell(cid, "Invalid target.")

            # Investigator's check choice.
            if obj.get("type") == "action" and p.role == "investigator":
                cmd = text.split()
                if len(cmd) == 2 and cmd[0].lower() == "check":
                    tcid = self.cid_by_name(cmd[1])
                    if tcid is not None and tcid != cid:
                        self.invest_target = (cid, tcid)
                        self.tell(cid, "You will investigate %s tonight."
                                  % self.name_of(tcid))
                    else:
                        self.tell(cid, "Invalid target.")
        elif ev[0] == "disconnect":
            _d, cid = ev
            # Keep the player record so game math stays stable; just note it.
            self.log("%s disconnected (night)" % self.name_of(cid))

    def _resolve_pitch(self):
        leader = self.leader()
        if not leader or self.pitch_target is None:
            if leader:
                self.tell(leader.cid, "You recruited no one tonight.")
            self.log("Leader pitched no one")
            return
        target = self.players[self.pitch_target]
        if target.role == "skeptic":
            # Skeptic resists. Only the Leader learns the attempt failed.
            self.tell(leader.cid,
                      "%s resisted your pitch! (a Skeptic)" % target.name)
            self.log("Pitch FAILED on %s (skeptic)" % target.name)
        else:
            target.converted = True
            self.tell(leader.cid, "%s has joined the cult." % target.name)
            self.tell(target.cid,
                      ">>> You have been CONVERTED. You are now in the cult. "
                      "Keep it secret. Type chat normally in the day; at "
                      "night your messages go to the cult only. <<<",
                      kind="role")
            self.cult_whisper("A new member joins us: %s." % target.name)
            self.log("CONVERTED %s" % target.name)

    def _resolve_checks(self):
        if not self.invest_target:
            return
        inv_cid, tcid = self.invest_target
        target = self.players[tcid]
        verdict = "a CULTIST" if target.is_cultist() else "NOT a cultist"
        self.tell(inv_cid, "Investigation result: %s is %s."
                  % (target.name, verdict), kind="role")
        self.log("INVESTIGATE %s -> %s (by %s)"
                 % (target.name, verdict, self.name_of(inv_cid)))

    # -- day phase ------------------------------------------------------

    def _day(self):
        self.phase = "day"
        self.votes = {}
        n_cult = len(self.cultists())
        self.announce("Dawn breaks. %d of you now serve the cult (rumour has "
                      "it). Discuss!" % n_cult)
        self.announce("You have %ds to talk. Then you will vote to EXPOSE one "
                      "person." % self.day_talk_time)

        # Talk phase: public broadcast chat.
        deadline = time.time() + self.day_talk_time
        while time.time() < deadline:
            for ev in self.server.poll(0.2):
                self._handle_day_chat_event(ev)

        # Vote phase.
        names = sorted(p.name for p in self.living())
        self.announce("VOTE now. Type: vote <name>. Valid: %s"
                      % ", ".join(names))
        deadline = time.time() + self.day_vote_time
        while time.time() < deadline:
            for ev in self.server.poll(0.2):
                self._handle_day_vote_event(ev)
            if len(self.votes) >= len(self.living()):
                break   # everyone voted; no need to wait out the clock

        self._resolve_expose()

    def _handle_day_chat_event(self, ev):
        if ev[0] == "message":
            _m, cid, obj = ev
            p = self.players.get(cid)
            if p is None:
                return
            if obj.get("type") == "chat":
                text = str(obj.get("text", "")).strip()
                if text:
                    # Public BROADCAST. Note: we attribute by the server's
                    # record of the name (tied to kernel UID), so nobody can
                    # speak as someone else.
                    self.announce("%s: %s" % (p.name, text), kind="chat")
        elif ev[0] == "disconnect":
            _d, cid = ev
            self.log("%s disconnected (day)" % self.name_of(cid))

    def _handle_day_vote_event(self, ev):
        if ev[0] == "message":
            _m, cid, obj = ev
            p = self.players.get(cid)
            if p is None:
                return
            text = str(obj.get("text", "")).strip()
            cmd = text.split()
            if obj.get("type") == "action" and len(cmd) == 2 \
               and cmd[0].lower() == "vote":
                tcid = self.cid_by_name(cmd[1])
                if tcid is None:
                    self.tell(cid, "No such player: %s" % cmd[1])
                elif cid in self.votes:
                    self.tell(cid, "You already voted for %s."
                              % self.name_of(self.votes[cid]))
                else:
                    self.votes[cid] = tcid
                    self.announce("%s has voted." % p.name)
        elif ev[0] == "message" and ev[2].get("type") == "chat":
            # allow talk to continue into the vote window
            pass

    def _resolve_expose(self):
        if not self.votes:
            self.announce("No votes were cast. No one is exposed today.")
            return
        tally = {}
        for tcid in self.votes.values():
            tally[tcid] = tally.get(tcid, 0) + 1
        top = max(tally.values())
        leaders = [c for c, n in tally.items() if n == top]
        if len(leaders) != 1:
            self.announce("The vote was tied. No one is exposed today.")
            self.log("Expose vote tied: %s"
                     % {self.name_of(c): n for c, n in tally.items()})
            return
        tcid = leaders[0]
        target = self.players[tcid]
        self.log("Expose vote: %s"
                 % {self.name_of(c): n for c, n in tally.items()})

        if target.is_cultist():
            was_leader = (target.role == "leader")
            target.exposed = True
            if was_leader:
                self.announce(">>> %s was the CULT LEADER! The town has "
                              "broken the cult! <<<" % target.name)
                self.winner = "Town wins! The Cult Leader was exposed."
                self.phase = "over"
            else:
                # Converted member is dragged back to the town side.
                target.converted = False
                self.announce(">>> %s was exposed as a CULTIST and has "
                              "renounced the cult! <<<" % target.name)
                self.tell(tcid, "You have been exposed and pulled back to "
                                "the town. You are no longer in the cult.",
                          kind="role")
        else:
            self.announce("%s was exposed... but was NOT a cultist. The cult "
                          "grows bolder." % target.name)

    # -- win checking ---------------------------------------------------

    def _check_win(self, after, rnd):
        if self.phase == "over":
            return True
        live = self.living()
        n_cult = len(self.cultists())
        if live and n_cult >= self.cult_fraction * len(live):
            self.winner = ("The Cult wins! %d of %d souls now serve. "
                           % (n_cult, len(live)))
            self.phase = "over"
            return True
        return False

    def _reveal_all(self):
        lines = []
        for p in sorted(self.players.values(), key=lambda x: x.name):
            tag = p.role.upper()
            if p.converted:
                tag += " (converted)"
            if p.exposed:
                tag += " (exposed)"
            lines.append("  %s : %s" % (p.name, tag))
        self.announce("Final roles:")
        for ln in lines:
            self.announce(ln)


# ---------------------------------------------------------------------------

def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "cultconfig"
    cfg = load_config(cfg_path)
    game = CultGame(cfg)
    try:
        game.run()
    except KeyboardInterrupt:
        print("\nServer interrupted; shutting down.")
        if game.server:
            try:
                game.server.broadcast({"type": "close", "text": "Server quit."})
            except Exception:
                pass
            game.server.close()


if __name__ == "__main__":
    main()
