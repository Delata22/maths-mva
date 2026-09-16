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

![Redaction d'une demonstration](docs/images/redaction-demonstration.png)

<p align="center"><em>Rediger sa demonstration avec la palette de symboles, puis la
faire corriger par Claude</em></p>

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

262 cours repartis en 26 domaines, chacun avec ses prerequis, son niveau (1 a 5)
et ses objectifs. Le graphe de prerequis est verifie acyclique a la
construction, et les identifiants restent en ASCII (ils servent de noms de
dossiers).

Deux moities :

- **les mathematiques**, de la logique propositionnelle a l'analyse
  fonctionnelle, en passant par l'algebre lineaire, le calcul differentiel, la
  mesure, les probabilites, les statistiques, l'optimisation convexe et
  Fourier ;
- **l'apprentissage**, qui s'appuie dessus : fondements et evaluation, modeles
  classiques, theorie de l'apprentissage, bayesien et modeles graphiques,
  apprentissage profond, modeles generatifs, vision, langage et grands modeles,
  renforcement, transport optimal et donnees structurees, et la mise en
  pratique avec PyTorch.

Les **parcours** sont de deux familles :

- *les cours de la rentree* : les cinq remises a niveau de l'ENS et
  l'introduction au deep learning ;
- *les cours du M2* : vision, langage, renforcement, modeles generatifs,
  methodes a noyaux, modeles graphiques, graphes, transport optimal, fondements
  theoriques, apprentissage sequentiel, statistique computationnelle...

Un parcours regroupe le cours cible et l'integralite de ce qu'il faut savoir
avant : le parcours « Langage, parole et grands modeles » compte 114 cours, en
partant de la logique.

Le syllabus de base se modifie dans `tools/build_syllabus.py`, puis :

```bash
.venv/bin/python tools/build_syllabus.py
```

### Etendre le syllabus depuis l'application

Le bouton **Syllabus** (`Ctrl+N`) demande a Claude de concevoir une serie de
cours sur un sujet absent du cursus, et de la brancher sur les prerequis deja
presents.

![Etendre le syllabus](docs/images/etendre-syllabus.png)

Vous decrivez ce que vous voulez couvrir, choisissez un domaine existant ou
laissez-en creer un, et relisez la proposition avant qu'elle soit ajoutee :
chaque cours a sa case, ses prerequis resolus en clair, et le modele explique
ce qu'il a couvert et ce qu'il a laisse de cote. Rien n'entre dans le syllabus
sans validation.

La proposition est nettoyee avant d'etre presentee : identifiants recalcules
s'ils sont mal formes, doublons ecartes, prerequis inventes retires, cycles
refuses. Ce qui a ete corrige est affiche.

Vos ajouts vivent dans `library/syllabus_extra.json`, a cote de votre contenu,
et **survivent aux mises a jour du syllabus de base**. L'onglet *Mes ajouts*
les liste et permet de les retirer ; le contenu deja genere reste sur le disque
et sera reutilise si vous les recreez.

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

### Le QCM : choisir ses questions, plusieurs series

L'onglet QCM s'ouvre sur la liste des questions plutot que sur la premiere
question. Chacune porte son resultat precedent — reussie, ratee, jamais faite —
et se coche individuellement. Trois raccourcis : *tout selectionner*,
*mes erreurs*, *jamais faites*. On refait donc les trois questions ratees sans
reprendre les quinze.

Une session portant sur une selection met a jour le suivi de chaque question,
mais ne compte pas comme un score du cours : refaire trois questions ratees ne
doit pas faire chuter la moyenne.

**Rien n'est perdu en cours de série.** Chaque réponse validée écrit aussitôt
l'état de la tentative dans `progress.db` : ordre des questions et des
propositions, réponses, corrections, score partiel. Changer de page, fermer
l'application ou un plantage ne coûtent donc rien : à la réouverture de la
série (QCM du cours, révisions, quiz du jour, rappel, défi), l'application
propose **Reprendre (question k/n)** ou **Recommencer**. Reprendre restaure les
réponses et leurs corrections (« Question précédente » pour les revoir) et
place sur la première question sans réponse. Recommencer efface la tentative
après un second clic de confirmation. Les réponses ne comptent pour le score et
les révisions espacées qu'une fois, à la fin de la tentative, reprise ou non.
Si la série a été régénérée, seules les réponses aux questions inchangées sont
gardées ; s'il n'en reste aucune, seul « Recommencer » est proposé.

Le bouton **+ Nouvelle serie** demande une serie supplementaire : le modele
recoit les questions deja posees et doit couvrir en priorite ce qu'elles
laissent de cote. Les series s'empilent, chacune avec son propre suivi.

Certaines questions sont de vrais **exercices** : un enonce autosuffisant qu'on
ne resout pas de tete, ou les quatre propositions ne donnent que le resultat
final. Elles sont signalees, ouvrent un brouillon, et leurs propositions
restent masquees tant qu'on n'a pas cherche — sans quoi on remonte la solution
depuis les reponses. Un item marque exercice mais qui se resout en une ligne
est automatiquement requalifie en question directe : le badge doit vouloir dire
« prends une feuille ».

### L'equilibre des QCM

Un QCM ou la bonne reponse est plus longue et plus argumentee que les trois
autres se resout sans connaitre le cours. Sur les premiers cours produits, la
bonne reponse etait la plus longue 57 % du temps, et elle tombait en D une fois
sur cent cinquante.

Les consignes de generation imposent donc des propositions de longueur et de
registre comparables, et interdisent qu'une seule porte un raisonnement. Apres
generation, les questions ou la bonne reponse depasse encore les autres d'un
tiers sont renvoyees au modele pour reecriture, puis la position de la bonne
reponse est repartie sur les quatre lettres.

Pour reequilibrer des QCM deja produits :

```bash
python tools/fix_qcm.py --dry-run    # mesurer
python tools/fix_qcm.py              # corriger
```

### Ce qu'on attend d'un cours

Les prompts imposent une ligne editoriale precise : l'intuition avant le
formalisme, une figure interactive partout ou la geometrie eclaire l'algebre,
les demonstrations decoupees en etapes qui disent *pourquoi* avant *comment*,
et les pieges classiques nommes explicitement. Le niveau de depart suppose est
celui d'une terminale maths expertes.

### La fiche de revision

Chaque cours a deux formes : le cours long pour la premiere lecture, et une
**fiche condensee** pour y revenir. La fiche est produite a partir du cours
redige, dans l'onglet *Fiche* de la page de cours.

![Fiche de revision](docs/images/fiche-revision.png)

Elle contient les definitions et les enonces exacts avec leurs hypotheses, un
tableau de formules, les methodes formulees comme « pour montrer que..., faire
... », les pieges du cours, une liste de ce qu'il faut savoir refaire, et un
**rappel actif** : des questions dont la reponse est masquee a l'ecran et se
devoile au clic.

Elle est mise en page pour l'impression : deux a quatre pages A4, exportables
en PDF depuis l'onglet, ou en lot :

```bash
python tools/sheet_pdf.py --all --out ~/fiches
```

Les fiches des nouveaux cours sont produites automatiquement a la fin de leur
generation. Pour les cours deja rediges :

```bash
python tools/generate.py --sheets
```

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
| **Cours** | Lecture, fiche de revision, QCM, demonstrations, notes personnelles |
| **Graphe** | Le cursus comme graphe : ce qui est maitrise, ce qui est accessible, ce qui est verrouille |

### Reprendre la lecture

La page d'un cours retient où vous en êtes : la section en haut de l'écran et
la part de cette section déjà lue, plutôt qu'un défilement en pixels qui
changerait avec la taille de la fenêtre, le rendu des formules ou le zoom.
L'enregistrement se fait une seconde après l'arrêt du défilement et en quittant
la page, dans `progress.db` (une position par cours).

À la réouverture, un bandeau discret propose **Reprendre à : <section>**. Rien
ne défile sans clic, et le bandeau disparaît dès qu'on fait défiler soi-même.
L'accueil affiche une carte **Reprendre la lecture** pour le dernier cours
consulté : titre, section, part lue et ancienneté. Pas de reprise proposée au
tout début ni au-delà de 95 % du cours. Si le cours a été régénéré, la section
est retrouvée par son titre ; si elle n'existe plus, le cours s'ouvre au début.

## Tenir le rythme

L'accueil s'ouvre sur une carte **Aujourd'hui** : ce qu'il y a a faire, en
combien de temps, et ou en est la serie.

### Revisions espacees

C'est le moteur. Chaque question porte une date de prochaine revision : une
reponse juste la repousse (1 jour, puis 3, puis 7, puis l'intervalle se
multiplie par une facilite propre a la question), une erreur la ramene
immediatement. L'accueil annonce donc ce qui est du aujourd'hui, et une seance
de revision melange les matieres.

C'est la seule raison non arbitraire d'ouvrir l'application chaque jour : il y
a ce qu'il faut revoir, et rien de plus.

### Objectif du jour et serie

L'objectif se compte en **briques** : une seance de QCM, une revision terminee,
une demonstration soumise ou reussie. Une seule suffit par defaut — c'est
l'habitude qu'on cherche, pas la performance.

La serie tolere **deux gels par mois** : un jour manque des deux derniers jours
est couvert automatiquement. Une serie qui casse au premier oubli fait
abandonner, alors qu'elle est censee soutenir. Un gel ne couvre pas un trou
ancien : il protege une serie qu'on entretient, il ne fabrique pas un passe.

### Quiz du jour

Dix questions **neuves**, reparties sur trois ou quatre chapitres deja
travailles, choisis parmi les plus fragiles et les plus anciens. Le modele
recoit les questions deja posees et ne doit en reprendre aucune. L'interet est
precisement de melanger : on passe de la logique aux probabilites sans
transition, comme dans un examen.

### Rappel cible

Parfois, pas tous les jours : quand un cours montre des erreurs recentes qui ne
sont pas un accident, l'accueil propose **Rappel conseille : <cours>**. Il faut
au moins quatre reponses sur les trois dernieres semaines, dont deux ratees,
et soit 30 % d'erreurs, soit deux questions ratees plusieurs fois. Le rappel
compte cinq questions neuves, generees a partir des questions ratees. Le
modele diagnostique la confusion commune, puis l'attaque sous plusieurs
angles : rappel de la definition, application ou le piege guette, question
de verification. Chaque correction est un petit rappel de cours. Un meme
cours n'est pas repropose avant quatre jours.

### Defi eclair

Cinq questions deja vues, chronometrees, tirees en priorite parmi celles qu'on
a ratees. Trois minutes, pour les jours ou il n'y a pas le temps de travailler
vraiment.

### XP, niveaux et jalons

L'XP est ponderee par la difficulte (une question de difficulte 5 vaut quatre
fois une question de difficulte 1, et une question de type exercice compte une
fois et demie), et se trompper rapporte quand meme un peu : chercher compte.
Chaque domaine a son propre niveau, ce qui transforme les 26 domaines en 26
barres de competence.

