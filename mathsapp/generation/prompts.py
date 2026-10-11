"""Prompts de generation. C'est ici que se joue la qualite pedagogique."""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from ..syllabus import Course, Syllabus

# ---------------------------------------------------------------------------
# Reference de l'API de figures. Injectee dans les prompts qui produisent du
# HTML. Doit rester compacte : elle est envoyee a chaque section.
# ---------------------------------------------------------------------------
MVIZ_API = r"""
API DE FIGURES (bibliotheque `mviz`, deja chargee, aucune dependance a importer)

  <div class="mviz" id="fig-nom"></div>
  <script>
  mviz.plot('#fig-nom', {
    xrange: [-3, 3], yrange: [-1, 4],   // fenetre mathematique
    ratio: 0.58,                         // hauteur / largeur (defaut 0.58)
    equal: true,                         // repere orthonorme (cercles ronds)
    xlabel: 'x', ylabel: 'y',
    grid: true, axes: true,              // mettre a false pour un schema pur
    caption: 'Legende sous la figure, avec $des maths$ si utile.',
    params: {                            // curseurs : facultatif mais precieux
      a: {min: -2, max: 2, step: 0.05, value: 1, label: 'a'}
    },
    animate: {param: 'a', period: 6, pingpong: true},  // bouton lecture
    draw: function (g, p) {
      g.curve(x => p.a * x * x, {color: 'accent', label: 'y = a x^2'});
      g.curve(x => Math.sin(x), {color: 'accent2', dash: true, label: 'sin'});
      g.param(t => [Math.cos(t), Math.sin(t)], [0, 2*Math.PI], {color: 'ok'});
      g.polyline([[0,0],[1,2],[2,1]], {color:'violet', fill:'violet', close:true});
      g.segment([0,0], [1,1], {color: 'muted', dash: true});
      g.hline(0); g.vline(1);
      g.point(1, p.a, {label: 'M', color: 'accent2'});
      g.vector([0,0], [1,2], {color: 'ok', label: '∇f'});
      g.area(x => Math.exp(-x*x), 0, [-1, 1], {color: 'accent'});
      g.bars([[0,1,0.4],[1,2,0.8]], {color: 'accent'});   // [x0, x1, hauteur]
      g.text(1, 3, 'annotation', {size: 13, color: 'muted'});
      g.heat((x,y) => x*x + 3*y*y);                        // champ scalaire
      g.contour((x,y) => x*x + 3*y*y, [0.5, 1, 2, 4]);     // lignes de niveau
      g.field((x,y) => [-2*x, -6*y], {n: 12});             // champ de vecteurs
    }
  });
  </script>

Couleurs nommees : accent (bleu), accent2 (orange), ok (vert), warn, violet,
pink, teal, muted. Elles s'adaptent au theme clair/sombre : ne mettez jamais de
couleur en dur.

Pour un schema libre (diagramme, patatoides, arbre, fleches entre boites) :

  mviz.draw('#fig-nom', {
    ratio: 0.45, caption: '...',
    draw: function (ctx, w, h, col) {   // ctx = canvas 2D, col = palette du theme
      ctx.strokeStyle = col.accent; ctx.fillStyle = col.fg; ctx.lineWidth = 2;
      ctx.font = '13px ui-sans-serif, system-ui, sans-serif';
      /* dessin libre en pixels */
    }
  });

Regles pour les figures :
- Une figure doit montrer un mecanisme, pas decorer. Si elle n'apprend rien, ne
  la mettez pas.
- Preferez un curseur (`params`) a trois figures statiques : voir bouger le
  parametre est ce qui fait comprendre.
- Le code doit etre du JavaScript ES5/ES6 simple et SANS ERREUR : il s'execute
  tel quel. Pas de bibliotheque externe, pas de `import`, pas de `await`.
- Chaque figure a un `id` unique dans la page.
"""

HTML_CONVENTIONS = r"""
LANGUE : francais, avec TOUS les accents et signes diacritiques
(e-accent-aigu, e-accent-grave, a-accent-grave, c-cedille, circonflexes...).
Ces consignes sont ecrites sans accents pour des raisons techniques :
n'imitez surtout pas ce style. Un texte de cours sans accents est
inacceptable. Cela vaut aussi pour les titres, les legendes de figures, les
libelles de curseurs et le texte dessine dans les figures.

FORMAT DE SORTIE : fragment HTML uniquement.
Interdit : ``` de code autour de la reponse, <html>, <head>, <body>, <article>,
commentaires d'introduction du type "Voici le cours". Vous ecrivez directement
les balises du contenu.

Maths : LaTeX entre $ ... $ (en ligne) et $$ ... $$ (centre). Le rendu est fait
par KaTeX : n'utilisez que des commandes supportees par KaTeX. Macros deja
definies : \R \N \Z \Q \C \E \P \1 \eps \dd \Var \Cov \rank \tr \diag \Id
\argmin \argmax \norm{...} \abs{...} \scal{...}{...}.
N'ecrivez JAMAIS de LaTeX en dehors des delimiteurs $.

Encadres disponibles (n'inventez pas d'autres classes) :

  <div class="box definition"><span class="box-title">Definition</span>
    <p>...</p></div>

  <div class="box theorem"><span class="box-title">Theoreme (nom)</span>
    <p class="statement">...</p></div>

  classes : definition, theorem, proposition, lemma, corollary,
            intuition, warning, example, recap

  <div class="box intuition"><span class="box-title">L'idee</span>...</div>
  <div class="box warning"><span class="box-title">Piege classique</span>...</div>
  <div class="box example"><span class="box-title">Exemple</span>...</div>
  <div class="box recap"><span class="box-title">A retenir</span>...</div>

Demonstrations : toujours dans un bloc repliable, decoupe en etapes nommees.

  <details class="proof" data-of="Nom exact du resultat demontre">
    <summary>Demonstration</summary>
    <div class="proof-body">
      <div class="proof-step"><span class="step-label">Etape 1 &mdash; ce qu'on cherche a obtenir</span>
        <p>...</p></div>
      <div class="proof-step"><span class="step-label">Etape 2 &mdash; ...</span>
        <p>...</p></div>
      <p class="qed">&#8718;</p>
    </div>
  </details>

L'attribut data-of est obligatoire : il sert a l'assistant pas-a-pas.
Chaque etape doit dire POURQUOI on la fait avant de dire ce qu'on fait.

Autres balises autorisees : p, h2, h3, h4, ul, ol, li, strong, em, code, pre,
table (thead/tbody/tr/th/td), blockquote, hr, span class="badge", figure,
figcaption, et les <div class="mviz"> + <script> des figures.
"""

STYLE = r"""
Vous ecrivez un cours de mathematiques pour un etudiant francais qui entre en
M2 MVA (ENS Paris-Saclay). Son niveau de depart a supposer : terminale option
maths expertes, solide mais sans aucune notion post-bac. Il vise l'IA
(optimisation, probabilites, apprentissage statistique).

CE QUI EST ATTENDU

1. L'intuition d'abord, toujours. Avant chaque definition formelle, expliquez
   le probleme qu'elle resout et donnez une image mentale concrete. Une notion
   qui tombe du ciel est un echec.
2. Longueur libre. Un cours long et lumineux vaut mieux qu'un cours court et
   opaque. Ne compressez jamais au prix de la comprehension. En revanche pas de
   remplissage : chaque paragraphe doit apporter quelque chose.
3. Visuel des que possible. Une figure interactive a chaque endroit ou la
   geometrie eclaire l'algebre.
4. Demontrez. Les resultats importants sont demontres, en etapes explicites,
   avec la strategie annoncee avant les calculs. Une preuve doit s'ouvrir sur
   "voici l'idee de la preuve en une phrase".
5. Nommez les pieges. A chaque notion delicate, dites explicitement l'erreur
   que tout le monde fait.
6. Reliez au ML quand c'est honnete. Si une notion sert directement en
   apprentissage, dites-le en une ou deux phrases. Ne forcez pas le lien s'il
   n'existe pas.
7. Rigueur : les enonces sont exacts, les hypotheses completes, les
   quantificateurs dans le bon ordre. Le ton est direct, en francais, sans
   emphase creuse ("fascinant", "puissant", "il est important de noter que").
   Vouvoyez le lecteur ou utilisez la forme impersonnelle.
8. Notation : introduisez chaque symbole avant de l'utiliser.
"""


def _context(syl: Syllabus, course: Course) -> str:
    prereqs = [syl.get(p) for p in course.prereqs]
    known = [syl.get(p) for p in syl.ancestors(course.id)]
    later = [syl.get(d) for d in course.dependents]
    lines = [
        "COURS A ECRIRE : %s" % course.title,
        "Domaine : %s" % syl.domain_name(course.domain),
        "Niveau : %d/5 (%s)" % (course.level, syl.levels.get(course.level, "")),
        "Resume vise : %s" % course.summary,
        "Objectifs pedagogiques (l'etudiant doit savoir les faire a la fin) :",
    ]
    lines += ["  - %s" % o for o in course.objectives]
    lines.append("Mots-cles a couvrir : %s" % ", ".join(course.keywords))
    if prereqs:
        lines.append("Prerequis directs (deja etudies, vous pouvez vous y appuyer sans les redemontrer) :")
        lines += ["  - %s" % c.title for c in prereqs if c]
    if known:
        lines.append("Notions supposees acquises plus en amont : %s"
                     % ", ".join(c.title for c in known[-14:] if c))
    if later:
        lines.append("Cours qui s'appuieront sur celui-ci (preparez le terrain sans les traiter) : %s"
                     % ", ".join(c.title for c in later if c))
    return "\n".join(lines)


# --------------------------------------------------------------------- plan
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "goal": {"type": "string"},
                    "content": {"type": "string"},
                    "figures": {"type": "array", "items": {"type": "string"}},
                    "proofs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "goal", "content"],
            },
        },
        "proved_in_course": {"type": "array", "items": {"type": "string"}},
        "left_as_exercise": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "sections", "proved_in_course", "left_as_exercise"],
}


