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

## Exercice 4.1

**Quelle ville a le salaire moyen le plus élevé ?**

Paris, avec un `salaire_min` moyen d'environ 57 442 € (suivie de Grenoble, ~53 046 €). C'est cohérent avec le jeu de données, où les salaires parisiens sont majorés de 6 000 €.

**Sur combien d'offres la moyenne est-elle réellement calculée ?**

`avg` ignore les documents où le champ est absent : seules les offres en CDI et CDD ont un `salaire_min`, soit 3389 offres sur 5000 (les 1611 alternances, stages et freelances sont exclues). Par ville, la moyenne porte donc sur moins d'offres que le `doc_count` affiché : pour Paris, 994 offres sur 1492.

**Remplacez `ville` par `titre` : quelle erreur, et comment la corriger ?**

Erreur 400 `illegal_argument_exception` :

```
Fielddata is disabled on [titre] in [offres]. Text fields are not optimised for operations that require per-document field data like aggregations and sorting, so these operations are disabled by default. Please use a keyword field instead.
```

`titre` est un champ `text` : il est découpé en tokens, on ne peut pas regrouper sur la valeur complète. La correction consiste à agréger sur le sous-champ `keyword` `titre.brut`, prévu pour ça dans le mapping.

## Exercice 4.4

Pour les 462 offres dont le titre contient « Data Engineer » :

- les 5 compétences les plus demandées sont Airflow (315), Spark (313), Kafka (312), Python (311) et SQL (301) ;
- le télétravail le plus fréquent est partiel (284 offres).

**L'agrégation porte-t-elle sur tout l'index ou seulement sur les résultats de la requête ?**

Seulement sur les résultats de la requête : les agrégations sont calculées sur les documents sélectionnés par `query`, ici les 462 offres « Data Engineer », et non sur les 5000 offres de l'index.

# TP2 — Logstash

## Mise en place

**Pourquoi ne pas utiliser le compte `elastic` pour Logstash ?**

`elastic` est superutilisateur : il peut tout lire, supprimer n'importe quel index et gérer la sécurité. Principe du moindre privilège : si le mot de passe de Logstash fuite, ou si un pipeline est mal écrit, les dégâts doivent être limités. `logstash_internal` peut seulement écrire dans `offres` et `logs-web-*` et gérer les modèles d'index. Même une lecture lui est refusée (`GET offres/_search` → 403).

**Que se passerait-il si le pipeline `web` tentait d'écrire dans `logs-generic-default` ?**

La requête serait refusée (403 `security_exception`, action non autorisée) : le rôle `logstash_writer` ne couvre que `offres` et `logs-web-*`. Logstash considère une 403 comme une erreur non réessayable : les événements sont perdus, ou mis en *dead letter queue* si elle est activée.

**Pourquoi le mot de passe est-il transmis par variable d'environnement plutôt qu'écrit dans les `.conf` ?**

Les `.conf` sont versionnés dans le dépôt, alors que `.env` est ignoré par git : le secret reste hors de l'historique. `docker-compose.override.yml` passe `LOGSTASH_INTERNAL_PASSWORD` au conteneur (`ES_PASSWORD`), et le pipeline le lit avec `${ES_PASSWORD}`. Le même pipeline fonctionne alors dans tous les environnements, et changer le mot de passe ne demande aucune modification du code.

## Exercice 0

**Quels champs Logstash a-t-il ajoutés à votre phrase ?**

À partir de la seule ligne tapée, rangée dans `message`, Logstash ajoute :

- `@timestamp` : date de l'événement ;
- `@version` : version du format d'événement (`"1"`) ;
- `event.original` : copie de la ligne brute, format ECS ;
- `host.hostname` : nom de la machine qui a produit l'événement, ici l'identifiant du conteneur éphémère.

Avec le filtre `mutate { uppercase => ["message"] }`, seul `message` passe en majuscules. `event.original` garde le texte d'origine.

**Que contient `@timestamp` : l'heure de quoi ?**

L'heure (UTC) à laquelle Logstash a reçu l'événement, pas l'heure où le fait s'est produit. Pour des logs, il faudra la remplacer par la date écrite dans la ligne (filtre `date`, partie 3). Sinon, rejouer un fichier de logs de la semaine passée daterait tous les événements du jour de l'ingestion.

**À quoi sert l'option `--path.data /tmp/essai` ?**

Le dossier de données contient l'état de Logstash : identifiant de nœud, files persistantes, *dead letter queue*, *sincedb*. Il est protégé par un verrou : deux instances ne peuvent pas partager le même dossier. Le Logstash éphémère utilise donc un dossier à part. Il peut ainsi tourner à côté du service `logstash`, qui utilise le volume `lsdata`, sans conflit de verrou et sans modifier son état.

## Exercice 1.1

Le kit fourni contenait déjà `offres.conf` complété (aucun `TODO`) :

- entrée `file` en mode `read`, codec `json`, `sincedb_path => "/dev/null"` et `file_completed_action => "log"` pour ne pas supprimer le fichier source ;
- sortie `elasticsearch` vers `offres` avec `document_id => "%{id}"`, `data_stream => "false"` et `manage_template => false`.

Syntaxe vérifiée : `Config Validation Result: OK`. Pour l'exercice 1.2, le bloc `filter` (TODO 6) a été retiré temporairement.

## Exercice 1.2

Avant lancement : `OFF-00002` a `_version` 3.

