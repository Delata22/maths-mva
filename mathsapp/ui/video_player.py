"""Onglet « Vidéos » d'un cours : lecteur HTML5 sur les fichiers locaux.

Aucune ressource distante : la page ne contient que des fichiers de
`library/_videos/`. Commandes limitées à lecture/pause, position, vitesse et
sous-titres.
"""
from __future__ import annotations

import html
import json
import re
from typing import List

from .. import videos as videos_mod
from . import theme

LANG_NAMES = {"fr": "Français", "en": "Anglais"}

_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>Vidéos</title>
<style>
:root { %(vars)s }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 14px/1.45 "Inter", "Segoe UI", system-ui, sans-serif; }
.wrap { display: flex; gap: 18px; padding: 16px 18px; height: 100vh; }
.list { width: 290px; flex: none; overflow-y: auto; }
.list button { display: block; width: 100%%; text-align: left; margin: 0 0 6px;
  padding: 9px 11px; border: 1px solid var(--line); border-radius: 9px;
  background: var(--bg2); color: var(--fg); font: inherit; cursor: pointer; }
.list button:hover { border-color: var(--accent); }
.list button.on { border-color: var(--accent); background: var(--accent_soft); }
.list small { display: block; color: var(--muted); margin-top: 2px; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
video { width: 100%%; max-height: calc(100vh - 150px); background: #000; border-radius: 10px; }
.bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; color: var(--fg2); }
.bar button { padding: 4px 10px; border: 1px solid var(--line2); border-radius: 7px;
  background: var(--bg2); color: var(--fg2); font: inherit; cursor: pointer; }
.bar button.on { border-color: var(--accent); color: var(--accent); }
.bar .sep { width: 14px; }
h2 { margin: 0; font-size: 17px; }
.credit { color: var(--muted); font-size: 12px; }
</style></head>
<body oncontextmenu="return false">
<div class="wrap">
  <div class="list" id="list"></div>
  <div class="main">
    <h2 id="title"></h2>
    <video id="v" controls preload="metadata" disablePictureInPicture
           controlsList="nodownload nofullscreen noremoteplayback noplaybackrate"></video>
    <div class="bar">
      <span>Vitesse</span><span id="speeds"></span>
      <span class="sep"></span>
      <span>Sous-titres</span><span id="subs"></span>
    </div>
    <div class="credit" id="credit"></div>
  </div>
</div>
<script>
var VIDEOS = %(videos)s, LANGS = %(langs)s;
var v = document.getElementById('v'), current = 0, rate = 1, lang = 'fr';
function el(tag, text, cls) { var e = document.createElement(tag); e.textContent = text;
  if (cls) e.className = cls; return e; }
function fmt(s) { var m = Math.floor(s / 60), r = s %% 60; return m + ' min ' + (r < 10 ? '0' : '') + r; }
function applySubs() {
  for (var i = 0; i < v.textTracks.length; i++)
    v.textTracks[i].mode = (v.textTracks[i].language === lang) ? 'showing' : 'disabled';
  drawSubs();
}
function drawSubs() {
  var box = document.getElementById('subs'); box.innerHTML = '';
  var opts = [[null, 'Aucun']].concat(Object.keys(VIDEOS[current].subtitles)
    .map(function (k) { return [k, LANGS[k] || k]; }));
  opts.forEach(function (o) {
    var b = el('button', o[1], o[0] === lang ? 'on' : '');
    b.onclick = function () { lang = o[0]; applySubs(); };
    box.appendChild(b);
  });
}
function drawSpeeds() {
  var box = document.getElementById('speeds'); box.innerHTML = '';
  [0.75, 1, 1.25, 1.5, 1.75, 2].forEach(function (r) {
    var b = el('button', r + '×', r === rate ? 'on' : '');
    b.onclick = function () { rate = r; v.playbackRate = r; drawSpeeds(); };
    box.appendChild(b);
  });
}
function show(i, autoplay) {
  current = i; var d = VIDEOS[i];
  v.innerHTML = ''; v.src = d.src;
  Object.keys(d.subtitles).forEach(function (k) {
    var t = document.createElement('track'); t.kind = 'subtitles'; t.srclang = k;
    t.label = LANGS[k] || k; t.src = d.subtitles[k]; v.appendChild(t);
  });
  v.load(); v.playbackRate = rate;
  setTimeout(applySubs, 0);
  document.getElementById('title').textContent = d.title;
  document.getElementById('credit').textContent =
    'Vidéo de ' + d.channel + ', lue hors ligne depuis la bibliothèque.';
  Array.prototype.forEach.call(document.querySelectorAll('.list button'), function (b, j) {
    b.className = j === i ? 'on' : ''; });
  if (autoplay) v.play();
}
v.addEventListener('loadedmetadata', function () { v.playbackRate = rate; applySubs(); });
VIDEOS.forEach(function (d, i) {
  var b = el('button', d.title); b.appendChild(el('small', d.channel + ' · ' + fmt(d.duration)));
  b.onclick = function () { show(i, true); };
  document.getElementById('list').appendChild(b);
});
drawSpeeds();
if (VIDEOS.length) show(0, false);
</script></body></html>
"""


def short_title(title: str) -> str:
    """« Vectors | Chapter 1, Essence of linear algebra » → « Ch. 1 — Vectors »."""
    m = re.match(r"^(.*?)\s*\|\s*Chapter (\d+),", title)
    return "Ch. %s — %s" % (m.group(2), m.group(1)) if m else title


def build_page(items: List[dict]) -> str:
    pal = theme.palette()
    base = videos_mod.videos_dir().as_uri() + "/"
    data = [{
        "title": short_title(v["title"]),
        "channel": v.get("channel", ""),
        "duration": int(v.get("duration") or 0),
        "src": base + v["file"],
        "subtitles": {k: base + f for k, f in (v.get("subtitles") or {}).items()},
    } for v in items]
    return _PAGE % {
        "vars": " ".join("--%s: %s;" % (k, html.escape(c)) for k, c in pal.items()),
        "videos": json.dumps(data, ensure_ascii=False).replace("</", "<\\/"),
        "langs": json.dumps(LANG_NAMES, ensure_ascii=False),
    }