def plan_prompt(syl: Syllabus, course: Course, max_sections: int = 9) -> str:
    return f"""{STYLE}

{_context(syl, course)}

TACHE : concevoir le plan detaille de ce cours. Ne redigez pas encore le cours.

Contraintes :
- Entre 5 et {max_sections} sections, dans un ordre ou chaque section ne
  suppose que ce qui precede.
- La premiere section motive : quel probleme concret rend cette notion
  necessaire. Elle ne definit rien de formel.
- La derniere section recapitule et fait le lien avec la suite du parcours.
- Pour chaque section : `content` decrit en 3 a 6 phrases ce qui sera
  reellement traite (definitions, resultats, exemples), `figures` liste les
  visualisations interactives prevues (une phrase chacune, ou liste vide),
  `proofs` liste les resultats demontres dans cette section.
- `proved_in_course` : les resultats demontres integralement dans le cours.
  Tous les resultats structurants doivent y etre.
- `left_as_exercise` : 4 a 6 resultats volontairement NON demontres dans le
  cours, laisses a l'etudiant. Choisissez-les faisables avec le seul contenu du
  cours, et representatifs. Ils seront enonces dans le cours avec la mention
  qu'ils sont a demontrer en exercice.
- `hook` : une phrase qui dit ce que l'etudiant saura faire a la fin.

Redigez en francais avec TOUS les accents. Ces consignes sont ecrites sans
accents pour des raisons techniques : n'imitez pas ce style.

Repondez uniquement par l'objet JSON."""


# ------------------------------------------------------------------ section
def section_prompt(syl: Syllabus, course: Course, plan: dict, index: int,
                   written_titles: List[str], covered: str = "",
                   upcoming: str = "", source_text: str = "") -> str:
    section = plan["sections"][index]
    total = len(plan["sections"])
    others = "\n".join(
        "  %d. %s%s\n     %s" % (i + 1, s["title"],
                                 "   <- SECTION A ECRIRE" if i == index else "",
                                 s.get("content", ""))
        for i, s in enumerate(plan["sections"])
    )
    left = plan.get("left_as_exercise", [])
    left_txt = "\n".join("  - %s" % r for r in left) or "  (aucun)"
    figures = "\n".join("  - %s" % f for f in section.get("figures", [])) or "  (a vous de juger)"
    proofs = "\n".join("  - %s" % p for p in section.get("proofs", [])) or "  (aucune imposee)"

    intro = ""
    if index == 0:
        intro = (
            "\nCette section est la premiere du cours. Commencez par :\n"
            "  <h1>%s</h1>\n"
            "  <p class=\"lead\">deux ou trois phrases : ce que ce cours apporte et "
            "ce que le lecteur saura faire a la fin.</p>\n"
            "puis le <h2> de la section. Aucune autre section n'aura de <h1>.\n"
            % course.title
        )
    elif index == total - 1:
        intro = ("\nC'est la derniere section : terminez par un encadre "
                 "<div class=\"box recap\"> qui liste ce qu'il faut retenir, puis un court "
                 "paragraphe sur ce que ce cours ouvre.\n")

    return f"""{STYLE}

{HTML_CONVENTIONS}

{MVIZ_API}

{_context(syl, course)}

PLAN COMPLET DU COURS :
{others}

DEJA INTRODUIT AVANT VOTRE SECTION. Ces notions sont acquises : utilisez-les
directement, sans les redefinir, sans les reexpliquer, sans « rappelons que ».
Si vous en avez besoin, renvoyez-y d'une incise (« la table de verite de
l'implication, vue plus haut »).
{covered if covered else "  (rien : votre section est la premiere)"}

TRAITE AILLEURS, PAS PAR VOUS. N'anticipez pas ces contenus : au plus une
phrase d'annonce si la transition l'exige.
{upcoming if upcoming else "  (rien)"}

Resultats volontairement laisses en exercice pour TOUT le cours :
{left_txt}
Si l'un d'eux apparait dans votre section, enoncez-le proprement dans un
encadre et ajoutez <span class="badge">a demontrer en exercice</span> a la fin
de l'enonce, sans donner la preuve ni l'esquisser.

TACHE : rediger la section {index + 1}/{total}, intitulee "{section['title']}".
Objectif de la section : {section['goal']}
Contenu prevu : {section['content']}
Figures prevues :
{figures}
Demonstrations attendues dans cette section :
{proofs}
{intro}{_source_block(plan, index, source_text)}
Commencez par <h2>{section['title']}</h2>. Utilisez des <h3> pour structurer.
Ne redigez que cette section. Pas de preambule, pas de conclusion generale du
cours (sauf si c'est la derniere section). Sortie : HTML brut, rien d'autre."""


# ---------------------------------------------------------------- exercices
EXERCISES_SCHEMA = {
    "type": "object",
    "properties": {
        "qcm": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string"},
                    "difficulty": {"type": "integer"},
                    "question": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "integer"},
                    "explanation": {"type": "string"},
                    "section": {"type": "string"},
                },
                "required": ["id", "kind", "difficulty", "question", "choices",
                             "answer", "explanation"],
            },
        },
        "proofs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "difficulty": {"type": "integer"},
                    "title": {"type": "string"},
                    "statement": {"type": "string"},
                    "hints": {"type": "array", "items": {"type": "string"}},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["title", "content"],
                        },
                    },
                    "solution": {"type": "string"},
                },
                "required": ["id", "difficulty", "title", "statement", "hints", "steps", "solution"],
            },
        },
    },
    "required": ["qcm", "proofs"],
}


def exercises_prompt(syl: Syllabus, course: Course, plan: dict, digest: str) -> str:
    left = plan.get("left_as_exercise", [])
    left_txt = "\n".join("  - %s" % r for r in left) or "  (aucun)"
    return f"""{STYLE}

Vous produisez les exercices d'un cours deja redige. Voici sa structure et ses
passages cles.

{_context(syl, course)}

PLAN DU COURS :
{json.dumps([{"titre": s["title"], "contenu": s["content"]} for s in plan["sections"]], ensure_ascii=False, indent=1)}

RESULTATS LAISSES A DEMONTRER PAR L'ETUDIANT :
{left_txt}

EXTRAITS DU COURS REDIGE (pour caler le vocabulaire et les notations) :
{digest}

TACHE : produire un JSON avec deux tableaux, `qcm` et `proofs`.

`qcm` : exactement 15 questions a choix unique, difficulte croissante.
  - 3 de difficulte 1 : verifier qu'une definition est comprise.
  - 3 de difficulte 2 : application directe, un pas de calcul ou de logique.
  - 3 de difficulte 3 : il faut combiner deux idees du cours.
  - 3 de difficulte 4 : cas limite, contre-exemple, hypothese qu'on retire.
  - 3 de difficulte 5 : question qui demande du recul, ou un raisonnement
    en plusieurs etapes.

DEUX TYPES DE QUESTIONS, indiques par le champ `kind`.

  `kind: "direct"` (10 questions) : on repond de tete ou en un pas. L'enonce
  tient en une ou deux phrases.

  `kind: "exercice"` (5 questions, UNIQUEMENT aux difficultes 3, 4 et 5) : un
  vrai exercice, celui qu'on fait sur une feuille. Le lecteur doit poser des
  calculs, verifier des hypotheses, mener un raisonnement en plusieurs etapes,
  avant de pouvoir choisir. Les quatre propositions ne donnent que le resultat
  final.

  Le critere est simple : si on peut repondre de tete ou en une ligne, ce n'est
  PAS un exercice, c'est une question directe. Mettez alors `kind: "direct"`.

  Contre-exemple, a ne pas produire :
      « Soit f(x,y,z) = xyz. Calculez le gradient en (1,2,3). »
    Trois derivees immediates, aucune decision a prendre. C'est une question
    directe deguisee.

  Exemple de ce qui est attendu :
      « Soit f la fonction definie sur R^2 par f(x,y) = x^3 - 3xy + y^3.
        Determinez tous les points critiques de f, puis, en etudiant la
        hessienne en chacun, dites lesquels sont des minimums locaux.
        Combien y en a-t-il, et en quel(s) point(s) ? »
    Il faut resoudre un systeme, calculer une hessienne, etudier son signe en
    deux points, conclure. Les propositions sont : « un seul, en (1,1) »,
    « deux, en (0,0) et (1,1) », « aucun », « un seul, en (0,0) ».

  Regles :
    * l'enonce fait au moins trois phrases, ou comporte une formule centree,
      et il est autosuffisant : toutes les donnees necessaires y figurent ;
    * il demande un resultat precis et verifiable (une valeur, un nombre, un
      point, une reponse oui/non assortie d'une raison), pas une dissertation ;
    * les distracteurs sont les resultats qu'on obtient en commettant une
      erreur precise et frequente en chemin — signe oublie, hypothese non
      verifiee, point critique manque, facteur absent — pas des valeurs prises
      au hasard ;
    * les propositions ne contiennent QUE le resultat, jamais la demarche ;
    * l'explication deroule la solution etape par etape, et dit a quelle
      erreur mene chaque distracteur.
  - 4 propositions par question, une seule correcte, `answer` = son index (0-3).
  - Les mauvaises reponses doivent correspondre a des erreurs REELLES et
    plausibles (confusion classique, quantificateur inverse, hypothese
    oubliee), jamais a du remplissage absurde.
  - EQUILIBRE DES PROPOSITIONS. C'est la regle la plus souvent violee, et elle
    suffit a rendre un QCM inutile : si la bonne reponse est plus longue ou
    plus argumentee que les autres, on la reconnait sans rien savoir du cours.
      * les quatre propositions ont une longueur et un registre comparables,
        a 20 % pres ;
      * si la bonne reponse porte un raisonnement, les trois autres en portent
        un aussi : un raisonnement faux mais plausible, celui que ferait
        vraiment quelqu'un qui se trompe ;
      * sinon, aucune des quatre n'en porte, et l'explication seule justifie.
        C'est le choix a preferer : une proposition est une affirmation, pas
        une demonstration ;
      * ecrivez les trois distracteurs d'abord, puis la bonne reponse dans le
        meme moule.
  - Repartissez la bonne reponse sur les quatre positions : elle ne doit pas
    tomber presque toujours en A ou en B.
  - Aucune proposition ne fait reference aux autres (« aucune des reponses
    ci-dessus », « les deux premieres ») : l'ordre des propositions change.
  - `explanation` : pourquoi la bonne reponse est bonne ET pourquoi le piege
    principal est un piege. 2 a 5 phrases.
  - `section` : le titre de la section du cours concernee.

`proofs` : 5 demonstrations a faire, difficulte croissante (1 a 5).
  - Reprenez en priorite les resultats laisses en exercice ci-dessus.
  - `statement` : l'enonce complet, hypotheses comprises.
  - `hints` : 3 indices, du plus vague au plus explicite. Le premier donne la
    strategie ("raisonnez par l'absurde"), le dernier donne la premiere ligne.
  - `steps` : le squelette de la preuve, 3 a 6 etapes. Chaque `title` nomme
    l'etape, chaque `content` explique en une a trois phrases CE QU'ON FAIT ET
    POURQUOI, sans dérouler tout le calcul.
  - `solution` : la demonstration complete et rigoureuse, redigee.

Redigez en francais avec TOUS les accents : ces consignes sont ecrites sans
accents pour des raisons techniques, n'imitez pas ce style.

Tous les champs texte sont du HTML simple (p, ul, li, strong, em, code) avec du
LaTeX entre $ ... $. Pas de titres <h*>, pas de figures, pas de blocs ```.
Repondez uniquement par l'objet JSON."""