**Les documents sont-ils indexés ?**

Non : aucun des 5 000 documents. Le journal affiche 5 000 `Could not index event to Elasticsearch`, et `_version` de `OFF-00002` reste à 3. `_count` vaut toujours 5000 : ce sont les documents d'`ingest.py`, jamais écrasés.

**Quelle erreur, quel code HTTP, quel type d'exception ?**

```
status: 400, "error" => {"type" => "strict_dynamic_mapping_exception",
"reason" => "[1:558] mapping set to strict, dynamic introduction of [log] within [_doc] is not allowed"}
```

**Quels noms de champs sont cités ?**

Seulement `log`, dans les 5 000 erreurs. Elasticsearch s'arrête au premier champ inconnu rencontré dans le document, mais `@timestamp`, `@version` et `event` (`event.original`) ajoutés par Logstash seraient refusés de la même façon.

**Lien avec `"dynamic": "strict"`**

Le mapping strict de l'exercice 1.4 du TP1 refuse tout document qui contient un champ absent du mapping, au lieu de l'ajouter automatiquement. Logstash ajoute aux données métier ses propres champs ECS (`@timestamp`, `@version`, `event.original`, `log.file.path`), qui ne figurent pas dans le mapping : tout le document est rejeté.

## Exercice 1.3

Filtre ajouté :

```
filter {
  mutate { remove_field => ["@timestamp", "@version", "event", "log", "host"] }
}
```

Après redémarrage : aucune erreur, l'API de supervision indique 5 000 événements lus, 5 000 envoyés, 40 requêtes bulk en 200.

**Le nombre de documents a-t-il changé ? Et le `_version` de `OFF-00002` ?**

`_count` reste à 5000, mais `_version` passe de 3 à 4.

**Pourquoi ?**

`document_id => "%{id}"` donne à chaque événement le même `_id` que celui utilisé par `ingest.py` (`OFF-00002`…). L'action `index` sur un `_id` existant **remplace** le document au lieu d'en créer un nouveau : pas de doublon, mais une nouvelle version.

**Pourquoi supprimer ces champs plutôt qu'assouplir le mapping ?**

Ces champs décrivent le transport (fichier lu, heure de lecture, ligne brute), pas l'offre d'emploi. Les garder alourdirait chaque document (`event.original` duplique toute la ligne JSON) et mélangerait technique et métier. Passer en `dynamic: true` ou `false` retirerait aussi la protection du mapping strict : une faute de frappe dans un champ, ou un champ inattendu, serait accepté sans erreur. Le contrat de l'index reste le mapping ; c'est au pipeline de s'y conformer.

**Pourquoi l'index `offres` doit-il exister avant le premier démarrage de Logstash ?**

Avec `manage_template => false`, Logstash n'installe aucun modèle d'index. Si `offres` n'existait pas, la première écriture le créerait automatiquement avec un **mapping dynamique** (le rôle `logstash_writer` a `create_index`) : `ville` et `contrat` en `text` + `keyword`, `localisation` en simple objet au lieu de `geo_point`, pas d'analyseur français, et les champs Logstash acceptés. Les requêtes `term`, `geo_distance` et les agrégations du TP1 ne marcheraient plus, et un mapping ne peut pas être corrigé après coup sans réindexer.

## Exercice 1.4

Après un nouveau redémarrage : `_count` = 5000, `_version` de `OFF-00002` = 5.

**Combien de fois le fichier a-t-il été lu ?**

À chaque démarrage du pipeline, soit 3 fois ici : le lancement en erreur, puis les deux redémarrages. `offres_lus.log` (dans le volume `lsdata`) contient trois lignes `/data/offres.ndjson`. `_version` 5 = 3 (TP1) + 2 lectures réussies.

**Que se passerait-il avec la sincedb par défaut au lieu de `/dev/null` ?**

La sincedb enregistrerait, dans le volume `lsdata`, que le fichier a été lu jusqu'au bout. Au redémarrage, Logstash reprendrait à cette position : rien ne serait relu et `_version` resterait à 4. Seules des lignes ajoutées au fichier seraient traitées. C'est le comportement voulu en production, pour ne pas retraiter des données déjà envoyées.

**Et si `document_id` n'était pas renseigné ?**

Elasticsearch générerait un `_id` aléatoire pour chaque événement, comme `POST essai/_doc` au TP1. Chaque lecture ajouterait 5 000 nouveaux documents : 10 000 puis 15 000 après les redémarrages, avec des offres en double dans les recherches et les agrégations. L'ingestion ne serait plus idempotente.

## Exercice 2.1

**Combien de pipelines sont chargés, avec combien de workers ?**

Deux pipelines, `offres` et `web` (`GET _node/pipelines`), avec 32 workers chacun et des lots de 125 événements. 32 est la valeur par défaut de `pipeline.workers` : le nombre de cœurs CPU vus par le conteneur.

**Que valent `in`, `filtered` et `out` pour `offres`, et que représentent-ils ?**

`in` = 5000, `filtered` = 5000, `out` = 5000. Ce sont les événements reçus par la file depuis l'entrée, ceux passés par les filtres, puis ceux transmis aux sorties. Les compteurs sont en mémoire et repartent de zéro à chaque démarrage de Logstash. Ils correspondent donc à la dernière lecture complète de `offres.ndjson`. Des valeurs égales indiquent qu'aucun événement n'est bloqué ni écarté.

**Quel plugin consomme le plus de temps ?**

