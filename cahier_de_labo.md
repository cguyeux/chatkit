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

**Non fait.** Build/push/déploiement Scaleway (`:v7`) : en attente de
décision de l'utilisateur, cf. proposition d'enchaînement.