# ---------------------------------------------------------------------- chat
def chat_system(course: Optional[Course], syl: Optional[Syllabus]) -> str:
    base = """Vous etes un tuteur de mathematiques. Votre interlocuteur prepare
son entree en M2 MVA (IA, ENS Paris-Saclay) et remonte tout son cursus de maths
depuis le niveau terminale.

Regles :
- Repondez en francais, directement, sans preambule ni flatterie.
- Donnez l'intuition avant le formalisme, puis le formalisme complet et exact.
- Si la question revele une confusion, nommez la confusion explicitement.
- Ne survendez pas : si un point est vraiment technique, dites-le.
- Si la question est vague, repondez a l'interpretation la plus utile et
  dites en une ligne ce que vous avez suppose. Ne posez une question en retour
  que si c'est reellement bloquant.
- Vous pouvez proposer un petit exercice de verification quand c'est pertinent.

FORMAT : repondez en HTML simple. Balises autorisees : p, ul, ol, li, strong,
em, code, pre, h4, table, et <div class="box intuition|warning|example">
<span class="box-title">Titre</span>...</div>. Les maths sont en LaTeX entre
$ ... $ ou $$ ... $$ (KaTeX). Pas de balises ``` autour de la reponse, pas de
<html> ni <body>. N'ecrivez JAMAIS de mathematiques dans <code> ni dans <pre> :
<code> est reserve aux identifiants de code. Macros disponibles : \\R \\N \\Z \\Q \\C \\E \\P \\eps \\dd
\\Var \\Cov \\rank \\tr \\diag \\Id \\argmin \\argmax \\norm{} \\abs{} \\scal{}{}."""
    if course is None:
        return base
    ctx = "\n\nCONTEXTE : la question porte sur le cours \"%s\" (%s, niveau %d/5). %s" % (
        course.title,
        syl.domain_name(course.domain) if syl else course.domain,
        course.level,
        course.summary,
    )
    if syl:
        acquired = [syl.title(p) for p in syl.ancestors(course.id)]
        if acquired:
            ctx += ("\nNotions deja vues dans le parcours, utilisables sans "
                    "explication prealable : %s." % ", ".join(acquired[-18:]))
        ctx += ("\nNe supposez PAS connu ce qui vient apres ce cours dans le "
                "cursus ; si c'est indispensable, signalez que c'est en avance.")
    return base + ctx


def proof_helper_system(course: Optional[Course], syl: Optional[Syllabus]) -> str:
    return chat_system(course, syl) + """

MODE DEMONSTRATION PAS A PAS. On vous donne une demonstration. Votre role :
expliquer la LOGIQUE de chaque etape, pas la reciter.
Pour chaque etape, dites : ce qu'on cherche a obtenir, pourquoi cette
manipulation-la est la bonne idee, et ce qui aurait echoue autrement.
Signalez ou se cache la difficulte reelle et quelles hypotheses sont utilisees
a quel moment (c'est presque toujours la que se trouve le sens de la preuve)."""


def proof_walkthrough_prompt(title: str, proof_text: str) -> str:
    return f"""Voici une demonstration extraite du cours, concernant : {title}

--- debut de la demonstration ---
{proof_text}
--- fin ---

Decortiquez-la. Structure attendue :
1. <h4>L'idee en une phrase</h4> : la strategie globale, avant tout calcul.
2. <h4>Etape par etape</h4> : pour chaque etape, un paragraphe qui dit ce qu'on
   veut obtenir, pourquoi ce mouvement precis, et quelle hypothese sert ici.
3. <h4>Ou est la difficulte</h4> : le point ou un etudiant bloque ou se trompe.
4. <h4>Ce qu'il faut retenir de la methode</h4> : le schema de preuve
   reutilisable ailleurs.

Ensuite l'utilisateur vous posera des questions sur cette demonstration."""


def proof_review_system(course: Optional[Course], syl: Optional[Syllabus],
                        mode: str = "complete") -> str:
    """Consignes de correction. `mode` vaut "etape" ou "complete"."""
    common = chat_system(course, syl) + """

VOUS RELISEZ LA COPIE D'UN ÉTUDIANT. Il cherche pour de vrai, il vous montre
où il en est. Votre travail est de l'aider à avancer, pas de noter.

Le ton, d'abord. Il compte autant que le contenu : une relecture décourageante
fait arrêter de chercher, et c'est chercher qui fait progresser.

- Commencez par ce qui est effectivement acquis, en le nommant précisément.
  « Vous avez bien posé la définition de Fréchet plutôt que de passer par les
  coordonnées » vaut quelque chose ; « bon début » ne vaut rien. Un compliment
  creux s'entend comme une politesse avant la sanction.
- Ne reprochez jamais à l'étudiant ce qu'il n'a pas prétendu faire.
- Une seule chose à reprendre à la fois : la première dans l'ordre de lecture.
  Le reste attendra la prochaine version. Une liste de six défauts ne se
  corrige pas, elle se subit.
- Formulez le manque comme la suite du travail, pas comme une lacune :
  « il reste à établir que… » plutôt que « vous n'avez pas montré que… ».
- Bannis : « il suffit de », « évidemment », « comme vous le savez »,
  « vous auriez dû », et toute ouverture par ce qui manque.
- Quand c'est juste, dites-le d'emblée et sans réserve. Ne cherchez pas un
  défaut pour équilibrer.

L'exactitude ne se négocie pas pour autant. Une affirmation fausse est dite
fausse, clairement, et vous dites pourquoi. Être encourageant ne veut pas dire
laisser passer : cela veut dire dire vrai sans humilier.

CE QUI N'EST PAS ÉCRIT N'EST PAS FORCÉMENT IGNORÉ. L'étudiant tape ses
démonstrations au clavier, ce qui est lent et pénible. Il abrège donc : il
saute les étapes de routine, écrit « on conclut », « idem », « de même », et
ne rédige pas les conclusions qui découlent immédiatement de ce qui précède.
C'est une économie d'écriture, pas un défaut de rigueur.

Distinguez donc deux choses, et ne les traitez pas de la même façon :

- Ce qui manque parce qu'il ne l'a pas tapé : une conclusion qui suit
  immédiatement, un calcul de routine annoncé mais non déroulé, une
  vérification triviale, un « de même » pour un cas symétrique. Considérez-le
  comme acquis. Vous pouvez le signaler, mais en une seule ligne groupée et
  sans en faire une remarque par item — par exemple « non rédigé, et sans
  doute clair pour vous : la conclusion et le cas symétrique ». Cela ne va
  jamais dans « le point à reprendre ».
- Ce qui manque parce qu'il ne sait pas le faire, ou ce qui est faux : une
  affirmation qui ne suit pas, une hypothèse absente qui change le résultat,
  une étape où se cache la vraie difficulté du problème. C'est là, et là
  seulement, que vous intervenez.

En cas de doute sur la nature d'un manque, posez la question en une phrase
plutôt que de l'imputer à une lacune.

Deux règles de fond :
- Une démonstration correcte mais différente de la solution de référence est
  correcte. Ne reprochez jamais une méthode différente ; si elle est plus
  longue ou plus fragile, dites-le après avoir reconnu qu'elle marche.
- Vous ne déroulez pas la solution. Vous donnez de quoi repartir, pas la
  suite. Seule exception : s'il demande explicitement la solution complète.
- Citez le passage exact de sa copie quand vous parlez d'un endroit précis."""

    if mode == "etape":
        return common + """

MODE « SUIS-JE SUR LA BONNE VOIE ». L'étudiant vous envoie volontairement un
travail EN COURS, souvent le début. Il ne prétend pas avoir fini.

Ne relevez donc jamais que la démonstration est incomplète : c'est le point de
départ, pas un défaut. Pas de verdict, pas de bilan.

Structure :
1. <h4>Où vous en êtes</h4> ce qui est établi à ce stade, formulé comme un
   acquis solide sur lequel s'appuyer. Soyez précis : quel résultat
   intermédiaire est maintenant disponible.
2. <h4>La direction</h4> répondez à sa question : ce chemin mène-t-il au but ?
   Si oui, dites pourquoi il est bon, et ce qu'il va falloir contrôler en
   route. Si non, dites-le franchement et tôt — le laisser creuser une
   impasse serait un mauvais service — en expliquant ce qui coince dans la
   stratégie, et quelle autre entrée est plus prometteuse.
3. <h4>La prochaine étape</h4> UNE seule, celle qui vient immédiatement après
   où il s'est arrêté. Une question ou une indication, jamais le calcul fait
   à sa place.
4. Si et seulement si un point de rédaction risque de le bloquer plus loin
   (quantificateur ambigu, objet utilisé avant d'être introduit), une remarque
   en une phrase. Sinon, n'en mettez pas : ce n'est pas le moment."""

    return common + """

MODE CORRECTION COMPLÈTE. L'étudiant considère sa démonstration terminée et
demande une relecture d'ensemble.

Structure :
1. <h4>Ce qui est acquis</h4> ouvrez par là, toujours. Nommez les étapes
   justes et les bons choix de méthode. C'est une partie du travail de
   relecture, pas une politesse.
2. <h4>Où en est la démonstration</h4> une phrase claire : elle tient ; elle
   tient mais il reste un point à établir ; elle bute sur une erreur de
   raisonnement ; elle ne répond pas à l'énoncé. Sans détour et sans dureté.
3. <h4>Le point à reprendre</h4> LE premier problème dans l'ordre de lecture :
   ce qui est affirmé, pourquoi cela ne suit pas, et une question ou une piste
   pour repartir. Un seul point, même s'il y en a d'autres.
4. <h4>Rédaction</h4> deux remarques au maximum, les plus utiles :
   quantificateurs, hypothèses utilisées sans être invoquées, « donc » non
   justifiés, objets employés avant d'être introduits. Omettez cette section
   si la rédaction est propre.
5. Si la démonstration est correcte : dites-le nettement en premier, signalez
   ce qui peut être allégé, et proposez une variante ou une généralisation à
   chercher. Pas de réserve inventée pour la forme.

Terminez sur ce qui est à portée immédiate, jamais sur l'inventaire de ce qui
manque."""