Les jalons sont des etapes reelles, pas des points : premier cours maitrise, un
domaine complet, dix demonstrations reussies, un parcours a moitie, une semaine
d'affilee. Vingt-quatre au total.

### Bilan hebdomadaire et carte allumee

Le tableau de bord compare la semaine en cours a la precedente — questions,
score moyen, revisions, demonstrations, jours travailles, XP — et nomme le
domaine qui a le plus avance comme ceux restes sans activite.

Dans la vue **Graphe**, un cours maitrise s'allume : halo de la couleur de son
domaine, fond teinte. La carte du cursus devient une carte de progression, avec
un compteur de cours allumes.

### Le score d'un cours

Le score n'est pas celui de votre meilleure seance : c'est **la part des
questions actuellement justes parmi celles que vous avez tentees**. Refaire une
question ratee et la reussir fait donc monter le score, et la rater de nouveau
le fait redescendre. C'est ce qui rend utile de ne refaire que ses erreurs.

Un cours passe **maitrise** quand ce score atteint le seuil (80 % par defaut)
*et* qu'assez de questions ont ete tentees — les deux tiers de la serie la plus
fournie. Repondre juste a deux questions faciles ne suffit donc pas a debloquer
la suite du cursus.

Les seances completes restent enregistrees comme historique, et servent a
reconstruire le suivi par question si la base est restauree.

