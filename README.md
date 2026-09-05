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

![Accueil](docs/images/accueil.png)

<table>
<tr>
<td width="50%"><img src="docs/images/cours-gradient.png" alt="Figure interactive"></td>
<td width="50%"><img src="docs/images/graphe.png" alt="Graphe des prerequis"></td>
</tr>
<tr>
<td align="center"><em>Une figure de cours : carte topographique, lignes de niveau et
gradient, avec curseurs</em></td>
<td align="center"><em>Le cursus comme graphe : ce qui est accessible, ce qui est
verrouille</em></td>
</tr>
<tr>
<td><img src="docs/images/qcm.png" alt="QCM"></td>
<td><img src="docs/images/demonstrations.png" alt="Demonstrations"></td>
</tr>
<tr>
<td align="center"><em>QCM a difficulte croissante</em></td>
<td align="center"><em>Demonstrations a faire, avec indices progressifs</em></td>
</tr>
</table>

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

**Ordre de grandeur.** Un cours complet fait 8 a 9 sections, soit environ
150 000 caracteres, une quinzaine de figures interactives et une trentaine de
resultats demontres. Comptez **15 a 20 minutes et 5 a 6 dollars** par cours avec
Opus. Generer les 142 cours du syllabus represente donc plusieurs jours de
calcul : mieux vaut generer parcours par parcours, ou au fil de l'eau.

Deux mecanismes rendent cela supportable :

- **les sections sont redigees en parallele** (3 par defaut, jusqu'a 6) ;
- **la generation est reprenable** : chaque section est ecrite dans son propre
  fichier, marque par une empreinte du plan. Une generation interrompue reprend
  ou elle s'etait arretee. Si le plan change, le cache est invalide.

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
- **Correction de sa propre demonstration** : voir ci-dessous.
- **Apres un QCM rate** : « Revoir mes erreurs avec Claude » envoie les
  questions manquees pour identifier la confusion de fond.

Chaque fil garde sa memoire entre les sessions.

### Rediger et faire corriger ses demonstrations

Chaque demonstration a faire dispose d'une zone de redaction, avec brouillon
enregistre automatiquement. Les mathematiques s'ecrivent en LaTeX entre `$ ... $`,
et trois choses evitent d'avoir a le taper a la main :

- une **palette de symboles** en six categories (logique, ensembles, analyse,
  algebre, grec, structures) qui insere au curseur ;
- des **raccourcis clavier** : `Alt+A` pour `\forall`, `Alt+E` pour `\exists`,
  `Alt+I` pour `\in`, `Alt+R` pour `\Rightarrow`, `Alt+Q` pour `\iff`,
  `Alt+G` pour `\nabla`, `Alt+F` pour `\frac`, `Alt+S` pour `\sum`,
  `Alt+T` pour `\int`, `Alt+L` pour `\lim`, `Alt+W` pour `\norm`,
  `Alt+M` pour entourer de `$…$` ;
- des **abreviations** developpees a l'espace : `=>`, `<=>`, `ssi`, `!=`, `>=`,
  `<=`, `->`, `|->`, `inf`, `qqs`, `ex`.

Un bouton *Apercu* rend le texte par KaTeX. **Faire corriger par Claude**
(ou `Ctrl+Entree`) ouvre une fenetre de correction : verdict, ce qui tient,
**le premier** point qui bloque avec une piste pour repartir, et les remarques
de redaction. La correction ne deroule pas la solution — sauf si vous la
demandez — et une preuve correcte differente de la solution de reference est
reconnue comme correcte. Vous corrigez, vous resoumettez : le fil garde les
versions precedentes et Claude dit si le point signale est regle.

---

## Generation en ligne de commande

Pratique pour lancer un gros lot et laisser tourner :

```bash
python tools/generate.py al-svd cd-hessienne     # des cours precis
python tools/generate.py --path opt-dualite-kkt  # un cours et tous ses prerequis
python tools/generate.py --track mva-optimisation
python tools/generate.py --list
```

## Outils de developpement

```bash
python tools/selftest.py           # verification de bout en bout, sans fenetre
python tools/selftest.py --chat    # ajoute un aller-retour reel avec Claude
python tools/shot.py al-svd                    # capture la page d'un cours
python tools/shot.py al-svd --view quiz        # ou son QCM
python tools/shot.py al-svd --anchor fig-svd   # cadre sur une figure
python tools/shot_app.py graphe /tmp/g.png     # capture une vue de l'app
python tools/install-desktop.sh                # entree dans le lanceur Ubuntu
```

---

## Ou vivent les donnees

```
library/
  <id-du-cours>/
    body.html        cours genere
    plan.json        plan et resultats laisses en exercice
    sections/        une section par fichier (reprise de generation)
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
  selftest.py        verification de bout en bout
  shot.py            capture d'une page de cours
  shot_app.py        capture d'une vue de l'application
```