def proof_review_prompt(title: str, statement: str, solution: str,
                        attempt: str, attempt_no: int = 1,
                        mode: str = "complete") -> str:
    again = ""
    if attempt_no > 1:
        again = ("\nC'est sa version numéro %d. Comparez avec ce qu'il avait écrit "
                 "plus tôt dans cette conversation : dites d'abord ce qui a "
                 "progressé, puis si le point signalé est réglé.\n" % attempt_no)
    if mode == "etape":
        intro = ("L'étudiant vous montre où il en est et demande s'il est sur la "
                 "bonne voie. Son travail est en cours : ne lui reprochez pas de "
                 "ne pas avoir fini.")
    else:
        intro = "L'étudiant considère sa démonstration terminée et demande une relecture."

    return f"""{intro}

ÉNONCÉ À DÉMONTRER ({title}) :
{statement}

SOLUTION DE RÉFÉRENCE (pour vous seul, à ne pas recopier ; une preuve correcte
qui en diffère reste correcte, et un chemin différent du sien peut très bien
aboutir) :
{solution}
{again}
--- ce qu'il a écrit ---
{attempt}
--- fin ---"""


DAILY_SCHEMA = {
    "type": "object",
    "properties": {"qcm": EXERCISES_SCHEMA["properties"]["qcm"]},
    "required": ["qcm"],
}


def daily_quiz_prompt(syl: Syllabus, items: List[dict], count: int = 10) -> str:
    """Questions du jour, reparties sur plusieurs cours deja etudies.

    `items` : [{course, digest, seen}] ou `seen` liste les enonces deja poses.
    """
    blocks = []
    for item in items:
        course = item["course"]
        seen = "\n".join("      - %s" % q[:110] for q in item.get("seen", [])[:18])
        blocks.append(
            "### %s  [%s]  niveau %d/5\n"
            "Objectifs : %s\n"
            "Extraits du cours :\n%s\n"
            "Questions deja posees sur ce cours (a ne pas reprendre) :\n%s"
            % (course.title, course.id, course.level,
               " ; ".join(course.objectives),
               item["digest"], seen or "      (aucune)"))
    corpus = "\n\n".join(blocks)
    titles = ", ".join(item["course"].title for item in items)

    return f"""{STYLE}

Vous composez le QUIZ DU JOUR : une serie courte qui fait reviser plusieurs
chapitres a la fois, pour entretenir ce qui a deja ete travaille.

Ce n'est pas le QCM d'un cours. Son interet est precisement de melanger : on
passe de la logique aux probabilites sans transition, comme dans un examen, et
on verifie que les notions anciennes tiennent encore.

COURS AU PROGRAMME DU JOUR : {titles}

{corpus}

TACHE : produire exactement {count} questions a choix unique, NOUVELLES.

Regles :
- Repartissez les questions entre les cours ci-dessus, a peu pres
  equitablement. Chaque cours doit apparaitre.
- Aucune question deja posee, meme reformulee ou avec d'autres valeurs. Les
  enonces existants vous sont donnes pour cela.
- Difficultes melangees, de 1 a 4 : le quiz du jour doit pouvoir se faire en
  cinq a huit minutes. Pas plus de deux questions de difficulte 4, et au plus
  une de type `exercice`.
- Privilegiez ce qui se verifie vite et ce qui s'oublie : definitions exactes,
  hypotheses d'un theoreme, contre-exemples, signes et facteurs, ordre des
  quantificateurs.
- Deux ou trois questions peuvent croiser deux cours du programme, si le lien
  est reel et pas artificiel.
- `section` : indiquez le TITRE du cours d'ou vient la question, pas la section.
- Toutes les regles du QCM s'appliquent : quatre propositions de longueur et de
  registre comparables, une seule correcte, distracteurs correspondant a des
  erreurs reelles, position de la bonne reponse repartie, aucune proposition ne
  renvoyant aux autres. Une proposition est une affirmation, pas une
  demonstration.
- L'explication dit pourquoi la bonne reponse est bonne et pourquoi le piege
  principal est un piege.
- Francais avec tous les accents ; ces consignes sont sans accents pour des
  raisons techniques, n'imitez pas ce style.

Repondez uniquement par {{"qcm": [...]}}, chaque question portant id, kind,
difficulty, question, choices, answer, explanation, section."""

# ---------------------------------------------------------------------------
# Restaure : ce bloc avait ete supprime par erreur lors de la reecriture de
# proof_review_system (commit c7f3618), qui avait tronque la fin du fichier.
# ---------------------------------------------------------------------------
SYLLABUS_SCHEMA = {
    "type": "object",
    "properties": {
        "domains": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "color": {"type": "string"},
                },
                "required": ["id", "name", "description"],
            },
        },
        "courses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "domain": {"type": "string"},
                    "level": {"type": "integer"},
                    "prereqs": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                    "objectives": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "domain", "level", "prereqs",
                             "summary", "objectives", "keywords"],
            },
        },
        "tracks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "goal": {"type": "string"},
                    "extra": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "goal"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["courses"],
}


def catalogue(syl: Syllabus, max_per_domain: int = 40) -> str:
    """Catalogue compact des cours existants, pour cabler les prerequis."""
    lines = []
    for did in syl.domain_order:
        courses = syl.by_domain(did)
        if not courses:
            continue
        lines.append("# %s  [%s]" % (syl.domain_name(did), did))
        for c in courses[:max_per_domain]:
            lines.append("  %-34s niv.%d  %s" % (c.id, c.level, c.title))
    return "\n".join(lines)


def syllabus_prompt(syl: Syllabus, request: str, count: int,
                    domain_hint: Optional[str] = None,
                    level_hint: Optional[str] = None) -> str:
    """Demande une extension du syllabus, cablee sur les cours existants."""
    if domain_hint:
        where = ("Rattachez les nouveaux cours au domaine existant « %s » (identifiant "
                 "`%s`). Ne creez pas de nouveau domaine." % (syl.domain_name(domain_hint), domain_hint))
    else:
        where = ("Creez UN nouveau domaine pour accueillir ces cours, avec un "
                 "identifiant court en ASCII, un nom en francais accentue, une "
                 "description d'une phrase et une couleur hexadecimale lisible sur "
                 "fond clair comme sur fond sombre. Si le sujet appartient "
                 "manifestement a un domaine deja present, utilisez-le plutot que "
                 "d'en creer un.")
    level = ""
    if level_hint:
        level = "\nNiveau vise : %s. Ajustez la profondeur en consequence.\n" % level_hint

    return f"""{STYLE}

Vous n'ecrivez pas un cours ici : vous concevez une EXTENSION DE SYLLABUS.

DEMANDE DE L'UTILISATEUR :
{request}

COURS DEJA PRESENTS DANS LE CURSUS (identifiant, niveau, titre). Vos prerequis
doivent pointer vers ces identifiants, ou vers des cours de votre propre
proposition :

{catalogue(syl)}

TACHE : proposer environ {count} cours qui couvrent la demande, dans l'esprit
du syllabus existant.
{where}{level}

Regles :
- Les identifiants sont en ASCII minuscule, sans accent, mots separes par des
  tirets, prefixes par un trigramme de domaine (par exemple `ts-stationnarite`).
  Ils servent de noms de dossiers : aucun accent, aucun espace.
- Tout le reste est en francais avec les accents : titres, resumes, objectifs,
  mots-cles. Ces consignes sont ecrites sans accents pour des raisons
  techniques, n'imitez pas ce style.
- Ordonnez les cours du plus fondamental au plus avance. Chaque cours doit
  avoir des prerequis coherents : ce qui est necessaire pour le suivre, ni
  plus, ni moins. Un cours d'entree dans le sujet s'appuie sur des cours
  existants du cursus, pas sur du vide.
- Ne redonnez JAMAIS un cours deja present dans le catalogue ci-dessus, meme
  sous un autre titre. Verifiez avant de proposer.
- Le graphe doit rester acyclique.
- `level` va de 1 (post-bac) a 5 (M2). Soyez honnete sur la difficulte.
- `summary` : une a deux phrases qui disent ce que le cours apporte, sur le ton
  du syllabus existant : concret, sans emphase.
- `objectives` : 3 a 4 competences verifiables, formulees a l'infinitif.
- `keywords` : 4 a 6 termes techniques.
- `tracks` : proposez au plus un parcours, dont `goal` est le cours le plus
  avance de la serie et `extra` deux ou trois autres cours importants. Omettez
  ce champ si un parcours n'a pas de sens ici.
- `notes` : une ou deux phrases pour dire ce que vous avez choisi de couvrir et
  ce que vous avez laisse de cote.

Repondez uniquement par l'objet JSON."""


# --------------------------------------------------------- fiche de revision
SHEET_CONVENTIONS = r"""
FORMAT : fragment HTML, sans ``` autour, sans <html>, <head>, <body>.
N'utilisez que les classes ci-dessous. N'en inventez aucune.

En-tête, une seule fois, en premier :

  <div class="sheet-head">
    <div class="meta">Domaine &middot; niveau n/5</div>
    <h1>Titre du cours</h1>
    <p class="oneline">Une phrase : à quoi sert ce cours, ce qu'il permet de
    faire. Pas de définition ici.</p>
  </div>

Ensuite des blocs, dans cet ordre :

  <section class="block"><h2>Définitions</h2>
    <div class="def"><b>Terme</b> &mdash; énoncé exact et complet.</div>
  </section>

  <section class="block"><h2>Résultats à connaître</h2>
    <div class="thm"><span class="tag">Théorème</span> <b>Nom.</b> Énoncé
    complet, hypothèses comprises. <span class="tag">idée</span> la stratégie
    de preuve en une demi-ligne.</div>
  </section>
  (valeurs possibles du premier tag : Théorème, Proposition, Lemme, Corollaire)

  <section class="block"><h2>Formules</h2>
    <table class="formulas">
      <tr><td>ce que ça calcule</td><td>$formule$</td></tr>
    </table>
  </section>

  <section class="block"><h2>Méthodes</h2>
    <div class="method"><span class="tag">Pour montrer que…</span> la marche à
    suivre, en une à trois phrases opératoires.</div>
  </section>

  <section class="block"><h2>Pièges</h2>
    <div class="trap"><span class="tag">Piège</span> l'erreur exacte, et ce
    qu'il faut faire à la place.</div>
  </section>

  <section class="block"><h2>À savoir refaire</h2>
    <ul class="check"><li>Compétence vérifiable, formulée à l'infinitif.</li></ul>
  </section>

  <section class="block"><h2>Rappel actif</h2>
    <div class="qa"><span class="q">Question courte ?</span>
    <span class="a">Réponse courte.</span></div>
  </section>

Balises libres à l'intérieur : p, ul, ol, li, b, strong, em, code, span.
Ajoutez class="cols" à une <section> pour la mettre sur deux colonnes : utile
seulement si ses éléments sont courts et sans formule centrée.

Mathématiques : LaTeX entre $ … $ ; les formules centrées $$ … $$ sont à éviter
dans une fiche, sauf pour un résultat vraiment central. Macros disponibles :
\R \N \Z \Q \C \E \P \eps \dd \Var \Cov \rank \tr \diag \Id
\argmin \argmax \norm{…} \abs{…} \scal{…}{…}.
"""


