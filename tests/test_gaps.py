"""Fiches de lacunes : extraction rangée, validation, révisions espacées.

  .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["MATHSAPP_LIBRARY"] = _TMP.name     # avant tout import de l'app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mathsapp import content, gaps, review, store  # noqa: E402

COURSE = "fou-series"


def raw(notion="Module au carré", same_as="", answer=1):
    return {"notion": notion, "course_id": COURSE, "difficulty": 1, "same_as": same_as,
            "question": "Que vaut $|z|^2$ ?", "choices": ["$z^2$", "$z\\bar z$", "$2z$", "$\\bar z$"],
            "answer": answer, "explanation": "Car $z\\bar z = a^2+b^2$.",
            "variants": [{"question": "Que vaut $|1+i|^2$ ?", "choices": ["1", "2", "0", "4"],
                          "answer": 1, "explanation": "$1+1$."}]}


class GapsTest(unittest.TestCase):
    def setUp(self):
        c = store.conn()
        c.execute("DELETE FROM question_result")
        c.commit()
        path = gaps._path()
        if path.exists():
            path.unlink()

    def test_exchanges_pair_question_and_answer_and_skip_selftest(self):
        t = store.create_thread(COURSE, "course", "Fourier")
        store.add_message(t, "user", "rappelle-moi le module")
        store.add_message(t, "assistant", "|z|^2 = z conj(z)")
        noise = store.create_thread("selftest-x", "course", "x")
        store.add_message(noise, "user", "bruit")
        ex = gaps.exchanges(0)
        self.assertEqual([(e["user"], e["assistant"]) for e in ex if e["course_id"] == COURSE][-1],
                         ("rappelle-moi le module", "|z|^2 = z conj(z)"))
        self.assertFalse(any(e["course_id"].startswith("selftest") for e in ex))

    def test_propose_validate_then_review_cycle(self):
        now = time.time()
        res = gaps.propose([raw(), raw(answer=9), dict(raw(), course_id="inconnu")],
                           {COURSE}, scanned_until=now, now=now)
        self.assertEqual(res["new"], 1)                       # réponse hors bornes et cours inconnu écartés
        self.assertEqual(gaps.load()["scanned_until"], now)
        card = gaps.cards(gaps.PROPOSED)[0]
        self.assertEqual(gaps.index(), {})                    # pas encore validée : pas en révision

        kept = gaps.decide([card["id"]], [], {card["id"]: "Module d'un complexe"}, now=now)
        self.assertEqual(kept[0]["notion"], "Module d'un complexe")
        due = review.due_items(now=now + 1)
        self.assertEqual([(d.set_id, d.question_id) for d in due], [(gaps.SET_ID, card["id"])])
        self.assertIn((COURSE, gaps.SET_ID, card["id"]), content.question_index())

        # réussie : elle est repoussée ; l'enregistrement passe par la série « lacunes »
        store.record_attempt(COURSE, 1, 1, {"answers": [{"id": card["id"], "ok": True}]},
                             set_id=gaps.SET_ID, partial=True)
        self.assertEqual(review.due_items(now=time.time() + 60), [])
        self.assertEqual(gaps.stats()["learning"], 1)

        # redemandée plus tard : pas de doublon, la fiche redevient due
        res = gaps.propose([raw(same_as=card["id"])], {COURSE}, scanned_until=now + 5)
        self.assertEqual((res["new"], res["relapsed"]), (0, [card["id"]]))
        self.assertEqual(len(gaps.cards()), 1)
        self.assertEqual(len(review.due_items(now=time.time() + 60)), 1)

    def test_dropped_cards_never_come_back(self):
        gaps.propose([raw()], {COURSE}, scanned_until=1.0)
        card = gaps.cards(gaps.PROPOSED)[0]
        self.assertEqual(gaps.decide([], [card["id"]]), [])
        self.assertEqual(gaps.cards(gaps.DISCARDED)[0]["id"], card["id"])
        self.assertEqual(review.due_items(now=time.time() + 60), [])

    def test_variants_rotate_by_day(self):
        gaps.propose([raw()], {COURSE}, scanned_until=1.0)
        card = gaps.cards(gaps.PROPOSED)[0]
        days = ["2026-10-11", "2026-10-12"]
        questions = {gaps.as_question(card, d)["question"] for d in days}
        self.assertEqual(len(questions), 2)
        q = gaps.as_question(card, days[0])
        self.assertEqual((q["kind"], q["section"], q["course_id"]), ("rappel", "Module au carré", COURSE))


if __name__ == "__main__":
    unittest.main()
