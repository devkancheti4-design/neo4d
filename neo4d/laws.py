"""The laws of the polytope swarm - specified, not written.

The law decides and the body only measures. For every decision the swarm makes, the body turns what it
measured into one byte, the SITUATION WORD, and a law turns that byte into an action. This file holds, for
each law: what each bit means, which words the body can produce, an independent branchy ORACLE that fixes
the table, every PRINCIPLE as a check run by enumeration on any kernel, and the anchors.

The kernels themselves come from the superoptimizer (prompts/*.md, generated from this file by
make_prompts.py). judge.py runs a kernel against everything here.

    HOP     8-cell only       which link to cross - the node id IS the address
    QUORUM  5-cell only       commit, abort or wait - every node hears every node in one round
    STEP    every shape       how good one neighbour is as the next hop
    ADMIT   every shape       what to do with a packet that just arrived
    MIRROR  centrally         where a read or write for one key goes, and when to repair -
            symmetric shapes  the copy lives at the antipode
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable

Kernel = Callable[[int], int]


def popc(x: int) -> int:
    return bin(x).count("1")


def low(x: int) -> int:
    """Index of the lowest set bit; x > 0."""
    return (x & -x).bit_length() - 1


def bit(x: int, i: int) -> int:
    return (x >> i) & 1


@dataclass
class Principle:
    id: str
    statement: str
    check: Callable[[Kernel, list[int]], list[int]]   # -> the words that violate it


@dataclass
class Law:
    name: str
    title: str
    shapes: str
    question: str
    range_hi: int                       # every output on 0..255 must land in 0..range_hi
    bits: list[tuple[str, str, str]]    # (bit position(s), name, set when)
    word: str                           # how the situation word is assembled
    reachable: Callable[[int], bool]
    unreachable_rules: list[str]
    oracle: Callable[[int], int]
    outputs: list[tuple[str, str]]      # (value(s), meaning)
    principles: list[Principle]
    verdict_name: Callable[[int], str] = lambda v: str(v)
    anchors: list[tuple[int, str]] = field(default_factory=list)   # (x, situation); want = oracle(x)

    def reach(self) -> list[int]:
        return [x for x in range(256) if self.reachable(x)]


def _cmp_pairs(k, R, key, nonzero_only=True):
    """Pairs (x, y) of reachable words, both ranked above 0, ordered by key."""
    live = [x for x in R if not nonzero_only or k(x) > 0]
    return [(x, y) for x in live for y in live if key(x) > key(y)]


# ======================================================================================= HOP (8-cell)
#   bits 0-3 DIFF  bit k: the destination's address differs from this node's in bit k
#   bits 4-7 DEAD  bit k: link k cannot be used
#   hop(x): 0..3 FORWARD across link d   4..7 DETOUR across link d-4   8 DELIVER   12 HOLD

def _hop_oracle(x):
    diff, dead = x & 15, x >> 4
    live = ~dead & 15
    if diff == 0:
        return 8
    if diff & live:
        return low(diff & live)
    if ~diff & live & 15:
        return 4 + low(~diff & live & 15)
    return 12


def _hop_principles():
    D = lambda x: x & 15
    L = lambda x: ~(x >> 4) & 15
    return [
        Principle("H0", "**Arrived.** `DIFF = 0`: DELIVER (8), whatever `DEAD` says.",
                  lambda k, R: [x for x in R if D(x) == 0 and k(x) != 8]),
        Principle("H1", "**Minimal while possible.** Some differing link is live: FORWARD across a live differing link "
                        "- the hop that lowers the distance (popcount of `DIFF`) by exactly one.",
                  lambda k, R: [x for x in R if D(x) & L(x) and not (0 <= k(x) <= 3 and ((D(x) & L(x)) >> k(x)) & 1)]),
        Principle("H2", "**Dimension order.** Of the live differing links, the LOWEST. On a whole cube this is e-cube "
                        "routing: every route is minimal and every packet crosses dimensions in ascending order, so "
                        "channel dependencies only ascend and routes cannot deadlock.",
                  lambda k, R: [x for x in R if D(x) & L(x) and k(x) != low(D(x) & L(x))]),
        Principle("H3", "**Detour only when blocked.** Every differing link is dead but a non-differing link is live: "
                        "DETOUR (4 + d) across the lowest live non-differing link. It costs two hops (out, and back "
                        "across the same dimension later) and is the only way forward.",
                  lambda k, R: [x for x in R if D(x) and not D(x) & L(x) and ~D(x) & L(x) & 15
                                and k(x) != 4 + low(~D(x) & L(x) & 15)]),
        Principle("H4", "**Nothing live, hold.** `DIFF != 0` and every link dead: HOLD (12).",
                  lambda k, R: [x for x in R if D(x) and L(x) == 0 and k(x) != 12]),
        Principle("H5", "**Never across a dead link.** A FORWARD or DETOUR names a live link.",
                  lambda k, R: [x for x in R if 0 <= k(x) <= 7 and not L(x) >> (k(x) & 3) & 1]),
        Principle("H6", "**Kinds are what they say.** FORWARD only across a differing link, DETOUR only across a "
                        "non-differing one, DETOUR never while a differing link is live, DELIVER only at "
                        "`DIFF = 0`, HOLD only when nothing is live.",
                  lambda k, R: [x for x in R if
                                (0 <= k(x) <= 3 and not D(x) >> k(x) & 1)
                                or (4 <= k(x) <= 7 and (D(x) >> (k(x) & 3) & 1 or D(x) & L(x)))
                                or (k(x) == 8 and D(x))
                                or (k(x) == 12 and (D(x) == 0 or L(x)))
                                or k(x) in (9, 10, 11, 13, 14, 15)]),
    ]


HOP = Law(
    name="hop",
    title="the HOP law",
    shapes="8-cell (the tesseract) only",
    question="Which of this node's four links a packet crosses next - decided for ONE packet at ONE node, from "
             "eight measured bits and nothing else.",
    range_hi=15,
    bits=[
        ("0", "DIFF0", "the destination's address differs from this node's in bit 0 - it lies across link 0"),
        ("1", "DIFF1", "... in bit 1 - across link 1"),
        ("2", "DIFF2", "... in bit 2 - across link 2"),
        ("3", "DIFF3", "... in bit 3 - across link 3"),
        ("4", "DEAD0", "link 0 cannot be used: it missed its heartbeat, or it is the link this packet arrived on "
                       "by a DETOUR (so a detour is never undone on the next hop)"),
        ("5", "DEAD1", "the same, link 1"),
        ("6", "DEAD2", "the same, link 2"),
        ("7", "DEAD3", "the same, link 3"),
    ],
    word="x = (here XOR destination) | DEAD << 4",
    reachable=lambda x: True,
    unreachable_rules=["None. Every combination of differing bits and dead links occurs."],
    oracle=_hop_oracle,
    outputs=[("0..3", "FORWARD across link d - one hop nearer"),
             ("4..7", "DETOUR across link d - 4 - one hop farther, only way on"),
             ("8", "DELIVER - this node is the destination"),
             ("12", "HOLD - keep the packet this tick, nothing is live"),
             ("9-11, 13-15", "never produced")],
    principles=_hop_principles(),
    verdict_name=lambda v: {8: "DELIVER", 12: "HOLD"}.get(v, f"FWD{v}" if v < 4 else f"DET{v-4}" if v < 8 else "?"),
)


# =================================================================================== QUORUM (5-cell)
#   bits 0-3 HEARD  bit i: peer i's vote arrived this round
#   bits 4-7 YES    bit i: peer i voted yes (only measurable if HEARD)
#   this node voted yes - a node voting no aborts on its own and never consults the law
#   quorum(x): 0 WAIT  1 COMMIT  2 ABORT

def _q_oracle(x):
    heard, yes = x & 15, x >> 4
    if popc(yes) >= 2:
        return 1
    if popc(heard & ~yes) >= 3:
        return 2
    return 0


def _q_view(votes, heard):
    return heard | (votes & heard) << 4


def _q_perm(x, p):
    h, y = x & 15, x >> 4
    ph = sum(bit(h, i) << p[i] for i in range(4))
    py = sum(bit(y, i) << p[i] for i in range(4))
    return ph | py << 4


def _q_principles():
    Y = lambda x: popc(x >> 4)
    N = lambda x: popc(x & 15 & ~(x >> 4))

    def agreement(k, R):
        bad = []
        for v in range(16):
            ks = {k(_q_view(v, h)) for h in range(16)}
            if 1 in ks and 2 in ks:
                bad.append(_q_view(v, 15))
        return bad

    def monotone(k, R):
        bad = []
        for v in range(16):
            for h1 in range(16):
                for h2 in range(16):
                    if h1 & ~h2 == 0:
                        a, b = k(_q_view(v, h1)), k(_q_view(v, h2))
                        if a in (1, 2) and b != a:
                            bad.append(_q_view(v, h1))
        return sorted(set(bad))

    def symmetric(k, R):
        return sorted({x for x in R for p in itertools.permutations(range(4)) if k(_q_perm(x, p)) != k(x)})

    return [
        Principle("Q0", "**Three yes of five commit.** This node's yes and at least two peers' yes: COMMIT (1).",
                  lambda k, R: [x for x in R if Y(x) >= 2 and k(x) != 1]),
        Principle("Q1", "**Three no of five abort.** At least three peers heard voting no: ABORT (2).",
                  lambda k, R: [x for x in R if N(x) >= 3 and k(x) != 2]),
        Principle("Q2", "**Silence is not a vote.** Otherwise WAIT (0). An unheard peer is neither yes nor no; no "
                        "verdict rests on who has not answered.",
                  lambda k, R: [x for x in R if Y(x) < 2 and N(x) < 3 and k(x) != 0]),
        Principle("Q3", "**Agreement.** For any one assignment of votes, no two partial views of it - two nodes "
                        "hearing different subsets of the peers - may yield COMMIT for one and ABORT for the other. "
                        "Two majorities of five always share a voter, and a voter votes once. Checked over all 16 "
                        "vote assignments and all 16 x 16 pairs of heard sets.",
                  agreement),
        Principle("Q4", "**Hearing more never un-decides.** If a view yields COMMIT or ABORT, every view that has heard "
                        "a superset of the same votes yields the same verdict.",
                  monotone),
        Principle("Q5", "**Peers are interchangeable.** Every permutation of the four peers is a symmetry of the "
                        "5-cell, so permuting the peer indices (in HEARD and YES together) never changes the verdict. "
                        "Checked on all 24 permutations.",
                  symmetric),
    ]


QUORUM = Law(
    name="quorum",
    title="the QUORUM law",
    shapes="5-cell only",
    question="Whether this node commits, aborts, or keeps waiting on one proposal - decided from the votes it has "
             "heard this round and nothing else.",
    range_hi=3,
    bits=[
        ("0", "HEARD1", "peer 1's vote arrived this round"),
        ("1", "HEARD2", "peer 2's vote arrived"),
        ("2", "HEARD3", "peer 3's vote arrived"),
        ("3", "HEARD4", "peer 4's vote arrived"),
        ("4", "YES1", "peer 1 voted yes"),
        ("5", "YES2", "peer 2 voted yes"),
        ("6", "YES3", "peer 3 voted yes"),
        ("7", "YES4", "peer 4 voted yes"),
    ],
    word="x = HEARD | YES << 4   (this node itself voted yes: a node that votes no aborts on its own and never "
         "consults the law)",
    reachable=lambda x: (x >> 4) & ~x & 15 == 0,
    unreachable_rules=["`YES` bit i without `HEARD` bit i - an unheard vote is unmeasured, and an unmeasured lane is "
                       "silent, not set."],
    oracle=_q_oracle,
    outputs=[("0", "WAIT"), ("1", "COMMIT"), ("2", "ABORT"), ("3", "never produced on a reachable word")],
    principles=_q_principles(),
    verdict_name=lambda v: {0: "WAIT", 1: "COMMIT", 2: "ABORT"}.get(v, "?"),
)


# ===================================================================================== STEP (any shape)
#   bit 0   LIVE     the link and the neighbour answered the last heartbeat
#   bit 1-2 DIST     the neighbour vs this node, hops to the destination: 0 one farther, 1 the same,
#                    2 one nearer, 3 the neighbour IS the destination
#   bit 3   ROOM     LIVE and the neighbour reported its queue at most half full
#   bit 4   FULL     LIVE and the neighbour reported its queue full
#   bit 5   QUIET    this node sent nothing across that link last tick
#   bit 6   VISITED  the packet's path record already holds the neighbour
#   bit 7   AHEAD    some neighbour of this node is LIVE, nearer (DIST 2 or 3) and not VISITED - full or not
#   step(x): 0 never this neighbour; higher = take first

def _step_fields(x):
    return x & 1, (x >> 1) & 3, bit(x, 3), bit(x, 4), bit(x, 5), bit(x, 6), bit(x, 7)


def _step_reachable(x):
    live, d, room, full, quiet, vis, ahead = _step_fields(x)
    if room and full:
        return False
    if not live and (room or full):
        return False
    if d == 3 and vis:
        return False
    if live and d >= 2 and not vis and not ahead:
        return False
    return True


def _step_oracle(x):
    live, d, room, full, quiet, vis, ahead = _step_fields(x)
    if not live or vis:
        return 0
    if d == 3:
        return 10
    if full:
        return 0
    if ahead and d < 2:
        return 0
    return 1 + 3 * d + room + quiet


def _step_principles():
    F = _step_fields
    dist = lambda x: F(x)[1]
    load = lambda x: F(x)[2] + F(x)[4]

    def s3(k, R):
        return sorted({x for x, y in _cmp_pairs(k, R, dist) if k(x) <= k(y)})

    def s4(k, R):
        nz = [x for x in R if k(x) > 0 and dist(x) < 3]
        bad = set()
        for x in nz:
            for y in nz:
                if dist(x) == dist(y):
                    if load(x) > load(y) and k(x) <= k(y):
                        bad.add(x)
                    if load(x) == load(y) and k(x) != k(y):
                        bad.add(x)
        return sorted(bad)

    def s6(k, R):
        got = {k(x) for x in R}
        return [] if got == set(range(11)) else [min(R)]

    return [
        Principle("S0", "**The veto.** Not `LIVE`, or `VISITED`: 0 - a path never revisits a node, so no packet "
                        "loops. `FULL` and not the destination: 0 - backpressure; the destination consumes, it does "
                        "not queue.",
                  lambda k, R: [x for x in R if (not F(x)[0] or F(x)[5] or (F(x)[3] and F(x)[1] != 3)) and k(x) != 0]),
        Principle("S1", "**The destination first.** A live neighbour that IS the destination: 10, strictly above "
                        "every other rank.",
                  lambda k, R: [x for x in R if F(x)[0] and F(x)[1] == 3 and not F(x)[5] and k(x) != 10]),
        Principle("S2", "**Wait for progress, never wander.** `AHEAD` and the neighbour is not nearer: 0. When a "
                        "nearer neighbour is live but full, the packet waits for it - congestion passes, a detour's "
                        "extra hops do not.",
                  lambda k, R: [x for x in R if F(x)[6] and F(x)[1] < 2 and k(x) != 0]),
        Principle("S3", "**Progress outranks load.** Of two neighbours both ranked above 0, the nearer one ranks "
                        "strictly higher, whatever `ROOM` and `QUIET` say. Load chooses only among the nearer "
                        "neighbours, wherever the shape offers more than one (table above) - it is never traded "
                        "against progress.",
                  s3),
        Principle("S4", "**Load is counted, not weighted.** At the same `DIST`, the rank follows `ROOM + QUIET`: more "
                        "ranks strictly higher, equal counts rank equal - `ROOM` alone ties `QUIET` alone.",
                  s4),
        Principle("S5", "**Usable unless vetoed.** A live, unvisited, not-full neighbour ranks at least 1 unless S2 "
                        "forbids it. So a nearer neighbour is always usable, and when not `AHEAD` (every nearer "
                        "neighbour dead or visited) one at the same distance or farther is too - a detour around "
                        "faults, and the packet can still move.",
                  lambda k, R: [x for x in R if F(x)[0] and not F(x)[5] and not F(x)[3]
                                and not (F(x)[6] and F(x)[1] < 2) and k(x) < 1]),
        Principle("S6", "**Dense.** The ranks produced on reachable words are exactly 0..10, no gaps.", s6),
    ]


STEP = Law(
    name="step",
    title="the STEP law",
    shapes="every shape - 5-, 8-, 16-, 24-, 120- and 600-cell",
    question="How good ONE neighbour is as the next hop for ONE packet - decided from eight measured bits and "
             "nothing else. The body ranks every neighbour and sends to the highest; ties go to the lowest "
             "neighbour index; if every rank is 0 the packet stays this tick.",
    range_hi=15,
    bits=[
        ("0", "LIVE", "the link and the neighbour answered the last heartbeat"),
        ("1-2", "DIST", "the neighbour's hops to the destination against this node's, from the shape's distance "
                        "table: `0` one farther, `1` the same, `2` one nearer, `3` the neighbour IS the destination. "
                        "(A neighbour's distance can differ by at most one, in any graph.)"),
        ("3", "ROOM", "`LIVE`, and the neighbour reported its queue at most half full"),
        ("4", "FULL", "`LIVE`, and the neighbour reported its queue full"),
        ("5", "QUIET", "this node sent nothing across that link last tick (measured locally - known even when the "
                       "link is down)"),
        ("6", "VISITED", "the packet's path record already holds the neighbour"),
        ("7", "AHEAD", "some neighbour of this node is `LIVE`, nearer (`DIST` 2 or 3) and not `VISITED` - full or "
                       "not. The same value for every neighbour in one decision"),
    ],
    word="x = LIVE | DIST << 1 | ROOM << 3 | FULL << 4 | QUIET << 5 | VISITED << 6 | AHEAD << 7",
    reachable=_step_reachable,
    unreachable_rules=[
        "`ROOM` and `FULL` together - at most half full and full.",
        "`ROOM` or `FULL` without `LIVE` - queue state rides on the heartbeat; with no heartbeat that lane is "
        "unmeasured, and an unmeasured lane is silent, not set.",
        "`DIST = 3` with `VISITED` - a packet that visited its destination was delivered there.",
        "`LIVE`, `DIST >= 2`, not `VISITED`, and not `AHEAD` - this neighbour is itself a live unvisited nearer "
        "neighbour, so `AHEAD` holds.",
    ],
    oracle=_step_oracle,
    outputs=[("0", "never this neighbour"), ("1..9", "a usable hop, higher first"), ("10", "the destination itself"),
             ("11-15", "never produced on a reachable word")],
    principles=_step_principles(),
)


# ==================================================================================== ADMIT (any shape)
#   bit 0   MINE        this node is the packet's destination
#   bit 1   DUP         this node already holds or has delivered this packet id
#   bit 2-3 Q           this node's queue: 0 empty, 1 under half, 2 half or more, 3 full
#   bit 4   LAST_HOP    the packet's hop budget is spent on arriving here
#   bit 5   COPY        the packet is the antipodal mirror copy, not the original
#   bit 6   URGENT      the packet is marked urgent
#   bit 7   SPENT       the sender has already been bounced the maximum number of times for this packet
#   admit(x): 0 DROP  1 ACCEPT  2 DELIVER  3 BOUNCE

def _admit_fields(x):
    return bit(x, 0), bit(x, 1), (x >> 2) & 3, bit(x, 4), bit(x, 5), bit(x, 6), bit(x, 7)


def _admit_oracle(x):
    mine, dup, q, last, copy, urgent, spent = _admit_fields(x)
    if dup:
        return 0
    if mine:
        return 2
    if last:
        return 0
    if q == 3:
        return 0 if spent else 3
    if copy and q == 2 and not urgent:
        return 0 if spent else 3
    return 1


def _admit_principles():
    F = _admit_fields
    yields = lambda x: F(x)[4] and F(x)[2] == 2 and not F(x)[5]
    open_ = lambda x: not F(x)[0] and not F(x)[1] and not F(x)[3]

    def a7(k, R):
        return [x for x in R if not F(x)[6] and k(x | 128) != (0 if k(x) == 3 else k(x))]

    return [
        Principle("A0", "**At most once.** `DUP`: DROP, always - a packet is delivered or forwarded once, however many "
                        "copies and retries reach a node.",
                  lambda k, R: [x for x in R if F(x)[1] and k(x) != 0]),
        Principle("A1", "**The destination consumes.** `MINE` and not `DUP`: DELIVER, whatever the queue, the budget "
                        "and the flags say - delivery does not use the forwarding queue.",
                  lambda k, R: [x for x in R if F(x)[0] and not F(x)[1] and k(x) != 2]),
        Principle("A2", "**The budget is respected.** Not `MINE` and `LAST_HOP`: DROP - it cannot go further, and "
                        "holding it would keep a slot forever.",
                  lambda k, R: [x for x in R if not F(x)[0] and not F(x)[1] and F(x)[3] and k(x) != 0]),
        Principle("A3", "**Backpressure, never silent loss.** Forwardable and the queue is full (`Q = 3`): BOUNCE - the "
                        "sender keeps it and retries - or DROP once `SPENT`.",
                  lambda k, R: [x for x in R if open_(x) and F(x)[2] == 3 and k(x) != (0 if F(x)[6] else 3)]),
        Principle("A4", "**Copies yield first.** Forwardable, a `COPY`, not `URGENT`, queue half or more (`Q = 2`): "
                        "BOUNCE, or DROP once `SPENT` - the original exists elsewhere; slots go to originals.",
                  lambda k, R: [x for x in R if open_(x) and yields(x) and k(x) != (0 if F(x)[6] else 3)]),
        Principle("A5", "**Otherwise ACCEPT.** An original at half or more is accepted; an urgent copy is treated as "
                        "an original.",
                  lambda k, R: [x for x in R if open_(x) and F(x)[2] < 3 and not yields(x) and k(x) != 1]),
        Principle("A6", "**Never DELIVER what is not `MINE`; never ACCEPT into a full queue.**",
                  lambda k, R: [x for x in R if (k(x) == 2 and not F(x)[0]) or (k(x) == 1 and F(x)[2] == 3)]),
        Principle("A7", "**`SPENT` only turns BOUNCE into DROP.** Setting it changes no other verdict.", a7),
    ]


ADMIT = Law(
    name="admit",
    title="the ADMIT law",
    shapes="every shape",
    question="What a node does with ONE packet that just arrived - decided from eight measured bits and nothing "
             "else.",
    range_hi=3,
    bits=[
        ("0", "MINE", "this node is the packet's destination"),
        ("1", "DUP", "this node already holds, or has delivered, this packet id"),
        ("2-3", "Q", "this node's forwarding queue: `0` empty, `1` under half, `2` half or more, `3` full"),
        ("4", "LAST_HOP", "the packet's hop budget is spent on arriving here"),
        ("5", "COPY", "the packet is the antipodal mirror copy (MIRROR law), not the original"),
        ("6", "URGENT", "the packet is marked urgent"),
        ("7", "SPENT", "this packet has already been bounced the maximum number of times"),
    ],
    word="x = MINE | DUP << 1 | Q << 2 | LAST_HOP << 4 | COPY << 5 | URGENT << 6 | SPENT << 7",
    reachable=lambda x: True,
    unreachable_rules=["None - every combination occurs."],
    oracle=_admit_oracle,
    outputs=[("0", "DROP"), ("1", "ACCEPT - queue it for forwarding"), ("2", "DELIVER - consume it here"),
             ("3", "BOUNCE - refuse; the sender keeps it and retries")],
    principles=_admit_principles(),
    verdict_name=lambda v: {0: "DROP", 1: "ACCEPT", 2: "DELIVER", 3: "BOUNCE"}.get(v, "?"),
)


# ==================================================================== MIRROR (centrally symmetric shapes)
#   bit 0 HOME_UP      the key's home node answered
#   bit 1 MIRROR_UP    its mirror - the home's antipode - answered
#   bit 2 HOME_CUR     the home holds the version of the key's last acknowledged write
#   bit 3 MIRROR_CUR   the mirror does
#   bit 4 NEAR_MIRROR  the requester is strictly fewer hops from the mirror than from the home
#   bit 5 WRITE        the operation is a write (else a read)
#   bit 6 REPAIRING    a repair of this key is already in flight
#   bit 7 ONE_OK       the key's policy allows acknowledging a write held by one copy
#   mirror(x): bits 0-1 TARGET 0 NONE 1 HOME 2 MIRROR 3 BOTH;  bit 2 REPAIR

def _m_fields(x):
    return tuple(bit(x, i) for i in range(8))


def _m_reachable(x):
    hu, mu, hc, mc, nm, w, rep, one = _m_fields(x)
    if hc and not hu:
        return False
    if mc and not mu:
        return False
    if hu and mu and not hc and not mc:
        return False
    return True


def _m_oracle(x):
    hu, mu, hc, mc, nm, w, rep, one = _m_fields(x)
    if w:
        if hu and mu:
            return 3
        if hu:
            return 1 if one else 0
        if mu:
            return 2 if one else 0
        return 0
    hok, mok = hu and hc, mu and mc
    if hok and mok:
        t = 2 if nm else 1
    elif hok:
        t = 1
    elif mok:
        t = 2
    else:
        t = 0
    repair = ((hok and mu and not mc) or (mok and hu and not hc)) and not rep
    return t | (4 if repair else 0)


def _m_principles():
    F = _m_fields
    T = lambda k, x: k(x) & 3
    REP = lambda k, x: (k(x) >> 2) & 1
    hok = lambda x: F(x)[0] and F(x)[2]
    mok = lambda x: F(x)[1] and F(x)[3]
    read = lambda x: not F(x)[5]

    def m4(k, R):
        bad = []
        for x in R:
            hu, mu, hc, mc, nm, w, rep, one = F(x)
            if not w or (hu and mu):
                continue
            want = 0 if not (hu or mu) else (0 if not one else (1 if hu else 2))
            if T(k, x) != want:
                bad.append(x)
        return bad

    def m5(k, R):
        bad = []
        for x in R:
            hu, mu, hc, mc, nm, w, rep, one = F(x)
            want = int(read(x) and not rep and bool((hok(x) and mu and not mc) or (mok(x) and hu and not hc)))
            if REP(k, x) != want:
                bad.append(x)
        return bad

    return [
        Principle("M0", "**Never serve stale.** A read goes to exactly one copy, and only to one that is up AND "
                        "current - or to none.",
                  lambda k, R: [x for x in R if read(x) and (T(k, x) == 3 or (T(k, x) == 1 and not hok(x))
                                                             or (T(k, x) == 2 and not mok(x)))]),
        Principle("M1", "**Never refuse while a current copy is up.** A read with an up, current copy has a target.",
                  lambda k, R: [x for x in R if read(x) and (hok(x) or mok(x)) and T(k, x) == 0]),
        Principle("M2", "**The nearer current copy; ties go home.** Both up and current: the mirror if "
                        "`NEAR_MIRROR`, else the home.",
                  lambda k, R: [x for x in R if read(x) and hok(x) and mok(x) and T(k, x) != (2 if F(x)[4] else 1)]),
        Principle("M3", "**Writes go to every live copy.** A write with both copies up: BOTH - which overwrites a "
                        "stale copy with no repair needed.",
                  lambda k, R: [x for x in R if F(x)[5] and F(x)[0] and F(x)[1] and T(k, x) != 3]),
        Principle("M4", "**One live copy: only if the key allows it.** A write with exactly one copy up goes to that "
                        "copy if `ONE_OK`, else to NONE - never acknowledge a write below the key's durability. "
                        "Neither up: NONE.",
                  m4),
        Principle("M5", "**Repair heals, once.** REPAIR is set exactly when the operation is a read, no repair is in "
                        "flight, and one copy is up and current while the other is up and stale. A write never sets "
                        "it: BOTH overwrites the stale copy itself, and a write to one copy has no live stale copy to "
                        "repair.",
                  m5),
        Principle("M6", "**Never a down copy.** No target includes a copy that did not answer.",
                  lambda k, R: [x for x in R if (T(k, x) in (1, 3) and not F(x)[0]) or (T(k, x) in (2, 3) and not F(x)[1])]),
    ]


MIRROR = Law(
    name="mirror",
    title="the MIRROR law",
    shapes="the centrally symmetric shapes - 8-, 16-, 24-, 120- and 600-cell (the 5-cell has no antipodes)",
    question="Where ONE read or write of ONE key goes, and whether it starts a repair - decided from eight "
             "measured bits and nothing else. Every key lives on its home node and on the home's antipode, the "
             "mirror.",
    range_hi=7,
    bits=[
        ("0", "HOME_UP", "the key's home node answered"),
        ("1", "MIRROR_UP", "its mirror - the home's antipode - answered"),
        ("2", "HOME_CUR", "the home holds the version of the key's last acknowledged write (from the key's write "
                          "log; a key never written is current everywhere)"),
        ("3", "MIRROR_CUR", "the mirror does"),
        ("4", "NEAR_MIRROR", "the requester is strictly fewer hops from the mirror than from the home"),
        ("5", "WRITE", "the operation is a write (else a read)"),
        ("6", "REPAIRING", "a repair of this key is already in flight"),
        ("7", "ONE_OK", "the key's policy allows acknowledging a write held by one copy"),
    ],
    word="x = HOME_UP | MIRROR_UP << 1 | HOME_CUR << 2 | MIRROR_CUR << 3 | NEAR_MIRROR << 4 | WRITE << 5 "
         "| REPAIRING << 6 | ONE_OK << 7",
    reachable=_m_reachable,
    unreachable_rules=[
        "`HOME_CUR` without `HOME_UP`, or `MIRROR_CUR` without `MIRROR_UP` - a node that did not answer has no "
        "measured version; the lane is silent.",
        "Both up and neither current - every acknowledged write is held by at least one copy, and storage is "
        "durable, so when both answer at least one holds the last acknowledged version.",
    ],
    oracle=_m_oracle,
    outputs=[("bits 0-1 = 0", "NONE - refuse (unavailable, never wrong)"), ("bits 0-1 = 1", "HOME"),
             ("bits 0-1 = 2", "MIRROR"), ("bits 0-1 = 3", "BOTH (writes only)"),
             ("bit 2", "REPAIR - copy the current copy over the stale one")],
    principles=_m_principles(),
    verdict_name=lambda v: ["NONE", "HOME", "MIRROR", "BOTH"][v & 3] + ("+R" if v & 4 else ""),
)


# ===================================================================== CARRY (fluidnet on any shape)
#   after one net has worked on a job: what travels on
#   bit 0 GREEN       no test fails now
#   bit 1 STABLE      re-running the suite on the current code gave the same failing set
#   bit 2 BROKE       a test that passed when the job left its edge node fails now
#   bit 3 UNPROVEN    some step in the carried repair rests on a class with no property proof
#   bit 4 STRICT      the job's policy demands every step proven
#   bit 5 PLAN_LEFT   the code still shows the signals of a dictionary not yet visited, with a live copy
#   bit 6 SPENT       the job's visit budget is spent
#   bit 7 RECHECKED   this state was already re-run once for stability
#   carry(x): 0 REFUSE  1 CARRY  2 ACCEPT  3 RECHECK

def _carry_fields(x):
    return tuple(bit(x, i) for i in range(8))


def _carry_oracle(x):
    green, stable, broke, unproven, strict, plan, spent, rechecked = _carry_fields(x)
    if broke:
        return 0
    if not stable:
        return 0 if rechecked else 3
    if green:
        return 0 if (strict and unproven) else 2
    if plan and not spent:
        return 1
    return 0


def _carry_principles():
    F = _carry_fields
    ok_accept = lambda x: F(x)[0] and F(x)[1] and not F(x)[2] and not (F(x)[4] and F(x)[3])
    return [
        Principle("C0", "**Accept exactly the certifiable.** ACCEPT (2) when, and only when, `GREEN`, `STABLE`, not "
                        "`BROKE`, and not (`STRICT` and `UNPROVEN`). Partial progress travels; only a green, stable, "
                        "provable module ever ships.",
                  lambda k, R: [x for x in R if (k(x) == 2) != bool(ok_accept(x))]),
        Principle("C1", "**Fail closed.** `BROKE`: REFUSE (0) - an edit that broke a passing test neither travels "
                        "nor ships; the original returns to the edge untouched.",
                  lambda k, R: [x for x in R if F(x)[2] and k(x) != 0]),
        Principle("C2", "**Instability is not evidence.** Not `STABLE` (and not `BROKE`): RECHECK (3) once; once "
                        "`RECHECKED`, REFUSE - flaky.",
                  lambda k, R: [x for x in R if not F(x)[1] and not F(x)[2] and k(x) != (0 if F(x)[7] else 3)]),
        Principle("C3", "**A green that cannot be certified is refused.** `GREEN`, `STABLE`, `STRICT` and "
                        "`UNPROVEN`: REFUSE - no later net can prove a step already taken.",
                  lambda k, R: [x for x in R if F(x)[0] and F(x)[1] and not F(x)[2] and F(x)[4] and F(x)[3]
                                and k(x) != 0]),
        Principle("C4", "**Carry while there is somewhere to go.** Red, `STABLE`, not `BROKE`, `PLAN_LEFT`, not "
                        "`SPENT`: CARRY (1) - whether or not this visit helped, another net may.",
                  lambda k, R: [x for x in R if not F(x)[0] and F(x)[1] and not F(x)[2] and F(x)[5]
                                and not F(x)[6] and k(x) != 1]),
        Principle("C5", "**Partial never ships.** Red, `STABLE`, not `BROKE`, and no plan left or the budget spent: "
                        "REFUSE.",
                  lambda k, R: [x for x in R if not F(x)[0] and F(x)[1] and not F(x)[2]
                                and (not F(x)[5] or F(x)[6]) and k(x) != 0]),
        Principle("C6", "**RECHECK only for instability.** A stable state is never rechecked, and `RECHECKED` never "
                        "yields RECHECK again.",
                  lambda k, R: [x for x in R if k(x) == 3 and (F(x)[1] or F(x)[7])]),
    ]


CARRY = Law(
    name="carry",
    title="the CARRY law",
    shapes="every shape - fluidnet's nets on the polytope",
    question="After one net has worked on a job, what travels on: the partial repair, the certified module, a "
             "recheck, or nothing - decided from eight measured bits and nothing else.",
    range_hi=3,
    bits=[
        ("0", "GREEN", "no test fails now"),
        ("1", "STABLE", "re-running the suite on the current code gave the same failing set"),
        ("2", "BROKE", "a test that passed when the job left its edge node fails now"),
        ("3", "UNPROVEN", "some step in the carried repair rests on a class with no property proof (fluidfix "
                          "fails open: no property is UNPROVEN, not REFUTED)"),
        ("4", "STRICT", "the job's policy demands every step proven"),
        ("5", "PLAN_LEFT", "the code still shows the signals of a dictionary not yet visited, and a copy of it is "
                           "live"),
        ("6", "SPENT", "the job's visit budget is spent"),
        ("7", "RECHECKED", "this state was already re-run once for stability"),
    ],
    word="x = GREEN | STABLE << 1 | BROKE << 2 | UNPROVEN << 3 | STRICT << 4 | PLAN_LEFT << 5 | SPENT << 6 "
         "| RECHECKED << 7",
    reachable=lambda x: not (bit(x, 0) and bit(x, 2)),
    unreachable_rules=["`GREEN` with `BROKE` - green means no test fails, so none that passed fails."],
    oracle=_carry_oracle,
    outputs=[("0", "REFUSE - the original returns to the edge, untouched"),
             ("1", "CARRY - the partial repair travels to the next net"),
             ("2", "ACCEPT - certified; ship it"), ("3", "RECHECK - re-run the suite once")],
    principles=_carry_principles(),
    verdict_name=lambda v: {0: "REFUSE", 1: "CARRY", 2: "ACCEPT", 3: "RECHECK"}.get(v, "?"),
)


# ====================================================================== SEEK (fluidnet on any shape)
#   rank ONE candidate net - a live copy of a dictionary the job still wants - as the next visit
#   bit 0   LIVE           the copy answered (the MIRROR law chose it)
#   bit 1-2 NEAR           hops from here: 0 here, 1 one hop, 2 at most half the diameter, 3 farther
#   bit 3-4 HITS           lines of the current code its taught signals match: 0, 1, 2, 3 or more
#   bit 5   TRIED          this dictionary already worked on this job
#   bit 6   UNCERTIFIABLE  the job is STRICT and a class whose signal hits has no property
#   bit 7   FULL           the net reported its queue full
#   seek(x): 0 never; higher = visit first

def _seek_fields(x):
    return bit(x, 0), (x >> 1) & 3, (x >> 3) & 3, bit(x, 5), bit(x, 6), bit(x, 7)


def _seek_reachable(x):
    live, near, hits, tried, unc, full = _seek_fields(x)
    if near == 0 and not tried:          # the net here works on every job that reaches it, on arrival
        return False
    if full and not live:                # no heartbeat, no queue report
        return False
    return True


def _seek_oracle(x):
    live, near, hits, tried, unc, full = _seek_fields(x)
    if not live or tried or hits == 0 or unc or full:
        return 0
    return 1 + 3 * (hits - 1) + (3 - near)          # NEAR is 1..3 here: band 0 is always TRIED


def _seek_principles():
    F = _seek_fields

    def k1(k, R):
        nz = [x for x in R if k(x) > 0]
        return sorted({x for x in nz for y in nz if F(x)[2] > F(y)[2] and k(x) <= k(y)})

    def k2(k, R):
        nz = [x for x in R if k(x) > 0]
        return sorted({x for x in nz for y in nz if F(x)[2] == F(y)[2] and F(x)[1] < F(y)[1] and k(x) <= k(y)}
                      | {x for x in nz for y in nz if F(x)[2] == F(y)[2] and F(x)[1] == F(y)[1] and k(x) != k(y)})

    return [
        Principle("K0", "**The veto.** Not `LIVE`, `TRIED`, `HITS = 0`, `UNCERTIFIABLE`, or `FULL`: 0 - never visit "
                        "a net that cannot answer, has had its turn, sees nothing in the code, cannot be certified, "
                        "or cannot take the job.",
                  lambda k, R: [x for x in R if (not F(x)[0] or F(x)[3] or F(x)[2] == 0 or F(x)[4] or F(x)[5])
                                and k(x) != 0]),
        Principle("K1", "**Evidence before distance.** Of two candidates ranked above 0, more `HITS` ranks strictly "
                        "higher, however far. A visit costs suite runs; a hop costs one message.",
                  k1),
        Principle("K2", "**Then the nearer.** Same `HITS`: the nearer band ranks strictly higher; same band, equal "
                        "rank.",
                  k2),
        Principle("K3", "**Usable unless vetoed.** A candidate that passes the veto ranks at least 1.",
                  lambda k, R: [x for x in R if F(x)[0] and not F(x)[3] and F(x)[2] and not F(x)[4]
                                and not F(x)[5] and k(x) < 1]),
        Principle("K4", "**Dense.** The ranks produced on reachable words are exactly 0..9, no gaps.",
                  lambda k, R: [] if {k(x) for x in R} == set(range(10)) else [min(R)]),
    ]


SEEK = Law(
    name="seek",
    title="the SEEK law",
    shapes="every shape - fluidnet's nets on the polytope",
    question="How good ONE candidate net is as the next visit for ONE job - decided from eight measured bits and "
             "nothing else. The body ranks every live copy of every dictionary the job still wants and travels "
             "to the highest; ties go to the lowest node index; if every rank is 0 the job is done travelling.",
    range_hi=15,
    bits=[
        ("0", "LIVE", "the copy answered - the MIRROR law chose it"),
        ("1-2", "NEAR", "hops from here: `0` here, `1` one hop, `2` at most half the diameter, `3` farther"),
        ("3-4", "HITS", "lines of the current code its taught signals match: `0`, `1`, `2`, `3` or more"),
        ("5", "TRIED", "this dictionary already worked on this job"),
        ("6", "UNCERTIFIABLE", "the job is `STRICT` and a class whose signal hits has no property"),
        ("7", "FULL", "the net reported its queue full"),
    ],
    word="x = LIVE | NEAR << 1 | HITS << 3 | TRIED << 5 | UNCERTIFIABLE << 6 | FULL << 7",
    reachable=_seek_reachable,
    unreachable_rules=[
        "`NEAR = 0` without `TRIED` - the net here works on every job that reaches it, on arrival.",
        "`FULL` without `LIVE` - the queue report rides on the heartbeat; an unmeasured lane is silent.",
    ],
    oracle=_seek_oracle,
    outputs=[("0", "never this net"), ("1..9", "visit, higher first"), ("10-15", "never produced on a reachable word")],
    principles=_seek_principles(),
)


LAWS = {law.name: law for law in (HOP, QUORUM, STEP, ADMIT, MIRROR, CARRY, SEEK)}


def judge(law: Law, k: Kernel, use_table: bool = True) -> dict[str, list[int]]:
    """Every check, by enumeration. Returns check name -> violating words."""
    R = law.reach()
    out: dict[str, list[int]] = {}
    if use_table:
        out["table"] = [x for x in R if k(x) != law.oracle(x)]
    out["range"] = [x for x in range(256) if not (0 <= k(x) <= law.range_hi)]
    for p in law.principles:
        out[p.id] = p.check(k, R)
    out["anchors"] = [x for x, _ in law.anchors if k(x) != law.oracle(x)]
    return out


def principles_fix_the_table(law: Law) -> list[tuple[int, int]]:
    """Every single-cell change to the oracle on a reachable word must break a PRINCIPLE (the table check off).
    Returns the (x, wrong value) pairs no principle catches - cells the principles leave open."""
    open_cells = []
    for x in law.reach():
        for v in range(law.range_hi + 1):
            if v == law.oracle(x):
                continue
            k = (lambda xx, x=x, v=v: v if xx == x else law.oracle(xx))
            res = judge(law, k, use_table=False)
            if not any(res[p.id] for p in law.principles):
                open_cells.append((x, v))
    return open_cells