La sortie `elasticsearch` : 19 495 ms, contre 2 465 ms pour le filtre `mutate` et 116 ms passées par l'entrée `file` à remplir la file. Ce temps, cumulé sur tous les workers, correspond surtout à l'attente des réponses `_bulk` d'Elasticsearch (réseau et indexation). C'est le goulot d'étranglement habituel d'un pipeline d'ingestion.

## Exercice 2.2

Le kit ne correspondait pas à l'énoncé : il n'y avait pas de ligne `DEAD_LETTER_QUEUE_ENABLE` à décommenter, et l'entrée lisait seulement `/data/offres.ndjson`. Ajouts faits : `DEAD_LETTER_QUEUE_ENABLE=true` dans `docker-compose.override.yml` et `path => "/data/offres*.ndjson"` dans `offres.conf`.

**Le document `OFF-99999` est-il dans l'index ? Où se trouve-t-il ?**

Non : `GET offres/_doc/OFF-99999` renvoie `"found": false` et `_count` reste à 5000. Il est dans la dead letter queue du pipeline `offres`, sur le disque du conteneur (volume `lsdata`), dans `/usr/share/logstash/data/dead_letter_queue/offres/1.log`. La supervision le confirme : 5001 événements `out`, mais `documents.successes` = 5000, `dlq_routed` = 1 et `bulk_requests.with_errors` = 1.

**Quelle raison de refus est enregistrée dans `[@metadata][dead_letter_queue]` ?**

```
"reason" => "Could not index event to Elasticsearch. status: 400, action: [\"index\", {_id: \"OFF-99999\", _index: \"offres\", ...}]
  ... "error" => {"type" => "strict_dynamic_mapping_exception",
  "reason" => "[1:45] mapping set to strict, dynamic introduction of [prime] within [_doc] is not allowed"}
```

`[@metadata][dead_letter_queue]` indique aussi le plugin qui a refusé le document (`plugin_type: elasticsearch`, `plugin_id`) et l'heure d'entrée en DLQ (`entry_time`). `[@metadata][path]` donne le fichier source, `/data/offres_test.ndjson`.

**Qu'apporte la DLQ par rapport à `raise_on_error=False` dans `ingest.py` ?**

Avec `raise_on_error=False`, le script continue malgré l'erreur et l'affiche, mais le document refusé n'est conservé nulle part une fois le script terminé. La DLQ conserve le document complet sur disque, avec la raison du refus et son origine, même après un redémarrage. On peut l'inspecter plus tard, compter les rejets dans la supervision et rejouer les documents avec l'entrée `dead_letter_queue`, sans relire tout le fichier source.

**Comment corriger et réinjecter ce document, en trois étapes ?**

1. Analyser : relire la DLQ (entrée `dead_letter_queue`, `pipeline_id => "offres"`) pour lire la raison du refus, ici le champ `prime` inconnu du mapping.
2. Corriger : écrire un pipeline de reprise qui lit la DLQ et retire le champ fautif (`mutate { remove_field => ["prime"] }`), en plus des champs Logstash, ou ajouter `prime` au mapping si c'est une vraie donnée métier. Ajouter un champ est possible sans réindexer.
3. Réinjecter : envoyer le résultat vers `offres` avec la même sortie (`document_id => "%{id}"`) et `commit_offsets => true`, pour que les documents traités ne soient pas relus. Vérifier ensuite avec `GET offres/_doc/OFF-99999`.

`data/offres_test.ndjson` a été supprimé ensuite.

## Exercice 2.3

**Sans `pipelines.yml`, combien de pipelines Logstash chargerait-il ?**

Un seul, `main` : l'image Docker charge tous les fichiers de `/usr/share/logstash/pipeline/` et concatène `offres.conf` et `web.conf` en une seule configuration.

**Que deviendrait une offre lue dans `offres.ndjson` ? Et une ligne de log d'accès ?**

Dans un pipeline unique, les entrées, les filtres et les sorties sont mis en commun : chaque événement passe par tous les filtres et part vers toutes les sorties.

- Une offre serait envoyée vers l'index `offres` et vers le data stream `logs-web-default`. Elle passerait aussi par les filtres de `web.conf`, qui ne s'appliquent pas à elle : `grok` échouerait et ajouterait le tag `_grokparsefailure`. Ce champ `tags` est inconnu du mapping strict, donc l'index `offres` la refuserait. Les journaux web, eux, seraient pollués par des offres d'emploi.
- Une ligne de log irait bien dans `logs-web-default`, mais aussi vers `offres`. Elle n'a pas de champ `id`, donc `_id` vaudrait littéralement `%{id}`, et le mapping strict la refuserait (`source`, `http`, `url`…). Cela ferait 20 700 erreurs dans le journal, ou 20 700 documents en DLQ. Elle passerait aussi par le `mutate` de `offres.conf`, appliqué en premier car les fichiers sont concaténés par ordre alphabétique.

**Deux autres avantages à isoler les pipelines**

- **Supervision et dépannage séparés** : compteurs `in`/`out`, DLQ et journaux par pipeline (`[offres]`, `[web]`). On voit immédiatement quel flux pose problème.
- **Indépendance** : un pipeline bloqué (Elasticsearch qui refuse, file pleine) ne freine pas l'autre, chacun a ses workers et sa file. Chacun peut aussi être réglé (`pipeline.workers`, `queue.type: persisted`…) et rechargé séparément.

