# Déploiement chatkit sur Scaleway Serverless Containers

Note de déploiement (ajoutée hors dépôt amont, non poussée). Application
full-stack : backend FastAPI (`server/`) + frontend Next.js (`web/`), déployés
en deux Serverless Containers distincts, scale-to-zero.

Démo OpenAI ChatKit auto-hébergée : le backend appelle l'API OpenAI à chaque
message (coût par requête). Endpoint public = dépense ouverte sur la clé utilisée.

## Ressources créées (région fr-par)

| Ressource | Valeur |
|-----------|--------|
| Registry namespace | `chatkit` -> `rg.fr-par.scw.cloud/chatkit` |
| Container namespace | `chatkit` (id `f92c84e6-c9df-4009-aa48-11f3390125be`) |
| Container backend | `api` (id `c109d80e-c82f-413c-9381-974304611cf0`), port 8080 |
| Container frontend | `web` (id `01416308-9185-4fa2-b1fd-cc432053d997`), port 8080 |
| Backend URL | https://chatkitf92c84e6-api.functions.fnc.fr-par.scw.cloud |
| Frontend URL (public) | https://chatkitf92c84e6-web.functions.fnc.fr-par.scw.cloud |
| Images | `rg.fr-par.scw.cloud/chatkit/api:v9`, `rg.fr-par.scw.cloud/chatkit/web:v9` |

## Configuration / variables

