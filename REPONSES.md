# Réponses aux questions du TP

## Exercice 0

**Les réponses sont-elles identiques d'un outil à l'autre ?**

Oui. Kibana Dev Tools, Hoppscotch et curl renvoient le même JSON (`name: es01`, `cluster_name: tp-eisi`, version `9.5.4`, Lucene `10.5.1`, `tagline: "You Know, for Search"`). Les trois outils appellent la même API REST ; seule la présentation change (Kibana et `?pretty` indentent le JSON).

**Quel code HTTP obtenez-vous sans authentification, et que dit le message d'erreur ?**

Code 401 Unauthorized, avec une `security_exception` :

```
"reason" : "missing authentication credentials for REST request [/?pretty]"
```

La sécurité étant activée (`xpack.security.enabled=true`), toute requête doit être authentifiée. L'en-tête `WWW-Authenticate` indique les méthodes acceptées : `Basic` (utilisateur / mot de passe) et `ApiKey`.

**Pourquoi Kibana n'a-t-il pas besoin que vous lui fournissiez le mot de passe à chaque requête ?**

On s'authentifie une seule fois à la connexion à Kibana, qui ouvre une session (cookie). Les requêtes de Dev Tools ne partent pas du navigateur vers Elasticsearch : elles passent par le serveur Kibana, qui les relaie à Elasticsearch avec les identifiants de l'utilisateur connecté (`elastic`). Le compte `kibana_system` sert uniquement au fonctionnement interne de Kibana, pas aux requêtes de l'utilisateur.

## Exercice 1.1

**Quelle version tourne ?**

Elasticsearch 9.5.4 (`GET /` → `version.number`), basé sur Lucene 10.5.1.

**Combien de nœuds ?**

Un seul nœud, `es01` (`GET _cat/nodes?v`). Il est master (`*`) et cumule tous les rôles (`node.role` = `cdfhilmrstw` : data, ingest, master, ml, transform…). C'est la configuration `discovery.type=single-node` du `docker-compose.yml`.

**Pourquoi voyez-vous des index commençant par un point ?**

Ce sont des index système et cachés créés par Elasticsearch et Kibana pour leur propre fonctionnement : configuration et objets Kibana (`.kibana_*`), sessions et profils de sécurité (`.security-*`, `.kibana_security_session_*`), alertes (`.internal.alerts-*`), historique ILM (`.ds-ilm-history-*`)… Le point signale qu'ils ne contiennent pas de données utilisateur et ne doivent pas être modifiés à la main. Ils sont masqués par défaut : `expand_wildcards=all` force leur affichage.

## Exercice 1.2 — CRUD

**Comment évolue `_version` ?**

Elle augmente de 1 à chaque écriture sur le document `1`, lecture exclue :

| Requête | `result` | `_version` |
| --- | --- | --- |
| `PUT essai/_doc/1` | `created` | 1 |
| `GET essai/_doc/1` | (lecture) | 1 |
| `POST essai/_update/1` | `updated` | 2 |
| `DELETE essai/_doc/1` | `deleted` | 3 |

La suppression compte aussi comme une écriture. `_version` est propre à chaque document (le document créé par `POST essai/_doc` démarre à 1), alors que `_seq_no` est un compteur global de l'index (0, 1, 2, 3).

**Quel identifiant reçoit le document créé par `POST essai/_doc` ?**

Un `_id` généré automatiquement par Elasticsearch : une chaîne aléatoire de 20 caractères (par exemple `HJCh7KABpe9Qn1wsIloC`), différente à chaque exécution. Sans `_id` stable, relancer la requête crée un doublon.

**L'index `essai` existait-il avant le premier `PUT` ?**

Non (`HEAD essai` → 404). Elasticsearch l'a créé automatiquement à la première écriture, avec les réglages par défaut (1 shard, 1 réplique) et un mapping dynamique déduit du document. Comme il n'y a qu'un nœud, la réplique ne peut pas être allouée : la réponse indique `"_shards": {"total": 2, "successful": 1}` et le cluster passe en jaune tant que l'index existe.