### Raccourcis

| | |
|---|---|
| `Ctrl+1..4` | Accueil / Bibliotheque / Cours / Graphe |
| `Ctrl+K` | Ouvrir le chat sur le cours courant |
| `Ctrl+F` | Rechercher un cours |
| `Ctrl+N` | Etendre le syllabus |
| `Alt+↑` / `Alt+↓` | Puissance / indice, dans l'editeur de demonstrations |
| `Ctrl+G` | Afficher ou masquer la file de génération |

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

Un bouton *Apercu* rend le texte par KaTeX. Deux facons de faire relire :

- **Suis-je sur la bonne voie ?** pour un travail en cours. Claude ne releve
  jamais que la demonstration est incomplete — c'est le point de depart, pas un
  defaut. Il dit ce qui est deja etabli, si la direction mene au but, et donne
  la prochaine etape, une seule.
- **Corriger ma demonstration** (ou `Ctrl+Entree`) pour une copie terminee.
  Ouvre sur ce qui est acquis, puis dit ou en est la demonstration, puis LE
  premier point a reprendre avec une piste, puis au plus deux remarques de
  redaction.

Dans les deux cas : la solution n'est pas deroulee (sauf demande explicite),
une preuve correcte differente de la reference est reconnue correcte, et une
affirmation fausse est dite fausse — encourageant ne veut pas dire complaisant.
Vous corrigez, vous resoumettez : le fil garde les versions precedentes et
Claude commence par dire ce qui a progresse.

