#!/usr/bin/env python3
"""Verification de bout en bout, sans interface visible.

  python tools/selftest.py           # tout sauf les appels au modele
  python tools/selftest.py --chat    # ajoute un vrai aller-retour avec Claude

Verifie : le syllabus et son graphe, la base, l'assemblage des pages, le pont
JavaScript (selection de texte, aide a la demonstration, fin de QCM, statut
d'une demonstration), et les vues principales.
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-logging --no-sandbox")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((ok, name, detail))
    print("%s %s%s" % ("  ok  " if ok else " ECHEC", name, ("  — %s" % detail) if detail else ""))
    return ok


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(predicate, timeout_ms: int = 15000, step: int = 100) -> bool:
    elapsed = 0
    while elapsed < timeout_ms:
        if predicate():
            return True
        wait(step)
        elapsed += step
    return predicate()


def test_syllabus() -> None:
    from mathsapp.syllabus import load
    syl = load()
    check("syllabus charge", len(syl.courses) == 142, "%d cours" % len(syl.courses))
    rank = syl.topo_rank
    bad = [(c.id, p) for c in syl.all() for p in c.prereqs if rank(p) >= rank(c.id)]
    check("ordre topologique coherent", not bad, str(bad[:3]))
    import re
    non_ascii = [c.id for c in syl.all() if not re.fullmatch(r"[a-z0-9-]+", c.id)]
    check("identifiants en ASCII", not non_ascii, str(non_ascii[:3]))
    orphans = [c.id for c in syl.all() for p in c.prereqs if p not in syl.courses]
    check("prerequis tous definis", not orphans, str(orphans[:3]))
    for tid in syl.tracks:
        path = syl.track_path(tid)
        seen: set = set()
        ok = True
        for cid in path:
            if any(p not in seen for p in syl.get(cid).prereqs):
                ok = False
                break
            seen.add(cid)
        check("parcours %s ordonne" % tid, ok, "%d cours" % len(path))


def test_store() -> None:
    from mathsapp import status as st_mod, store
    from mathsapp.syllabus import load
    syl = load()
    statuses = st_mod.compute(syl)
    check("statuts calcules", len(statuses) == len(syl.courses))
    first = syl.topo[0]
    check("premier cours accessible", statuses[first].unlocked, first)
    tid = store.create_thread(None, "selftest", "test")
    store.add_message(tid, "user", "coucou")
    check("fil de discussion persiste", len(store.messages(tid)) == 1)
    store.clear_thread(tid)


def test_pages() -> None:
    from mathsapp import content
    page = content.build_page("<h2>Test $x^2$</h2>", "Test", "light")
    ok = ("katex.min.css" in page and "mviz.js" in page and "<h2>Test $x^2$</h2>" in page
          and "__ASSETS__" not in page and "__BODY__" not in page)
    check("assemblage de la page de cours", ok)
    cleaned = content.clean_html("```html\n<h2>A</h2>\n```")
    check("nettoyage des reponses du modele", cleaned == "<h2>A</h2>", repr(cleaned))


def test_bridge() -> None:
    """Le JavaScript des pages doit pouvoir rappeler l'application."""
    from mathsapp import content
    from mathsapp.paths import library_dir
    from mathsapp.ui.webview import WebView

    view = WebView(with_bridge=True)
    view.resize(900, 700)
    view.show()
    got: dict = {}
    view.bridge.ask_requested.connect(lambda t, h: got.update(ask=(t, h)))
    view.bridge.proof_help_requested.connect(lambda i, h, t: got.update(proof=(i, h)))
    view.bridge.quiz_finished.connect(lambda p: got.update(quiz=p))
    view.bridge.proof_status_changed.connect(lambda i, v: got.update(status=(i, v)))

    body = ('<h2>Section test</h2><p>Un peu de texte $a^2+b^2$.</p>'
            '<h2>Deuxieme section</h2><p>Suite, avec $$\\int_0^1 x\\,\\dd x$$.</p>'
            '<details class="proof" data-of="Theoreme test"><summary>Demonstration</summary>'
            '<div class="proof-body"><p>Preuve.</p></div></details>'
            '<div class="mviz" id="fig-t"></div>'
            '<script>mviz.plot("#fig-t", {xrange:[-2,2], yrange:[-1,4],'
            ' draw:function(g){g.curve(function(x){return x*x;});}});</script>')
    d = library_dir() / "_views"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "selftest.html"
    path.write_text(content.build_page(body, "Selftest", "light"), encoding="utf-8")

    loaded: dict = {}
    view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
    view.load_file(path)
    check("page de test chargee", wait_until(lambda: "ok" in loaded) and loaded["ok"])
    wait(2500)

    probe: dict = {}
    view.page().runJavaScript(
        "document.querySelectorAll('.katex').length", lambda r: probe.update(katex=r))
    view.page().runJavaScript(
        "document.querySelectorAll('#fig-t canvas').length", lambda r: probe.update(canvas=r))
    view.page().runJavaScript(
        "document.querySelectorAll('#toc a').length", lambda r: probe.update(toc=r))
    view.page().runJavaScript(
        "!!document.getElementById('ask-bubble')", lambda r: probe.update(bubble=r))
    wait_until(lambda: len(probe) == 4, 8000)
    check("formules rendues par KaTeX", probe.get("katex", 0) >= 1, "%s formules" % probe.get("katex"))
    check("figure mviz dessinee", probe.get("canvas", 0) == 1)
    check("sommaire construit", probe.get("toc", 0) >= 1, "%s entrees" % probe.get("toc"))
    check("bouton de selection installe", bool(probe.get("bubble")))

    ready: dict = {}
    view.page().runJavaScript("typeof window.app", lambda r: ready.update(kind=r))
    wait_until(lambda: "kind" in ready, 5000)
    check("pont expose au JavaScript", ready.get("kind") == "object", str(ready))
    view.page().runJavaScript("app.askAbout('extrait choisi', 'Section test');")
    view.page().runJavaScript("app.openProofHelper('p1', 'Theoreme test', 'texte');")
    view.page().runJavaScript("app.quizFinished('{\"total\":2,\"correct\":1}');")
    view.page().runJavaScript("app.setProofStatus('p1', 'done');")
    ok = wait_until(lambda: len(got) == 4, 8000)
    check("pont JS -> application", ok, str(sorted(got)))
    check("  selection de texte transmise", got.get("ask") == ("extrait choisi", "Section test"))
    check("  aide a la demonstration transmise", got.get("proof") == ("p1", "Theoreme test"))
    check("  fin de QCM transmise", '"correct":1' in (got.get("quiz") or ""))
    check("  statut de demonstration transmis", got.get("status") == ("p1", "done"))
    view.deleteLater()


