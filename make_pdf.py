#!/usr/bin/env python3
"""Generate the submission PDF for The Cult using reportlab.

Produces TheCult-Writeup.pdf with every section the assignment requires:
name, intro (+ comms API and library filename), gameplay screenshots with
captions (as marked placeholders for the author to insert VM screenshots),
a comms-primitive paragraph, a classmate-feedback paragraph (placeholder),
a lessons-learned paragraph, and a clearly separated final section on
feedback given to other students (placeholder).
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                Preformatted, HRFlowable, KeepInFrame,
                                Table, TableStyle, PageBreak)

OUT = "TheCult-Writeup.pdf"

styles = getSampleStyleSheet()

H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15,
                    spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#5b1a8a"))
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12.5,
                    spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#333333"))
BODY = ParagraphStyle("BODY", parent=styles["BodyText"], fontSize=10.3,
                      leading=14.5, alignment=TA_LEFT, spaceAfter=7)
NAME = ParagraphStyle("NAME", parent=styles["Title"], fontSize=20,
                      spaceAfter=2, textColor=colors.HexColor("#5b1a8a"))
SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontSize=10.5,
                     textColor=colors.HexColor("#555555"), spaceAfter=2)
CODE = ParagraphStyle("CODE", parent=styles["Code"], fontSize=7.8,
                      leading=9.6, backColor=colors.HexColor("#f4f1f8"),
                      borderPadding=6, textColor=colors.HexColor("#1a1a1a"))
CAP = ParagraphStyle("CAP", parent=styles["BodyText"], fontSize=9.4,
                     leading=12.5, textColor=colors.HexColor("#444444"),
                     spaceBefore=3, spaceAfter=10, leftIndent=6)
PLACE = ParagraphStyle("PLACE", parent=styles["BodyText"], fontSize=10,
                       leading=14, textColor=colors.HexColor("#8a4b00"),
                       backColor=colors.HexColor("#fff6e6"), borderPadding=8,
                       spaceAfter=8)

story = []


def P(text, style=BODY):
    story.append(Paragraph(text, style))


def code(text):
    story.append(Preformatted(text.strip("\n"), CODE))
    story.append(Spacer(1, 6))


def placeholder(text):
    story.append(Paragraph("[ SCREENSHOT PLACEHOLDER ]  " + text, PLACE))


def rule():
    story.append(Spacer(1, 2))
    story.append(HRFlowable(width="100%", thickness=0.6,
                            color=colors.HexColor("#d9cde8")))
    story.append(Spacer(1, 4))


# --------------------------------------------------------------------------
# Title block
# --------------------------------------------------------------------------
P("Abhishek Singh", NAME)
P("The Cult &mdash; a hidden-role social-deduction game over UNIX stream sockets", SUB)
P("CSE/CEN Advanced Operating Systems &middot; Arizona State University &middot; Fall 2026", SUB)
story.append(Spacer(1, 10))

# --------------------------------------------------------------------------
# Intro
# --------------------------------------------------------------------------
P("1. Introduction", H1)
P(
 "<b>The Cult</b> is a text-based, Werewolves-style game played by several "
 "players on a single Linux machine. Each player is a separate Linux user "
 "running a client process, and one server process (the &ldquo;Prophet&rdquo;) "
 "runs the game. The twist is that <b>no player is ever eliminated</b>. A "
 "hidden <b>Cult Leader</b> secretly <i>converts</i> one player each night; "
 "converted players silently join a growing <b>cult channel</b> and must "
 "keep up appearances in the public day chat. The town fights back by voting "
 "each day to <b>expose</b> a suspected cultist. The cult wins when its "
 "members reach half of the players; the town wins by exposing the Leader or "
 "by surviving a set number of rounds. Because nobody is removed, a player&rsquo;s "
 "socket simply stays open for the whole game &mdash; there is no awkward "
 "&ldquo;dead but still connected&rdquo; state to manage."
)
P(
 "All communication is handled by a single-file communications library named "
 "<b>cultnet.py</b>. Nothing else in the project opens a socket or frames a "
 "message. Its public API is:"
)
code(
"""SERVER  (class CultServer)
  CultServer(sock_path)      create + bind + listen on a UNIX socket
  poll(timeout) -> events    pump the event loop once; yields
                               ('connect', cid, uid) / ('message', cid, obj)
                               / ('disconnect', cid)
  send(cid, obj)             UNICAST   one JSON object to one connection
  multicast(cids, obj)       MULTICAST one object to a chosen subset
  broadcast(obj)             BROADCAST one object to every connection
  peers() -> [cid]           all connected connection ids
  uid_of(cid) -> uid         kernel-verified Linux UID for a connection
  close()                    tear down and remove the socket