def sheet_prompt(syl: Syllabus, course: Course, plan: Optional[dict],
                 substance: str) -> str:
    sections = ""
    if plan and plan.get("sections"):
        sections = "\n".join("  - %s" % sec["title"] for sec in plan["sections"])
    return f"""Vous rédigez une FICHE DE RÉVISION à partir d'un cours déjà écrit.

Ce n'est pas un résumé du cours : c'est l'outil qu'on relit trois mois plus
tard, quand on a compris une fois et qu'on veut tout retrouver en dix minutes.
Le cours long existe déjà pour la première lecture.

CE QUI EST ATTENDU

1. Densité. Aucune phrase de liaison, aucune introduction, aucune transition.
   Chaque ligne porte une information qu'on peut avoir oubliée.
2. Exactitude absolue. Un énoncé incomplet sur une fiche est pire que rien :
   il installe une erreur. Toutes les hypothèses figurent. Si un théorème a une
   hypothèse qu'on oublie souvent, c'est précisément celle qu'il faut écrire.
3. Rien qui ne soit dans le cours. Vous condensez, vous n'ajoutez pas. Vous
   pouvez reformuler plus court, jamais inventer un résultat.
4. Opérationnel. La section Méthodes doit répondre à « je bloque, je fais
   quoi ». Formulez « Pour montrer que… : … », pas « on peut noter que ».
5. Les pièges sont ce qui a le plus de valeur à la relecture : reprenez ceux du
   cours, formulés comme des avertissements courts.
6. Le rappel actif sert à se tester : 6 à 10 questions dont la réponse tient en
   une ligne. Des questions qui vérifient la compréhension, pas la mémoire d'un
   mot.
7. Longueur visée : deux à quatre pages A4 une fois imprimée. Un cours dense
   peut aller à cinq. Ne descendez pas sous deux pages : ce serait un survol.
8. Français avec tous les accents, y compris dans les titres de blocs.

{SHEET_CONVENTIONS}

COURS À CONDENSER : {course.title}
Domaine : {syl.domain_name(course.domain)} &middot; niveau {course.level}/5
Objectifs annoncés :
{chr(10).join("  - " + o for o in course.objectives)}
Plan du cours :
{sections}

MATIÈRE DU COURS (titres de sections, encadrés, résultats démontrés) :
{substance}

Produisez la fiche. Sortie : HTML brut, rien d'autre."""


QCM_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "integer"},
                },
                "required": ["id", "choices", "answer"],
            },
        },
    },
    "required": ["questions"],
}


def qcm_repair_prompt(course: Course, questions: List[dict]) -> str:
    """Demande de reecrire les propositions desequilibrees d'un QCM."""
    payload = json.dumps(
        [{"id": q["id"], "question": q["question"], "choices": q["choices"],
          "answer": q["answer"], "explanation": q.get("explanation", "")}
         for q in questions], ensure_ascii=False, indent=1)
    return f"""Dans ce QCM du cours « {course.title} », la bonne réponse se
reconnaît à sa forme : elle est nettement plus longue ou plus argumentée que
les trois autres. On peut donc y répondre sans rien savoir du cours, ce qui
rend l'exercice inutile.

Réécrivez les PROPOSITIONS de chaque question. Ne touchez ni à l'énoncé, ni à
l'explication, ni à la difficulté.

Règles :
- Les quatre propositions ont une longueur et un registre comparables, à 20 %
  près. Comptez les caractères.
- Une proposition est une affirmation, pas une démonstration. Retirez le
  raisonnement de la bonne réponse plutôt que d'en ajouter partout — sauf si
  la question porte précisément sur le choix d'un raisonnement, auquel cas les
  quatre en portent un, dont trois faux mais plausibles.
- Chaque distracteur reste l'erreur réelle qu'il incarnait : ne le remplacez
  pas par du remplissage. Vous le reformulez, vous ne le changez pas de nature.
- La bonne réponse reste la même affirmation ; `answer` doit pointer vers elle
  dans le nouvel ordre.
- Aucune proposition ne fait référence aux autres.
- Français avec tous les accents. Du LaTeX entre $ … $ si nécessaire.

QUESTIONS À CORRIGER :
{payload}

Répondez uniquement par l'objet JSON, avec pour chaque question son `id`, ses
quatre `choices` et l'index `answer`."""


def extra_quiz_prompt(syl: Syllabus, course: Course, plan: dict, digest: str,
                      existing: List[dict], count: int = 15) -> str:
    """Une serie de QCM supplementaire, qui ne redit pas la precedente."""
    seen = "\n".join(
        "  - [%s] %s" % (q.get("kind", "direct"),
                         re.sub(r"<[^>]+>", " ", q.get("question", ""))[:160])
        for q in existing)
    return f"""{STYLE}

Vous produisez une SERIE SUPPLEMENTAIRE de questions pour un cours dont une
serie existe deja. Elle doit permettre de se retester sans retomber sur les
memes items.

{_context(syl, course)}

PLAN DU COURS :
{json.dumps([{"titre": s["title"], "contenu": s["content"]} for s in plan["sections"]], ensure_ascii=False, indent=1)}

EXTRAITS DU COURS :
{digest}

QUESTIONS DEJA POSEES — n'en reprenez aucune, ni sous une autre formulation,
ni en changeant seulement les valeurs numeriques :
{seen}

TACHE : produire {count} nouvelles questions, avec la meme repartition de
difficulte et les memes regles que la premiere serie, dont 5 de type
`exercice`. Couvrez en priorite les points du cours que la serie precedente
laisse de cote, et abordez sous un autre angle ceux qu'elle traite deja.

Repondez uniquement par un objet JSON de la forme {{"qcm": [...]}}, avec les
memes champs que la premiere serie : id, kind, difficulty, question, choices,
answer, explanation, section."""


# ---------------------------------------------------------------------------
# TD : lecture d'un sujet et correction commentée
# ---------------------------------------------------------------------------
TD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subject": {"type": "string"},
        "exercises": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "string"},
                    "title": {"type": "string"},
                    "statement": {"type": "string"},
                    "courses": {"type": "array", "items": {"type": "string"}},
                    "key_results": {"type": "array", "items": {"type": "string"}},
                    "difficulty": {"type": "integer"},
                },
                "required": ["number", "title", "statement", "courses", "key_results"],
            },
        },
    },
    "required": ["title", "exercises"],
}


def td_structure_prompt(syl: Syllabus, pdf_path: str, document_text: str = "") -> str:
    """Lire un sujet de TD en PDF et le découper, formules comprises.

    `document_text` : texte déjà extrait, pour un moteur qui ne lit pas les PDF.
    """
    if document_text:
        access = (f"Voici le texte du sujet de TD, extrait automatiquement du PDF\n"
                  f"« {pdf_path} ». Travaillez uniquement à partir de ce texte, "
                  f"n'ouvrez aucun fichier.\nL'extraction abîme souvent les formules : "
                  f"rétablissez-les en LaTeX d'après\nle contexte mathématique.\n\n"
                  f"--- début du document ---\n{document_text}\n--- fin du document ---")
    else:
        access = (f"Lisez le sujet de TD situé dans le fichier suivant, avec l'outil Read,\n"
                  f"page par page et en entier :\n\n    {pdf_path}")
    return f"""{access}

Vous devez en produire une transcription STRUCTURÉE et FIDÈLE.

1. `title` : le titre du TD tel qu'il apparaît ; `subject` : la matière en
   quelques mots.
2. `exercises` : TOUS les exercices, dans l'ordre, sans en omettre aucun.
   Vérifiez à la fin que le nombre d'exercices correspond au dernier numéro du
   sujet. Pour chacun :
   - `number` : son numéro tel qu'écrit ;
   - `title` : son titre, ou à défaut quelques mots qui le résument ;
   - `statement` : l'énoncé COMPLET, questions comprises, en HTML simple
     (p, ol, ul, li, b, em) avec toutes les mathématiques en LaTeX entre $…$
     ou $$…$$. Recopiez les formules exactement : exposants, indices,
     fractions, ensembles d'indices, conditions. N'inventez rien, ne résolvez
     rien, ne reformulez pas. Les questions numérotées vont dans un <ol>.
   - `courses` : les identifiants des cours du catalogue ci-dessous qui
     contiennent les définitions et théorèmes nécessaires pour résoudre
     l'exercice. Deux à cinq, du plus directement utile au plus général.
     Uniquement des identifiants présents dans le catalogue.
   - `key_results` : les résultats précis dont la résolution a besoin, nommés
     comme dans un cours (« théorème de convergence dominée », « formule de
     transfert », « lemme de Borel-Cantelli »), trois à six.
   - `difficulty` : de 1 à 5, pour un étudiant qui entre en M2.

CATALOGUE DES COURS (identifiant, niveau, titre) :

{catalogue(syl)}

Répondez uniquement par l'objet JSON."""


TD_CONVENTIONS = r"""
CONVENTIONS DE LA CORRECTION

Fragment HTML uniquement : pas de ``` autour, pas de <html>, <head>, <body>.
Mathématiques en LaTeX entre $…$ et $$…$$ (KaTeX). Macros disponibles :
\R \N \Z \Q \C \E \P \1 \eps \dd \Var \Cov \rank \tr \diag \Id
\argmin \argmax \norm{…} \abs{…} \scal{…}{…}.

Pour renvoyer à un cours de l'application, utilisez exactement :
    <a class="course-ref" data-course="IDENTIFIANT">Titre du cours</a>
avec un identifiant pris dans la liste des cours rattachés. Le lecteur pourra
cliquer pour l'ouvrir.

Encadrés disponibles, et seulement ceux-là :
    <div class="box intuition"><span class="box-title">L'idée</span>…</div>
    <div class="box theorem"><span class="box-title">Ce qu'on utilise</span>…</div>
    <div class="box definition"><span class="box-title">Définition</span>…</div>
    <div class="box warning"><span class="box-title">Piège</span>…</div>
    <div class="box example"><span class="box-title">Exemple</span>…</div>
    <div class="box recap"><span class="box-title">À retenir</span>…</div>

La solution détaillée de chaque question va dans un bloc repliable, pour que
le lecteur puisse chercher avec l'idée seule avant de lire la suite :

    <details class="proof" data-of="Exercice N, question k">
      <summary>Solution détaillée</summary>
      <div class="proof-body">
        <div class="proof-step"><span class="step-label">Étape 1 — ce qu'on veut obtenir</span>
          <p>…</p></div>
        …
        <p class="qed">&#8718;</p>
      </div>
    </details>
"""


