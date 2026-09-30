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

## Exercice 2.2

**Le nombre de documents a-t-il doublé ?**

Non. Après une relance sans `--reset`, l'index contient toujours 5000 documents : les 5000 offres ont été réécrites, pas ajoutées.

**Pourquoi fixer `_id` à partir du champ `id` est-il essentiel ?**

Chaque offre a toujours le même `_id` (`OFF-00001`, …). L'action `index` du bulk remplace alors le document existant au lieu d'en créer un nouveau : l'ingestion est idempotente, on peut la relancer (reprise après erreur, mise à jour des données) sans créer de doublons. Seul `_version` augmente.

**Que se passerait-il avec des identifiants générés par Elasticsearch ?**

Chaque exécution attribuerait un nouvel `_id` aléatoire à chaque offre (comme `POST essai/_doc` à l'exercice 1.2) : les 5000 offres seraient ajoutées en double, soit 10000 documents après la deuxième exécution, 15000 après la troisième, etc. Impossible alors de mettre à jour ou de retrouver une offre par son identifiant métier.

## Exercice 2.3

Sortie de `python ingest.py` avec l'offre `OFF-99999` contenant `"prime": 3000` :

```
Erreur : {'index': {'_index': 'offres', '_id': 'OFF-99999', 'status': 400, 'error': {'type': 'strict_dynamic_mapping_exception', 'reason': '[1:703] mapping set to strict, dynamic introduction of [prime] within [_doc] is not allowed'}}}
5000 documents indexés, 1 erreurs
5000 documents dans 'offres'
```

**Le lot entier est-il rejeté ou seulement ce document ?**

Seulement ce document. L'API `_bulk` renvoie un statut par opération : `OFF-99999` est refusé (400, `strict_dynamic_mapping_exception` à cause du champ `prime`), les 5000 autres offres du fichier sont indexées normalement.

**Quel est l'intérêt de `raise_on_error=False` pour un pipeline ?**

Le script ne s'arrête pas à la première erreur : les documents valides sont chargés, et les erreurs sont collectées puis affichées (identifiant, type, raison). Un document défectueux ne bloque pas toute l'ingestion, et on peut ensuite corriger ou rejouer uniquement les documents rejetés. Avec `raise_on_error=True` (valeur par défaut), `helpers.bulk` lèverait une exception `BulkIndexError` et le traitement s'interromprait.

## Exercice 3.1

**Quels mots disparaissent avec `french` ?**

Les mots vides (*stop words*) : `les`, `sur`, `des`. Ils sont trop fréquents pour aider à distinguer les documents.

**Que devient `l'analyse` ?**

`analys`. L'élision retire `l'`, puis la racinisation (*stemming*) réduit le mot à sa racine. Avec `standard`, `l'analyse` reste un seul token, apostrophe comprise : une recherche sur « analyse » ne le retrouverait pas.

**Analysez « donnée » puis « données » avec chaque analyseur : obtenez-vous le même terme ?**

- `standard` : non, `donnée` et `données` restent deux termes différents (seule la mise en minuscules est appliquée).
- `french` : oui, les deux donnent `done` (pluriel supprimé, accents retirés, racinisation).

**Qu'en déduisez-vous pour la recherche ?**

Avec l'analyseur `french`, une recherche sur « donnée » retrouve les documents contenant « données » (et inversement) : la recherche devient insensible au pluriel, au féminin, aux accents et aux conjugaisons. Il faut appliquer le même analyseur à l'indexation et à la recherche, sinon les tokens de la question ne correspondent pas à ceux de l'index. C'est pourquoi `titre`, `description` et `competences.texte` utilisent `french` dans le mapping de `offres`.

## Exercice 3.2

**Pourquoi les deux requêtes `term` renvoient-elles 0 résultat ?**

`term` cherche la valeur exacte, sans analyser la question.

- `ville` est un `keyword` : la valeur indexée est `Paris` avec une majuscule, telle quelle. `paris` ne correspond à aucun terme (la comparaison est sensible à la casse).
- `titre` est un `text` analysé par `french` : l'index ne contient pas la chaîne `Data Engineer Senior` mais des tokens séparés et normalisés (`data`, `engin`, `senio`). La phrase entière non analysée ne correspond à aucun d'eux.

**Corrections**

- `{ "term": { "ville": "Paris" } }` : 1492 offres.
- `{ "term": { "titre.brut": "Data Engineer Senior" } }` : 103 offres. Le sous-champ `brut` est un `keyword` qui stocke le titre complet tel quel.

**Relancez la première avec `"operator": "and"` : que change le nombre de résultats ?**

Il passe de 4190 à 393 résultats. Par défaut, `match` combine les tokens en OU : une offre contenant seulement « projets » suffit, et presque toutes les descriptions en parlent. Avec `and`, l'offre doit contenir les deux tokens (« projets » et « bancaires »), la recherche est donc beaucoup plus précise.

## Exercice 3.3

**Quel paramètre rattrape la faute ?**

`"fuzziness": "AUTO"`. Sans lui, « kubernetis » (token `kuberneti`) ne correspond à aucun terme de l'index (`kubernet` pour « Kubernetes ») : les 739 résultats viennent uniquement de « terraform ». Avec `fuzziness`, Elasticsearch accepte les termes à une distance d'édition près (1 à 2 caractères selon la longueur du mot) : `kuberneti` retrouve `kubernet`, et on passe à 969 résultats.

**Comment évolue l'ordre des résultats avec le poids sur `titre` ?**

Il ne change pas : mêmes documents, mêmes scores. Aucun titre ne contient « kubernetes » ni « terraform » (les titres sont de la forme métier + niveau, comme « Architecte Cloud Lead ») : le champ `titre` ne contribue pas au score, et le multiplier par 3 ne modifie rien. Le poids ne joue que si le terme recherché apparaît dans le champ pondéré (par exemple une recherche « architecte cloud » ferait remonter les offres dont le titre correspond).

## Exercice 3.4

**Comparez les `_score` avec et sans le bloc `should`.**

Les deux requêtes renvoient les mêmes 25 offres : `should` n'est pas obligatoire ici puisque `must` et `filter` sont présents, il ne filtre rien.

- Sans `should` : toutes les offres ont le même score (2.048).
- Avec `should` : les offres dont `competences` contient `Elasticsearch` passent à 4.014 et remontent en tête, les autres restent à 2.048.

`should` sert donc uniquement de bonus de pertinence.

**Pourquoi placer les critères exacts dans `filter` plutôt que dans `must` (deux raisons) ?**

1. Pas de calcul de score : un critère exact (contrat, ville, salaire) répond par oui ou non, il n'a pas à influencer la pertinence. Dans `must`, il ajouterait des points au score et fausserait le classement ; dans `filter`, seul le texte recherché détermine l'ordre.
2. Performance : sans score à calculer, le filtre est plus rapide, et son résultat est mis en cache par Elasticsearch, donc réutilisé directement pour les requêtes suivantes qui ont le même filtre.

## Exercice 3.6

**Pourquoi `from` + `size` est-il limité à 10 000 par défaut, et quelle API utiliser au-delà ?**

Pour renvoyer la page commençant à `from`, chaque shard doit trouver et trier ses `from + size` meilleurs résultats, puis le nœud coordinateur les fusionne et jette les `from` premiers. Le coût en mémoire et en CPU augmente donc avec la profondeur de la page : la limite `index.max_result_window` (10 000) protège le cluster contre ces requêtes coûteuses.

Au-delà, on utilise `search_after` avec un point in time (PIT) : on ouvre un PIT (`POST offres/_pit?keep_alive=1m`) qui fige une vue cohérente de l'index, on trie sur un critère stable, puis chaque page repart des valeurs de tri du dernier résultat de la page précédente (`search_after`). Chaque requête ne traite que `size` documents, quelle que soit la profondeur.