- **Backend** `api` :
  - `OPENAI_API_KEY` : variable d'environnement **secrète** Scaleway (jamais dans
    l'image ni le dépôt). Utilisée seulement pour le trajet OpenAI/GPT-4.1 par
    défaut (clé partagée) ; sans clé perso fournie par le formateur, le
    diagnostic échoue si elle manque et que GPT-4.1 est sélectionné.
  - `MISTRAL_API_KEY` : idem, variable **secrète**, pour le trajet Mistral (le
    choix par défaut du sélecteur de modèle, cf. § Multi-fournisseur ci-dessous).
  - `PUBLIC_BASE_URL` : URL publique du backend (liens absolus vers les PDF `/static`).
  - `VECTOR_STORE_ID` : défaut codé (`vs_6a11...`, org de l'auteur amont). La
    fonction doctrine-QA n'opère que si la clé OpenAI appartient à l'org qui
    possède ce vector store ; sinon override via env `VECTOR_STORE_ID`. Ne
    concerne QUE le trajet OpenAI à clé partagée (`FileSearchTool`) ; Mistral
    et toute clé personnelle passent par la recherche locale (§ ci-dessous).
- **Frontend** `web` (Next.js standalone, `NEXT_PUBLIC_*` bakés AU BUILD via
  `--build-arg`) :
  - `NEXT_PUBLIC_CHATKIT_API_URL` = URL publique du backend (baké à v1).
  - `NEXT_PUBLIC_CHATKIT_DOMAIN_KEY` = `domain_pk_6aa810d2bd3c8195872895a04b628d3b076759a02a964444`
    (clé réelle, domaine `formation.gclab.fr` enregistré dans l'allowlist OpenAI
    depuis le 2026-09-14 ; bakée dans l'image `web:v5`). Si le domaine public change
    ou que la clé est régénérée côté OpenAI, refaire le rebuild (§ ci-dessous) avec
    la nouvelle valeur, sinon le widget ChatKit échoue avec
    `IntegrationError: Domain verification failed`.

## Modifications de code (locales, non poussées)

- `server/app/orchestrator.py` : URL statique `127.0.0.1:8000` -> `PUBLIC_BASE_URL` (env).
- `web/next.config.ts` : ajout `output: "standalone"`.
- `web/src/app/ChatKitComponent.tsx` : `url` et `domainKey` lus depuis
  `NEXT_PUBLIC_CHATKIT_API_URL` / `NEXT_PUBLIC_CHATKIT_DOMAIN_KEY` (fallback dev).
- `server/Dockerfile`, `server/.dockerignore`, `web/Dockerfile`, `web/.dockerignore` : ajoutés.

## Multi-fournisseur (Mistral par défaut, GPT-4.1 en second choix, clé perso) — 2026-09-15

Ajouté pour un usage « démonstrateur local, formateurs qui testent » (pas de
public final) : un sélecteur dans l'interface (icône engrenage) laisse
choisir Mistral (gratuit, par défaut) ou GPT-4.1/OpenAI, et coller sa propre
clé API si le quota partagé est épuisé.

- **Frontend** (`web/src/app/ChatKitComponent.tsx`) : le choix vit en
  `sessionStorage` (effacé à la fermeture de l'onglet, jamais `localStorage`
  pour ne pas persister un secret tiers) et est renvoyé à **chaque** requête
  ChatKit via les en-têtes `X-Provider` / `X-Provider-Api-Key` (extension du
  wrapper `_fetch` qui posait déjà `userId`). Patron déjà documenté dans
  `~/.agents/knowledge/deployment.md` (BYOK par requête, override qui
  court-circuite un mode par défaut), réutilisé tel quel.
- **Backend** : `main.py` lit ces en-têtes et les place dans le dict
  `context` déjà transmis par `server.process()` (même mécanisme que
  `USER_ID_KEY`, déjà thread à travers toute la pile). `orchestrator.py`
  lit `ctx.request_context` en tête de `handle()`/`handle_qcm_submit()` et
  fixe un `ContextVar` (`app/providers.py::current_provider`) lu par les huit
  classes d'agents pour construire leur `Agent` à la demande (`_build_agent()`)
  au lieu d'un agent fixé une fois pour toutes à l'import — Mistral via
  l'extension LiteLLM du SDK Agents (`agents-agents[litellm]`,
  `LitellmModel(model="mistral/mistral-large-latest", ...)`), OpenAI
  inchangé sur le trajet clé partagée.
- **Recherche documentaire hors trajet OpenAI-clé-partagée**
  (`app/local_search.py`) : `FileSearchTool` est propre au vector store
  OpenAI privé de ce compte — inaccessible à une clé Mistral ou à une clé
  OpenAI étrangère. Repli sur une recherche BM25 locale (`rank-bm25`) sur le
  PDF de doctrine, exposée comme un outil nommé `file_search` (même nom que
  l'outil OpenAI, pour que les consignes de prompt existantes restent
  valables sans les réécrire).
- **Le PDF n'a pas de calque texte exploitable sur ses pages de contenu**
  (export de mise en page ; `pypdf` et `PyMuPDF` n'y récupèrent que l'en-tête
  répété, ~41 caractères/page). Un rendu de page + OCR (Tesseract, `fra`)
  récupère le vrai contenu. **Précalculé au build Docker**
  (`app/build_doctrine_index.py`, appelé depuis le `Dockerfile`, résultat
  baké dans `app/doctrine_chunks.json`) et non à la première requête : sur
  les 140 mvCPU du conteneur `api`, OCR-iser 24 pages à la volée a fait
  paraître le premier diagnostic figé plusieurs minutes en test réel.
  Regénérer ce fichier (rebuild, ou `python build_doctrine_index.py` en
  local) si le PDF change.
- **Mémoire du conteneur `api` relevée de 250 à 560 Mo** (plafond autorisé
  pour 140 mvCPU) en même temps que ce déploiement, par prudence pour le
  rendu de page/OCR — `scw` n'accepte `memory-limit-bytes` qu'en unité `G`/`GB`
  (`0.56GB`, pas `560MB`).
- Fiabilité constatée en test réel (Mistral, gratuit) : la sortie JSON est
  parfois enveloppée dans un bloc ```` ```json ```` malgré la consigne
  « ONLY JSON » (jamais vu côté GPT-4.1 avec les mêmes consignes) ; et un
  tour d'appel d'outil se termine parfois par une réponse vide sans lever
  d'exception. Les deux sont couverts par `providers.py::run_agent_text`
  (dépouille un éventuel bloc de code, une reprise bornée à 1 essai sur
  sortie vide), utilisé par tous les générateurs qui parsent du JSON.

## Refonte du 2026-09-15 (quatre axes : vitrine, fiabilité, pédagogie, outillage formateur)

Détail des motifs dans le cahier de labo (entrées du 2026-09-15). Ce qui change pour le déploiement :

- **Ancrage doctrinal** : `server/app/doctrine_pages.json` (transcription structurée des 24 pages
  par un modèle de vision, `transcribe_pages.py`, à relire par les formateurs) est **commité** et
  chargé en priorité par `content.py` ; l'OCR Tesseract (`doctrine_chunks.json`) et les images de
  page (`pages/*.png`) restent générés au build par `build_doctrine_index.py`. Plus aucun outil
  `file_search` sur le trajet Mistral : le texte des pages est injecté dans les prompts.
- **Persistance** : sessions apprenant, fils ChatKit, journal d'événements et cache de contenu vont
  dans un bucket Object Storage (`storage.py`). Variables secrètes du conteneur `api` :
  `STATE_S3_BUCKET=chatkit-formation-state`, `STATE_S3_ENDPOINT=https://s3.fr-par.scw.cloud`,
  `STATE_S3_REGION=fr-par`, `STATE_S3_ACCESS_KEY`, `STATE_S3_SECRET_KEY` (application IAM
  `chatkit-api-storage`, politique ObjectStorageFullAccess sur le projet, clé expirant le
  2027-09-15 ; valeurs dans `~/.config/chatkit/scw_storage.env`, jamais dans le dépôt). Sans ces
  variables, repli sur un répertoire local (`STATE_LOCAL_DIR`, perdu au scale-to-zero).
- **Code d'accès formateur** : `ACCESS_CODE=<code>` (secret) exige l'en-tête `X-Access-Code` sur
  `/chatkit`, `/progress` et l'upload ; le front affiche une porte de saisie. Vide = accès libre.
- **CORS** : `ALLOWED_ORIGINS=https://formation.gclab.fr,https://chatkitf92c84e6-web.functions.fnc.fr-par.scw.cloud`
  (défaut `*` si absent).
- **Modèles** : `MISTRAL_MODEL` (défaut `mistral/mistral-large-latest`), `MISTRAL_VISION_MODEL`
  (défaut idem : `pixtral-large-latest` a été retiré par Mistral, « Invalid model » le 2026-09-15),
  `OPENAI_MODEL` (défaut `gpt-4.1`). **Le compte OpenAI n'a plus de crédit au 2026-09-15**
  (`credit_balance_exhausted`) : le second choix du sélecteur ne fonctionne qu'avec une clé
  personnelle tant que CG n'a pas rechargé.
- **Quota par apprenant** : `MAX_GENERATIONS_PER_DAY` (défaut 150) ; `LLM_CONCURRENCY` (défaut 2,
  palier gratuit Mistral ~1 req/s) ; `DIAGNOSTIC_Q_NUM` (défaut 10), `PRACTICE_MIN_Q` (4).
- **Endpoints ajoutés** : `GET /health` (état, source doctrinale, backend de stockage, taille de la
  banque), `GET /progress` (barre d'état du front).
- **Outillage formateur** (`server/app/`, hors ligne, dans l'image ou en local avec `PYTHONPATH=server`) :
  `generate_bank.py` (candidats de questions vers un xlsx à relire), `import_bank.py` (lignes
  « validé » vers `question_bank.json` et/ou la clé `bank/questions.json` du bucket, servie sans
  rebuild), `trainer_report.py` (apprenants, taux de réussite par notion, questions les plus
  ratées, signalements, pouces), `eval_generation.py` (validité, distribution des lettres,
  doublons, ancrage jugé, latence, par fournisseur), `smoke_its.py` (parcours complet contre
  l'orchestrateur réel, à lancer dans l'image avec `MISTRAL_API_KEY`).

## Build + déploiement (rappel)

Backend :
```
cd server && docker build --network=host -f Dockerfile -t chatkit-api:latest .
docker tag chatkit-api:latest rg.fr-par.scw.cloud/chatkit/api:vN && docker push rg.fr-par.scw.cloud/chatkit/api:vN
set -a; source ~/.config/chatkit/scw_storage.env; set +a
scw container container update c109d80e-c82f-413c-9381-974304611cf0 image=rg.fr-par.scw.cloud/chatkit/api:vN region=fr-par secret-environment-variables.OPENAI_API_KEY="$OPENAI_API_KEY" secret-environment-variables.MISTRAL_API_KEY="$MISTRAL_API_KEY" secret-environment-variables.STATE_S3_ACCESS_KEY="$STATE_S3_ACCESS_KEY" secret-environment-variables.STATE_S3_SECRET_KEY="$STATE_S3_SECRET_KEY" environment-variables.STATE_S3_BUCKET=chatkit-formation-state environment-variables.STATE_S3_ENDPOINT=https://s3.fr-par.scw.cloud environment-variables.STATE_S3_REGION=fr-par environment-variables.PUBLIC_BASE_URL=https://chatkitf92c84e6-api.functions.fnc.fr-par.scw.cloud
scw container container redeploy c109d80e-c82f-413c-9381-974304611cf0 region=fr-par
```

Frontend (rebuild nécessaire si l'URL backend ou le domainKey change) :
```
cd web && docker build --network=host -f Dockerfile --build-arg NEXT_PUBLIC_CHATKIT_API_URL="https://chatkitf92c84e6-api.functions.fnc.fr-par.scw.cloud" --build-arg NEXT_PUBLIC_CHATKIT_DOMAIN_KEY="<vraie-cle-domaine>" -t chatkit-web:latest .
docker tag chatkit-web:latest rg.fr-par.scw.cloud/chatkit/web:vN && docker push rg.fr-par.scw.cloud/chatkit/web:vN
scw container container update 01416308-9185-4fa2-b1fd-cc432053d997 image=rg.fr-par.scw.cloud/chatkit/web:vN region=fr-par
scw container container redeploy 01416308-9185-4fa2-b1fd-cc432053d997 region=fr-par
```

## Pièges rencontrés

- `scw` 2.56.1 : les variables secrètes se passent en MAP : `secret-environment-variables.OPENAI_API_KEY=<valeur>` (PAS `.0.key=/.0.value=`, qui échoue silencieusement -> CID null).
- `update` qui touche les env : re-passer la clé secrète à chaque update (sinon risque de la perdre). L'`update` redéploie déjà ; `redeploy` ensuite est redondant.
- `NEXT_PUBLIC_*` figés au build : rebuilder le frontend pour tout changement d'URL backend ou de domainKey.
- `memory-limit-bytes` n'accepte que l'unité `G`/`GB` (`0.56GB`), jamais `MB` ; et la valeur est plafonnée par le palier `mvcpu-limit` en cours (140 mvCPU -> 140-560 Mo).