def td_correction_prompt(syl: Syllabus, td_title: str, exercise: dict,
                         materials: List[dict], index: int, total: int) -> str:
    """Correction pédagogique d'un exercice de TD.

    `materials` : [{course, generated, substance}] pour les cours rattachés.
    """
    blocks = []
    for item in materials:
        course = item["course"]
        if item.get("generated") and item.get("substance"):
            body = "Extraits du cours déjà rédigé dans l'application :\n" + item["substance"]
        else:
            body = ("Ce cours n'est pas encore rédigé dans l'application. Son programme :\n"
                    "Résumé : %s\nObjectifs : %s\nMots-clés : %s"
                    % (course.summary, " ; ".join(course.objectives),
                       ", ".join(course.keywords)))
        blocks.append("### %s  [identifiant : %s]\n%s" % (course.title, course.id, body))
    material = "\n\n".join(blocks) or "(aucun cours rattaché)"
    results = "\n".join("  - %s" % r for r in exercise.get("key_results", [])) or "  (non précisés)"

    return f"""{STYLE}

{MVIZ_API}

{TD_CONVENTIONS}

Vous rédigez la CORRECTION COMMENTÉE d'un exercice de TD, pour un étudiant qui
entre en M2 MVA et vient de chercher l'exercice. Ce n'est pas un corrigé
d'examen à recopier : c'est une correction qui fait COMPRENDRE, pour qu'il sache
refaire seul un exercice voisin.

TD : {td_title} — exercice {index + 1} sur {total}

ÉNONCÉ :
{exercise.get("statement", "")}

RÉSULTATS QUE LA RÉSOLUTION MOBILISE (repérés à la lecture du sujet) :
{results}

COURS DE L'APPLICATION RATTACHÉS À CET EXERCICE :
{material}

CE QUI EST ATTENDU

1. Ouvrez par <h2>Exercice {exercise.get("number", index + 1)} — {exercise.get("title", "")}</h2>,
   puis un court paragraphe : ce que l'exercice fait vraiment travailler, et
   pourquoi c'est utile (en apprentissage quand le lien est honnête).
2. Pour CHAQUE question, dans l'ordre, un <h3> puis :
   a. un encadré « L'idée » AVANT tout calcul : l'intuition, l'image mentale,
      la stratégie de preuve en une ou deux phrases. C'est la partie la plus
      importante : quelqu'un qui bloque doit pouvoir repartir avec elle seule.
      Dites pourquoi c'est CETTE approche qui marche, et ce qui échouerait.
   b. un encadré « Ce qu'on utilise » : les définitions et théorèmes du cours
      invoqués, énoncés PRÉCISÉMENT avec leurs hypothèses, chacun avec un
      renvoi au cours via <a class="course-ref" …>. Quand le cours n'est pas
      encore rédigé dans l'application, énoncez quand même le résultat
      complètement, et renvoyez au cours correspondant.
   c. la solution détaillée dans un bloc <details class="proof"> découpé en
      étapes nommées. Chaque étape dit ce qu'on cherche à obtenir avant de le
      faire, et signale le moment où chaque hypothèse sert.
   d. un encadré « Piège » quand il y a une erreur classique réelle à cette
      question : hypothèse oubliée, interversion non justifiée, confusion
      entre modes de convergence, indépendance supposée à tort.
3. Une figure interactive quand elle éclaire vraiment : un lim sup comme
   « infiniment souvent », une loi qui se déforme avec un paramètre, une
   convergence en loi, une chaîne de Markov qui converge. Pas de décoration.
4. Terminez par un encadré « À retenir » : les deux ou trois réflexes de méthode
   réutilisables ailleurs.
5. Rigueur complète, mais pas de formalisme gratuit. Le ton est celui d'un bon
   chargé de TD qui explique au tableau.
6. Français avec tous les accents.

Sortie : le fragment HTML, rien d'autre."""


# ---------------------------------------------------------------------------
# TD d'entraînement : feuille d'exercices de rédaction pour un cours rédigé
# ---------------------------------------------------------------------------
TRAINING_SCHEMA = {
    "type": "object",
    "properties": {
        "exercises": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "string"},
                    "title": {"type": "string"},
                    "statement": {"type": "string"},
                    "hints": {"type": "array", "items": {"type": "string"}},
                    "solution": {"type": "string"},
                    "section": {"type": "string"},
                },
                "required": ["level", "title", "statement", "hints", "solution", "section"],
            },
        },
    },
    "required": ["exercises"],
}


def training_prompt(syl: Syllabus, course: Course, section_titles: List[str],
                    substance: str, seen: List[str]) -> str:
    """Feuille de TD : 5 à 8 exercices de rédaction, indices et corrigés."""
    later = [syl.get(d) for d in course.dependents]
    later_txt = ", ".join(c.title for c in later if c) or "(aucun)"
    sections = "\n".join("  - %s" % t for t in section_titles) or "  (aucune)"
    seen_txt = "\n".join("  - %s" % t for t in seen[:40]) or "  (aucun)"
    return f"""{STYLE}

{_context(syl, course)}

Vous composez une FEUILLE DE TD d'entraînement pour ce cours, déjà rédigé dans
l'application. Ce ne sont pas des QCM : ce sont des exercices de rédaction,
qu'on cherche sur une feuille puis qu'on rédige.

SECTIONS DU COURS (titres exacts) :
{sections}

MATIÈRE DU COURS RÉDIGÉ (énoncés, définitions, notations à reprendre telles quelles) :
{substance}

EXERCICES DÉJÀ DONNÉS DANS LES FEUILLES PRÉCÉDENTES (ne pas les reprendre) :
{seen_txt}

CE QUI EST ATTENDU

1. Entre 5 et 8 exercices, de difficulté croissante, chacun étiqueté par le
   champ `level` :
     - "application" : application directe d'une définition ou d'un théorème
       du cours (2 exercices environ) ;
     - "classique" : l'exercice qu'on retrouve dans tout bon recueil, qui
       combine deux idées du cours (2 à 3 exercices) ;
     - "approfondissement" : demande du recul, un contre-exemple, une
       hypothèse qu'on affaiblit, ou un raisonnement en plusieurs étapes
       (1 à 3 exercices).
2. Cohérence : mêmes notations et même vocabulaire que le cours. Vous pouvez
   utiliser ce cours et sa chaîne de prérequis (listés plus haut), RIEN
   d'autre. Aucune notion des cours ultérieurs : {later_txt}.
3. Pour chaque exercice :
     - `title` : quelques mots qui nomment l'exercice ;
     - `statement` : énoncé complet et autosuffisant, questions numérotées
       si besoin (<ol>) ;
     - `hints` : un ou deux indices progressifs, le premier donne la
       stratégie, le second la première étape concrète ;
     - `solution` : corrigé complet et rédigé, rigoureux, qui dit pourquoi on
       fait chaque étape avant de la faire, et signale où sert chaque
       hypothèse ;
     - `section` : le titre EXACT de la section du cours concernée, pris dans
       la liste ci-dessus (chaîne vide si aucune ne convient).
4. Français avec TOUS les accents.

Tous les champs texte sont du HTML simple (p, ol, ul, li, strong, em) avec du
LaTeX entre $ ... $ et $$ ... $$ (KaTeX ; macros \\R \\N \\Z \\Q \\C \\E \\P \\eps
\\norm{{}} \\abs{{}} \\scal{{}}{{}}). Pas de titres <h*>, pas de figures, pas de
blocs ```. Répondez uniquement par l'objet JSON."""


# ---------------------------------------------------------------------------
# Brouillon d'une démonstration : comment on TROUVE la preuve
# ---------------------------------------------------------------------------
BROUILLON_SCHEMA = {
    "type": "object",
    "properties": {
        "trivial": {"type": "boolean"},
        "html": {"type": "string"},
    },
    "required": ["trivial", "html"],
}


def brouillon_prompt(syl: Syllabus, course: Course, title: str, statement: str,
                     proof: str) -> str:
    """Brouillon de recherche d'une preuve, cohérent avec la preuve rédigée."""
    short_note = ("La preuve est courte : brouillon bref, quelques lignes, en gardant "
                  "seulement les intertitres utiles." if len(proof) < 700 else "")
    return f"""{_context(syl, course)}

Vous écrivez le BROUILLON DE RECHERCHE d'une démonstration de ce cours. La
preuve rédigée existe déjà et le lecteur l'a sous les yeux. Elle dit COMMENT on
rédige ; vous montrez comment on la TROUVE : ce qu'on essaie, pourquoi, et d'où
sortent les choix qui paraissent tomber du ciel (fonction auxiliaire, $\\eps/2$,
choix de $N$ ou de $\\delta$, bonne variable, constante, borne, récurrence
renforcée…).

RÉSULTAT DÉMONTRÉ : {title}

ÉNONCÉ (et contexte qui précède la preuve) :
{statement or "(voir la preuve)"}

PREUVE RÉDIGÉE (référence : mêmes notations, mêmes étapes) :
{proof[:9000]}

CE QUI EST ATTENDU, dans le champ `html`, avec ces intertitres <h4> :
1. « Point de départ » : ce qu'on veut, ce qu'on a ; les hypothèses
   disponibles et celle qui a l'air de devoir servir.
2. « L'idée directrice » : l'idée de la preuve, et pourquoi elle est
   naturelle ici (ce qui, dans l'énoncé, la suggère).
3. « À rebours » : démarche à rebours ou par analyse-synthèse qui fait
   apparaître le choix clé. Par exemple : on écrit l'inégalité souhaitée, on
   voit ce qu'il faut imposer, on en déduit $N$ ou $\\delta$. Calculs de brouillon
   assumés, avec leurs tâtonnements.
4. « Une tentative naïve » (seulement si elle est instructive) : l'essai
   qu'on ferait d'abord, où il échoue, ce que cet échec apprend.
5. « Retour à la preuve rédigée » : le lien explicite avec chaque étape de la
   preuve propre (« c'est pour cela que la preuve commence par poser… »).
6. « L'astuce à retenir » : une seule phrase, l'astuce réutilisable ailleurs.

Ton de cahier de recherche : phrases courtes, « on essaie », « ça ne marche
pas parce que », « il faudrait que… donc on prend… ». Pas de rédaction
formelle, pas de répétition intégrale de la preuve. Restez strictement cohérent
avec la preuve rédigée et ses notations.
{short_note}
Si la preuve est immédiate (une ligne, aucun choix à expliquer), mettez
`trivial` à true et, dans `html`, une ou deux phrases qui disent pourquoi il
n'y a rien à chercher. Sinon `trivial` vaut false.

Format de `html` : HTML simple (h4, p, ul, ol, li, strong, em), maths en LaTeX
entre $ ... $ et $$ ... $$ (KaTeX ; macros \\R \\N \\Z \\Q \\C \\E \\P \\eps
\\norm{{}} \\abs{{}} \\scal{{}}{{}}). Pas de blocs ```, pas de <h1>-<h3>.
Français avec TOUS les accents. Répondez uniquement par l'objet JSON."""


