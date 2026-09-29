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

## Exercice 1.2

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

## Exercice 1.3

**Quel type reçoit `salaire` ?**

`text`, avec un sous-champ `salaire.keyword` de type `keyword` (`ignore_above: 256`). Le premier document envoie `"45000"` entre guillemets : le mapping dynamique voit une chaîne et applique la règle par défaut des chaînes (`text` + `keyword`), sans regarder que le contenu est numérique. Même chose pour `actif` : `"true"` entre guillemets devient `text`, pas `boolean`.

**Et `publication` ?**

`date`. La détection de dates (`date_detection`, activée par défaut) reconnaît le format `2026-08-02` dans la chaîne.

**Pourquoi le document 2 est-il accepté ?**

Le mapping de `salaire` est déjà fixé à `text` par le document 1, et le type ne change plus. La valeur `52000` du document 2 est convertie en chaîne `"52000"` pour être indexée : Elasticsearch accepte le document sans erreur, alors que le type est incohérent entre les deux documents. `_source` garde la valeur d'origine (nombre), ce qui masque le problème à la lecture.

**Quelle conséquence pour un tri ou un filtre `salaire > 50000` ?**

Les comparaisons se font dans l'ordre lexicographique (caractère par caractère), pas numérique :

- un filtre `range` sur `salaire.keyword` `> "50000"` considérerait `"9000"` comme supérieur à `"50000"` (car `"9" > "5"`) ;
- un tri croissant rangerait `"9000"` après `"52000"` ;
- un tri directement sur `salaire` (`text`) échoue : un champ `text` n'est ni triable ni agrégeable (erreur `Fielddata is disabled`).

Impossible aussi de calculer une moyenne ou un histogramme de salaires. Pour corriger, il faut un mapping explicite (`integer`) et recréer l'index puis réindexer, d'où l'intérêt de déclarer le mapping avant d'ingérer les données.

## Exercice 1.4

**Quelle erreur obtenez-vous ?**

Code 400, `strict_dynamic_mapping_exception` :

```
"reason" : "[1:18] mapping set to strict, dynamic introduction of [champ_inconnu] within [_doc] is not allowed"
```

Avec `"dynamic": "strict"`, tout champ absent du mapping fait rejeter le document entier au lieu d'ajouter le champ au mapping.

**Pourquoi est-ce une bonne pratique en production ?**

- Le schéma reste maîtrisé : pas de type deviné de travers (cf. exercice 1.3, `salaire` en `text`) qu'on ne pourrait plus corriger sans recréer l'index.
- Les erreurs sont visibles immédiatement : une faute de frappe dans un nom de champ (`salaire_mx`) ou un changement de format côté producteur est rejeté à l'ingestion au lieu de polluer silencieusement l'index.
- Pas d'explosion du mapping : des clés imprévues (données utilisateur, JSON variable) ne créent pas des milliers de champs, qui consomment de la mémoire et dégradent le cluster.