## Exercice 2.4

**Avec la file en mémoire, que deviennent les événements lus mais pas encore envoyés ?**

Ils sont perdus. La file en mémoire disparaît avec le processus quand `docker kill` l'arrête brutalement, sans laisser Logstash vider sa file. Avec `sincedb_path => "/dev/null"`, tout le fichier serait relu au redémarrage. Mais avec une sincedb réelle, la position pourrait déjà être enregistrée au-delà de ces événements, qui ne seraient jamais indexés.

**Quel réglage change ce comportement, et quelle garantie obtient-on ?**

`queue.type: persisted`, dans `pipelines.yml` pour un pipeline donné ou dans `logstash.yml`. La file est écrite sur disque, dans le volume `lsdata`. Un événement n'en sort qu'une fois envoyé avec succès (accusé de réception d'Elasticsearch). Au redémarrage, les événements encore en file sont rejoués : c'est la garantie « au moins une fois » (*at-least-once*).

**Pourquoi le `document_id` devient-il alors indispensable ?**

« Au moins une fois » signifie qu'un événement peut être envoyé deux fois : s'il a été indexé juste avant l'arrêt, mais pas encore retiré de la file, il sera renvoyé au redémarrage. Avec `document_id => "%{id}"`, ce renvoi remplace le même document (`_version` + 1) au lieu de créer un doublon. Sans `_id` métier, chaque rejeu ajouterait une copie de l'offre.

## Exercice 3.1

`data/access.log` : 20 700 lignes. La première est identique à l'exemple de l'énoncé.

Sous Windows, `generate_access_logs.py` écrit le fichier avec des fins de ligne CRLF : `Path.write_text` traduit `\n` en `\r\n`. `grok` reconnaissait quand même les lignes, car `COMBINEDAPACHELOG` n'est pas ancré en fin de ligne, mais chaque `message` indexé se terminait par un `\r` parasite. Le fichier a été converti en LF (`sed -i 's/\r$//' data/access.log`) et le data stream recréé. Le générateur n'a pas été modifié, pour que le jeu de données reste identique pour tous.

## Exercice 3.2

Test dans Kibana, Dev Tools puis Grok Debugger : première ligne de `access.log` en *Sample Data*, `%{COMBINEDAPACHELOG}` en *Grok Pattern*, puis *Simulate*.

**Quels champs sont extraits ?**

```json
{
  "clientip": "203.0.113.123", "ident": "-", "auth": "-",
  "timestamp": "23/Sep/2026:00:00:39 +0200",
  "verb": "GET", "request": "/offres/OFF-01468", "httpversion": "1.1",
  "response": "200", "bytes": "43686",
  "referrer": "\"https://jobs.example.org/recherche\"",
  "agent": "\"Mozilla/5.0 (Linux; Android 15; Pixel 9) ... Mobile Safari/537.36\""
}
```

Le Grok Debugger utilise les anciens noms (sans ECS) : `clientip`, `verb`, `request`, `response`… Les guillemets restent dans `referrer` et `agent`. Logstash 9 travaille en mode ECS par défaut : dans le pipeline, le même motif produit les noms ECS du tableau de l'énoncé (`source.address`, `http.request.method`, `url.original`, `http.response.status_code`, `http.response.body.bytes`, `http.request.referrer`, `user_agent.original`), sans guillemets. On le vérifie sur les documents indexés (exercice 3.4).

**Sous quel type apparaît `http.response.status_code` ?**

Dans le Grok Debugger, le code (`response`) apparaît comme une chaîne : `"200"`, entre guillemets, tout comme `bytes`. Par défaut, grok capture du texte. En mode ECS, le motif utilisé par Logstash convertit ces deux captures en entier (`%{INT:[http][response][status_code]:int}`) : dans les documents indexés, `http.response.status_code` vaut `200`, sans guillemets.

**Pourquoi `timestamp` doit-il encore être traité ?**

`grok` ne fait que découper le texte : `timestamp` est la chaîne `23/Sep/2026:00:00:39 +0200`, pas une date. `@timestamp` reste l'heure de lecture par Logstash. Il faut le filtre `date` pour analyser cette chaîne (mois en anglais, fuseau `+0200`) et la placer dans `@timestamp`. Sinon, les 7 jours de trafic seraient tous datés de la minute d'ingestion, et aucune analyse dans le temps ne serait possible.

**Motif extrayant `OFF-01468` de `/offres/OFF-01468/postuler`**

Testé dans le Grok Debugger, avec *Sample Data* `/offres/OFF-01468/postuler`, *Grok Pattern* `^/offres/%{OFFRE_ID:offre_id}` et le motif personnalisé (*Custom Patterns*) :

```
OFFRE_ID OFF-[0-9]{5}
```

Résultat : `{ "offre_id": "OFF-01468" }`. Grâce à l'ancre `^`, une URL hors `/offres/` (`/recherche?q=OFF-01468`) n'est pas reconnue. Dans `web.conf`, le même motif est déclaré avec `pattern_definitions` et écrit dans `[labels][offre_id]`.

## Exercice 3.3

Comme `offres.conf`, `web.conf` était fourni complet dans le kit (aucun `TODO`). Syntaxe validée (`Config Validation Result: OK`). Le pipeline :

1. lit `/data/access.log` en mode `read` ;
2. découpe chaque ligne avec `grok` et `%{COMBINEDAPACHELOG}` ;
3. date l'événement avec `date` (`dd/MMM/yyyy:HH:mm:ss Z`, `locale => "en"`), puis supprime `timestamp` ;
4. décompose le navigateur avec `useragent` (`user_agent.name`, `user_agent.os.*`, `user_agent.device.name`) ;
5. extrait l'identifiant d'offre dans `labels.offre_id`, seulement pour les URL `/offres/OFF-…` ;
6. retire `event.original` si `grok` a réussi (doublon de `message`) et écrit dans le data stream `logs-web-default` (`data_stream_type/dataset/namespace`).

Supervision : 20 700 événements en entrée et en sortie, `grok` principal à 20 700 correspondances et 0 échec, 8 511 URL d'offres reconnues, 166 requêtes bulk en 200.

## Exercice 3.4

**Combien de documents et combien d'échecs de `grok` ?**

20 700 documents et 0 `_grokparsefailure`.

**Nom de l'index caché et signification**

`.ds-logs-web-default-2026.10.01-000001` :

- `.ds-` : index caché de data stream (*backing index*), on n'écrit jamais dedans directement ;
- `logs-web-default` : nom du data stream, soit `<type>-<dataset>-<namespace>` ;
- `2026.10.01` : date de création de l'index, et non date des événements (23–29/09) ;
- `000001` : génération, incrémentée à chaque *rollover*. La politique ILM `logs` crée régulièrement un nouvel index, et seul le plus récent reçoit les écritures.

**Le premier événement est-il bien daté ?**

Oui : `@timestamp` = `2026-09-22T22:00:39.000Z`, soit le 23/09/2026 à 00:00:39 en +02:00. Elasticsearch stocke les dates en UTC ; le fuseau `+0200` de la ligne a été pris en compte par le filtre `date`.

**Quel type a reçu `http.response.status_code`, et pourquoi est-ce important ?**

`long` : un type numérique, fourni par les mappings ECS du modèle `logs`. On peut ainsi faire des requêtes d'intervalle (`range` `gte: 500` pour toutes les erreurs serveur, `http.response.status_code >= 400` en KQL ou ES|QL) et des agrégations numériques (histogrammes, statistiques). En `keyword`, `"500" > "40"` serait une comparaison de texte, et un intervalle de codes ne voudrait rien dire. C'est indispensable pour l'enquête sur l'incident en partie 4.

**Quel `index.mode` est utilisé ?**

`logsdb` : mode de stockage optimisé pour les logs, activé par défaut depuis la 9.0 pour `logs-*-*`. Le tri de l'index par hôte et par date, la compression et le `_source` synthétique réduisent fortement l'espace disque.

## Exercice 3.5

**Que constatez-vous ?**

Après un simple redémarrage de Logstash, `_count` passe de 20 700 à 41 400 : tout le fichier a été relu (`sincedb_path => "/dev/null"`) et chaque ligne indexée une deuxième fois. La première ligne existe en deux exemplaires, avec deux `_id` aléatoires différents (`AaD2ZPQcaUoQCZSEi1zN`, `AaD2ZPQcaUoQCZT32760`).

**Pourquoi le problème ne se posait-il pas pour `offres` ?**

`offres.conf` fixe `document_id => "%{id}"` et utilise l'action `index` : relire une offre remplace le document qui a le même `_id` (`_version` + 1). `web.conf` ne fixe aucun `_id` : Elasticsearch en génère un nouveau à chaque écriture.

**Peut-on mettre à jour ou remplacer un document dans un data stream ?**

Pas par écriture classique : un data stream est en ajout seul et n'accepte que `op_type: create`. Un `PUT logs-web-default/_doc/<id>` ou un `POST` en `index` est refusé (`only write ops with an op_type of create are allowed in data streams`). Une écriture en `create` avec un `_id` déjà présent est refusée (409). On peut seulement passer par `_update_by_query` ou `_delete_by_query`, ou viser directement l'index caché (`.ds-…`) avec ses `_seq_no` / `_primary_term`. C'est réservé aux corrections exceptionnelles.

**Deux solutions pour rejouer le fichier sans doublon**

1. Garder une vraie sincedb : supprimer `sincedb_path => "/dev/null"`. La position de lecture est alors enregistrée dans `/usr/share/logstash/data`, sur le volume `lsdata`, et un redémarrage ne relit pas un fichier déjà traité. Cette solution évite la relecture, mais ne protège pas d'un vrai rejeu : sincedb supprimée, fichier recopié (nouvel inode), ou rejeu volontaire après correction du pipeline.
2. Un `_id` déterministe calculé à partir de la ligne, avec le filtre `fingerprint` :

   ```
   fingerprint {
     source => "message"
     method => "SHA256"
     target => "[@metadata][fingerprint]"
   }
   ```

   et `document_id => "%{[@metadata][fingerprint]}"` dans la sortie. La même ligne produit toujours le même `_id`. Au rejeu, l'écriture en `create` d'un `_id` existant est refusée en 409, que Logstash ignore : l'ingestion devient idempotente. Le hachage étant dans `@metadata`, il n'est pas stocké dans le document. Limite : deux lignes réellement identiques (même IP, même seconde, même requête) n'en feraient qu'une.

L'état propre a ensuite été restauré (Logstash arrêté, `DELETE _data_stream/logs-web-default`, redémarrage) : 20 700 documents.

## Partie 4

## Exercice 4.1

Répartition par code HTTP (20 700 requêtes)

| Code | Requêtes | Part |
| --- | --- | --- |
| 200 | 17 805 | 86,0 % |
| 201 | 1 492 | 7,2 % |
| 404 | 508 | 2,5 % |
| 304 | 488 | 2,4 % |
| 503 | 402 | 1,9 % |
| 500 | 5 | 0,02 % |

**Par méthode** : `GET` 19 208 (92,8 %), `POST` 1 492 (7,2 %). Les 1 492 `POST` correspondent exactement aux 1 492 réponses 201 : ce sont les candidatures (`POST /offres/OFF-…/postuler`).

**Volume moyen par jour** : 20 700 requêtes sur 7 jours, soit ≈ 2 957 requêtes par jour. Le trafic est régulier : de 2 832 (23/09) à 3 274 (28/09, gonflé par l'incident). Le découpage est fait par jour en heure de Paris : en UTC, le premier « jour » ne contient que 233 requêtes, celles du 23/09 entre 00:00 et 02:00.

## Exercice 4.2

**1. Jour et créneau**

- Pas d'une heure : les erreurs 5xx sont quasi toutes concentrées sur une seule heure, le lundi 28/09/2026 de 14:00 à 15:00 (402 erreurs ; au plus 1 par heure ailleurs).
- Pas de 5 minutes : 35 à 53 erreurs dans chaque tranche de 14:00 à 14:45, puis plus aucune.
- Première erreur à 14:00:08, dernière à 14:44:56.

**2. URL touchées, et celles qui ne l'ont pas été**

Seule l'API est touchée, et presque uniquement sa première page : `/api/offres?ville=<ville>&page=1`, pour les 7 villes (Bordeaux 71, Lyon 67, Lille 61, Paris 54, Nantes 53, Montpellier 48, Toulouse 46), plus 2 requêtes sur d'autres pages. Les 400 requêtes `page=1` du créneau ont toutes échoué.

Pendant ces 45 minutes, tout le reste a répondu normalement : accueil (12 × 200), recherche (17 × 200), pages d'offres (31 × 200), candidatures (7 × 201), fichiers statiques (200/304). Le site restait utilisable ; seule l'API de listing des offres était en panne.

**3. Nombre d'erreurs et durée**

402 réponses 503 (*Service Unavailable*), toutes entre 14:00:08 et 14:44:56 : environ 45 minutes. Le code 503 indique un service indisponible ou surchargé, et non un bug applicatif. Les 5 erreurs 500 de la semaine sont isolées, à d'autres dates, sans lien avec l'incident.

**4. Comportement des clients**

Le volume sur les URL touchées a explosé : 403 requêtes API sur 14:00–14:45, contre 4 à 15 sur le même créneau les autres jours, soit environ 40 fois plus. Les requêtes `page=1`, d'ordinaire 0 à 6, passent à 400.

| Créneau 14:00–14:45 | 23/09 | 24/09 | 25/09 | 26/09 | 27/09 | 28/09 | 29/09 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Requêtes API | 11 | 5 | 11 | 15 | 4 | 403 | 9 |

Ce volume vient de 308 adresses IP différentes (1 à 4 erreurs chacune), avec tous les navigateurs habituels répartis à parts égales (Safari, Mobile Safari, Chrome Mobile, Firefox, Chrome), et sans `referrer` (appels directs à l'API). Ce n'est donc ni un client isolé ni une attaque.

Explication proposée : la hausse commence à la première erreur et s'arrête avec la dernière, sans montée en charge avant 14:00. Elle est donc une conséquence de la panne, pas sa cause. Quand l'API renvoie 503, les clients réessaient : l'application (le front-end ou l'app mobile qui appelle `/api/offres`) relance la requête automatiquement, et les utilisateurs rechargent la page. Ces réessais multiplient la charge sur un service déjà indisponible, ce qui peut prolonger la panne. D'où l'intérêt côté client d'un backoff exponentiel et du respect de l'en-tête `Retry-After`.

## Exercice 4.3

**1. Adresse IP**

`203.0.113.66` : 300 réponses 404, contre 3 au maximum pour toute autre adresse.

**2. Moment et durée**

Le samedi 26/09/2026 de 03:12:00 à 03:16:59 (heure de Paris), soit 5 minutes pile, à 60 requêtes par minute, une par seconde. C'est un rythme régulier de machine, en pleine nuit.

**3. URL demandées : que cherchait ce robot ?**

Six chemins, demandés en boucle (43 à 59 fois chacun) :

| URL | Ce que cherche le robot |
| --- | --- |
| `/admin` | une interface d'administration |
| `/.git/config` | un dépôt Git exposé (code source, identifiants de dépôt) |
| `/.env` | un fichier de secrets (mots de passe, clés d'API) |
| `/phpmyadmin/` | une console d'administration MySQL |
| `/server-status` | la page d'état d'Apache (requêtes en cours, IP des clients) |
| `/wp-login.php` | la page de connexion WordPress (attaque par force brute) |

C'est un scanner de vulnérabilités : il ne cherche pas les offres, mais des fichiers sensibles oubliés et des interfaces d'administration mal protégées, typiques de PHP, WordPress et Apache. Toutes les réponses sont des 404 : rien n'est exposé.

**4. `user_agent.original` : comment le distinguer d'un navigateur ?**

`Mozilla/5.0 zgrab/0.x`. Le préfixe `Mozilla/5.0` imite un navigateur, mais il manque tout ce qu'envoie un vrai navigateur : système d'exploitation, moteur de rendu (`AppleWebKit`, `Gecko`), nom et version du navigateur. `zgrab` est un outil de scan réseau connu. Le filtre `useragent` ne le reconnaît pas : `user_agent.name` et `user_agent.os.name` valent `Other`. Le comportement trahit aussi le robot : rythme d'une requête par seconde, URL qui n'existent pas sur le site, aucun `referrer`, en pleine nuit.

L'adresse `203.0.113.66` apparaît aussi 27 fois avec des navigateurs normaux (consultations, candidatures), réparties sur la semaine. Une même adresse peut être partagée (NAT, box, réseau d'entreprise) : il vaut mieux filtrer sur le user agent et le créneau que bloquer l'IP sans précaution.

**D'où viennent les autres 404, et sont-elles inquiétantes ?**

Les 208 autres 404 sont toutes sur des pages d'offres (`/offres/OFF-09003` à `/offres/OFF-09993`). Elles viennent de 172 adresses et de navigateurs normaux, sont réparties sur toute la semaine, et ont toutes pour `referrer` `https://jobs.example.org/recherche`. Or l'index `offres` ne contient que `OFF-00001` à `OFF-05000` : ce sont des offres qui n'existent plus, expirées ou retirées, mais encore proposées par la page de recherche.

Elles ne sont pas inquiétantes pour la sécurité. C'est en revanche un défaut fonctionnel à signaler : la recherche renvoie des liens morts, ce qui dégrade l'expérience (environ 30 par jour). Il faudrait retirer ces offres de l'index de recherche, ou renvoyer un 410 Gone avec une page proposant des offres similaires.

## Exercice 4.4

Classement des consultations (`GET`, code 200, `labels.offre_id` présent) :

| Rang | Offre | Vues | Titre | Ville | Contrat |
| --- | --- | --- | --- | --- | --- |
| 1 | OFF-04662 | 8 | Développeur Front-end Senior | Bordeaux | Freelance |
| 2 | OFF-01153 | 7 | Développeur Java Confirmé | Toulouse | Freelance |
| 2 | OFF-03141 | 7 | Développeur Python Confirmé | Bordeaux | CDI |
| 4 | OFF-00289 | 6 | Data Scientist Lead | Lyon | CDI |
| 4 | OFF-00901 | 6 | Développeur Java Junior | Paris | CDI |
| 4 | OFF-01275 | 6 | Administrateur Bases de Données Lead | Paris | CDI |
| 4 | OFF-01660 | 6 | Architecte Cloud Senior | Lyon | CDI |
| 4 | OFF-02899 | 6 | Data Engineer (Alternance) | Lyon | Alternance |
| 4 | OFF-03126 | 6 | Administrateur Bases de Données Junior | Lyon | CDI |
| 4 | OFF-03145 | 6 | Data Engineer Lead | Montpellier | CDI |
| 4 | OFF-03524 | 6 | Développeur Python (Alternance) | Toulouse | Alternance |
| 4 | OFF-03923 | 6 | Architecte Cloud Confirmé | Lyon | CDI |

Seules les 3 premières places sont nettes : 9 offres sont ex æquo à 6 vues pour les places 4 à 10. Un « top 10 » strict dépendrait d'un critère arbitraire (ici l'ordre des identifiants), donc les 12 sont listées. Les écarts sont faibles : 8 vues au maximum sur une semaine, et 50 offres sont à 5 vues. Aucune offre ne se détache vraiment du lot.

Titre, ville et contrat ont été obtenus en une seule requête Dev Tools sur `offres`, avec une requête `ids` sur les 12 identifiants (voir `requetes/enquete.txt`). Les `labels.offre_id` des logs sont exactement les `_id` de l'index, grâce au `document_id => "%{id}"` de la partie 1.

## Exercice 4.5

**Part du trafic mobile**

| `user_agent.os.name` | Requêtes | Part |
| --- | --- | --- |
| Mac OS X | 4 150 | 20,0 % |
| iOS | 4 099 | 19,8 % |
| Windows | 4 058 | 19,6 % |
| Android | 4 056 | 19,6 % |
| Linux | 4 037 | 19,5 % |
| Other (robot `zgrab`) | 300 | 1,4 % |

Les mobiles (iOS + Android) représentent 8 155 requêtes, soit 39,4 % du trafic, ou 40,0 % du trafic humain si l'on retire les 300 requêtes du robot.

**Les trois navigateurs les plus utilisés** (`user_agent.name`)

1. **Safari** : 4 150 (20,0 %)
2. **Mobile Safari** : 4 099 (19,8 %)
3. **Chrome** : 4 058 (19,6 %)

Suivent Chrome Mobile (4 056) et Firefox (4 037) : les cinq navigateurs sont presque à égalité (un écart de 113 requêtes), et le classement n'est pas vraiment significatif. Chaque système n'a d'ailleurs qu'un navigateur dans ces logs (Safari sur Mac, Mobile Safari sur iOS, Chrome sur Windows, Chrome Mobile sur Android, Firefox sur Linux). En regroupant par famille, Safari (8 249) et Chrome (8 114) dominent, devant Firefox (4 037).

## Partie 5 — Tableau de bord

Tableau de bord « Site de recrutement — trafic », période enregistrée du 23/09/2026 00:00 au 30/09/2026 00:00 (heure de Paris). Capture : `captures/tableau-de-bord.png`.

| Panneau | Type | Contenu | Valeur sur la semaine |
| --- | --- | --- | --- |
| Requêtes | Indicateur Lens | `count()` | 20 700 |
| Taux d'erreur serveur | Indicateur Lens | `count(kql='http.response.status_code >= 500') / count()`, format pourcentage | 1,97 % (407 / 20 700) |
| Trafic dans le temps | Barres empilées Lens | `@timestamp` en abscisse, ventilé par `http.response.status_code` | pic de 404 le 26/09 (robot), pic de 503 le 28/09 (incident) |
| Offres les plus consultées | Tableau Lens | Top 10 de `labels.offre_id`, requête du panneau `http.request.method : GET and http.response.status_code : 200` | mêmes résultats que l'exercice 4.4 |
| Navigateurs | Anneau Lens | Top 5 de `user_agent.name` | ≈ 20 % chacun |
| Offres par ville | Carte (Maps) | Data view `offres`, champ `localisation`, points colorés par `ville` | 12 villes |

Les deux anomalies de l'enquête se voient au premier coup d'œil sur l'histogramme : la barre bleue (404) dans la nuit du 26/09 et la barre rose (503) l'après-midi du 28/09.

Pour la carte, une grille d'agrégation (`geotile`) a d'abord été essayée. Les offres étant dispersées d'environ 5 km autour du centre de leur ville, une même ville était coupée entre plusieurs cellules, et les nombres affichés ne correspondaient à rien. La couche finale affiche les documents, colorés par `ville`, avec `ville`, `titre` et `contrat` en infobulle.

Interactivité vérifiée : un clic sur le segment rose (503) de la barre du 28/09 propose deux filtres, `http.response.status_code: 503` et le créneau de la barre. Une fois appliqués, tout le tableau de bord se met à jour :

- Requêtes : 402 ;
- Taux d'erreur serveur : 100,00 % ;
- l'histogramme passe en pas de 5 minutes et montre les erreurs de 14:00 à 14:45 ;
- le tableau des offres est vide (aucune consultation en 200 parmi des 503) ;
- l'anneau donne la répartition des navigateurs touchés.

La carte des offres, qui ne contient aucun code HTTP, n'est pas concernée par ce filtre.

### Bonus — Alerte « plus de 50 réponses 5xx en 5 minutes »

Règle de type Elasticsearch query sur `logs-web-*` : requête `http.response.status_code >= 500`, condition « nombre de documents > 50 », fenêtre de 5 minutes, vérification toutes les minutes, action via le connecteur Server log.

**Pourquoi elle ne se déclenchera pas sur ces logs :** à chaque exécution, la règle compte les documents dont `@timestamp` se situe dans les 5 dernières minutes avant l'heure actuelle. Nos événements sont datés du 23 au 29/09/2026, grâce au filtre `date` : aucun ne tombe jamais dans cette fenêtre glissante. Pourtant, l'incident du 28/09 aurait déclenché l'alerte, avec 35 à 53 erreurs par tranche de 5 minutes, soit plus de 50 sur une fenêtre glissante à plusieurs reprises.

**Comment la tester :**

1. Injecter des erreurs datées de maintenant : par exemple 60 documents `{"@timestamp": "<maintenant>", "http": {"response": {"status_code": 503}}}` via `POST logs-web-default/_bulk`, en action `create`. Il faut le faire avec un compte autorisé : `logstash_internal` peut écrire, `elastic` aussi. Autre solution : faire réémettre par Logstash quelques lignes de log dont la date est l'heure courante.
2. Attendre la prochaine vérification (1 minute) : l'alerte passe à l'état *Active* et le message apparaît dans le journal de Kibana (`docker compose logs kibana`).
3. Contrôler aussi le cas négatif : avec 50 erreurs ou moins, rien ne doit se déclencher.
4. Supprimer ensuite les documents de test (`_delete_by_query` sur leur `@timestamp`) pour ne pas fausser les statistiques.

Avant de produire de vrais événements, la prévisualisation de la règle (Test query) permet de vérifier la requête et le seuil sur une fenêtre élargie.

### Restitution — rapport d'incident (exercice 4.2)

- **Quoi** : l'API de listing des offres (`/api/offres?ville=…&page=1`) a répondu 503 Service Unavailable à toutes les requêtes, pour les 7 villes. Le reste du site (accueil, recherche, fiches d'offres, candidatures) a fonctionné normalement.
- **Quand** : le lundi 28/09/2026, de 14:00:08 à 14:44:56 (heure de Paris), soit environ 45 minutes. Début et fin sont nets, sans dégradation progressive.
- **Impact** : 402 requêtes en échec, soit 1,9 % du trafic de la semaine, mais 100 % des appels à cette API pendant l'incident. 308 clients différents ont été touchés, sur tous les navigateurs et appareils. Le taux d'erreur serveur de la semaine monte à 1,97 %, contre 0,02 % hors incident (5 erreurs 500 isolées).
- **Aggravation** : les clients ont réessayé, et le volume d'appels à l'API a été multiplié par environ 40 sur la période (403 requêtes au lieu de 4 à 15). Cela a ajouté de la charge sur un service déjà indisponible.
- **Recommandations** : alerte sur le taux de 5xx (voir le bonus), backoff exponentiel et respect de `Retry-After` côté client, analyse des journaux du service de l'API (saturation, dépendance indisponible, déploiement à 14:00 ?).
