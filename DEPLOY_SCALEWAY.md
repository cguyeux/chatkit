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
| Images | `rg.fr-par.scw.cloud/chatkit/api:v5`, `rg.fr-par.scw.cloud/chatkit/web:v5` |

## Configuration / variables

- **Backend** `api` :
  - `OPENAI_API_KEY` : variable d'environnement **secrète** Scaleway (jamais dans
    l'image ni le dépôt). Requise ; sans elle, tout chat échoue.
  - `PUBLIC_BASE_URL` : URL publique du backend (liens absolus vers les PDF `/static`).
  - `VECTOR_STORE_ID` : défaut codé (`vs_6a11...`, org de l'auteur amont). La
    fonction doctrine-QA n'opère que si la clé OpenAI appartient à l'org qui
    possède ce vector store ; sinon override via env `VECTOR_STORE_ID`.
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

## Build + déploiement (rappel)

Backend :
```
cd server && docker build --network=host -f Dockerfile -t chatkit-api:latest .
docker tag chatkit-api:latest rg.fr-par.scw.cloud/chatkit/api:vN && docker push rg.fr-par.scw.cloud/chatkit/api:vN
scw container container update c109d80e-c82f-413c-9381-974304611cf0 image=rg.fr-par.scw.cloud/chatkit/api:vN region=fr-par secret-environment-variables.OPENAI_API_KEY="$OPENAI_API_KEY"
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
