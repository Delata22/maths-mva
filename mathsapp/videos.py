"""Vidéos pédagogiques locales, rattachées aux cours.

Les vidéos sont téléchargées une fois pour toutes dans `library/_videos/` et
lues hors ligne dans l'application : pas de YouTube à l'exécution, donc ni
recommandations ni commentaires. Le manifeste `videos.json` décrit chaque
vidéo et les cours auxquels elle se rattache.

Outil de développement (curation) :
    python -m mathsapp.videos list
    python -m mathsapp.videos add <url> --course al-matrices [--course ...]
    python -m mathsapp.videos map <id> --course al-reduction
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
from typing import Dict, List, Optional

from .paths import library_dir

# QtWebEngine (wheels PySide6) ne lit pas H.264/AAC : VP9 + Opus en webm.
FORMAT = ("247+bestaudio[ext=webm][language^=en]/247+bestaudio[ext=webm]"
          "/bv*[height<=720][ext=webm]+ba[ext=webm]")
SUB_LANGS = ("fr", "en")


def videos_dir() -> pathlib.Path:
    return library_dir() / "_videos"


def manifest_file() -> pathlib.Path:
    return videos_dir() / "videos.json"


def read() -> Dict[str, list]:
    path = manifest_file()
    if not path.exists():
        return {"videos": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"videos": []}
    data.setdefault("videos", [])
    return data


def write(data: dict) -> None:
    videos_dir().mkdir(parents=True, exist_ok=True)
    manifest_file().write_text(json.dumps(data, ensure_ascii=False, indent=1),
                               encoding="utf-8")


def for_course(course_id: str) -> List[dict]:
    """Vidéos rattachées au cours dont le fichier est bien présent."""
    out = []
    for v in read()["videos"]:
        if course_id in v.get("courses", []) and (videos_dir() / v["file"]).exists():
            out.append(v)
    return out


# ---------------------------------------------------------------- curation
def entry_from_info(info_path: pathlib.Path, slug: str) -> Optional[dict]:
    """Entrée du manifeste à partir du .info.json écrit par yt-dlp."""
    info = json.loads(info_path.read_text(encoding="utf-8"))
    d = videos_dir()
    media = d / ("%s.webm" % slug)
    if not media.exists():
        return None
    subs = {lang: "%s.%s.vtt" % (slug, lang) for lang in SUB_LANGS
            if (d / ("%s.%s.vtt" % (slug, lang))).exists()}
    return {
        "id": info["id"],
        "title": info.get("title") or slug,
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": int(info.get("duration") or 0),
        "file": media.name,
        "subtitles": subs,
        "source": info.get("webpage_url") or "",
        "courses": [],
    }


def _yt_dlp() -> str:
    found = shutil.which("yt-dlp") or str(pathlib.Path.home() / ".local/bin/yt-dlp")
    if not pathlib.Path(found).exists():
        sys.exit("yt-dlp introuvable")
    return found


def add(url: str, courses: List[str], slug: Optional[str] = None) -> dict:
    d = videos_dir()
    d.mkdir(parents=True, exist_ok=True)
    if slug is None:
        out = subprocess.run([_yt_dlp(), "--print", "id", "--skip-download", url],
                             capture_output=True, text=True, check=True)
        slug = "yt-" + out.stdout.strip().splitlines()[-1]
    subprocess.run([
        _yt_dlp(), "--no-warnings", "--no-playlist", "-f", FORMAT,
        "--merge-output-format", "webm", "--write-subs", "--sub-langs", ",".join(SUB_LANGS),
        "--sub-format", "vtt", "--write-info-json", "-o", str(d / ("%s.%%(ext)s" % slug)), url,
    ], check=True)
    entry = entry_from_info(d / ("%s.info.json" % slug), slug)
    if entry is None:
        sys.exit("téléchargement incomplet pour %s" % url)
    entry["courses"] = list(courses)
    data = read()
    data["videos"] = [v for v in data["videos"] if v["id"] != entry["id"]] + [entry]
    write(data)
    return entry


def map_courses(video_id: str, courses: List[str]) -> None:
    data = read()
    for v in data["videos"]:
        if v["id"] == video_id:
            v["courses"] = sorted(set(v.get("courses", [])) | set(courses))
            write(data)
            return
    sys.exit("vidéo inconnue : %s" % video_id)


def main(argv: Optional[List[str]] = None) -> None:
    from .syllabus import load
    parser = argparse.ArgumentParser(prog="python -m mathsapp.videos")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_add = sub.add_parser("add", help="télécharger une vidéo et la rattacher")
    p_add.add_argument("url")
    p_add.add_argument("--course", action="append", default=[])
    p_add.add_argument("--slug")
    p_map = sub.add_parser("map", help="rattacher une vidéo déjà présente")
    p_map.add_argument("id")
    p_map.add_argument("--course", action="append", default=[])
    args = parser.parse_args(argv)

    if args.cmd == "list":
        for v in read()["videos"]:
            print("%s  %-40s  %s" % (v["id"], v["file"], ", ".join(v.get("courses", []))))
        return
    syl = load()
    unknown = [c for c in args.course if c not in syl.courses]
    if unknown:
        sys.exit("cours inconnus : %s" % ", ".join(unknown))
    if args.cmd == "add":
        entry = add(args.url, args.course, args.slug)
        print("ajoutée : %s (%s)" % (entry["title"], entry["file"]))
    else:
        map_courses(args.id, args.course)


if __name__ == "__main__":
    main()
