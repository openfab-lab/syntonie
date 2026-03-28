#!/usr/bin/env python3
"""
ttl2topics.py — Generate topics.json from syntonie.ttl vocabularies

Collects all skos:prefLabel and skos:hiddenLabel (FR) from Vocabulary instances,
plus any additional curated terms not in the ontology yet.
Run: python syntonie/scripts/ttl2topics.py
"""

import json
from pathlib import Path
from rdflib import Graph, Namespace, RDF, Literal

SYNTONIE = Namespace("https://syntonie.be/ns/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

TTL_PATH = Path(__file__).parent.parent / "data" / "syntonie.ttl"
OUT_PATH = Path(__file__).parent.parent / "static" / "js" / "topics.json"

# Terms that should be in autocomplete but aren't (yet) in the ontology.
# As the TTL grows, these can be removed.
CURATED_EXTRAS = [
    # Geographic / institutional anchors
    "Ixelles", "Bruxelles", "Erasmus",
    "Innoviris", "Cocof", "Fédération Wallonie-Bruxelles",
    # Maker-specific tools (not yet in vocab)
    "Arduino", "Raspberry Pi", "imprimante 3D",
    "électronique", "couture", "textile",
    # Community terms
    "faire ensemble", "partager", "confiance",
    "communauté", "collaboration", "impact social",
    "écosystème", "constellation",
    # Entities
    "OpenFab", "Politype",
    # Misc intent words
    "curieux", "explorer", "expérimenter",
    "mon propre projet", "liberté créative",
    "prototype rapide", "recherche-action",
    "repair café", "open hardware",
    "intelligence artificielle", "IA",
    "démocratie", "citoyen",
]


def main():
    g = Graph()
    g.parse(str(TTL_PATH), format="turtle")

    topics = set()

    # Collect from all Vocabulary instances
    for vocab in g.subjects(RDF.type, SYNTONIE.Vocabulary):
        for pred in (SKOS.prefLabel, SKOS.hiddenLabel):
            for obj in g.objects(vocab, pred):
                if isinstance(obj, Literal) and obj.language == "fr":
                    # hiddenLabel can be comma-separated in some serializations
                    for term in str(obj).split(", "):
                        term = term.strip()
                        if term:
                            topics.add(term)

    # Collect from TRIGGERS in recipes.js (project names, CTA keywords)
    # These are the trigger words that map to recipes
    for proj in g.subjects(RDF.type, SYNTONIE.Project):
        for obj in g.objects(proj, SYNTONIE.status):
            status = str(obj)
        # Add project titles as potential autocomplete targets
        for obj in g.objects(proj, Namespace("http://purl.org/dc/terms/").title):
            if isinstance(obj, Literal) and (obj.language == "fr" or obj.language is None):
                title = str(obj)
                # Only add short titles (long ones are CTAs, not search terms)
                if len(title) < 30:
                    topics.add(title)

    # Add curated extras
    topics.update(CURATED_EXTRAS)

    # Sort: lowercase-aware, French-friendly
    sorted_topics = sorted(topics, key=lambda t: t.lower())

    OUT_PATH.write_text(json.dumps(sorted_topics, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT_PATH.name}: {len(sorted_topics)} topics ({len(topics - set(CURATED_EXTRAS))} from TTL, {len(set(CURATED_EXTRAS))} curated)")


if __name__ == "__main__":
    main()