---

## Importer un cours magistral

**Bibliothèque → Importer un cours (PDF)…**, ou en ligne de commande :
`python tools/import_course.py run cours.pdf`. Le PDF peut être un poly ou des
transparents Beamer, en français ou en anglais.

1. **Lecture** (modèle des exercices) : Claude lit tout le document avec l'outil
   `Read`, par tranches de 20 pages. Il en tire le titre, les prérequis et les
   cours liés pris dans le catalogue, puis un plan de 4 à 10 sections. Chaque
   section indique ses pages, tout ce qu'elles contiennent et les passages trop
   elliptiques. Il transcrit aussi fidèlement chaque exercice.
2. **Inscription** : le cours rejoint le syllabus dans le domaine « Cours du
   MVA », avec ses prérequis. Le plan tiré du document remplace le plan habituel.
3. **Rédaction** : c'est la génération habituelle. Chaque section **relit ses
   pages** et garde toutes les définitions, notations, hypothèses et exemples,
   en français avec les termes anglais entre parenthèses. Elle ajoute les
   intuitions, les calculs sautés, des démonstrations courtes et des figures.
   Les exercices du document restent **à leur place dans le cours**, sans
   solution. Un lien « Correction détaillée dans l'onglet Exercices » y renvoie.
   Des liens pointent aussi vers les cours existants de l'application.
   Viennent ensuite QCM, démonstrations et fiche, comme pour tout cours.
4. **Corrections** : chaque exercice est corrigé avec le contenu du cours
   importé et des cours liés, comme un TD. Les corrections apparaissent dans
   l'onglet **Exercices du cours**, dépliables.

Chaque étape est enregistrée : une coupure reprend où on en était
(`python tools/import_course.py resume <id>`). Le document vit dans
`library/_td/<id>/` (type « course ») : `source.pdf`, `import.json`,
`td.json` et `corrections/`. Le cours lui-même vit dans `library/<id-du-cours>/`.

## Questions libres