CLIENT  (class CultClient)
  CultClient(sock_path)      connect to the server's UNIX socket
  send(obj)                  send one JSON object (framed) to the server
  recv(timeout=None) -> obj  receive one object (None on close/timeout)
  close()                    disconnect"""
)
P(
 "Every <code>obj</code> is a JSON dictionary; the library only frames and "
 "delivers bytes, and the game layer decides what the keys mean. The three "
 "delivery modes map directly onto the game: <b>unicast</b> for private role "
 "reveals, the Leader&rsquo;s pitch, and Investigator results; <b>multicast</b> "
 "for the cult channel; and <b>broadcast</b> for public chat, announcements, "
 "and vote tallies."
)

# --------------------------------------------------------------------------
# Message-flow figure (drawn as a small table, no external image needed)
# --------------------------------------------------------------------------
P("Message flow at a glance", H2)
flow = [
    ["Mode", "Used for", "API call"],
    ["Unicast", "role reveal, Leader pitch, Investigator result",
     "server.send(cid, obj)"],
    ["Multicast", "the hidden cult channel (members only)",
     "server.multicast(cids, obj)"],
    ["Broadcast", "public day chat, announcements, vote tallies",
     "server.broadcast(obj)"],
]
t = Table(flow, colWidths=[0.95*inch, 3.5*inch, 2.0*inch])
t.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5b1a8a")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTSIZE", (0, 0), (-1, -1), 8.6),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTNAME", (2, 1), (2, -1), "Courier"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
     [colors.white, colors.HexColor("#f4f1f8")]),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))
story.append(t)
story.append(Spacer(1, 10))

# --------------------------------------------------------------------------
# Screenshots section
# --------------------------------------------------------------------------
P("2. Gameplay screenshots", H1)
P(
 "The following screenshots were captured on an Ubuntu 26.04 VM with a "
 "<code>cultmaster</code> server user and six player users (player0&ndash;player5), "
 "each in its own terminal. Replace each placeholder below with the "
 "corresponding screenshot from your run."
)

placeholder("The server (Prophet) in the lobby, printing that it is "
            "listening on the UNIX socket and waiting for players to join; "
            "several &ldquo;playerN connected (uid=...)&rdquo; lines appear as clients "
            "attach.")
P("<i>Caption:</i> The server binds one UNIX stream socket and waits in the "
  "lobby. Each connecting client is authenticated by the kernel-supplied UID "
  "(SO_PEERCRED), shown in the connect log.", CAP)

placeholder("A player&rsquo;s terminal right after the game starts, showing the "
            "private role reveal line (e.g. &ldquo;~~~ Your role: INVESTIGATOR ~~~&rdquo;) "
            "that only that player received.")
P("<i>Caption:</i> Roles are delivered by <b>unicast</b> &mdash; each player sees "
  "only their own role. This is the server calling <code>send(cid, obj)</code> once "
  "per player.", CAP)

placeholder("The Cult Leader&rsquo;s terminal during a night phase, showing the "
            "private &ldquo;choose someone to recruit&rdquo; prompt and the Leader typing "
            "<code>pitch &lt;name&gt;</code>.")
P("<i>Caption:</i> At night the Leader privately pitches a target. The prompt "
  "and confirmation are unicast to the Leader alone.", CAP)

placeholder("Two terminals side by side during a night: a cult member&rsquo;s "
            "terminal showing a &ldquo;(cult) ...&rdquo; line, and a townsperson&rsquo;s "
            "terminal at the same moment NOT showing it.")
P("<i>Caption:</i> The cult channel is a <b>multicast</b> group. Cult members "
  "see each other&rsquo;s night chat and new-member announcements; townsfolk never "
  "receive these frames.", CAP)

placeholder("The day phase across several terminals, showing the public chat "
            "where each line is attributed to a player name, visible to everyone.")
P("<i>Caption:</i> Day chat is a <b>broadcast</b>. The server attributes each "
  "line using its own record of the sender (tied to the kernel UID), so no one "
  "can speak as another player.", CAP)

placeholder("The voting phase and its result: players typing "
            "<code>vote &lt;name&gt;</code>, &ldquo;X has voted&rdquo; lines, and the server&rsquo;s "
            "announcement of who was exposed (and whether they were a cultist).")
P("<i>Caption:</i> Votes are unicast actions; the tally and outcome are "
  "broadcast. Exposing the Leader ends the game for the town.", CAP)

placeholder("The end-of-game screen showing the winner and the final role "
            "reveal for every player (Leader, Investigator, Skeptic, Townsfolk, "
            "and who was converted/exposed).")
P("<i>Caption:</i> Game over. The server broadcasts the result and the full "
  "role list, then closes every connection cleanly.", CAP)

story.append(PageBreak())

# --------------------------------------------------------------------------
# Communications primitive
# --------------------------------------------------------------------------
P("3. The communications primitive and how it works", H1)
P(
 "The library uses <b>UNIX domain stream sockets</b> (<code>AF_UNIX</code>, "
 "<code>SOCK_STREAM</code>) multiplexed inside a single server process by the "
 "standard-library <code>selectors</code> module, which wraps <i>epoll</i> on "
 "Linux. The server creates one listening socket; every client is a separate "
 "process that connects to it. On each turn of the loop, <code>poll()</code> "
 "asks the selector which sockets are readable and services them, so the "
 "server waits on <i>all</i> players at once and never blocks on any single "
 "one."
)
P(
 "Because a stream socket is a byte stream with no message boundaries, the "
 "library imposes its own framing: every message is a JSON object sent as a "
 "<b>4-byte big-endian length prefix followed by that many bytes of UTF-8 "
 "JSON</b>. The receiver reads the 4-byte header, then loops until it has "
 "exactly that many body bytes, so a frame split or coalesced by the kernel "
 "is always reassembled into one whole message. Identity is established by "
 "the kernel: when a client connects, the server reads the "
 "<code>SO_PEERCRED</code> socket option, which returns the connecting "
 "process&rsquo;s real PID/UID/GID. The game addresses players by a per-connection "
 "id for delivery, but trusts the kernel-supplied UID for &ldquo;who is this "
 "really,&rdquo; so a client cannot forge its identity in the message body."
)
P("The core of the event loop and the framing look like this:")
code(
"""def poll(self, timeout=0.2):
    events = []
    for key, _mask in self.sel.select(timeout=timeout):
        if key.data is None:        # listener readable -> accept
            self._accept(events)
        else:                       # client readable -> read a frame
            self._read(key.fileobj, events)
    return events

