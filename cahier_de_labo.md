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
