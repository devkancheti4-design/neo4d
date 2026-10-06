"""The 32-kind router's judge, judged: its reference against brute force over GL(5,2), a second correct router
passing, six wrong routers caught - the same checks as `python -m neo4d.judge_router5 --selfcheck`, smaller."""
import os

from neo4d import judge_router5


def test_router5_judge_selfcheck():
    assert judge_router5.selfcheck(words=400_000, procs=os.cpu_count() or 8, bf_per=300) == 0
