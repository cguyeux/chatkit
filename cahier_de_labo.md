# Cahier de laboratoire — chatkit (déploiement)

Projet : copie de travail locale et déploiement du dépôt public
`github.com/helmi1105/chatkit` (démo OpenAI ChatKit auto-hébergée, full-stack
FastAPI + Next.js). Ce cahier journalise le travail d'infrastructure, pas la
recherche amont. Append-only, horodaté.

---

**Archive :** entrées jusqu'au 2026-08-31 déplacées dans `cahier_de_labo_archive.md`, verbatim, consultable via `rg`.
Ne conserver ici que les dernières entrées ; le skill /cahier-de-labo archive au fil de l'eau.

---

## 2026-09-14 17h30 — Site public inaccessible (chat vide) ; domainKey ChatKit renseignée ; round-trip revalidé en v5

**Signalement.** L'utilisateur signale que `https://formation.gclab.fr/` « ne
marche pas ». Diagnostic (`agent-browser`, console + réseau) : le serveur
répond bien (HTTP 200, tous les chunks Next.js chargent), mais le widget
ChatKit échoue avec `IntegrationError: Domain verification failed for
https://formation.gclab.fr`, renvoyant vers
`platform.openai.com/settings/organization/security/domain-allowlist`. Le
panneau central restait vide (seuls les 3 boutons de contrôle s'affichaient).
Cause confirmée dans le code : `web/src/app/ChatKitComponent.tsx` lit
`NEXT_PUBLIC_CHATKIT_DOMAIN_KEY`, restée au placeholder documenté dans
`DEPLOY_SCALEWAY.md` (`localhost`) malgré les builds `:v3`/`:v4` — le domaine
`formation.gclab.fr` n'avait donc jamais été validé côté OpenAI.

**Correctif.** L'utilisateur a ajouté `formation.gclab.fr` à l'allowlist de
domaines de son organisation OpenAI et fourni la clé publique générée
(`domain_pk_6aa8...4444`, valeur complète dans `DEPLOY_SCALEWAY.md`). Rebuild
`web` -> `:v5` avec `--build-arg NEXT_PUBLIC_CHATKIT_DOMAIN_KEY=<cette clé>`
(URL backend inchangée), push registre, `scw container container update` +
attente `ready` (~30s).

**Vérification navigateur réel (agent-browser, site public).** Plus
d'`IntegrationError` en console ; écran d'accueil ChatKit affiché (« Hey,
what can I do for you? », composer « Your Agent is ready! »).

**Garde-fous respectés.** Machine chargée en nombre de sessions (22 vivantes,
plafond 12) mais CPU/RAM réellement disponibles (load1 ~3/16, 25 Gio libres) :
tâche déclarée via `agentctl task start --force --why` (T99441, 2 Gio/2
cœurs, ~2 min réelles) plutôt que forcée en silence. Rien poussé sur `origin`
(helmi1105), uniquement build/push registre Scaleway. Aucune clé secrète
(OPENAI_API_KEY) touchée ; la clé de domaine, publique par nature (`domain_pk_`),
est documentée en clair dans `DEPLOY_SCALEWAY.md` comme le reste de la
configuration de déploiement.

**Dette documentaire corrigée.** `DEPLOY_SCALEWAY.md` indiquait encore l'image
`web:v1` et le placeholder `localhost` alors que le déploiement réel en était
à `:v4` : mis à jour pour refléter `:v5` et la vraie clé.

---

## 2026-09-14 17h45 — Correction d'accent (contenu pédagogique) ; backend redéployé en v5

**Relecture demandée.** L'utilisateur signale des fautes de français/accent
après le premier test réussi. Audit complet du dépôt (code, widgets, guide
`docs/learner_guide.md`, données pédagogiques) : une seule anomalie trouvée,
`OPERATIONNELLE` sans accent dans deux titres de KC
(« CARTOGRAPHIE OPÉRATIONNELLE - exemple feu urbain/forêt », `g_k31`/`g_k32`),
présente dans `server/app/kc_graph1.json` (le fichier réellement chargé par
`orchestrator.py`, `KC_GRAPH_PATH`) et sa copie `gold_ecg_annotation_v1.json`
(non utilisée par le code mais corrigée par cohérence).

**Correctif + déploiement.** Correction directe dans les deux JSON. Commit
`d9e84ca`. Rebuild `api` -> `:v5` (pas de `--build-arg`, juste `COPY app`),
push registre, `scw container container update` (avec re-passage de
`SecretEnvironmentVariables.OPENAI_API_KEY`, cf. piège déjà documenté) +
attente `ready` (~40s). Vérification navigateur réelle : frontend/chat
toujours fonctionnels après redéploiement backend (écran d'accueil ChatKit
inchangé). Contenu corrigé non re-testé en bout en bout via le flux complet
diagnostic -> QCM (aurait consommé l'API OpenAI sans ajouter de certitude :
correction statique d'un fichier de données, déjà validée par relecture
JSON complète).

**Git.** Push sur `fork` (cguyeux) : `0210a26..d9e84ca`. `origin` (Helmi)
non touché, comme toujours ; Helmi informé par mail pour qu'il intègre ces
modifications (garde anti-DoS + config env-driven + correctif d'accent) de
son côté s'il le souhaite.

---

## 2026-09-14 18h05 — Accueil francisé pour les pompiers ; frontend v6

**Signalement.** L'utilisateur : « ils cliquent, ils comprennent rien ni à
ce que cela fait, ni à sa puissance, ils partent ». Audit de l'accueil réel :
`lang="en"`, titre d'onglet « AgentKit demo », greeting ChatKit « Hey, what
can I do for you? », suggestions génériques (« Hello! », « What can you
do? »), bouton « Learner Guide » pointant en dur vers
`http://127.0.0.1:8000/docs/learner_guide.md` (mort en production : ouvre
localhost sur la machine du visiteur). Aucune explication de ce que fait
l'outil ni de sa valeur avant que l'utilisateur doive deviner en tapant
« Hello! ».

**Découverte utile.** `orchestrator.py::_help_text()` (commande `aide`) sert
déjà un guide correct **en français**, indépendant du fichier
`docs/learner_guide.md` (resté en anglais, jamais traduit, seulement utilisé
par le bouton cassé). Le bouton cassé était donc à la fois inutile et
redondant.

**Correctifs (web/src/app).**
- `layout.tsx` : `lang="fr"`, titre d'onglet et description en français.
- `page.tsx` : suppression du bouton « Learner Guide » cassé ; libellés des
  deux boutons restants traduits (Vue partagée/Plein écran, Mode clair/Mode
  sombre).
- `ChatKitComponent.tsx` : bandeau d'intro (titre, une phrase sur la valeur
  de l'outil : QCM adaptatif, indices, reconnaissance de symboles par photo,
  suivi de progression) avec bouton « Démarrer le diagnostic » qui appelle
  `chatkit.sendUserMessage({text: "start diagnostic"})` (pas
  `chatkit.control.sendUserMessage`, qui n'existe pas dans
  `@openai/chatkit-react` 1.1.1 — piège tsc rencontré et corrigé). Bandeau
  masqué automatiquement au premier message envoyé (`onResponseStart`).
  Greeting et 3 suggestions de démarrage traduites et alignées sur les
  commandes réelles du backend (`start diagnostic` / `radar` / `aide`,
  icônes `star-filled` / `chart` / `book-open`). Placeholder du composer,
  message d'erreur, bouton Réessayer, et libellés du volet latéral
  (Fermer/Source PDF/Graphique/Carte) traduits.

**Validation avant déploiement.** `npx tsc --noEmit` propre, `next build`
propre, `next start` local sur le port 3900 + capture d'écran
(`agent-browser`) : bandeau et suggestions conformes. Pas de test du clic
réel « Démarrer le diagnostic » (aurait déclenché un vrai appel à l'API
OpenAI facturé sur la clé de l'utilisateur, sans ajouter de certitude par
rapport à la vérification de type + relecture de code).

**Déploiement.** `web` -> `:v6` (mêmes `--build-arg` que `:v5`), push
registre, update + redeploy, vérifié `ready` puis re-testé en navigateur
réel sur `formation.gclab.fr` : rendu identique à l'aperçu local, aucune
erreur console.

**Git.** Commits `ce81d16` (accueil francisé), poussés sur `fork`.

**Non fait à ce stade (pistes possibles, non demandées).** Traduction
complète de `docs/learner_guide.md` (actuellement mort, sans conséquence
puisque non lié depuis l'UI) ; persistance du bandeau masqué en
`localStorage` (actuellement remis à zéro à chaque rechargement, volontaire
: garder simple, un pompier revient rarement plusieurs fois par session) ;
tour guidé pas à pas au-delà du bandeau statique.

---

## 2026-09-14 18h20 — Tour guidé pas à pas (remplace le bandeau statique)

**Décision.** Parmi les pistes ouvertes en fin de séance précédente
(tour guidé / traduction de `learner_guide.md` / autre), l'utilisateur a
choisi le tour guidé, seule option ciblant directement le problème signalé
(« ils cliquent, ils comprennent rien... ils partent »).

**Conception.** Nouveau composant `web/src/app/GuidedTour.tsx` : modale
overlay (6 étapes, points de progression, Précédent/Suivant/Passer) qui
remplace le bandeau statique de la v6. Contenu calé sur le parcours réel
côté backend (`server/app/orchestrator.py::_help_text()`) plutôt qu'inventé :
diagnostic de niveau -> mini-leçon + quiz -> indices sur erreur -> photo de
symbole -> `radar` de progression -> `aide` toujours disponible. Dernière
étape : CTA « Démarrer le diagnostic » (envoie `start diagnostic`, identique
au bouton de l'ancien bandeau). Bouton « Passer » à chaque étape ; une fois
le tour fermé (passé ou terminé), un petit bouton « 🧭 Visite guidée » en
haut à gauche du panneau permet de le rouvrir (piste non couverte par
l'ancien bandeau, qui disparaissait sans retour possible).

**Intégration (`ChatKitComponent.tsx`).** État `showIntro` renommé
`showTour` + `tourStep` ; `onResponseStart` ferme le tour comme il fermait
le bandeau. Overlay du tour en `z-10`, sous l'overlay d'erreur existant
(`z-20`) : en cas d'échec de chargement du chat, l'erreur reste prioritaire
et visible.

**Validation avant déploiement.** `npx tsc --noEmit` et `next build` propres.
`next start` local (port 3901) + `agent-browser` (pas de Chrome personnel,
app locale sans authentification) : contenu de l'étape 1 vérifié par
`get text`, navigation testée en cliquant 5x sur « Suivant » jusqu'à l'étape
6 (CTA "Démarrer le diagnostic" présent, dernier point de progression actif),
bouton « Passer » vérifié (fait disparaître la modale, fait apparaître le
bouton de réouverture). Captures dans le scratchpad de session. Pas de test
du clic réel sur le CTA final (aurait déclenché un appel facturé à l'API
OpenAI, backend non lancé en local de toute façon). Session `agent-browser`
et serveur `next start` local fermés en fin de vérification.

**Décision utilisateur (sondage).** Committer + pousser sur `fork` puis
déployer immédiatement (option recommandée retenue, plutôt que commit seul
ou ne rien faire).

**Git.** Commit `5423e61` (« feat(ux): tour guidé pas à pas pour l'accueil
pompiers »), poussé sur `fork` (`8f2fd30..5423e61`). `origin` non touché.

**Déploiement.** Garde-fou ressources partagées déclenché au premier essai
de build (22 sessions vivantes, plafond 12) ; mesure réelle faite
(`agentctl status` : load1 ~1.8/16, RAM 24.8 Gio dispo, PSI io <1%) avant de
forcer, session enregistrée au registre (`docs-38` / `agentctl register`),
tâche déclarée `agentctl task start --force --why` (T02031, 2 Gio/2 cœurs,
~1 min réelle, même profil que les forçages v5/v6). `web` -> `:v7` (mêmes
`--build-arg` qu'en v5/v6, URL backend et domainKey inchangés), push
registre, `scw container container update` + attente `ready` (~20s).

**Vérification navigateur réel (agent-browser, site public
`formation.gclab.fr`).** Tour guidé affiché dès le chargement, sans
`IntegrationError` ni « chat n'a pas pu se charger » (backend réel
joignable, contrairement au test local sans backend). Rendu identique à
l'aperçu local. Session fermée après capture.

**Dette documentaire corrigée.** `DEPLOY_SCALEWAY.md` : image `web`
`:v6` -> `:v7`.

---

## 2026-09-14 18h27 — Transition avant génération lente ; bouton d'aide (?) + documentation en ligne

**Signalement.** L'utilisateur, après avoir testé le tour guidé : « ensuite on
enchaine sur du moulinage, puis un qcm à remplir : il manque de la
transition. Aussi, il faudrait un (?) qui pointe vers un tutorial et une doc
en ligne. »

**Diagnostic.** Trois déclencheurs (`start diagnostic`, `practice`, `next`)
appellent chacun un ou plusieurs LLM côté backend (`_start_diagnostic`,
`_start_practice`, `_next_kc_micro_lesson` dans `orchestrator.py`) puis
retournent directement un widget QCM ou une leçon, sans aucun message
intermédiaire : l'utilisateur voit un silence (spinner générique ChatKit)
puis un contenu qui « tombe du ciel ». Découverte annexe : le bouton
« Learner Guide » cassé de la v6 (déjà retiré) pointait vers un mount
`/docs` (`main.py`) qui n'est en réalité jamais actif en production — le
`Dockerfile` backend ne copie que `app/`, pas le répertoire `docs/` du dépôt
(`DOCS_DIR = APP_DIR.parent.parent / "docs"` ne résout donc rien dans
l'image). Le mount `/static` (`StaticFiles(directory=APP_DIR)`), lui,
fonctionne réellement en production (déjà prouvé par le PDF de doctrine
servi depuis `server/app/`) : c'est ce mount qu'il fallait réutiliser plutôt
que réparer le mount mort.

**Correctifs (`server/app/orchestrator.py`, `server/app/chatkit_server.py`).**
Constantes `START_DIAGNOSTIC_TRIGGERS`/`PRACTICE_TRIGGERS`/`NEXT_KC_TRIGGERS`
extraites (source unique, réutilisées dans `handle()`). Nouvelle méthode
`Orchestrator.peek_transition_message(ctx, text)` : relit les mêmes
pré-conditions que `handle()` (KC courant défini, portillon de pratique
validé, module non verrouillé) SANS déclencher la génération, et renvoie un
court texte de transition uniquement quand la branche lente va réellement
s'exécuter (pour éviter l'incohérence « je prépare... » suivi d'un
avertissement de blocage). `chatkit_server.respond()` appelle ce helper
juste avant `orch.handle()` et, si un texte est renvoyé, l'émet en premier
message (`yield` immédiat), donc visible avant le `moulinage`, plutôt
qu'après.

**Documentation en ligne (`server/app/guide_fr.html`).** Traduction et mise
en forme de `docs/learner_guide.md` (resté en anglais, jamais lié) en page
HTML autonome française, palette claire/sombre alignée sur l'app
(`prefers-color-scheme`), servie via le mount `/static` déjà fonctionnel en
production (`<backend>/static/guide_fr.html`). Reprend le déroulé conseillé,
les commandes, la réponse aux QCM, l'envoi de photo de symbole, le suivi de
progression.

**UI (`web/src/app/ChatKitComponent.tsx`, `GuidedTour.tsx`).** Bouton rond
« ? » toujours visible (`z-30`, au-dessus du tour et de l'overlay d'erreur),
ouvre un petit menu à deux entrées : « Revoir la visite guidée » (rouvre
`GuidedTour`) et « Documentation complète » (lien externe vers
`${NEXT_PUBLIC_CHATKIT_API_URL}/static/guide_fr.html`, nouvel onglet).
Dernière étape du tour mise à jour pour mentionner ce bouton.

**Validation avant déploiement.** `python3 -m py_compile` propre sur les deux
fichiers backend (le venv local `server/.venv` s'est révélé vide/cassé,
aucun paquet installé — non réparé, hors périmètre, la vraie validation des
dépendances se fait par le build Docker). `npx tsc --noEmit` et `next build`
propres côté frontend. `next start` local (port 3902) + `agent-browser` :
bouton « ? » et menu vérifiés (snapshot + capture), `href` du lien
documentation confirmé pointer vers `.../static/guide_fr.html`. Page
`guide_fr.html` ouverte en `file://` direct : rendu clair et sombre tous
deux vérifiés par capture d'écran. Pas de vérification du texte de
transition en conditions réelles (nécessiterait un vrai appel OpenAI) ; la
logique de garde (`peek_transition_message`) a été relue pour miroir exact
des conditions de `handle()`, pas exécutée en bout en bout.

**Décision utilisateur (sondage).** Committer + pousser sur `fork` puis
déployer immédiatement les deux conteneurs (option recommandée retenue).

**Git.** Commit `823cd20` (« feat(ux): transition avant génération lente +
bouton d'aide et doc en ligne »), poussé sur `fork` (`18204e4..823cd20`).

**Déploiement.** Garde-fou forcé une nouvelle fois (T03364, même motif que
les précédents). `api` -> `:v6` (pas de `--build-arg`, `COPY app` inchangé),
`web` -> `:v8` (mêmes `--build-arg` qu'en v7). Build+push des deux images,
`scw container container update` sur les deux conteneurs (re-passage de
`OPENAI_API_KEY` pour `api`), attente `ready` (~30-35s chacun).

**Vérification navigateur réel (agent-browser, site public
`formation.gclab.fr`).** Chat toujours fonctionnel après redéploiement
backend (pas d'erreur de chargement). Bouton « ? » présent, menu ouvert,
`href` du lien documentation confirmé pointer vers le vrai backend public
(`.../static/guide_fr.html`), requête `curl` directe : `HTTP 200`. **Non
vérifié** : le texte de transition lui-même, qui n'apparaît qu'au premier
vrai `start diagnostic`/`practice`/`next` (coût API OpenAI réel) — décision
prise en amont avec l'utilisateur de ne pas déclencher cet appel pour ce
test, comme à chaque déploiement précédent de ce projet.

**Dette documentaire corrigée.** `DEPLOY_SCALEWAY.md` : images `api`
`:v5` -> `:v6`, `web` `:v7` -> `:v8`.

---

## 2026-09-15 10h29 — Signalement Yvon Stortz : diagnostic « 0 partout », investigation statique

**Signalement (Slack, DM Christophe Guyeux <-> Yvon Stortz, 2026-09-14
18h47-18h53).** Après avoir reçu le mail annonçant le « Démonstrateur
formateur intelligent : cartographie opérationnelle (version alpha) »,
Yvon teste sur téléphone. Verbatim : « OK. j'ai tout rempli et j'ai 0
partout » puis « du coup il m'explique les principes de base. alors que
j'avais tout coché. Première approche : je ne comprends pas bien 🙂 ».
Aucune URL, capture ni message d'erreur technique fournis ; fil resté
sans réponse.

**Vérification infra.** Site public `HTTP 200` (curl direct, 2026-09-15).
Conteneurs Scaleway `api` (`:v6`) et `web` (`:v8`) tous deux `ready`. Le
signalement n'est donc pas une panne d'infrastructure.

**Analyse statique du code (pas de reproduction en direct : aurait
déclenché un appel OpenAI facturé, décision prise de ne pas le faire sans
validation préalable).** Le symptôme (« 0 partout » sur un QCM diagnostic
de 8 questions rempli en entier, puis micro-leçon de base comme si rien
n'était su) correspond exactement au chemin `_process_answers` avec
`sess.scope == "diagnostic"` (`orchestrator.py:2561`) quand
`ScoreFindWeaknessAgent.find_weakness` (`orchestrator.py:1579`) ne trouve
AUCUNE réponse correcte : chaque comparaison `u == correct.upper()`
échoue systématiquement. Deux hypothèses distinctes identifiées, non
départagées faute de test en direct :

1. **Format de la clé LLM `answer`.** `DiagnosticQcmAgent.generate()`
   (`orchestrator.py:814`) demande au modèle (gpt-4.1, prompt libre, PAS
   de schéma de sortie strict / `response_format`) de renvoyer
   `"answer":"A/B/C/D"` par question, valeur ensuite prise telle quelle
   comme vérité terrain (`hidden[num] = str(q["answer"]).upper().strip()`,
   ligne 2291) sans validation. Le widget, lui, encode toujours ses
   options en dur `"A"/"B"/"C"/"D"` (`qcm_widget_data`, ligne 126) quel
   que soit ce que le modèle a mis dans `answer`. Si le modèle s'écarte du
   format demandé pour une partie ou la totalité des questions (texte
   complet, ponctuation, etc.), la comparaison échoue pour ces
   questions — potentiellement toutes si le modèle a divergé de façon
   systématique sur ce run précis.
2. **Extraction du payload du widget.** `_extract_answers_from_payload`
   (`chatkit_server.py:362`) gère deux formes de payload possibles
   (`values.answers` dict imbriqué, ou clés plates `answers.N`) sans
   qu'aucun test en conditions réelles n'ait jamais validé laquelle le
   SDK ChatKit produit réellement en production (cahier du 2026-09-14 :
   « Pas de test du clic réel sur le CTA final », partout où un appel
   OpenAI réel aurait été facturé). Un troisième format non couvert
   ferait échouer `int(str(key))` silencieusement (clé ignorée), donnant
   `user_answers` vide et donc 0 partout — correspondance exacte avec le
   symptôme.

**Risque architectural distinct, noté mais pas la cause la plus probable
du symptôme précis.** `Orchestrator._sessions` (ligne 1722) et
`MyDataStore` (`data_store.py:45`, commentaire du fichier : « Simple
in-memory store ») sont 100 % en mémoire process, sans aucune
persistance externe. Les conteneurs Scaleway sont `scale-to-zero`
(`min_scale=0`, timeout 5 min pour `api`). Une session perdue par
redémarrage à froid produirait normalement le message dédié « ⚠️ No
active QCM. Type: start diagnostic » (ligne 2563), pas un score de 0
partout suivi d'une micro-leçon — donc ne colle pas exactement au
signalement d'Yvon, mais reste une fragilité réelle pour tout usage
multi-utilisateurs ou étalé dans le temps (diagnostic + tour guidé
dépassant 5 minutes).

**Non fait.** Aucune reproduction en direct (coût OpenAI), aucun
correctif appliqué, aucun redéploiement. Décision de la suite renvoyée à
l'utilisateur (reproduction en direct vs instrumentation par logs vs
correctif défensif sur les deux hypothèses avant tout nouveau test
utilisateur).

**Décision utilisateur (sondage).** Corriger puis reproduire (option
recommandée retenue) : verrouiller le format de réponse LLM, instrumenter
par logs, redéployer, puis un seul run réel pour valider.

**Correctif hypothèse 1 (`orchestrator.py`).** Nouvelle fonction
`normalize_qcm_answers()` : coerce le champ `answer` de chaque question
générée par LLM en une lettre nue A/B/C/D (extraction par regex si le
modèle a répondu autre chose que la lettre seule, `"A"` par défaut en
dernier recours, avec `print()` d'avertissement à chaque coercition
effective). Appliquée aux quatre points de génération JSON qui partagent
le même défaut : `DiagnosticQcmAgent.generate()`,
`PracticeQcmAgent.generate_adaptive()`, `PracticeQcmAgent.repair_coverage()`,
`ModuleQcmAgent.generate()` — pas seulement le diagnostic signalé, les
trois QCM partagent le même prompt libre sans schéma de sortie strict et
la prochaine étape du même parcours (pratique) aurait reproduit le bug
à l'identique.

**Instrumentation (hypothèse 2, `chatkit_server.py` et `orchestrator.py`).**
`print()` du payload brut de `qcm.submit` et des réponses extraites
avant le garde `if not submitted_answers`, et `print()` du détail
soumis/correct/score par KC dans `_process_answers`. Objectif : si le
correctif de l'hypothèse 1 ne suffit pas, la prochaine soumission réelle
(logs console Scaleway, pas d'accès CLI `scw` aux logs trouvé) montrera
directement si l'extraction du payload échoue.

**Validation avant déploiement.** `python3 -m py_compile` propre sur les
deux fichiers modifiés (venv local `server/.venv` toujours vide/cassé,
non réparé, hors périmètre — même limite que les sessions précédentes).

**Déploiement.** Garde-fou ressources partagées déclenché (23 sessions
vivantes, plafond 12, RAM effective 5.8 Gio < plancher) ; mesure réelle
faite (`agentctl budget` : load1 ~1.8/16, RAM 23.8 Gio dispo) avant de
forcer, session enregistrée (`agentctl register --name chatkit-fix`),
tâche déclarée `agentctl task start --force --why` (T61859, 2 Gio/2
cœurs, ~74s réelles). `api` -> `:v7` (`web` non touché, aucun changement
frontend). Build Docker, push registre, `scw container container
update` (repassage `OPENAI_API_KEY`), attente `ready` (~20s).

**Reproduction en direct (agent-browser via `npx agent-browser`, pas
installé globalement ; site public, pas de Chrome personnel requis).**
Parcours réel : accueil -> clic « Démarrer le diagnostic » -> QCM de 8
questions généré (~20s, thème doctrine cartographie opérationnelle
pompiers) -> 8 réponses cochées en variant délibérément les lettres
(A,B,C,D,A,B,C,D, sans connaître les bonnes réponses) -> Submit.

**Résultat : correctif confirmé.** Réponse reçue : « Candidate weak KC:
LA FORME » suivie d'une micro-leçon ciblée sur cette notion (référence
p.3). Vérification a posteriori sur le contenu de la leçon : la bonne
réponse à la Q8 (« Quelle variable visuelle détermine l'identité
graphique principale d'un objet ? ») est explicitement « La forme »
(choix A) — j'avais coché D (« L'orientation »), donc une vraie erreur
sur la KC en question ; de même Q1 attendait « Étoile » (B) et j'avais
coché A (« Carré »), Q1 et Q8 relevant tous deux de la même KC
« LA FORME ». Le diagnostic a donc correctement discriminé une KC
réellement ratée parmi 8 questions aux réponses volontairement
mélangées, à l'opposé exact du symptôme « 0 partout » rapporté par
Yvon : la comparaison LLM-answer / choix-utilisateur fonctionne de
nouveau. Aucune erreur console JS, aucun `IntegrationError` (vérifié
via `agent-browser console`). Session `agent-browser` fermée après
capture.

**Dette documentaire corrigée.** `DEPLOY_SCALEWAY.md` : image `api`
`:v6` -> `:v7`.

**Non fait.** Pas de réponse envoyée à Yvon sur Slack (hors périmètre
technique, laissé à l'utilisateur). Logs Scaleway (`print()` ajoutés)
non consultés faute d'accès CLI aux logs de conteneurs — seule la
console Scaleway les montrerait ; non nécessaire, la reproduction a
validé le correctif directement par son résultat fonctionnel.

---

## 2026-09-15 11h12 — Procédure de déploiement Scaleway envoyée à Helmi Baazaoui

Helmi Baazaoui (doctorant de CG, auteur amont du dépôt
`github.com/helmi1105/chatkit`) a reçu par mail la procédure de
déploiement Scaleway de ce projet (commandes `docker build`/`tag`/`push`
+ `scw container container update` pour les deux conteneurs `api` et
`web`, génération du domainKey ChatKit côté organisation OpenAI, et les
trois pièges déjà consignés dans `DEPLOY_SCALEWAY.md`), pour qu'il
puisse déployer sa propre instance sur son propre compte Scaleway. Pas
de pièce jointe (le fichier `DEPLOY_SCALEWAY.md` n'a pas été transmis
tel quel : ses identifiants de ressources — namespace, IDs de
conteneurs, domainKey — sont propres au compte Scaleway/OpenAI de CG et
inutilisables par Helmi ; la procédure a été retapée avec des
espaces réservés `<ton-namespace>`, `<container-id>`, `<ta-clé>`).
Registre tutoiement, conforme aux échanges habituels avec lui
(vérifié sur l'historique de mail avant rédaction).

**Incident d'outillage rencontré et contourné, pas encore documenté
dans le projet lui-même (versé à la KB inter-projets, cf.
`~/.agents/knowledge/superhuman-mcp.md`).** Le composeur de brouillon
Superhuman (`create_or_update_draft`, paramètre `body`) supprime
silencieusement l'espace précédant tout `.` ou `:`, y compris à
l'intérieur d'un bloc `<pre>` de code : la commande
`docker build ... -t chatkit-api:latest .` en est ressortie
`chatkit-api:latest.`, contexte de build perdu, commande cassée. Même
résultat avec `./` à la place de `.`. Contournement : remplacer le `.`
de contexte par `$PWD` (équivalent fonctionnel, insensible à la
réécriture), détecté en relisant le `body` renvoyé par le serveur
avant `send_draft`, pas celui envoyé.

---

## 2026-09-15 14h45 — Sélecteur de modèle (Mistral par défaut, GPT-4.1 en second choix, clé API personnelle)

**Contexte.** L'utilisateur a reformulé le périmètre : ce déploiement est un
démonstrateur **local, réservé aux formateurs qui testent**, pas un service
public à grande échelle. Ça change le calcul de risque sur le palier gratuit
Mistral (coût nul, entraînement par défaut sur les données — acceptable ici,
inacceptable pour de vrais stagiaires pompiers) et sur la clé personnelle
(les formateurs, contrairement à des stagiaires grand public, peuvent
raisonnablement en avoir une).

**Demande.** Un menu déroulant dans l'interface, Mistral par défaut, GPT-4.1
en second choix, et la possibilité de coller sa propre clé API si le quota
partagé est épuisé.

**Architecture retenue (détail complet dans `DEPLOY_SCALEWAY.md` §
Multi-fournisseur).** Le choix vit côté navigateur (`sessionStorage`,
jamais persisté par le serveur), renvoyé à chaque requête ChatKit par les
en-têtes `X-Provider`/`X-Provider-Api-Key` — patron BYOK déjà documenté dans
`~/.agents/knowledge/deployment.md`, réutilisé tel quel plutôt que réinventé.
Première version stockait le choix côté serveur (`Session.provider` +
endpoint `/settings` séparé) ; simplifiée en cours de route vers le design
par en-tête, plus robuste (pas de dépendance au `thread_id`, qui n'est pas
forcément disponible avant le premier message) et plus proche du patron déjà
éprouvé — refactor fait par un fork, vérifié indépendamment après coup
(`py_compile` + `grep` de contrôle, rien de résiduel de l'ancien design).

**Nouveau module `app/providers.py`.** `ProviderChoice` + `ContextVar`
`current_provider`, fixé en tête de `Orchestrator.handle()` et
`handle_qcm_submit()` à partir de `ctx.request_context`. Les huit classes
d'agents (`DiagnosticQcmAgent`, `KcEssentialTargetAgent`, `PracticeQcmAgent`,
`ModuleQcmAgent`, `MicroLessonAgent`, `ExplainMistakeAgent`,
`LearnerQuestionAgent`, `VisualQuestionAgent`) sont passées d'un `Agent`
construit une fois pour toutes à l'import à un `_build_agent()` construit à
la demande depuis le `ContextVar` — mécanique mais touche tout le fichier.
Modèle OpenAI par classe préservé exactement (`gpt-4.1` pour la plupart,
`gpt-5.1` pour `ModuleQcmAgent`, `gpt-5.5` pour `VisualQuestionAgent`, cette
dernière basculée sur `mistral/pixtral-large-latest` côté Mistral pour
garder la vision). Mistral atteint via l'extension LiteLLM du SDK Agents
(`openai-agents[litellm]`, ajouté à `requirements.txt`).

**Recherche documentaire hors trajet OpenAI-clé-partagée
(`app/local_search.py`).** `FileSearchTool` est lié au vector store OpenAI
privé de ce compte, inaccessible à une clé Mistral ou à une clé OpenAI
étrangère. Repli sur une recherche BM25 locale (`rank-bm25`), exposée sous
le nom `file_search` (identique à l'outil OpenAI) pour que les consignes de
prompt existantes, écrites du temps où il n'y avait qu'un seul fournisseur,
restent valables sans réécrire les huit blocs d'instructions.

**Découverte en testant : le PDF de doctrine n'a pas de texte
extractible.** `pypdf` puis `PyMuPDF` (les deux testés) ne récupèrent que
l'en-tête répété sur les pages de contenu (~41 caractères), jamais le corps
réel — confirmé en dumpant le texte brut page par page. Le fichier est un
export de mise en page (« Charte graphique »), pas un PDF à calque texte
normal. Rendu de page + OCR (Tesseract, `fra`) récupère le vrai contenu,
vérifié directement : requêtes « LA FORME », « couleur », « pictogramme
sinistre » passent de 0 résultat à des passages réels et pertinents
(24 chunks en-tête-seul -> 171 chunks de contenu réel).

**Deuxième découverte, en testant sur le conteneur réel : l'OCR à la volée
est bien trop lent pour les 140 mvCPU de Scaleway.** Le premier diagnostic
réel en production est resté figé plusieurs minutes (aucune réponse, aucune
erreur), alors que le même test tournait en quelques secondes en local
(CPU du poste, sans commune mesure avec 140 mvCPU). Correctif : l'OCR est
désormais **précalculé au build Docker** (`app/build_doctrine_index.py`,
appelé depuis le `Dockerfile` juste après `COPY app /app/app`), le résultat
baké dans `app/doctrine_chunks.json` — le conteneur déployé ne fait plus
jamais d'OCR à l'exécution, seulement une lecture de fichier JSON.
Mémoire du conteneur `api` relevée de 250 à 560 Mo (plafond pour 140 mvCPU)
par prudence en même temps.

**Troisième découverte, en testant en direct sur `api:v8` (avant le
correctif OCR, donc confondue un temps avec la lenteur) : Mistral enveloppe
parfois sa sortie JSON dans un bloc ```` ```json ```` malgré la consigne
« Return ONLY JSON »**, ce que GPT-4.1 ne fait jamais avec les mêmes
consignes (comparaison directe faite). Un tour d'appel d'outil se termine
aussi parfois par une réponse vide, sans exception. Les deux corrigés par
`providers.py::run_agent_text` (dépouille un bloc de code éventuel, une
reprise bornée à un essai sur sortie vide), qui remplace l'appel direct à
`Runner.run` dans les cinq points qui parsent du JSON (diagnostic, pratique
×2, module, micro-leçon) plus l'extraction de cibles essentielles.

**Message d'erreur utilisateur amélioré.** `providers.py::friendly_llm_error`
distingue quota dépassé (invite à ouvrir les réglages et ajouter sa clé) de
clé refusée (invite à vérifier la clé collée), au lieu d'un message
technique brut ; branché aux deux points d'entrée qui appellent
l'orchestrateur (`respond()` et l'action `qcm.submit`, cette dernière
n'avait auparavant AUCUN `try/except`, un appel LLM raté y aurait fait
remonter une exception non gérée).

**Frontend (`web/src/app/ChatKitComponent.tsx`).** Bouton engrenage à côté
du bouton « ? » existant, ouvre un panneau avec le menu déroulant (Mistral
par défaut, GPT-4.1) et un champ mot de passe pour la clé perso, tous deux
persistés en `sessionStorage` et renvoyés par le wrapper `_fetch` déjà
existant (qui posait déjà l'en-tête `userId`).

**Validation avant déploiement.** `python3 -m py_compile` propre sur les
six fichiers backend touchés. `npx tsc --noEmit` et `next build` propres
côté frontend. Build Docker réel (seule vraie validation vu le venv
`server/.venv` toujours cassé) : conteneur lancé en local, script de fumée
exécuté DANS le conteneur pour appeler réellement `DiagnosticQcmAgent`
via Mistral (gratuit, donc sans les précautions de coût habituelles à ce
projet) — cycle complet observé : génération → appels `file_search` →
JSON valide → `normalize_qcm_answers`, avec un vrai aller-retour de
diagnostic des trois bugs ci-dessus avant d'obtenir un résultat propre.

**Déploiement.** Garde-fou ressources partagées forcé à trois reprises
(mêmes motifs que les sessions précédentes de ce projet : builds Docker
courts, empreinte négligeable). `api` -> `:v8` puis `:v9` (après le
correctif OCR), `web` -> `:v9`. Secret `MISTRAL_API_KEY` ajouté au
conteneur `api` en plus de `OPENAI_API_KEY` déjà présent (toujours la clé
partagée « nouveau », la rotation vers une clé dédiée `chatkit-formation-gclab`
discutée plus tôt dans la journée reste en suspens côté CG).

**Vérification finale en direct (`agent-browser`, site public).** Panneau
réglages présent et fonctionnel (menu déroulant + champ clé visibles).
Diagnostic complet de 8 questions généré avec succès via Mistral,
ancrage doctrinal réel visible dans les questions (« La forme (contour ou
enveloppe) », « lignes de crête », couleurs par thème). ~3 minutes de bout
en bout pour les 8 questions (plusieurs appels d'outils séquentiels par
question) — lent mais fonctionnel, cohérent avec un usage formateur/test
plutôt qu'un usage à fort trafic. Aucune erreur console JS. Session fermée
après capture.

**Non fait.** Pas de test réel du trajet GPT-4.1 (aurait coûté, la
correction du trajet OpenAI n'a pas changé le chemin de code déjà validé
avant cette séance, seulement sa construction dynamique par
`_build_agent()`) ; pas de test réel de `VisualQuestionAgent` côté Mistral
(`mistral/pixtral-large-latest`, jamais exercé en conditions réelles — nom
de modèle à vérifier si un formateur signale un échec sur l'envoi de photo
en mode Mistral). Rotation de la clé OpenAI dédiée toujours en attente du
geste de CG (commande donnée dans la session, jamais confirmée exécutée).

---

## 2026-09-15 15h15 — CG ne voyait pas le sélecteur : cache HTML d'un an trouvé, erreur JSON en prod non reproduite

**Signalement.** CG, après un rechargement forcé et un onglet privé, ne
voyait toujours pas le sélecteur, et obtenait « ⚠️ Erreur interne (Mistral) :
Expecting value: line 1 column 1 (char 0) » sur un diagnostic.

**Deux problèmes distincts, pas un seul.**

**1) Cache HTML réel, indépendant du navigateur — confirmé et corrigé.**
`curl -I https://formation.gclab.fr/` montrait
`cache-control: s-maxage=31536000` (un an), défaut Next.js pour une page
entièrement statique (`web/src/app/page.tsx`), sans aucune config de
revalidation explicite. Un rechargement forcé ne contourne PAS un cache
d'infrastructure en amont du navigateur — c'est précisément pourquoi ni le
hard refresh ni l'onglet privé n'ont rien changé. Correctif :
`web/next.config.ts`, `headers()` pose `Cache-Control: no-store,
must-revalidate` sur `/` uniquement (les chunks `_next/static/` gardent
leur cache normal, sans risque, noms de fichiers hachés par contenu).
Vérifié après déploiement : l'en-tête vaut désormais bien `no-store`.

**2) Erreur JSON en production — NON reproduite malgré 12 essais réels
contre l'image exacte de prod (`api:v9` repullée depuis le registre).**
3 essais du chemin direct (`Runner.run` + prompt manuel) et 3 essais du
vrai chemin `agent.generate()`, tous avec fence markdown correctement
dépouillé, tous aboutis. Hypothèse la plus probable, non confirmée : mes
propres essais de diagnostic tournaient EN PARALLÈLE de la tentative
réelle de CG, sur la même clé Mistral gratuite partagée — un vrai
rate-limit de leur côté produirait exactement ce symptôme (réponse vide,
aucune exception explicite) sans laisser de trace distinguable a
posteriori. Conteneur de test arrêté dès ce constat pour ne plus
contribuer à la contention pendant que CG teste.

**Durcissement appliqué quand même, indépendamment de la cause exacte**
(`providers.py`). `strip_code_fence` passe de `re.match` (ancré début/fin)
à `re.search` : un préambule avant le bloc ```` ```json ```` (le modèle
écrit parfois une phrase avant le JSON) ne fait plus échouer l'extraction.
`run_agent_text` : la condition de succès n'est plus « non vide » mais
« non vide ET commence par `[` ou `{` » (`_looks_like_json`), et les
reprises passent de 1 à 2 (3 essais au total). Paramètre `expect_json`
ajouté pour un futur appelant texte-libre qui ne voudrait pas de cette
contrainte.

**Déploiement.** `api` -> `:v10`, `web` -> `:v10`. Les deux `ready`,
vérifiés.

**Non fait.** Cause racine de l'erreur JSON ponctuelle non confirmée
(non reproduite) ; le durcissement réduit la probabilité de récidive sans
prouver qu'il l'aurait empêchée cette fois précisément. À surveiller si ça
se reproduit alors qu'aucun test local ne tourne en parallèle.

---

## 2026-09-15 15h30 — Audit de l'expérience et du comportement du chatbot, pistes d'amélioration

**Demande.** CG demande des pistes pour améliorer le chatbot de
formation.gclab.fr : expérience utilisateur, comportement et qualité.
Séance de lecture seule, aucun fichier de code modifié, aucun
déploiement.

**Méthode.** Lecture intégrale de `orchestrator.py` (2982 lignes),
`chatkit_server.py`, `providers.py`, `local_search.py`, `main.py`,
`data_store.py`, du front (`ChatKitComponent.tsx`, `page.tsx`,
`GuidedTour.tsx`), du graphe `kc_graph1.json` (32 KC, 8 modules, 4
unités, 23 pages) et des trois dernières entrées du cahier. Lecture des
fiches KB `llm-app-observabilite.md` et `deployment.md` (entrées chatkit
et BYOK).

**Constats vérifiés dans le code (défauts, pas des goûts).**

1. Langue et jargon : formulaire de leçon rendu avec des libellés anglais
   (`_format_lesson_form` : « PDF basis », « Objective », « Rule to
   remember »), messages de flux en anglais (« Candidate weak KC »,
   « Validated KC », « Type: next », « Diagnostic screening result: this
   quiz identifies… »), indices en français sans accents, et le mot
   « KC » exposé partout au stagiaire. Seuls `ExplainMistakeAgent` et
   `VisualQuestionAgent` imposent le français ; les cinq agents
   générateurs de QCM et de leçons n'ont aucune consigne de langue.
2. Diagnostic tronqué : `_kc_nodes_for_diagnostic` prend les 8 premières
   KC de l'ordre pédagogique sur 32, avec 8 questions, soit une question
   par KC. Les 24 KC restantes ne sont jamais sondées, et la faiblesse
   détectée repose sur une seule question. Le parcours est ensuite
   linéaire depuis la KC faible : les KC antérieures restent à 0 au
   radar.
3. Coercition dangereuse de la réponse LLM : `_coerce_qcm_answer_letter`
   cherche la première lettre A-D dans le texte et renvoie « A » sinon.
   Une réponse donnée sous forme de texte (« Carré », « Bleu ») devient
   la lettre « C » ou « B » sans rapport avec la bonne option, et une
   réponse illisible devient « A ». Le stagiaire est alors corrigé à
   tort. Pas de schéma de sortie structuré sur aucun agent.
4. Repli mensonger : `_start_practice` sert un QCM factice (« Fallback
   question (model output invalid) », options A-D, réponse A) quand le
   modèle échoue, au lieu de le dire.
5. État volatil : `MyDataStore` et `Orchestrator._sessions` sont en
   mémoire, `evidence_log.jsonl` sur le disque du conteneur ; le
   conteneur Scaleway est scale-to-zero. Un formateur qui revient le
   lendemain repart de zéro, et les traces d'usage disparaissent. Le
   `userId` côté navigateur, lui, persiste (localStorage), donc la
   persistance serveur suffirait. La maîtrise est en outre indexée par
   fil de discussion, pas par utilisateur.
6. Question libre impossible pendant un QCM ou avant le diagnostic :
   `handle()` renvoie l'aide dès que `phase == "waiting_answers"` ou
   qu'aucune KC n'est sélectionnée. `LearnerQuestionAgent` refuse en
   plus toute notion « future », ce qui bloque un pompier qui veut juste
   identifier un symbole.
7. Pas de corrigé : après soumission, le stagiaire ne voit jamais
   question par question ce qu'il a coché et la bonne réponse, seulement
   une explication en prose limitée aux 5 premières erreurs ; en cas de
   réussite, rien du tout. Les indices (`_build_hint_ladder`) sont des
   gabarits génériques, pas liés à la question ratée.
8. Latence structurelle : chaque génération laisse le LLM appeler
   `file_search` séquentiellement (~3 min pour 8 questions sur Mistral,
   mesuré le 2026-09-15), alors que chaque KC tient sur une page connue
   (`pages` dans le graphe) et que l'OCR est déjà précalculé : le texte
   de la page pourrait être injecté directement. La pratique enchaîne
   jusqu'à trois appels (cibles, génération, réparation) ; les leçons
   « first_exposure » et les cibles essentielles ne dépendent pas de
   l'apprenant et pourraient être précalculées.
9. Front : visite guidée réaffichée à chaque chargement (`showTour`
   non persisté) ; commandes à taper en anglais (« practice », « next »,
   « hint ») et suggestion de départ qui envoie « start diagnostic » en
   clair dans le fil ; volet droit en `w-1/2` non adapté au mobile ;
   pouces de feedback ChatKit activés mais aucun gestionnaire serveur,
   donc retour perdu ; toute erreur HTTP recouvre le chat d'un écran
   « n'a pas pu se charger » avec rechargement forcé.
10. Sécurité et coût : CORS ouvert, aucun code d'accès, clés partagées
    derrière un endpoint public (déjà noté dans la KB deployment.md).
11. Granularité du seuil : 70 % avec un QCM pouvant compter 2 questions,
    donc une erreur sur deux échoue, et 2/3 aussi.
12. Ancrage textuel seul : le mémento est une charte visuelle (formes,
    couleurs, symboles) ; l'index BM25 ne porte que le texte OCR, aucune
    question ne montre un symbole.

**Pistes proposées à CG (détail dans la réponse de séance, résumé ici).**
A. Vitrine stagiaire : franciser et débarrasser du jargon, boutons
d'action à la place des commandes, corrigé question par question, visite
guidée mémorisée, mobile, erreurs non bloquantes.
B. Fiabilité et vitesse : sorties structurées (schéma JSON / Pydantic),
injection directe du texte de page, parallélisation, cache des contenus
indépendants de l'apprenant, repli honnête, persistance des sessions et
des traces.
C. Pédagogie : diagnostic couvrant tout le cours, parcours en file des
notions faibles, seuil et longueur minimale cohérents, radar montrant
estimé vs validé, indices spécifiques, questions visuelles avec image
de symbole, mode question libre.
D. Outillage formateur : banque de questions générées hors ligne puis
validées par les formateurs et servie sans LLM, signalement d'une
question depuis le widget, évaluation hors ligne de la qualité
(ancrage, distribution des lettres, doublons), tableau de bord des
questions les plus ratées, code d'accès et quota.

**Décision attendue.** Choix par CG des axes à lancer ; rien n'est
engagé. Aucune piste n'est validée par un test, ce sont des lectures de
code.

---

## 2026-09-15 18h40 — Refonte du tuteur sur les quatre axes, déployée en v11 et vérifiée en direct

**Décision de CG.** Les quatre axes de l'audit du jour retenus ensemble
(fiabilité et vitesse, vitrine stagiaire, pédagogie, outillage formateur).

**Fait, backend (`server/app/`).** Réécriture de `orchestrator.py`
(1 100 lignes contre 2 982), nouveaux modules `schemas.py` (sorties
Pydantic, résolution de la clé de réponse contre les propositions, mélange
des choix, questions inexploitables écartées), `content.py` (ancrage par
injection du texte des pages), `storage.py` (bucket S3 avec repli local),
`bank.py` (banque validée servie sans LLM), `widgets/its_widgets.py`
(boutons d'action serveur `its.command`, corrigé avec « Signaler cette
question », fiche source avec image de page, carte de progression),
`providers.py` (une seule voie `run_structured` : sortie typée du SDK,
reprise avec backoff sur 429, repli texte lenient), `chatkit_server.py`
(rendu par blocs, `ProgressUpdateEvent` pendant les générations,
`add_feedback` journalisé), `main.py` (`/health`, `/progress`, code d'accès
optionnel `ACCESS_CODE`, CORS restreint), `data_store.py` (fils ChatKit
persistés, `TypeAdapter(ThreadItem)` vérifié en aller-retour). Diagnostic
sur tout le mémento (tirage par chapitre, une question par notion,
génération parallèle bornée à 2), file des notions faibles, leçon de
reprise seulement sous 50 %, indices générés à partir des erreurs réelles,
questions libres acceptées à tout moment, français partout.

**Fait, contenu.** `transcribe_pages.py` : transcription structurée des 24
pages par `mistral-large-latest` (vision) en `doctrine_pages.json`, 246
symboles et 105 règles ; la page 3 retrouve ses six formes avec leur sens et
la page 4 ses couleurs, que l'OCR perdait. Une règle hallucinée corrigée à la
main (« forme, couleur, taille, orientation » -> forme, couleur, état,
surcharge) ; **relecture complète par les formateurs à faire**, le fichier
est la vérité servie au tuteur. Images de page rendues au build (110 dpi).

**Fait, front (fork).** Accueil et visite guidée en français (mémorisée),
barre de progression alimentée par `/progress`, porte de code d'accès,
erreurs non bloquantes, volet droit empilé sur mobile, thème clair par
défaut, bouton « Recommencer à zéro ». `tsc` et `next build` propres.

**Fait, outillage formateur.** `generate_bank.py` (candidats vers xlsx à
relire), `import_bank.py` (lignes « validé » vers `question_bank.json` ou la
clé `bank/questions.json` du bucket, sans rebuild), `trainer_report.py`,
`eval_generation.py`, `smoke_its.py`. Aucun n'a encore été lancé en vrai
hors `smoke_its.py`.

**Infra.** Bucket `chatkit-formation-state` (fr-par), application IAM
`chatkit-api-storage` + politique ObjectStorageFullAccess + clé expirant le
2027-09-15 (`~/.config/chatkit/scw_storage.env`). Images `api:v11`,
`web:v11` déployées ; `v10` conservée pour retour arrière. `ACCESS_CODE`
non posé (le site reste ouvert tant que CG n'a pas choisi un code).

**Mesures.** Test de fumée dans l'image (Mistral) : diagnostic 10 questions
en 17 à 29 s (contre ~3 min avant), soumission + leçon 9-10 s, quiz 16-18 s,
échec + feedback + leçon de reprise 28-50 s, question libre 2-3 s, 16
générations pour le parcours complet. En production (agent-browser, site
public) : diagnostic affiché en 30 s à froid, corrigé 4/10 rendu, fiche
source avec image, bouton « Lancer le quiz » -> quiz en 24 s, barre d'état
« Notion 2/32 : LA FORME · Chapitre : Définition du langage
cartographique ». Bucket vérifié : `sessions/`, `threads/`, `events/`,
`cache/` présents après le test.

**Découvertes.** (1) Le compte OpenAI n'a plus de crédit
(`credit_balance_exhausted`) : le second choix du sélecteur ne marche
qu'avec une clé personnelle. (2) `pixtral-large-latest` retiré par
Mistral ; `mistral-large-latest` porte la vision. (3) Montrer un schéma JSON
à Mistral lui fait renvoyer le schéma : le repli texte montre un exemple
d'instance. (4) Le chemin structuré du SDK Agents échoue par intermittence
sur `Feedback` (« Invalid JSON ») ; le repli texte prend le relais, vu deux
fois sur deux runs.

**Non fait / réserves.** Relecture humaine de `doctrine_pages.json` ;
banque de questions vide (0 question validée, tout passe encore par le
modèle) ; questions visuelles avec image de symbole non implémentées
(seule l'image de page entière est montrée) ; `eval_generation.py` et
`generate_bank.py` jamais exécutés ; pas de test du trajet OpenAI (sans
crédit) ni de l'envoi de photo en production ; le quiz de reprise reformule
mais reste proche du premier sur une notion aussi courte que LA FORME ;
CORS restreint aux deux origines connues, à élargir si un autre domaine
apparaît. Commits `a0a56c8`, `2f66ea8`, `7a5deb0` poussés sur `fork`.

**Décision CG (18h55).** Code d'accès formateur reporté : le site reste
ouvert. Ordre retenu pour la prochaine séance : relecture de
`doctrine_pages.json` avec les formateurs, puis pose du code
(`ACCESS_CODE` en secret du conteneur `api`, procédure dans
`DEPLOY_SCALEWAY.md`).
