# Maths MVA

Application de bureau (Ubuntu, PySide6) pour reprendre les mathematiques de zero
et arriver pret aux cours de remise a niveau du M2 MVA.

Le principe : un syllabus complet de 142 cours, de la logique propositionnelle
aux modeles generatifs, relies par un graphe de prerequis. Chaque cours est
**genere a la demande par le `claude` installe localement** — cours redige,
figures interactives, demonstrations, QCM a difficulte croissante et
demonstrations a faire. Un chat Opus est disponible partout, y compris pour se
faire expliquer une demonstration etape par etape.

Tout est local : aucun serveur, aucun navigateur, KaTeX embarque.

---

## Installation

```bash
git clone git@github.com:Delata22/maths-mva.git
cd maths-mva
./run.sh
```

`run.sh` cree l'environnement virtuel et installe PySide6 au premier lancement.

Prerequis : Python 3.10+, et le CLI [`claude`](https://claude.com/claude-code)
authentifie (`claude auth`). L'application verifie sa presence au demarrage.

---

## Comment ca marche

### Le syllabus

142 cours repartis en 16 domaines, chacun avec ses prerequis, son niveau (1 a 5)
et ses objectifs. Le graphe de prerequis est verifie acyclique a la
construction.

Six **parcours** correspondent aux cours de remise a niveau de l'ENS :
probabilites, optimisation convexe, analyse fonctionnelle, statistiques,
analyse de Fourier, et l'introduction au deep learning. Un parcours regroupe le
cours cible et l'integralite de ce qu'il faut savoir avant.

Le syllabus se modifie dans `tools/build_syllabus.py`, puis :

```bash
.venv/bin/python tools/build_syllabus.py
```

### La generation

Un cours est produit en trois temps, pour que chaque appel reste de taille
raisonnable et que la progression soit lisible :

1. **plan** — sections, figures prevues, resultats demontres, et une reserve de
   resultats volontairement laisses a demontrer en exercice ;
2. **sections** — chacune redigee separement, en connaissant le plan complet et
   ce qui precede ;
3. **exercices** — 15 QCM de difficulte 1 a 5 et 5 demonstrations a faire, en
   reprenant en priorite les resultats laisses de cote.

Le CLI tourne en `--safe-mode`, sans outils, dans un repertoire neutre : ni les
hooks, ni les `CLAUDE.md`, ni les reglages de projet de la machine n'influencent
le contenu genere.

Les modeles sont configurables (Preferences) : Opus pour les cours et le chat,
Sonnet pour les exercices par defaut.

### Ce qu'on attend d'un cours

Les prompts imposent une ligne editoriale precise : l'intuition avant le
formalisme, une figure interactive partout ou la geometrie eclaire l'algebre,
les demonstrations decoupees en etapes qui disent *pourquoi* avant *comment*,
et les pieges classiques nommes explicitement. Le niveau de depart suppose est
celui d'une terminale maths expertes.

### Les figures

Les cours utilisent `mviz`, une petite bibliotheque maison (aucune dependance) :
courbes, courbes parametrees, champs de vecteurs, lignes de niveau, cartes de
chaleur, curseurs et animations. Les couleurs suivent le theme clair/sombre.

---

## Utilisation

| Vue | A quoi ca sert |
|---|---|
| **Accueil** | Avancement global, les six parcours MVA, ce qu'on peut attaquer maintenant, ce qu'il faut reviser |
| **Bibliotheque** | Les 142 cours, filtrables par domaine, niveau, statut et parcours, avec le score de QCM |
| **Cours** | Lecture, QCM, demonstrations, notes personnelles |
| **Graphe** | Le cursus comme graphe : ce qui est maitrise, ce qui est accessible, ce qui est verrouille |

Un cours passe **maitrise** quand le meilleur score de QCM atteint le seuil
(80 % par defaut), ce qui debloque les cours qui en dependent.

### Raccourcis

| | |
|---|---|
| `Ctrl+1..4` | Accueil / Bibliotheque / Cours / Graphe |
| `Ctrl+K` | Ouvrir le chat sur le cours courant |
| `Ctrl+F` | Rechercher un cours |
| `Ctrl+G` | Afficher la file de generation |

### Le chat

- **Panneau lateral** : questions libres, avec le contexte du cours ouvert et de
  ce qui a deja ete vu dans le cursus.
- **Selection dans un cours** : surligner un passage fait apparaitre
  « Demander a Claude », qui pre-remplit la question.
- **Demonstration pas a pas** : sur toute demonstration, du cours comme des
  exercices, « Decortiquer avec Claude » ouvre une fenetre dediee ou l'IA
  explique la logique de chaque etape, et ou l'on peut poser des questions.
- **Apres un QCM rate** : « Revoir mes erreurs avec Claude » envoie les
  questions manquees pour identifier la confusion de fond.

Chaque fil garde sa memoire entre les sessions.

---

## Generation en ligne de commande

Pratique pour lancer un gros lot et laisser tourner :

```bash
python tools/generate.py al-svd cd-hessienne     # des cours precis
python tools/generate.py --path opt-dualite-kkt  # un cours et tous ses prerequis
python tools/generate.py --track mva-optimisation
python tools/generate.py --list
```

---

## Ou vivent les donnees

```
library/
  <id-du-cours>/
    body.html        cours genere
    plan.json        plan et resultats laisses en exercice
    exercises.json   QCM et demonstrations
    meta.json        modele, duree, cout
  progress.db        scores, statuts, notes, fils de discussion
```

`library/` n'est pas versionne : c'est votre progression et votre contenu. Pour
le sauvegarder, copiez ce dossier. Pour repartir de zero sur un cours,
clic droit > *Supprimer le contenu genere* (les scores sont conserves).

---

## Structure du code

```
mathsapp/
  syllabus.py        chargement du syllabus, graphe de prerequis
  status.py          verrouille / disponible / a etudier / en cours / maitrise
  store.py           SQLite : scores, statuts, notes, discussions
  content.py         lecture des cours generes et assemblage des pages
  chat.py            conversation en streaming
  generation/
    claude_cli.py    appels au CLI claude
    prompts.py       ligne editoriale et format de sortie
    pipeline.py      plan -> sections -> exercices
    queue.py         file d'attente en arriere-plan
  ui/                fenetre principale et vues
  assets/            KaTeX, styles, mviz, pages QCM et demonstrations
tools/
  build_syllabus.py  source du syllabus
  generate.py        generation sans interface
```
