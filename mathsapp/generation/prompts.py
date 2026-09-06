"""Prompts de generation. C'est ici que se joue la qualite pedagogique."""
from __future__ import annotations

import json
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
                   written_titles: List[str]) -> str:
    section = plan["sections"][index]
    total = len(plan["sections"])
    others = "\n".join(
        "  %d. %s%s" % (i + 1, s["title"], "  <- section a ecrire" if i == index else "")
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

Sections deja redigees : {", ".join(written_titles) if written_titles else "aucune"}
(ne les reecrivez pas, ne les resumez pas, enchainez simplement)

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
{intro}
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
                    "difficulty": {"type": "integer"},
                    "question": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "integer"},
                    "explanation": {"type": "string"},
                    "section": {"type": "string"},
                },
                "required": ["id", "difficulty", "question", "choices", "answer", "explanation"],
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
  - 4 propositions par question, une seule correcte, `answer` = son index (0-3).
  - Les mauvaises reponses doivent correspondre a des erreurs REELLES et
    plausibles (confusion classique, quantificateur inverse, hypothese
    oubliee), jamais a du remplissage absurde.
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


def proof_review_system(course: Optional[Course], syl: Optional[Syllabus]) -> str:
    return chat_system(course, syl) + """

MODE CORRECTION DE COPIE. L'etudiant vous soumet SA demonstration. Vous la
corrigez comme un correcteur exigeant et utile, pas comme un corrige.

Regles absolues :
- Une demonstration correcte mais differente de la solution de reference est
  correcte. Ne reprochez jamais une methode differente ; si elle est plus
  longue ou plus fragile, dites-le apres avoir reconnu qu'elle marche.
- Vous ne deroulez PAS la solution. Vous pointez le premier endroit qui bloque
  et vous donnez de quoi repartir, pas la suite. L'etudiant doit pouvoir
  corriger lui-meme et resoumettre.
- Une seule exception : s'il demande explicitement la solution complete.
- Soyez precis sur l'endroit : citez le passage exact de sa copie.

Structure de la reponse :
1. <h4>Verdict</h4> une phrase : correcte / correcte mais incomplete /
   erreur de raisonnement / hors sujet. Sans detour.
2. <h4>Ce qui tient</h4> ce qui est effectivement acquis dans la copie. Soyez
   concret : nommez les etapes justes. Si la copie est mauvaise, dites au
   moins quelle intention etait bonne.
3. <h4>Le point a reprendre</h4> LE premier probleme dans l'ordre de lecture
   (pas une liste de tout ce qui ne va pas) : ce qui est affirme, pourquoi ca
   ne suit pas, et une question ou une piste qui debloque.
4. <h4>Redaction</h4> quantificateurs mal places ou absents, hypotheses non
   utilisees ou utilisees sans le dire, « donc » non justifies, objets employes
   avant d'etre introduits, cas limites oublies. Trois remarques au maximum,
   les plus importantes.
5. Si la demonstration est correcte : dites-le franchement, signalez ce qui
   peut etre allege, et proposez une variante ou une generalisation a chercher.

Ne felicitez pas pour la forme. Une copie fausse doit etre dite fausse."""


def proof_review_prompt(title: str, statement: str, solution: str,
                        attempt: str, attempt_no: int = 1) -> str:
    again = ""
    if attempt_no > 1:
        again = ("\nC'est sa version numero %d. Comparez avec ce qu'il avait ecrit "
                 "plus tot dans cette conversation : dites d'abord si le point que "
                 "vous aviez signale est corrige.\n" % attempt_no)
    return f"""Corrigez cette demonstration.

ENONCE A DEMONTRER ({title}) :
{statement}

SOLUTION DE REFERENCE (pour vous seul, a ne pas recopier ; une preuve correcte
qui en differe reste correcte) :
{solution}
{again}
--- copie de l'etudiant ---
{attempt}
--- fin de la copie ---"""


# ---------------------------------------------------------------- syllabus
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
