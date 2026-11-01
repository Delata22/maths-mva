"""Packs de cours, profil et conception d'un nouveau cursus (modèle simulé)."""
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


class _Lib:
    """Bibliothèque vide et isolée, le temps d'un test."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("MATHSAPP_LIBRARY")
        os.environ["MATHSAPP_LIBRARY"] = self.tmp.name
        from mathsapp import curriculum, syllabus
        curriculum.reload()
        syllabus.load.cache_clear()
        return pathlib.Path(self.tmp.name)

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("MATHSAPP_LIBRARY", None)
        else:
            os.environ["MATHSAPP_LIBRARY"] = self.old
        from mathsapp import curriculum, syllabus
        curriculum.reload()
        syllabus.load.cache_clear()
        self.tmp.cleanup()


def fake_runner(calls):
    """Réponses du modèle, dans l'ordre : architecture, un lot par domaine, parcours."""
    answers = [
        {"pack": {"title": "Physique quantique", "description": "De la mécanique à la QM.",
                  "discipline": "Physique", "goal": "comprendre la mécanique quantique.",
                  "style": ["Vérifier les unités.", ""]},
         "domains": [
             {"id": "Méca Classique", "name": "Mécanique classique", "description": "d",
              "scope": "lagrangien", "count": 3, "color": "pas une couleur"},
             {"id": "mq", "name": "Mécanique quantique", "description": "d",
              "scope": "Schrödinger", "count": 3, "color": "#123456"},
         ],
         "notes": "ok"},
        {"courses": [
            {"id": "mec-newton", "title": "Lois de Newton", "domain": "autre", "level": 1,
             "prereqs": ["ana-derivation", "invente"], "summary": "s",
             "objectives": ["o"], "keywords": ["k"]},
            {"id": "Mec Lagrange", "title": "Formalisme lagrangien", "domain": "x", "level": 3,
             "prereqs": ["mec-newton", "cd-extrema"], "summary": "s",
             "objectives": ["o"], "keywords": ["k"]},
            {"id": "al-svd", "title": "Doublon", "domain": "x", "level": 3,
             "prereqs": [], "summary": "s", "objectives": ["o"], "keywords": ["k"]},
        ]},
        {"courses": [
            {"id": "mq-schrodinger", "title": "Équation de Schrödinger", "domain": "mq",
             "level": 4, "prereqs": ["mec-lagrange", "al-spectral"], "summary": "s",
             "objectives": ["o"], "keywords": ["k"]},
        ]},
        {"tracks": [{"id": "qm", "title": "Vers la QM", "goal": "mq-schrodinger",
                     "extra": ["mec-newton", "inconnu"]},
                    {"id": "x", "title": "Cible inconnue", "goal": "nope"}]},
    ]

    def runner(prompt, system, schema, label, lo, hi):
        calls.append(label)
        return answers[len(calls) - 1], 0.5
    return runner


