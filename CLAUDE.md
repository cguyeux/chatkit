# CLAUDE.md

## Nature du projet

Copie de travail locale et déploiement de « PDF2ITS », un système de tutorat
intelligent auto-hébergé bâti sur OpenAI ChatKit (backend FastAPI dans
`server/`, frontend Next.js dans `web/`). Le dépôt amont est
`github.com/helmi1105/chatkit` (projet d'un tiers, pas une recherche de
Christophe Guyeux) ; le travail ici est de l'infrastructure de déploiement,
pas de la recherche scientifique — pas d'`etat_des_decouvertes.md` ni de
`pistes.md` attendus.

## Remotes git : ne jamais pousser sur `origin`

```
origin  https://github.com/helmi1105/chatkit.git   (dépôt amont, lecture seule)
fork    https://github.com/cguyeux/chatkit.git      (seul remote sur lequel pousser)
```

Toute modification locale se pousse UNIQUEMENT sur `fork`. Ne jamais pousser
sur `origin`, même par erreur de remote par défaut.

## Cahier de laboratoire

`cahier_de_labo.md` existe déjà et est explicitement borné : il journalise le
travail de déploiement, pas la recherche amont (cf. son en-tête). Continuer
selon la même convention (append-only, horodaté) via `/cahier-de-labo update`
après toute intervention notable.

## Déploiement

`DEPLOY_SCALEWAY.md` documente le déploiement en cours : deux Serverless
Containers Scaleway scale-to-zero (`api` et `web`, région fr-par), backend qui
appelle l'API OpenAI à chaque message (coût par requête, clé personnelle de
l'utilisateur lue depuis l'environnement, jamais commitée ni affichée). Suivre
ce fichier pour toute mise à jour d'image (`:vN`) ou de configuration.

## Pièges déjà rencontrés (cf. cahier de labo)

- Le CDN OpenAI utilisé par `chatkit.js` peut renvoyer des 503 prolongés,
  indépendants du déploiement local : ne pas diagnostiquer côté serveur avant
  d'avoir écarté ce point.
- L'upload d'attachments nécessite une garde de taille anti-DoS avant lecture
  du corps de requête (déjà appliquée, cf. commit `f24988b`) : ne pas la
  retirer lors d'un refactor.
