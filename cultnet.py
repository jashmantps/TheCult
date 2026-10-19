#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# cultnet.py  --  The Cult: communications library
#
# Author: Abhishek Singh
# Course: CSE/CEN Advanced Operating Systems, ASU, Fall 2026
#
# This single file is the ENTIRE communications library for "The Cult".
# Both the game server (cultserver.py) and the player client (cultclient.py)
# import this module and talk to each other ONLY through the functions
# defined here. Nothing else in the project opens a socket or frames a
# message directly.
#
# Communications primitive
# -------------------------
# UNIX domain STREAM sockets (AF_UNIX, SOCK_STREAM) multiplexed in a single
# server process with an event loop built on the standard-library
# `selectors` module (which wraps epoll on Linux).  This is deliberately a
# step up from the named pipes used in the Werewolves reference code:
#
#   * One server process handles every player at once via select/epoll.
#     It never does a blocking read on one specific player's channel, so
#     there is no per-player "which pipe is the server waiting on" wait
#     state for an attacker to observe.
#   * Peer identity comes from the kernel via the SO_PEERCRED socket option,
#     so a player cannot forge messages as another player -- the sender UID
#     is read from the kernel, never from the message body.
#   * Messages are length-prefixed JSON written straight into the socket.
#     They are never interpolated into a shell command, so the whole class
#     of command-injection bugs from the pipe version cannot occur here.
#
# Message framing
# ---------------
# Every logical message is a JSON object.  On the wire it is sent as:
#
#       [ 4-byte big-endian unsigned length ][ UTF-8 JSON payload ]
#
# The 4-byte length prefix tells the receiver exactly how many bytes to
# read for the body, which solves the stream-socket "message boundaries"
# problem (TCP/UNIX streams are byte streams, not datagrams, so two sends
# can arrive coalesced or split).  recv_msg() loops until it has the whole
# frame before handing a complete message back.
#
# Public API (see each function's docstring for details)
# ------------------------------------------------------
#   SERVER SIDE (class CultServer):
#       CultServer(sock_path)          -- create + bind + listen
#       .poll(timeout)                 -- pump the event loop once; returns
#                                         a list of ('event', data) tuples
#       .send(cid, obj)                -- UNICAST one JSON obj to one player
#       .multicast(cids, obj)          -- MULTICAST to a subset of players
#       .broadcast(obj)                -- BROADCAST to every connected player
#       .peers()                       -- list of connected connection ids
#       .uid_of(cid)                   -- kernel-verified UID for a connection
#       .close()                       -- tear everything down
#
# Players are addressed by a per-connection id (cid) assigned at accept
# time, NOT by UID.  UID is the *authenticated identity* (from the kernel)
# and is available via uid_of(cid); cid is the *address* used for delivery.
# Keeping the two separate means several clients that happen to share a UID
# (e.g. the grader running five terminals as one user) are still distinct
# addressable players, while the game can still trust uid_of() to say who
# each connection really is.
#
#   CLIENT SIDE (class CultClient):
#       CultClient(sock_path)          -- connect to the server
#       .send(obj)                     -- send one JSON obj to the server
#       .recv(timeout)                 -- receive one JSON obj (or None)
#       .close()                       -- disconnect
#
# The "obj" passed around is any JSON-serialisable Python dict.  The game
# layer decides what keys mean; the library only cares about framing and
# delivery.
# ---------------------------------------------------------------------------

import os
import json
import socket
import struct
import selectors

# SO_PEERCRED returns a `struct ucred { pid_t pid; uid_t uid; gid_t gid; }`.
# On Linux all three are 32-bit ints, so the struct format is three native
# ints "iii".  We read it off the accepted socket to learn, from the kernel,
# which UID is on the other end.
_UCRED_FMT = "iii"
_UCRED_SIZE = struct.calcsize(_UCRED_FMT)

# Length prefix: 4-byte unsigned big-endian integer.
_LEN_FMT = "!I"
_LEN_SIZE = struct.calcsize(_LEN_FMT)


# ---------------------------------------------------------------------------
# Low-level framing helpers (shared by both sides)
# ---------------------------------------------------------------------------

def _encode(obj):
    """Serialise a Python object to a length-prefixed JSON frame (bytes)."""
    body = json.dumps(obj).encode("utf-8")
    return struct.pack(_LEN_FMT, len(body)) + body


def _recv_exactly(sock, nbytes):
    """Read exactly nbytes from a blocking socket, or return None on EOF.

    A stream socket may return a short read, so we loop until we have the
    full count. Returns None if the peer closed the connection partway.
    """
    chunks = []
    remaining = nbytes
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:           # peer closed -> EOF
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame(sock):
    """Read one complete length-prefixed frame and return the decoded obj.

    Returns None if the connection closed. Raises on malformed data.
    """
    header = _recv_exactly(sock, _LEN_SIZE)
    if header is None:
        return None
    (length,) = struct.unpack(_LEN_FMT, header)
    body = _recv_exactly(sock, length)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


def _peer_uid(sock):
    """Ask the kernel for the UID of the process on the other end.

    Uses the SO_PEERCRED socket option. This is the authentication
    mechanism: the UID is reported by the kernel based on the real
    credentials of the connecting process and cannot be spoofed by the
    client's message content.
    """
    cred = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _UCRED_SIZE)
    _pid, uid, _gid = struct.unpack(_UCRED_FMT, cred)
    return uid