def test_views() -> None:
    from mathsapp.ui.main_window import MainWindow, PAGE_GRAPH, PAGE_HOME, PAGE_LIBRARY
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    wait(600)
    window.go(PAGE_LIBRARY)
    check("bibliotheque construite", window.library.tree.topLevelItemCount() == 16)
    window.go(PAGE_GRAPH)
    check("graphe construit", len(window.graph.scene.nodes) == 142)
    window.go(PAGE_HOME)
    first = window.syl.topo[0]
    window.open_course(first)
    check("page de cours ouverte", window.course_page.course.id == first)
    window.toggle_theme()
    window.toggle_theme()
    check("bascule de theme", True)
    window.close()


def test_chat() -> None:
    from mathsapp.ui.chat_panel import ChatPanel
    from mathsapp.syllabus import load
    panel = ChatPanel(load())
    panel.resize(500, 700)
    panel.show()
    wait(1500)
    panel.set_context(None, "selftest-chat")
    panel.composer.setPlainText("Reponds exactement : PONG")
    panel.send()
    ok = wait_until(lambda: not panel.busy, 120000)
    check("aller-retour avec Claude", ok and bool(panel.session.history()),
          panel.session.history()[-1]["content"][:60] if panel.session.history() else "")
    panel.session.reset()
    panel.deleteLater()


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication([])
    from mathsapp.ui import theme
    app.setStyleSheet(theme.stylesheet())

    print("\n--- syllabus ---")
    test_syllabus()
    print("\n--- progression ---")
    test_store()
    print("\n--- assemblage des pages ---")
    test_pages()
    print("\n--- pont javascript ---")
    test_bridge()
    print("\n--- vues ---")
    test_views()
    if "--chat" in sys.argv:
        print("\n--- chat (appel reel au modele) ---")
        test_chat()

    for widget in app.topLevelWidgets():
        widget.close()
    wait(200)

    failed = [name for ok, name, _ in RESULTS if not ok]
    print("\n%d verifications, %d echec(s)" % (len(RESULTS), len(failed)))
    for name in failed:
        print("  -", name)
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # QtWebEngine se plaint bruyamment a la destruction du profil ; on sort
    # sans laisser Python demonter l'arbre d'objets.
    os._exit(code)