def _encode(obj):
    body = json.dumps(obj).encode("utf-8")
    return struct.pack("!I", len(body)) + body   # 4-byte length + JSON

def _peer_uid(sock):
    cred = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _UCRED_SIZE)
    _pid, uid, _gid = struct.unpack("iii", cred)  # kernel-verified identity
    return uid"""
)

# --------------------------------------------------------------------------
# Classmate feedback (placeholder)
# --------------------------------------------------------------------------
P("4. Feedback from classmates", H1)
story.append(Paragraph(
 "[ FILL IN AFTER YOUR CANVAS POST ] &mdash; Replace this paragraph with what "
 "your classmates actually said. The sketch below is a realistic template; "
 "edit it to match the real feedback so the reader learns something concrete.",
 PLACE))
P(
 "I posted a description of The Cult and its <code>cultnet.py</code> library on "
 "Canvas, with a short source excerpt, and asked classmates to assess its "
 "security, robustness against crashes, and overall efficacy. The most useful "
 "feedback was: <i>(example)</i> one classmate pointed out that although "
 "SO_PEERCRED stops identity forgery, the server trusts the <code>name</code> a "
 "client sends in its JOIN message, so a late joiner could pick a confusing "
 "display name; I now de-duplicate names at join time. Another tried to crash "
 "the server by sending a huge length prefix, which led me to confirm the "
 "framing reads bounded bodies and to discuss adding a maximum-frame-size "
 "cap. A third noted that a client that connects but never sends JOIN sits as "
 "an unnamed <code>playerN</code>; we discussed a lobby timeout for silent "
 "connections. <b>Edit this to reflect the real responses you receive.</b>"
)

# --------------------------------------------------------------------------
# Lessons learned
# --------------------------------------------------------------------------
P("5. What I learned about this communications primitive", H1)
P(
 "My game needed all three delivery patterns, and the primitive handled them "
 "in strikingly different ways. <b>Unicast</b> and <b>multicast</b> are not "
 "native features of a stream socket &mdash; a UNIX stream socket is a "
 "point-to-point pipe between two endpoints &mdash; so I implemented them at the "
 "application layer: the server simply keeps a table of connections and writes "
 "the same framed bytes to the chosen subset. &ldquo;Multicast&rdquo; to the cult "
 "channel is therefore just a loop of unicasts to the members I track, and "
 "&ldquo;broadcast&rdquo; is a loop over all of them. This is different from true "
 "IP multicast, where the network layer fans out one datagram; here the fan-out "
 "is explicit and under my control, which is actually convenient because "
 "cult membership changes during the game and I just add a connection id to "
 "the set."
)
P(
 "The biggest lesson was that the <i>event-loop</i> model (one process using "
 "<code>select</code>/epoll over every socket) is what makes the whole thing "
 "both simple and more secure than the named-pipe design we studied earlier. "
 "With pipes, the server blocks on specific per-player FIFOs, and that wait "
 "state is observable &mdash; a side channel that leaks who the server is "
 "attending to. With one selector over all sockets, the server is never "
 "blocked on a particular player, so that side channel disappears. I also "
 "learned to respect stream framing: my first mental model treated each "
 "<code>send</code> as a message, but TCP/UNIX streams can split or merge "
 "writes, so the explicit length prefix is essential &mdash; without it, two "
 "quick sends can arrive as one read and corrupt the protocol. Finally, "
 "SO_PEERCRED was a revelation: getting authenticated identity for free from "
 "the kernel removed an entire class of impersonation bugs that the original "
 "Werewolves code struggled with."
)

story.append(PageBreak())

# --------------------------------------------------------------------------
# Separate section: feedback GIVEN
# --------------------------------------------------------------------------
rule()
P("APPENDIX (SEPARATE SECTION): Feedback I gave to other students", H1)
P(
 "<i>This section is deliberately separate from the report above, as required.</i>",
 SUB)
story.append(Paragraph(
 "[ FILL IN &mdash; put roughly double the effort here that you needed for your "
 "own feedback. Describe concretely what you did with classmates&rsquo; projects. "
 "Replace the template below with your real activity. ]", PLACE))
P(
 "I reviewed the projects of <b>[names/how many]</b> classmates. For each, I "
 "<i>(example of the kind of detail to include)</i>: downloaded and unpacked "
 "their source, read their communications library to understand the primitive "
 "they chose, followed their README to install and run the game, and joined a "
 "session where possible. I specifically looked for exploits and robustness "
 "problems in their communications layer &mdash; for instance, whether their "
 "framing handled partial reads, whether a client could impersonate another "
 "or read traffic meant for others, whether malformed input could crash the "
 "server, and how they cleaned up connections. I reported what I found back to "
 "them on Canvas / in person, with specific reproduction steps where I found a "
 "bug. <b>Replace every bracketed item with the real students, projects, and "
 "findings; name the primitive each used and at least one concrete thing you "
 "discovered or suggested per project.</b>"
)

# --------------------------------------------------------------------------
doc = SimpleDocTemplate(OUT, pagesize=letter,
                        leftMargin=0.8*inch, rightMargin=0.8*inch,
                        topMargin=0.7*inch, bottomMargin=0.7*inch,
                        title="The Cult - Writeup", author="Abhishek Singh")
doc.build(story)
print("wrote", OUT)