# ---------------------------------------------------------------------------
# Server side
# ---------------------------------------------------------------------------

class CultServer:
    """Event-loop server for The Cult.

    One listening UNIX stream socket; every accepted client is registered
    with a selector. poll() pumps the loop once and reports what happened.
    Each connection gets a unique integer id (cid) used for delivery, and
    carries the kernel-supplied peer UID for authentication.
    """

    def __init__(self, sock_path):
        self.sock_path = sock_path
        # Start from a clean slate: remove a stale socket file if present.
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass

        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(sock_path)
        self.listener.listen(128)
        self.listener.setblocking(False)

        # World-writable so any playerN can connect. The security boundary
        # is SO_PEERCRED, not the socket file mode: even if anyone can
        # connect, the kernel still tells us exactly who they are.
        try:
            os.chmod(sock_path, 0o777)
        except OSError:
            pass

        self.sel = selectors.DefaultSelector()
        self.sel.register(self.listener, selectors.EVENT_READ, data=None)

        # cid is a monotonically increasing connection id. We map it both
        # to the socket (for sending) and to the authenticated UID.
        self._next_cid = 0
        self.conns = {}         # cid  -> conn socket
        self.cid_of = {}        # conn -> cid
        self.uids = {}          # cid  -> kernel-verified UID

    # -- addressing -----------------------------------------------------

    def peers(self):
        """Return a list of connection ids for all connected players."""
        return list(self.conns.keys())

    def uid_of(self, cid):
        """Return the kernel-verified UID of a connection, or None."""
        return self.uids.get(cid)

    # -- sending --------------------------------------------------------

    def send(self, cid, obj):
        """UNICAST: deliver one JSON object to exactly one connection."""
        conn = self.conns.get(cid)
        if conn is None:
            return False
        try:
            conn.sendall(_encode(obj))
            return True
        except OSError:
            self._drop(conn)
            return False

    def multicast(self, cids, obj):
        """MULTICAST: deliver the same object to a chosen subset."""
        for cid in list(cids):
            self.send(cid, obj)

    def broadcast(self, obj):
        """BROADCAST: deliver the same object to every connection."""
        self.multicast(self.peers(), obj)

    # -- the event loop -------------------------------------------------

    def poll(self, timeout=0.2):
        """Pump the selector once and return a list of events.

        Each event is a tuple:
            ('connect',    cid, uid)     -- a new player attached
            ('message',    cid, obj)     -- a framed message arrived
            ('disconnect', cid)          -- a player went away

        Because selectors waits on ALL sockets at once, the server never
        blocks on any single player. This is the property that removes the
        pipe wait-state side channel.
        """
        events = []
        for key, _mask in self.sel.select(timeout=timeout):
            if key.data is None:
                # Activity on the listener -> a new connection to accept.
                self._accept(events)
            else:
                # Activity on a client socket -> readable data (or EOF).
                self._read(key.fileobj, events)
        return events

    def _accept(self, events):
        conn, _addr = self.listener.accept()
        uid = _peer_uid(conn)           # kernel-verified identity
        conn.setblocking(True)          # framed reads are simplest blocking
        cid = self._next_cid
        self._next_cid += 1
        self.conns[cid] = conn
        self.cid_of[conn] = cid
        self.uids[cid] = uid
        self.sel.register(conn, selectors.EVENT_READ, data=cid)
        events.append(("connect", cid, uid))

    def _read(self, conn, events):
        cid = self.cid_of.get(conn)
        try:
            obj = _recv_frame(conn)
        except (OSError, ValueError):
            obj = None
        if obj is None:
            self._drop(conn)
            events.append(("disconnect", cid))
            return
        events.append(("message", cid, obj))

    def _drop(self, conn):
        cid = self.cid_of.pop(conn, None)
        if cid is not None:
            self.conns.pop(cid, None)
            self.uids.pop(cid, None)
        try:
            self.sel.unregister(conn)
        except (KeyError, ValueError):
            pass
        try:
            conn.close()
        except OSError:
            pass

    def close(self):
        for conn in list(self.cid_of.keys()):
            self._drop(conn)
        try:
            self.sel.unregister(self.listener)
        except (KeyError, ValueError):
            pass
        try:
            self.listener.close()
        except OSError:
            pass
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Client side
# ---------------------------------------------------------------------------

class CultClient:
    """Thin client wrapper around one UNIX stream socket to the server."""

    def __init__(self, sock_path):
        self.sock_path = sock_path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(sock_path)

    def send(self, obj):
        """Send one JSON object to the server as a framed message."""
        self.sock.sendall(_encode(obj))

    def recv(self, timeout=None):
        """Receive one JSON object from the server.

        With timeout=None this blocks until a full frame arrives (or the
        connection closes, returning None). With a numeric timeout it
        returns None if nothing arrived in that window.
        """
        if timeout is not None:
            self.sock.settimeout(timeout)
            try:
                return _recv_frame(self.sock)
            except socket.timeout:
                return None
            finally:
                self.sock.settimeout(None)
        return _recv_frame(self.sock)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