class CurriculumTest(unittest.TestCase):
    def test_new_library_starts_with_maths_only(self):
        with _Lib() as lib:
            from mathsapp import curriculum, syllabus
            self.assertEqual(curriculum.active_ids(), ["maths"])
            syl = syllabus.load()
            self.assertTrue(all(c.pack == "maths" for c in syl.all()))
            self.assertEqual(syl.discipline(), "mathématiques")
            self.assertTrue((lib / "curriculum.json").exists())

    def test_existing_library_keeps_ml_pack(self):
        with _Lib() as lib:
            (lib / "dl-cnn").mkdir()
            from mathsapp import curriculum, syllabus
            curriculum.reload()
            self.assertEqual(curriculum.active_ids(), ["maths", "ml"])
            syl = syllabus.load()
            self.assertEqual(len(syl.courses), 262)
            # les remises à niveau du socle passent dans « Les bases » du pack ML
            self.assertEqual(syl.tracks["maths-proba"].group, "ml-bases")
            self.assertIn("Remise à niveau", syl.tracks["maths-proba"].title)

    def test_disabling_a_pack_keeps_syllabus_consistent(self):
        with _Lib() as lib:
            from mathsapp import curriculum, syllabus, syllabus_extra
            curriculum.set_active(["ml"])
            # un ajout perso qui dépend d'un cours de ML
            syllabus_extra.write_extra({"domains": [], "courses": [{
                "id": "perso-x", "title": "X", "domain": "dl", "level": 3,
                "prereqs": ["dl-cnn", "al-svd"], "summary": "", "objectives": [],
                "keywords": []}], "tracks": [{"id": "t", "title": "T", "goal": "perso-x",
                                              "extra": ["dl-cnn"], "group": "ml-avance"}]})
            syllabus.load.cache_clear()
            self.assertIn("dl-cnn", syllabus.load().courses)
            curriculum.set_active([])
            syllabus.load.cache_clear()
            syl = syllabus.load()
            self.assertNotIn("dl-cnn", syl.courses)
            self.assertEqual(syl.get("perso-x").prereqs, ["al-svd"])
            self.assertEqual(syl.tracks["t"].group, curriculum.CUSTOM_GROUP)
            syl.track_path("t")

    def test_design_save_and_load_a_pack(self):
        with _Lib() as lib:
            from mathsapp import curriculum, curriculum_gen, syllabus
            syl = syllabus.load()
            calls = []
            pack, notes, cost = curriculum_gen.design(
                {"subject": "physique quantique", "goals": "la QM"}, 6,
                fake_runner(calls), syl)
            self.assertEqual(len(calls), 4)
            self.assertEqual(cost, 2.0)
            self.assertEqual(pack["id"], "physique-quantique")
            self.assertEqual(pack["discipline"], "physique")
            self.assertEqual(pack["style"], ["Vérifier les unités."])
            ids = [c["id"] for c in pack["courses"]]
            self.assertEqual(ids, ["mec-newton", "mec-lagrange", "mq-schrodinger"])
            dom = {c["id"]: c["domain"] for c in pack["courses"]}
            self.assertEqual(dom["mec-newton"], "meca_classique")
            newton = pack["courses"][0]
            self.assertEqual(newton["prereqs"], ["ana-derivation"])
            self.assertEqual(pack["courses"][2]["prereqs"], ["mec-lagrange", "al-spectral"])
            self.assertTrue(pack["domains"][0]["color"].startswith("#"))
            self.assertEqual(len(pack["tracks"]), 1)
            self.assertEqual(pack["tracks"][0]["extra"], ["mec-newton"])
            self.assertEqual(pack["requires"], ["maths"])
            self.assertEqual(curriculum_gen.check(pack, curriculum.merged_base()), [])

            curriculum.save_pack(pack)
            curriculum.set_active(curriculum.active_ids() + [pack["id"]])
            syllabus.load.cache_clear()
            syl = syllabus.load()
            self.assertEqual(syl.discipline("mq-schrodinger"), "physique")
            self.assertEqual(syl.discipline("al-svd"), "mathématiques")
            self.assertIn("comprendre la mécanique quantique", syl.goals())
            path = syl.track_path(pack["tracks"][0]["id"])
            self.assertIn("al-spectral", path)
            self.assertEqual(path[-1], "mq-schrodinger")

            from mathsapp.generation import prompts
            text = prompts.style(syl, syl.get("mq-schrodinger"))
            self.assertIn("Discipline : physique", text)
            self.assertIn("Vérifier les unités.", text)
            self.assertNotIn("apprentissage automatique", text)

            # export puis import : un nouvel identifiant, rien d'écrasé
            out = lib / "partage.json"
            curriculum.export_pack(pack["id"], out)
            new_id = curriculum.import_pack(out)
            self.assertNotEqual(new_id, pack["id"])
            self.assertEqual(json.loads(out.read_text())["id"], pack["id"])
            curriculum.delete_pack(new_id)
            self.assertNotIn(new_id, curriculum.available())
            with self.assertRaises(ValueError):
                curriculum.delete_pack("maths")

    def test_builtin_packs_are_consistent(self):
        from mathsapp import curriculum
        packs = {p.stem: json.loads(p.read_text()) for p in curriculum.BUILTIN_DIR.glob("*.json")}
        self.assertEqual(set(packs), {"maths", "ml"})
        maths_ids = {c["id"] for c in packs["maths"]["courses"]}
        for c in packs["maths"]["courses"]:
            self.assertTrue(set(c["prereqs"]) <= maths_ids, c["id"])


if __name__ == "__main__":
    unittest.main()