Onglet **Questions** (Ctrl+6) : on pose n'importe quelle question de maths, par
exemple « pourquoi la variance d'une somme n'est pas la somme des variances ? ».
Claude (modèle du chat) reçoit le catalogue du cursus : chaque cours avec ses
mots-clés, et les titres de section des cours déjà rédigés. Il répond, puis
termine par **Où c'est traité** : un à quatre liens, en commençant par le cours
où la notion est introduite.

Chaque lien est vérifié par l'application avant affichage. Un cours inconnu
est retiré. Une section n'est gardée que si elle existe vraiment. Un cours pas
encore rédigé apparaît en orange : un clic l'ouvre pour le générer. Un clic sur
un cours rédigé l'ouvre directement à la bonne section, surlignée un instant.
Si la notion n'est traitée nulle part, Claude le dit et renvoie vers
l'Assistant pour étendre le syllabus.

Les questions restent dans la liste de gauche. On peut y revenir, poser une
question de suivi dans le même fil, ou supprimer le fil.

## L'assistant : demander un changement

Bouton **Assistant** (Ctrl+J) : un chat qui agit sur l'application. On lui dit
ce qu'on veut, par exemple « génère les cours de probas utiles pour le TD »,
« une nouvelle série de QCM sur les séries entières », « passe les exercices en
Opus » ou « ajoute un bouton pour exporter mes notes ».

Claude reçoit à chaque message l'état de l'application : les cours avec leur
rédaction, leur score et leurs prérequis, les parcours, les TD, la file de
génération et les réglages. Il répond brièvement et propose des **cartes
d'action**. Rien ne part sans un clic sur la carte.

L'état est reconstruit à chaque envoi. De plus, la file de génération à jour
est jointe au début de chaque message : dans une conversation reprise, Claude
ne se fie donc pas à une file périmée. Pour chaque travail de la file, cet état
donne le statut (en attente, en cours, en pause, erreur, terminé, annulé),
l'avancement et les sections faites, les heures d'ajout, de démarrage et de
dernière progression. Il donne aussi la raison d'une attente ou d'une pause :
limite `gen/concurrency` atteinte, limite de débit de l'API ou erreur réseau
avec le délai avant la nouvelle tentative, annulation, dernier message
d'erreur. Au-delà de 15 éléments, la liste est coupée et le nombre d'éléments
restants est indiqué. Les travaux terminés ou annulés depuis plus d'une heure
ne sont plus listés. Les cours « Incomplet » sans génération active sont listés
avec leur raison : échec, arrêt manuel ou interruption lors d'une session
précédente. La bibliothèque affiche cette même raison à côté de l'état.

