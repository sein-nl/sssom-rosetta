"""Tests for the OMOP/Athena graph builder and cross-linking."""

from __future__ import annotations

import polars as pl
from rdflib import Literal
from rdflib.namespace import RDF, SKOS

from sssom_rosetta.vocabulary import omop
from sssom_rosetta.vocabulary.namespaces import omop_iri, sct_iri, source_concept_iri

CONCEPTS = pl.DataFrame(
    {
        "concept_id": ["1001", "1002", "1003", "1004"],
        "concept_name": [
            "Glucose [Mass/volume]",
            "Type 2 diabetes mellitus",
            'Aspirin 81 MG "low dose"',
            "RxNorm-ext product",
        ],
        "vocabulary_id": ["LOINC", "SNOMED", "ICD10CM", "RxNorm Extension"],
        "concept_code": ["2345-7", "44054006", "E11.9", ""],
    }
)

RELATIONSHIPS = pl.DataFrame(
    {
        "concept_id_1": ["1003", "1002"],
        "concept_id_2": ["1002", "1001"],
        "relationship_id": ["Maps to", "Is a"],
    }
)


def test_source_concept_iri_returns_none_for_rxnorm_extension() -> None:
    assert source_concept_iri("RxNorm Extension", "") is None
    assert source_concept_iri("SNOMED", "44054006") == sct_iri("44054006")


def test_source_concept_iri_percent_encodes_illegal_chars() -> None:
    # LOINC class codes can contain spaces/ampersands that are illegal in an
    # IRI path; they must be percent-encoded so rdflib can serialize them.
    iri = source_concept_iri("LOINC", "H&P.SURG PROC")
    assert iri is not None
    assert str(iri) == "https://loinc.org/H%26P.SURG%20PROC"
    # Plain codes with unreserved chars are left intact.
    assert str(source_concept_iri("LOINC", "2345-7")) == "https://loinc.org/2345-7"


def test_build_graph_concept_nodes_and_crosslinks() -> None:
    graph = omop.build_graph(CONCEPTS, RELATIONSHIPS)

    loinc_node = omop_iri("1001")
    assert (loinc_node, RDF.type, SKOS.Concept) in graph
    assert (
        loinc_node,
        SKOS.prefLabel,
        Literal("Glucose [Mass/volume]", lang="en"),
    ) in graph
    assert (loinc_node, SKOS.notation, Literal("2345-7")) in graph
    # LOINC concept cross-linked to its native source IRI.
    assert (loinc_node, SKOS.exactMatch, source_concept_iri("LOINC", "2345-7")) in graph

    # SNOMED concept cross-linked to sct: IRI (the merge bridge).
    assert (omop_iri("1002"), SKOS.exactMatch, sct_iri("44054006")) in graph

    # RxNorm Extension: no native code, so no exactMatch to a source IRI.
    ext_node = omop_iri("1004")
    assert (ext_node, RDF.type, SKOS.Concept) in graph
    assert not list(graph.objects(ext_node, SKOS.exactMatch))


def test_build_graph_relationship_predicates() -> None:
    graph = omop.build_graph(CONCEPTS, RELATIONSHIPS)
    # 'Maps to' -> exactMatch between OMOP nodes.
    assert (omop_iri("1003"), SKOS.exactMatch, omop_iri("1002")) in graph
    # 'Is a' -> broadMatch (child -> parent).
    assert (omop_iri("1002"), SKOS.broadMatch, omop_iri("1001")) in graph
