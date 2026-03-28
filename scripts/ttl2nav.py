#!/usr/bin/env python3
"""
ttl2nav.py — Generate navigation.json from syntonie.ttl

Reads the RDF ontology and produces a clean JSON file for recipes.js.
Run: python syntonie/scripts/ttl2nav.py
"""

import json
from pathlib import Path
from rdflib import Graph, Namespace, Literal, RDF

SYNTONIE = Namespace("https://syntonie.be/ns/")
DCTERMS = Namespace("http://purl.org/dc/terms/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
SCHEMA = Namespace("https://schema.org/")

TTL_PATH = Path(__file__).parent.parent / "data" / "syntonie.ttl"
OUT_PATH = Path(__file__).parent.parent / "data" / "navigation.json"


def lang_str(g, subj, pred, lang="fr"):
    """Get a literal value, preferring the given language."""
    for obj in g.objects(subj, pred):
        if isinstance(obj, Literal):
            if obj.language == lang or obj.language is None:
                return str(obj)
    # fallback: any literal
    for obj in g.objects(subj, pred):
        if isinstance(obj, Literal):
            return str(obj)
    return None


def get_status(g, subj):
    for obj in g.objects(subj, SYNTONIE.status):
        return str(obj)
    return None


def build_project(g, proj_uri):
    """Extract project data from graph."""
    proj_id = lang_str(g, proj_uri, DCTERMS.identifier) or str(proj_uri).split("/")[-1]

    # Semantic neighbors
    neighbors = []
    for bn in g.objects(proj_uri, SYNTONIE.hasSemanticNeighbor):
        target = None
        for t in g.objects(bn, SYNTONIE.neighborTarget):
            target = lang_str(g, t, DCTERMS.identifier) or str(t).split("/")[-1]
        score = None
        for s in g.objects(bn, SYNTONIE.proximityScore):
            score = float(s)
        reason = None
        for r in g.objects(bn, SYNTONIE.proximityReason):
            reason = str(r)
        if target:
            neighbors.append({"target": target, "score": score, "reason": reason})
    neighbors.sort(key=lambda n: -(n["score"] or 0))

    # CTA
    cta = None
    for bn in g.objects(proj_uri, SYNTONIE.hasCallToAction):
        cta = {
            "type": lang_str(g, bn, SYNTONIE.ctaType),
            "title": {"fr": lang_str(g, bn, DCTERMS.title, "fr")},
            "target": lang_str(g, bn, SYNTONIE.ctaTarget),
        }

    return {
        "id": proj_id,
        "title": {"fr": lang_str(g, proj_uri, DCTERMS.title, "fr")},
        "description": {"fr": lang_str(g, proj_uri, DCTERMS.description, "fr")},
        "status": get_status(g, proj_uri),
        "created": lang_str(g, proj_uri, DCTERMS.created),
        "neighbors": neighbors if neighbors else None,
        "cta": cta,
    }


def build_recipe(g, cat_uri):
    """Extract category/recipe data."""
    cat_id = str(cat_uri).split("/")[-1].replace("cat-", "")

    # Projects in this category
    projects = []
    for proj in g.objects(cat_uri, SYNTONIE.containsProject):
        proj_id = lang_str(g, proj, DCTERMS.identifier) or str(proj).split("/")[-1]
        projects.append(proj_id)

    # Suggested categories
    suggests = []
    for sug in g.objects(cat_uri, SYNTONIE.suggestsCategory):
        sug_id = str(sug).split("/")[-1].replace("cat-", "")
        suggests.append(sug_id)

    # Vocabularies
    vocabs = []
    for v in g.objects(cat_uri, SYNTONIE.hasVocabulary):
        v_id = str(v).split("/")[-1].replace("vocab-", "")
        vocabs.append(v_id)

    return {
        "id": cat_id,
        "label": {"fr": lang_str(g, cat_uri, DCTERMS.title, "fr")},
        "headline": {"fr": lang_str(g, cat_uri, SCHEMA.headline, "fr")},
        "projects": projects,
        "suggests": suggests,
        "vocabularies": vocabs,
        "status": get_status(g, cat_uri),
    }


def build_vocabulary(g, vocab_uri):
    """Extract vocabulary with all hidden labels."""
    v_id = str(vocab_uri).split("/")[-1].replace("vocab-", "")

    hidden_fr = [str(o) for o in g.objects(vocab_uri, SKOS.hiddenLabel) if getattr(o, "language", None) == "fr"]
    hidden_en = [str(o) for o in g.objects(vocab_uri, SKOS.hiddenLabel) if getattr(o, "language", None) == "en"]

    return {
        "id": v_id,
        "prefLabel": {
            "fr": lang_str(g, vocab_uri, SKOS.prefLabel, "fr"),
            "en": lang_str(g, vocab_uri, SKOS.prefLabel, "en"),
        },
        "hiddenLabels": {
            "fr": hidden_fr,
            "en": hidden_en,
        },
    }


def main():
    g = Graph()
    g.parse(str(TTL_PATH), format="turtle")
    print(f"Loaded {len(g)} triples from {TTL_PATH.name}")

    # Collect all categories (explicit rdf:type only)
    recipes = {}
    for cat in g.subjects(RDF.type, SYNTONIE.Category):
        r = build_recipe(g, cat)
        recipes[r["id"]] = r

    # Collect all projects
    projects = {}
    for proj in g.subjects(RDF.type, SYNTONIE.Project):
        p = build_project(g, proj)
        projects[p["id"]] = p

    # Collect all vocabularies
    vocabularies = {}
    for vocab in g.subjects(RDF.type, SYNTONIE.Vocabulary):
        v = build_vocabulary(g, vocab)
        vocabularies[v["id"]] = v

    # Collect roles
    roles = {}
    for role in g.subjects(RDF.type, SYNTONIE.Role):
        r_id = str(role).split("/")[-1].replace("role-", "")
        prio_vocabs = [str(v).split("/")[-1].replace("vocab-", "") for v in g.objects(role, SYNTONIE.prioritizesVocabulary)]
        roles[r_id] = {
            "id": r_id,
            "label": {
                "fr": lang_str(g, role, SKOS.prefLabel, "fr"),
                "en": lang_str(g, role, SKOS.prefLabel, "en"),
            },
            "prioritizedVocabularies": prio_vocabs,
        }

    output = {
        "_generated": "from syntonie.ttl via ttl2nav.py",
        "_source": "https://syntonie.be/ns/",
        "recipes": recipes,
        "projects": projects,
        "vocabularies": vocabularies,
        "roles": roles,
    }

    # Remove None values for cleaner JSON
    def clean(obj):
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items() if v is not None}
        if isinstance(obj, list):
            return [clean(i) for i in obj]
        return obj

    output = clean(output)

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT_PATH.name}: {len(recipes)} recipes, {len(projects)} projects, {len(vocabularies)} vocabularies, {len(roles)} roles")


if __name__ == "__main__":
    main()