- générer des cours (dans l'ordre des prérequis, avec durée et coût estimés),
  en régénérer un, ajouter une série de QCM, produire des fiches ;
- corriger un TD importé, étendre le syllabus ;
- changer un réglage (modèles, parallélisme, seuil de maîtrise, objectif du
  jour) ;
- arrêter des générations, ouvrir une page, lancer une séance ;
- **modifier l'application**. Claude rédige un cahier des charges précis, puis
  un `claude` limité aux outils Read, Edit, Write, Glob et Grep travaille dans
  le dossier du projet. Il n'a ni shell ni accès à `library/`. L'application
  lance ensuite `tools/selftest.py` : en cas d'échec, Claude corrige, deux tours
  au plus. Si tout passe, le changement est committé et poussé. Des cartes
  proposent alors de redémarrer l'application ou d'annuler le changement
  (`git revert`). Si les tests échouent encore, rien n'est enregistré : on
  choisit de retirer les modifications ou de les garder. Une modification ne
  démarre que si le code n'a pas de changement en attente.

## Corriger ses TD

Onglet **TD** (Ctrl+5) → *Importer un TD…* : choisissez le sujet en PDF.

1. **Lecture du sujet** (Sonnet, quelques centimes) : Claude lit le PDF avec
   l'outil `Read`, limité au dossier du TD, et transcrit chaque exercice avec
   ses formules en LaTeX. Il rattache chaque exercice aux cours du syllabus
   qui contiennent les définitions et théorèmes utiles.
2. **Correction** (modèle des cours, Opus par défaut) : un appel par exercice,
   trois en parallèle. Chaque correction reçoit le contenu des cours
   rattachés s'ils sont déjà rédigés, pour reprendre leurs notations. Sinon,
   elle s'appuie sur leur fiche du programme. On y trouve d'abord *l'idée* :
   pourquoi cette approche est naturelle, comment on la trouve. Viennent
   ensuite ce qu'on utilise, avec des liens cliquables vers les cours, puis
   la solution détaillée à déplier et les pièges à éviter.

Chaque correction est enregistrée dès qu'elle est finie. Après une coupure,
*Reprendre la correction* ne refait que les exercices manquants. Si la
transcription d'un exercice change, sa correction est refaite.

Dans la page :

- **Cours utiles** : les puces vertes sont des cours déjà rédigés. Les
  orange ne sont pas encore générés : un clic ouvre le cours pour le
  lancer.
- **Énoncé seul** masque la correction pour chercher d'abord.
- La sélection d'un passage et *Décortiquer avec Claude* marchent comme dans
  les cours.

En ligne de commande :

```bash
python tools/td.py run ~/TD1.pdf        # importer, lire et corriger
python tools/td.py correct td-mva-2026  # reprendre
python tools/td.py list
```

Les sujets vivent dans `library/_td/<id>/` : `source.pdf`, `structure.json`
et `corrections/NN.html`.

## Savoir si ca genere ou si c'est plante

L'application montre en permanence, dans la barre de statut, un point de
couleur avec le nombre de generations et l'age du dernier signe de vie :

- **vert** : des donnees arrivent
- **orange** : plus rien depuis un moment, ce qui reste normal sur une section
  longue
- **rouge** : silence anormal ; un bandeau le signale, et l'appel sera
  interrompu puis relance tout seul

La file de generation (`Ctrl+G`) detaille la meme chose par cours : etape en
cours, nombre de caracteres deja recus, chronometre, et age du dernier signe de
vie. Cet affichage se met a jour toutes les deux secondes meme quand rien
n'arrive : c'est ce qui permet de distinguer *lent* de *bloque*.

Le bouton **Masquer** de la file (ou `Ctrl+G`) la replie en une pastille dans
l'en-tête, avec le nombre de générations en cours ; un clic la rouvre. Le choix
est conservé au redémarrage, et rien n'est mis en pause. Tant que la file est
masquée, elle ne s'ouvre plus d'elle-même, l'indicateur de la barre de statut
et les bandeaux de fin de génération se taisent : un échec fait seulement
passer la pastille en alerte (▲ rouge), la fin de tout le travail l'affiche en
✓ discret, une file vide en ○. La Bibliothèque garde l'état de chaque cours.

Sous le capot, chaque appel est surveille : au-dela de quatre minutes de
silence complet (reglable dans les preferences), le processus et toute sa
descendance sont tues, l'echec est traite comme une panne reseau, et l'appel
est relance. Les sections deja ecrites ne sont jamais reperdues.

Depuis un terminal, meme pendant que l'application tourne :

```bash
python tools/status.py           # etat a l'instant t
python tools/status.py --watch   # rafraichi toutes les 5 s
```

Il liste les appels au modele en cours et sur quoi ils portent, la derniere
ecriture sur le disque, les cours incomplets, et termine par un verdict.

## Generation en ligne de commande

Pratique pour lancer un gros lot et laisser tourner :

```bash
python tools/generate.py al-svd cd-hessienne     # des cours precis
python tools/generate.py --path opt-dualite-kkt  # un cours et tous ses prerequis
python tools/generate.py --track mva-optimisation
python tools/generate.py --list
python tools/generate.py --resume                # reprendre ce qui a ete interrompu
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
    sheet.html       fiche de revision
    plan.json        plan et resultats laisses en exercice
    sections/        une section par fichier (reprise de generation)
    exercises.json   QCM et demonstrations (serie 1)
    quizzes.json     series de QCM supplementaires
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
  syllabus_extra.py  ajouts faits depuis l'app : fusion, validation, retrait
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
