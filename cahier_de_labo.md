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