# ---------------------------------------------------------------------------
# Rappel ciblé : cinq questions sur les notions qui coincent dans un cours
# ---------------------------------------------------------------------------
def refresher_prompt(syl: Syllabus, course: Course, digest: str, missed: List[dict],
                     seen: List[str], count: int = 5) -> str:
    """`missed` : [{question, choices, answer, explanation, tries}] ratées récemment."""
    letters = "ABCD"
    blocks = []
    for i, q in enumerate(missed, 1):
        choices = "\n".join("      %s. %s%s" % (letters[k], c, "   ← bonne réponse"
                                                  if k == q.get("answer") else "")
                            for k, c in list(enumerate(q.get("choices") or []))[:4])
        blocks.append("  %d. (ratée %s)\n      %s\n%s\n      Explication : %s"
                      % (i, "plusieurs fois" if (q.get("tries") or 0) >= 2 else "récemment",
                         q.get("question", ""), choices, q.get("explanation", "")))
    missed_text = "\n\n".join(blocks) or "  (aucune question précise)"
    seen_text = "\n".join("  - %s" % s[:110] for s in seen[:30]) or "  (aucune)"

    return f"""{STYLE}

Vous préparez un RAPPEL CIBLÉ sur le cours « {course.title} » [{course.id}],
niveau {course.level}/5.

L'étudiant a travaillé ce cours, mais ses dernières réponses montrent qu'une ou
deux notions ne tiennent pas. Il ne s'agit pas de refaire le QCM : il s'agit de
reprendre précisément ce qui coince, sous un autre angle, en cinq minutes.

Objectifs du cours : {" ; ".join(course.objectives)}

Extraits du cours :
{digest}

Questions ratées récemment :
{missed_text}

Questions déjà posées sur ce cours (à ne pas reprendre, même reformulées) :
{seen_text}

MÉTHODE :
1. Diagnostiquez d'abord, pour vous, la confusion commune aux questions ratées :
   hypothèse oubliée, définition approximative, quantificateurs inversés, erreur
   de calcul typique… C'est elle qu'il faut viser.
2. Produisez exactement {count} questions à choix unique, NOUVELLES, qui
   attaquent cette confusion par des chemins différents, dans cet ordre :
   - une ou deux questions de rappel (énoncé exact, hypothèses, définition),
     difficulté 1 à 2 ;
   - deux questions d'application directe où la confusion ferait tomber dans
     le piège, difficulté 2 à 3 ;
   - une dernière question un peu plus exigeante, difficulté 3 ou 4, qui montre
     que la notion est vraiment en place (au plus une question `exercice`).
3. Chaque explication est un PETIT RAPPEL DE COURS : en deux à quatre phrases,
   énoncez le résultat ou la définition exacte, dites pourquoi la bonne
   réponse en découle, et pourquoi le piège principal est tentant et faux.
   L'étudiant doit pouvoir se remettre la notion en tête en lisant les
   corrections, sans rouvrir le cours.

Règles du QCM, toutes applicables : quatre propositions de longueur et de
registre comparables, une seule correcte, distracteurs correspondant à des
erreurs réelles (en priorité celle diagnostiquée), position de la bonne
réponse variée, aucune proposition qui renvoie aux autres. Une proposition est
une affirmation, pas une démonstration.

`section` : le titre de la section du cours d'où vient la notion.
Formules en LaTeX entre $…$. Français avec tous les accents.

Répondez uniquement par {{"qcm": [...]}}, chaque question portant id, kind,
difficulty, question, choices, answer, explanation, section."""


# ---------------------------------------------------------------------------
# Assistant de l'application
# ---------------------------------------------------------------------------
def assistant_system(state: str) -> str:
    return f"""Vous êtes l'assistant intégré à « Maths MVA », une application de bureau
qui prépare son utilisateur à la rentrée du M2 MVA : cursus de mathématiques
complet (262 cours et plus), cours rédigés par Claude à la demande, QCM,
démonstrations, fiches de révision, corrections de TD, révisions espacées.

Votre rôle : comprendre ce que l'utilisateur veut faire DANS l'application et le
lui préparer. Vous ne faites rien vous-même : vous proposez des actions, que
l'application affiche sous forme de cartes et qu'il valide d'un clic.

CE QUE VOUS POUVEZ PROPOSER (bloc <actions> en fin de réponse, JSON) :
- {{"type": "generate_courses", "courses": ["id", …]}} : rédiger des cours.
  Rangez-les dans l'ordre des prérequis. Si des prérequis ne sont pas rédigés,
  dites-le, et proposez-les aussi quand ils sont nécessaires pour suivre.
- {{"type": "regenerate_course", "course": "id"}} : refaire un cours rédigé.
- {{"type": "new_quiz_set", "course": "id"}} : une série de QCM supplémentaire.
- {{"type": "generate_sheets", "courses": ["id", …]}} : fiches de révision.
- {{"type": "correct_td", "td": "id"}} : lire et corriger un TD importé.
- {{"type": "extend_syllabus", "request": "…", "count": 8}} : ajouter des
  chapitres au syllabus (sujet décrit précisément).
- {{"type": "set_setting", "key": "…", "value": …}} : un des réglages listés.
- {{"type": "cancel_generation", "courses": ["id"]}} ou {{"type":
  "cancel_generation", "all": true}}.
- {{"type": "open", "page": "home|library|graph|td|course", "course": "id"}}.
- {{"type": "start_session", "kind": "review|daily|challenge"}}.
- {{"type": "modify_app", "request": "…", "summary": "…"}} : changer le CODE
  de l'application (nouvelle fonction, bug, présentation, comportement).
  `request` est un cahier des charges autonome et précis, rédigé pour un
  développeur qui ne voit pas cette conversation : ce qui doit changer, où ça
  se voit dans l'application, le comportement attendu, les cas limites.
  `summary` : une phrase pour l'utilisateur.

FORME DE LA RÉPONSE :
- HTML simple et court (p, ul, li, strong, em) ; maths en LaTeX entre $…$.
- Dites en une ou deux phrases ce que vous proposez et pourquoi, avec le coût
  quand il est notable. N'affirmez jamais qu'une action est faite : elle ne
  l'est qu'après le clic.
- Puis, s'il y a des actions, TOUT À LA FIN :
  <actions>[{{"type": "generate_courses", "courses": ["pro-esperance", "pro-convergences"]}}]</actions>
- N'utilisez que des identifiants présents dans l'état ci-dessous.
- Si la demande est ambiguë au point de risquer une dépense inutile, posez
  une question courte au lieu de proposer une action.
- Pour une question de mathématiques pure, répondez brièvement et signalez que
  le bouton « Chat » ouvre le tuteur, plus adapté.
- Français avec tous les accents.
- Chaque message de l'utilisateur commence par un bloc <etat_a_jour> : la file
  de génération la plus récente, qui prévaut sur tout état plus ancien. Pour
  diagnostiquer une génération en attente, en pause ou interrompue, citez la
  raison qui y figure.

ÉTAT ACTUEL DE L'APPLICATION :
{state}"""


def code_change_system() -> str:
    return """Vous modifiez le code de « Maths MVA », une application de bureau Python
(PySide6 + QtWebEngine) qui aide son utilisateur à préparer le M2 MVA. Vous
travaillez dans le dossier du projet, avec les outils Read, Edit, Write, Glob
et Grep. Vous n'avez pas de shell : l'application lancera elle-même la suite de
tests (tools/selftest.py) après vous et vous renverra les échecs éventuels.

MÉTHODE :
1. Lisez d'abord README.md, en particulier la section « Structure du code »,
   puis les fichiers concernés. Comprenez l'existant avant de toucher.
2. Faites la modification la plus simple qui remplit la demande, dans le style
   du code environnant (noms, commentaires, idiomes). Pas de nouvelle
   dépendance.
3. Utilisez Edit pour des remplacements ciblés. Ne réécrivez JAMAIS un fichier
   existant en entier avec Write, et ne tronquez jamais un fichier : c'est la
   cause de régressions graves dans ce projet.
4. Ajoutez ou adaptez un test dans tools/selftest.py quand la modification a
   une logique vérifiable. Mettez à jour README.md si une fonction visible
   change.
5. Textes de l'interface en français avec tous les accents.

INTERDITS : le dossier library/ (données et progression de l'utilisateur),
.venv/, .git/, tout fichier hors du projet. Ne modifiez pas les réglages de
l'utilisateur. Ne supprimez pas de fonctionnalité sans que ce soit demandé.

L'application tourne pendant que vous travaillez : vos changements prendront
effet au prochain redémarrage.

RÉPONSE FINALE : en HTML simple, une liste <ul> de trois à six points : ce qui
a changé, dans quels fichiers, et comment le voir dans l'application. Si la
demande n'était pas réalisable telle quelle, dites-le franchement et ce que
vous avez fait à la place."""


def code_change_prompt(request: str) -> str:
    return "Modification demandée :\n\n%s" % request.strip()


def code_fix_prompt(report: str) -> str:
    return ("Les tests de l'application échouent après vos modifications. Voici le "
            "rapport (échecs, puis fin de la sortie) :\n\n%s\n\n"
            "Corrigez la cause, sans affaiblir les tests existants. Répondez ensuite "
            "avec le même format de résumé final." % report[-6000:])


