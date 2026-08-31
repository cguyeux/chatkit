# Cahier de laboratoire — chatkit (déploiement)

Projet : copie de travail locale et déploiement du dépôt public
`github.com/helmi1105/chatkit` (démo OpenAI ChatKit auto-hébergée, full-stack
FastAPI + Next.js). Ce cahier journalise le travail d'infrastructure, pas la
recherche amont. Append-only, horodaté.

---

## 2026-06-08 19h17 — Déploiement full-stack (backend + frontend) sur Scaleway

**Objectif.** Mettre le site en ligne, comme airgos/annotation_mtbc (Serverless
Containers scale-to-zero), en utilisant la clé OpenAI de l'utilisateur
(autorisation explicite, lue depuis `~/.bashrc`, jamais affichée ni commitée).

**Nature de l'app.** Démo OpenAI ChatKit auto-hébergée : backend FastAPI
(`server/app/main.py`, endpoint POST `/chatkit`, `/static` sert un PDF de
doctrine) appelant l'API OpenAI via l'Agents SDK, et frontend Next.js
(`web/`, widget ChatKit chargé depuis le CDN OpenAI). Orchestrateur multi-agents
(doctrine QA via vector store, fiches d'étude, QCM, cartes OSM, graphiques).
Store de threads en mémoire (éphémère).

**Source.** Clone local divergent (1 commit local « chore: update lockfile »,
2 commits distants plus récents). Choix : déployer `origin/main` (dernière
version GitHub) ; commit local sauvegardé sur la branche `local-backup-pre-deploy`,
puis `reset --hard origin/main`. La version origin/main est mieux structurée que
la copie locale (env-driven `os.getenv`, pas de dépendance MCP externe).

**Modifications (locales, non poussées).**
- `server/app/orchestrator.py` : URL statique en dur `http://127.0.0.1:8000/static/...`
  -> `PUBLIC_BASE_URL` (env), pour des liens PDF absolus corrects en prod.
- `web/next.config.ts` : ajout `output: "standalone"` (image Docker minimale).
- `web/src/app/ChatKitComponent.tsx` : `url` backend et `domainKey` rendus
  configurables via `NEXT_PUBLIC_CHATKIT_API_URL` / `NEXT_PUBLIC_CHATKIT_DOMAIN_KEY`
  (l'URL backend était codée en dur sur `127.0.0.1:8000`).
- Ajout de `server/Dockerfile` (+ .dockerignore) et `web/Dockerfile` (+ .dockerignore).

**Déploiement.** Namespaces registry+container `chatkit`. Backend `api`
(CID `c109d80e...`) avec `OPENAI_API_KEY` en variable **secrète** Scaleway +
`PUBLIC_BASE_URL`. Frontend `web` (CID `01416308...`) buildé avec l'URL publique
du backend bakée. Les deux en `ready`, port 8080, scale-to-zero.
- Backend : https://chatkitf92c84e6-api.functions.fnc.fr-par.scw.cloud
- Frontend (public) : https://chatkitf92c84e6-web.functions.fnc.fr-par.scw.cloud

**Vérifications.** Backend : démarre (clé câblée, pas d'erreur startup), POST
`/chatkit` sans header -> 400 attendu, avec header `userId` + body vide -> 500
(on dépasse l'auth et on entre dans le traitement ChatKit), `/static` PDF -> 200.
Frontend : page 200, `chatkit.js` (CDN OpenAI) référencé, URL backend de prod
bien bakée dans le bundle (plus de `127.0.0.1`), contrat d'en-tête `userId`
cohérent des deux côtés. Round-trip chat complet NON testable ici (navigateur
Claude-in-Chrome non connecté ; le widget ChatKit ne se teste qu'en navigateur).

**Limites / actions côté utilisateur (OpenAI).**
1. **domainKey** : encore `localhost`. Pour que le widget ChatKit se charge sur
   le domaine de prod, enregistrer `chatkitf92c84e6-web.functions.fnc.fr-par.scw.cloud`
   dans l'allowlist OpenAI (platform.openai.com → security → domain-allowlist),
   récupérer la vraie clé de domaine, puis rebuild frontend avec
   `--build-arg NEXT_PUBLIC_CHATKIT_DOMAIN_KEY=<clé>`.
2. **Vector store** : `VECTOR_STORE_ID` défaut = org de l'auteur amont. La
   doctrine-QA n'opère que si la clé OpenAI fournie appartient à cette org ;
   sinon override `VECTOR_STORE_ID` (env) avec un store de l'org de la clé.
3. **Coût/exposition** : endpoint public consommant les crédits OpenAI de la clé
   à chaque message. Garde-fou (auth basique) proposé, non posé (non demandé).

**Connaissances (cf. `~/.claude/knowledge/deployment.md`).** Secrets scw en
syntaxe map ; app multi-container (frontend buildé avec l'URL backend publique
bakée) ; `NEXT_PUBLIC_*` figés au build via `--build-arg`.

**Garde-fous respectés.** Rien poussé sur le dépôt amont de helmi1105 ; clé
OpenAI uniquement en variable secrète Scaleway, jamais affichée/commitée.

---

## 2026-06-08 19h29 — Correctif domainKey : page noire (widget ChatKit ne reste pas monté)

**Symptôme rapporté.** « Le texte du chatbot apparaît et disparaît aussitôt,
puis page noire. »

**Diagnostic (confirmé code + doc).** Le widget se montait (écran d'accueil
visible avant tout appel backend), puis chatkit.js échouait à la vérification de
domaine (`domainKey: "localhost"` sur le domaine de prod) et se détruisait,
laissant le fond du thème sombre par défaut (`bg-slate-950`) = « page noire ».
Aggravant : l'état `error` du composant n'est rendu nulle part (échec silencieux).
Doc OpenAI ChatKit : `domainKey` = « domain key used to verify the registered
domain », obligatoire en config self-hosted (`CustomApiConfig`). README amont
idem. Ce n'était ni le backend ni le câblage (l'accueil s'affiche sans appel
serveur), bien l'init ChatKit.

**Correctif.** L'utilisateur a enregistré le domaine frontend dans l'allowlist
OpenAI et fourni la clé `domain_pk_6a26fb39…` (clé publique côté client, non
secrète, destinée au bundle). Rebuild frontend `v2` avec
`--build-arg NEXT_PUBLIC_CHATKIT_DOMAIN_KEY=domain_pk_…`, push, update du
container `web` -> `:v2`, redeploy. Vérifié : page 200, la vraie `domain_pk_…`
est servie dans le bundle live (`chunks/app/page-*.js`), `localhost` n'est plus
le domainKey actif.

**Reste à faire côté utilisateur.** Recharger (hard refresh) et confirmer que le
chat se charge et répond. Si toujours noir : vérifier que le domaine enregistré
dans l'allowlist correspond EXACTEMENT à
`chatkitf92c84e6-web.functions.fnc.fr-par.scw.cloud` (sinon la clé ne matche
pas) ; option proposée : remplacer la page noire silencieuse par un message
d'erreur visible (non encore fait, à la demande).

---

## 2026-08-31 12h30 — Fork GitHub, merge amont, build+push+redeploy v3

**Objectif.** Passer de « rien poussé sur le dépôt amont, déploiement à partir
du seul code local » à un état versionné, sur demande explicite de l'utilisateur
(« commit pull push et deploy sur scaleway »).

**Changement de garde-fou.** `origin` pointe vers le dépôt amont public d'un
tiers (`github.com/helmi1105/chatkit`), sur lequel l'utilisateur n'a pas de
droits d'écriture — confirmé en clarifiant avec lui plutôt qu'en tentant un
push aveugle. Choix retenu : créer un fork personnel `github.com/cguyeux/chatkit`
(`gh repo fork helmi1105/chatkit`), ajouté comme remote `fork`, et y pousser.
`origin` (helmi1105) reste intact, non touché.

**Séquence.**
1. Commit local des 9 fichiers de déploiement en attente depuis le
   2026-06-08 (Dockerfiles, `.dockerignore`, `DEPLOY_SCALEWAY.md`, ce cahier,
   correctifs `PUBLIC_BASE_URL` / `NEXT_PUBLIC_CHATKIT_*`).
2. `git pull origin main` : 2 commits amont en attente (« Add adaptive ITS
   workflow and learner guide », « update README »), touchant entre autres
   `orchestrator.py` et `ChatKitComponent.tsx` — mêmes fichiers que nos
   correctifs de déploiement. Conflit réel sur le bloc CONFIG
   d'`orchestrator.py` (résolu à la main : conservé `PUBLIC_BASE_URL` local
   + commentaire amont) ; `ChatKitComponent.tsx` fusionné automatiquement
   par git (nos changements ne recoupaient pas ceux de l'amont).
3. `git push fork main` : réussi.
4. Rebuild + push registre Scaleway des deux images en `:v3` (les `:v1`/`:v2`
   dataient d'avant le merge amont, donc du code obsolète côté backend
   `orchestrator.py`/`main.py`/`data_store.py` et frontend `page.tsx`) :
   - backend `api` -> `:v3`, `scw container container update` avec
     re-passage de `OPENAI_API_KEY` (secret Scaleway, sinon risque de perte
     documenté dans `DEPLOY_SCALEWAY.md`).
   - frontend `web` -> `:v3`, rebuild avec les MÊMES `--build-arg` qu'en
     prod (`NEXT_PUBLIC_CHATKIT_API_URL` inchangée, `NEXT_PUBLIC_CHATKIT_DOMAIN_KEY`
     = `domain_pk_6a26fb39...` récupérée en clair depuis le bundle JS déjà
     servi en prod, faute d'être stockée en local — clé publique par design,
     non secrète).
5. Vérification post-déploiement : frontend 200 avec la bonne `domain_pk_...`
   bakée dans le bundle, backend répond 400 sur `POST /chatkit` sans header
   (comportement attendu, auth active).

**Incidents transitoires.** `docker login` a d'abord échoué (mauvais parsing
du secret `scw`, corrigé en passant par `scw config get secret-key`) ; build
frontend a échoué 2 fois sur `npm ci` (`ETIMEDOUT` puis `ECONNRESET`,
instabilité réseau ponctuelle) avant de réussir au 3ᵉ essai — aucune action
corrective nécessaire au-delà du retry.

**Garde-fous respectés.** Rien poussé sur `origin` (helmi1105) ; clé OpenAI
jamais affichée ni commitée, uniquement repassée en variable secrète Scaleway
via `$OPENAI_API_KEY` de l'environnement local.

---

## 2026-08-31 13h15 — Test fonctionnel navigateur v3 : widget invisible, cause externe

**Objectif.** Vérifier le round-trip complet du widget ChatKit en navigateur
réel (jamais fait lors du déploiement initial du 08/06, faute de Claude-in-Chrome
connecté à l'époque), sur le frontend `:v3` fraîchement déployé.

**Constat.** Page frontend 200, panneau ChatKit vide (ni écran d'accueil, ni
message d'erreur visible), une erreur console `Event` non descriptive émise
par le chunk du SDK ChatKit à chaque chargement.

**Diagnostic.** `read_network_requests` montre le script tiers
`https://cdn.platform.openai.com/deployments/chatkit/chatkit.js` en **503**
de façon reproductible (4 tentatives navigateur sur ~5 minutes, rechargements
espacés). Confirmé hors navigateur : `curl` direct sur ce même script alterne
`200` / `503` / échec TLS (`unexpected eof`) sur des essais successifs à 2-3s
d'intervalle. Le frontend (`:v3`) et le backend (`:v3`) répondent correctement
de leur côté (200 sur `/`, 400 attendu sur `POST /chatkit` sans header) : ce
n'est PAS une régression du déploiement, c'est une indisponibilité
intermittente du CDN OpenAI `cdn.platform.openai.com` au moment du test,
indépendante de notre infrastructure.

**Reste à faire.** Retester plus tard (ou laisser l'utilisateur confirmer)
quand le CDN OpenAI sera stable. Le défaut déjà noté le 08/06 — état `error`
du composant ChatKit jamais rendu visuellement (échec silencieux, panneau
blanc/vide au lieu d'un message clair) — reste d'actualité et aggrave le
diagnostic pour un futur incident CDN : proposé alors et toujours non fait,
à la demande.
