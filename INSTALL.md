# Installer FastLearning

Application de bureau pour apprendre une discipline scientifique de zéro : un
cursus complet (les maths en socle, puis le domaine de ton choix) de cours
générés à la demande, avec QCM, démonstrations, fiches, TD corrigés et
révisions espacées. Les cours sont écrits par l'assistant en ligne de commande
installé sur ta machine : **Codex** ou **Claude Code**. L'app n'a besoin d'aucune
clé d'API : elle passe par ton compte, déjà connecté dans le CLI.

Testée sous Ubuntu.

## 1. Ce qu'il faut avant

```bash
sudo apt install python3 python3-venv poppler-utils
npm install -g @openai/codex     # si Codex n'est pas déjà installé
codex login                      # se connecter une fois
```

- Python 3.10 ou plus récent.
- `poppler-utils` fournit `pdftotext`, qui sert à lire les PDF de TD et de cours.
- Vérifie que `codex exec "dis bonjour"` répond dans un terminal.

## 2. Lancer

```bash
git clone https://github.com/Delata22/FastLearning.git
cd FastLearning
./run.sh
```

Le premier lancement crée un environnement Python et installe PySide6 : compte
une minute. Ensuite, `./run.sh` suffit. Pour avoir l'app dans le menu des
applications : `tools/install-desktop.sh`.

## 3. Régler le moteur (une fois)

L'app choisit seule le CLI installé. Dans **Préférences > Génération** :

- **Moteur** : laisse « Automatique », ou force « Codex » ;
- **Modèle codex (cours)** et **(exercices)** : vide = le modèle par défaut de
  ton Codex. Tu peux mettre un modèle plus puissant pour les cours et un plus
  rapide pour les exercices ;
- le bouton **Tester le CLI** vérifie que tout répond.

## 4. Créer ton cursus

Au premier lancement, seul le socle de mathématiques est actif. Sur l'accueil,
**Créer un cursus…** (ou le menu **Cursus → Nouveau cursus**) : indique le
domaine (par exemple « Physique quantique »), tes objectifs avec tes mots, ton
niveau de départ, et une taille indicative. Claude conçoit le cursus complet,
avec les fondations qui manquent (mécanique, électromagnétisme, maths en
plus…), branché sur les cours de maths. Tu relis, puis **Enregistrer et
activer** : les parcours apparaissent sur l'accueil.

Règle aussi ton profil dans **Cursus → Packs et profil** (niveau de départ,
ce que les cours doivent savoir de toi) : il est repris dans tous les cours.
Le pack « Apprentissage automatique » est disponible au même endroit.

## 5. Bon à savoir

- La bibliothèque démarre vide. Ouvre un cours dans **Bibliothèque** ou dans le
  **Graphe**, puis **Générer**. Un cours complet (texte, figures, QCM,
  démonstrations, fiche) prend 15 à 30 minutes et consomme une bonne part de
  quota. Commence par un ou deux cours.
- Tes données (cours générés, progression, notes) vivent dans le dossier
  `library/` à côté de l'app. Pour tout recommencer, supprime-le.
- L'app a été conçue et rodée avec Claude. Avec Codex, les montants en « $ »
  restent à zéro, et « Modifier l'application » depuis l'Assistant n'est pas
  disponible. Les imports de PDF passent par le texte extrait, donc les
  formules des transparents sont moins fiables.
- Le mode d'emploi complet est dans `README.md`.
