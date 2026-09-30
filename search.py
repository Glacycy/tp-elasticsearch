"""Mini-défi — moteur de recherche d'offres en ligne de commande.

Attendu :
  python search.py "développeur python"
  python search.py "données spark" --ville Lyon --contrat CDI --salaire-min 45000
  python search.py "kubernetes" --autour "43.6108,3.8767"--rayon 50km --teletravail partiel
"""

from __future__ import annotations

import argparse

from es_client import INDEX, get_client


def construire_requete(args: argparse.Namespace) -> dict:
    """Requête bool : texte pondéré et tolérant aux fautes, filtres optionnels."""
    filtres = [{"term": {champ: valeur}} for champ, valeur in
               (("ville", args.ville), ("contrat", args.contrat), ("teletravail", args.teletravail)) if valeur]
    if args.salaire_min is not None:
        filtres.append({"range": {"salaire_max": {"gte": args.salaire_min}}})
    if args.autour:
        lat, lon = map(float, args.autour.split(","))
        filtres.append({"geo_distance": {"distance": args.rayon, "localisation": {"lat": lat, "lon": lon}}})
    return {"bool": {
        "must": {"multi_match": {"query": args.texte, "fuzziness": "AUTO",
                                 "fields": ["titre^3", "competences.texte^2", "description"]}},
        "filter": filtres,
    }}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("texte")
    p.add_argument("--ville")
    p.add_argument("--contrat", choices=["CDI", "CDD", "Alternance", "Freelance", "Stage"])
    p.add_argument("--teletravail", choices=["aucun", "partiel", "total"])
    p.add_argument("--salaire-min", type=int)
    p.add_argument("--autour", help="lat,lon")
    p.add_argument("--rayon", default="30km")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--taille", type=int, default=10)
    args = p.parse_args()

    es = get_client()
    r = es.search(
        index=INDEX,
        query=construire_requete(args),
        from_=(args.page - 1) * args.taille,
        size=args.taille,
        highlight={"fields": {"description": {}}},
        aggs={champ: {"terms": {"field": champ}} for champ in ("ville", "contrat", "competences")},
    )

    print(f"{r['hits']['total']['value']} offres (page {args.page})")
    for hit in r["hits"]["hits"]:
        o = hit["_source"]
        salaire = f"{o['salaire_min']}-{o['salaire_max']} €" if "salaire_min" in o else "salaire non précisé"
        print(f"\n[{hit['_score']:.2f}] {o['titre']} — {o['entreprise']} — {o['ville']}, {o['contrat']}, {salaire}")
        for extrait in hit.get("highlight", {}).get("description", []):
            print("   ", extrait)

    print("\nFacettes")
    for nom, agg in r["aggregations"].items():
        print(f"  {nom} : " + ", ".join(f"{b['key']} ({b['doc_count']})" for b in agg["buckets"]))


if __name__ == "__main__":
    main()