# ---------------------------------------------------------------------------
# Questions libres
# ---------------------------------------------------------------------------
def question_system(catalogue: str) -> str:
    return f"""Vous êtes le tuteur de mathématiques de l'application « Maths MVA ». Votre
interlocuteur prépare le M2 MVA et reprend tout le cursus depuis la terminale. Il
pose ici une question libre, sur n'importe quel sujet de maths.

RÉPONDRE :
- Directement, sans préambule ni flatterie. L'intuition d'abord, puis l'énoncé
  exact, hypothèses comprises. Si c'est court, ajoutez l'idée de la preuve ou un
  exemple qui éclaire.
- Si la question révèle une confusion, nommez-la.
- Une longueur proportionnée à la question : une question simple appelle une
  réponse courte.
- Si la question est vague, répondez à l'interprétation la plus utile et dites
  en une ligne ce que vous avez supposé.

POINTER VERS LES COURS :
- Terminez par <h4>Où c'est traité</h4> suivi d'une liste <ul> d'un à quatre
  liens, du plus pertinent au moins pertinent :
  <li><a class="course-ref" data-course="ID" data-section="Titre exact">Titre du cours — titre de la section</a> : ce qu'on y trouve, en une phrase.</li>
- `data-course` : un identifiant du catalogue ci-dessous, et rien d'autre.
- `data-section` : seulement pour un cours rédigé, en recopiant EXACTEMENT un
  titre de sa liste de sections. Pour un cours non rédigé, omettez l'attribut.
- Placez d'abord le cours où la notion est introduite. Ajoutez le cours
  prérequis si la question montre qu'il manque une base, et le cours où la
  notion sert vraiment si c'est éclairant.
- Vous pouvez aussi placer ces liens dans le corps de la réponse.
- Si la notion n'est traitée dans aucun cours du cursus, dites-le franchement,
  indiquez le cours le plus proche, et précisez que l'Assistant (Ctrl+J) peut
  ajouter des chapitres au syllabus.

FORMAT : HTML simple (p, ul, ol, li, strong, em, h4, table, et
<div class="box intuition|warning|example"><span class="box-title">Titre</span>…</div>).
Maths en LaTeX entre $…$ ou $$…$$. Jamais de maths dans <code> ni dans <pre>, pas
de balises ``` autour de la réponse. Macros disponibles : \\R \\N \\Z \\Q \\C
\\E \\P \\eps \\dd \\Var \\Cov \\norm{{}} \\abs{{}} \\scal{{}}{{}}.
Français avec tous les accents.

CATALOGUE DU CURSUS (id | titre | niveau | rédaction | mots-clés ; puis les
sections des cours rédigés) :
{catalogue}"""


# ---------------------------------------------------------------------------
# Cours importés depuis un PDF
# ---------------------------------------------------------------------------
_STR = {"type": "string"}
_STRS = {"type": "array", "items": {"type": "string"}}
COURSE_IMPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": _STR, "original_title": _STR, "author": _STR, "language": _STR,
        "summary": _STR, "level": {"type": "integer"},
        "keywords": _STRS, "objectives": _STRS, "prereqs": _STRS, "related": _STRS,
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": _STR, "title": _STR, "pages": _STR, "goal": _STR,
                           "content": _STR, "intuitions": _STRS, "proofs": _STRS,
                           "exercises": _STRS},
            "required": ["title", "pages", "goal", "content"]}},
        "exercises": {"type": "array", "items": {
            "type": "object",
            "properties": {"number": _STR, "title": _STR, "pages": _STR, "statement": _STR,
                           "courses": _STRS, "key_results": _STRS,
                           "difficulty": {"type": "integer"}},
            "required": ["number", "title", "statement"]}},
    },
    "required": ["title", "summary", "level", "prereqs", "related", "sections", "exercises"],
}


def course_import_prompt(syl: Syllabus, pdf_path: str, document_text: str = "") -> str:
    if document_text:
        access = (f"LE DOCUMENT : texte extrait automatiquement du PDF « {pdf_path} ».\n"
                  f"Travaillez uniquement à partir de ce texte, n'ouvrez aucun fichier. "
                  f"L'extraction\nabîme souvent les formules : rétablissez-les en LaTeX. "
                  f"Les numéros de page sont\nceux du PDF ; les transparents répètent "
                  f"souvent la même page en ajoutant un\nélément : ne comptez chaque "
                  f"contenu qu'une fois.\n\n--- début du document ---\n{document_text}\n"
                  f"--- fin du document ---")
    else:
        access = (f"LE DOCUMENT : {pdf_path}\n"
                  f"Lisez-le EN ENTIER avec l'outil Read, par tranches de 20 pages au plus\n"
                  f"(paramètre pages). Les transparents Beamer répètent souvent la même page "
                  f"en\najoutant un élément à chaque fois : ne comptez chaque contenu "
                  f"qu'une fois, mais\nnotez les pages où il se trouve.")
    return f"""Vous préparez l'import d'un cours magistral dans « Maths MVA », une
application qui prépare au master MVA. Le cours sera réécrit section par
section, fidèlement mais avec plus d'intuition, et ses exercices seront corrigés.
Votre travail ici : lire le document et en établir le plan détaillé.

{access}

À PRODUIRE :
- title : titre français précis du cours (par exemple « Rappels d'optimisation —
  partie I »). original_title, author, language (fr, en…).
- summary : deux ou trois phrases sur ce que couvre le cours.
- level : de 1 à 5 sur l'échelle de l'application (4 = M1, 5 = M2).
- keywords : 5 à 12 ; objectives : 4 à 8, formulés « savoir … ».
- prereqs : identifiants du catalogue ci-dessous que le cours suppose connus, les
  plus directs (2 à 6).
- related : identifiants du catalogue qui traitent des notions utilisées ou
  prolongées par le cours (jusqu'à 12). Ils serviront aux liens dans le texte.
- sections : 4 à 10 sections qui suivent l'ordre du document. Pour chacune :
  title (français) ; pages (plage du PDF, par exemple "5-18") ; goal (une
  phrase) ; content (6 à 12 phrases qui citent TOUTES les définitions, énoncés
  avec hypothèses, exemples et remarques de ces pages, avec leurs notations) ;
  intuitions (endroits où les transparents sont trop elliptiques et où une
  intuition, un dessin ou un calcul intermédiaire aiderait) ; proofs (résultats à
  démontrer dans la section : ceux prouvés dans le document, et ceux dont une
  preuve courte éclaire) ; exercises (numéros des exercices situés dans ces pages).
- exercises : TOUS les exercices du document, dans l'ordre. Pour chacun : number
  (tel qu'imprimé), title (court, en français), pages, statement (énoncé complet
  et fidèle, traduit en français, en HTML simple avec les maths en LaTeX entre
  $…$, mêmes notations, sous-questions dans une liste <ol>), courses (identifiants
  du catalogue utiles pour le résoudre, 1 à 4), key_results (résultats à
  mobiliser), difficulty (1 à 5).

Ne résumez pas à la légère : ce plan sert à réécrire le cours sans rien perdre.
Répondez uniquement par le JSON demandé.

CATALOGUE DES COURS EXISTANTS (identifiant, niveau, titre) :
{catalogue(syl, max_per_domain=400)}"""


def _source_block(plan: dict, index: int, source_text: str = "") -> str:
    """Consignes propres à un cours importé : relire les pages, garder les exercices."""
    source = plan.get("source")
    if not source:
        return ""
    section = plan["sections"][index]
    origin = source.get("original_title") or "cours magistral"
    if source.get("author"):
        origin += ", " + source["author"]
    pages = section.get("pages") or "(voir le plan)"
    intuitions = "\n".join("  - %s" % t for t in section.get("intuitions") or []) \
        or "  (à vous de juger)"
    exercises = "\n".join("  - Exercice %s : %s" % (e["number"], e["title"])
                          for e in section.get("exercises") or []) or "  (aucun dans ces pages)"
    related = "\n".join("  - %s : %s" % (r["id"], r["title"])
                        for r in source.get("related") or []) or "  (aucun)"
    if source_text:
        access = ("Votre section correspond aux pages %s du document, dont voici le texte\n"
                  "extrait automatiquement. Travaillez à partir de ce texte, n'ouvrez aucun\n"
                  "fichier. L'extraction abîme souvent les formules : rétablissez-les en LaTeX\n"
                  "d'après le contexte. Votre réponse ne contient que le HTML de la section.\n\n"
                  "--- pages %s ---\n%s\n--- fin ---" % (pages, pages, source_text))
    else:
        access = ("Le PDF se lit avec l'outil Read : %s\n"
                  "Votre section correspond aux pages %s. Lisez ces pages AVANT d'écrire\n"
                  "(outil Read, paramètre pages), et au besoin une page avant ou après pour le\n"
                  "contexte. Votre réponse finale ne contient que le HTML de la section."
                  % (source.get("pdf", ""), pages))
    return f"""

SOURCE : ce cours réécrit un cours magistral du master MVA (« {origin} »).
{access}

FIDÉLITÉ : tout ce que contiennent ces pages figure dans votre section :
définitions, notations (gardez exactement celles du document), énoncés avec leurs
hypothèses, exemples, remarques. Les transparents répètent souvent une page en
ajoutant un élément : n'écrivez chaque chose qu'une fois. Rédigez en français ;
à la première occurrence d'un terme, donnez entre parenthèses le terme anglais
du document.

AJOUTS : les transparents sont télégraphiques, votre cours ne doit pas l'être.
Ajoutez l'intuition avant le formalisme, les étapes de calcul sautées, des
démonstrations courtes quand elles éclairent, des exemples et des figures mviz
utiles. Points signalés comme trop elliptiques :
{intuitions}

EXERCICES DU DOCUMENT DANS CES PAGES :
{exercises}
Insérez chacun à l'endroit où il apparaît dans le document, avec son énoncé
complet et fidèle, SANS solution ni indication :
  <div class="box exercise" data-exercise="NUMÉRO"><span class="box-title">Exercice NUMÉRO — titre</span>
    <p>énoncé…</p>
    <p><a class="exercise-ref" data-exercise="NUMÉRO">Correction détaillée dans l'onglet Exercices</a></p></div>
La classe « exercise » s'ajoute exceptionnellement aux encadrés autorisés.

LIENS VERS LES COURS DE L'APPLICATION : quand la section s'appuie sur une notion
traitée dans l'un de ces cours, liez-la à sa première mention avec
<a class="course-ref" data-course="IDENTIFIANT">texte</a>. Un à quatre liens par
section, là où ils aident vraiment :
{related}
"""
