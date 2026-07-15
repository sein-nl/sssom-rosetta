"""Tests for mapping/protege.py: OWL restriction-based export for Protege.

Uses a small inline CSV + CSVW metadata fixture (2 rows: one exactMatch, one
broadMatch) so tests run offline and fast, per AGENTS.md's testing
conventions. See mapping/protege.py's module docstring for why this writer
exists alongside mapping/io.py's flat-triple write_ttl.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from linkml_runtime.utils.metamodelcore import URI
from rdflib import OWL, RDF, RDFS, Graph, URIRef

from sssom_rosetta.mapping.io import read_mapping_set_csvw
from sssom_rosetta.mapping.protege import write_owl_restrictions
from sssom_rosetta.models.sssom import MappingSet

MAPPING_SET_ID = "https://example.org/mappings/omop-onz-g"
LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"

PREFIX_MAP = {
    "omop": "https://w3id.org/omop/ontology#",
    "onz-g": "http://purl.org/ozo/onz-g#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "semapv": "https://w3id.org/semapv/vocab/",
}

CSV_CONTENT = (
    "subject_id,predicate_id,object_id,mapping_justification\n"
    "omop:Person,skos:exactMatch,onz-g:Client,semapv:ManualMappingCuration\n"
    "omop:Provider,skos:broadMatch,onz-g:Caregiver,semapv:ManualMappingCuration\n"
)

METADATA_CONTENT = {
    "@context": "http://www.w3.org/ns/csvw",
    "url": "omop-onz-g.csv",
    "tableSchema": {
        "columns": [
            {"name": "subject_id", "datatype": "string"},
            {"name": "predicate_id", "datatype": "string"},
            {"name": "object_id", "datatype": "string"},
            {"name": "mapping_justification", "datatype": "string"},
        ]
    },
}


@pytest.fixture
def mapping_set(tmp_path: Path) -> MappingSet:
    csv_path = tmp_path / "omop-onz-g.csv"
    metadata_path = tmp_path / "omop-onz-g.metadata.json"
    csv_path.write_text(CSV_CONTENT)
    metadata_path.write_text(json.dumps(METADATA_CONTENT))
    return read_mapping_set_csvw(
        csv_path,
        metadata_path,
        mapping_set_id=MAPPING_SET_ID,
        license=LICENSE,
        curie_map=PREFIX_MAP,
    )


def test_exact_match_becomes_equivalent_class(
    mapping_set: MappingSet, tmp_path: Path
) -> None:
    output_path = tmp_path / "build" / "protege" / "omop-onz-g.combined.ttl"

    write_owl_restrictions(mapping_set, output_path, prefix_map=PREFIX_MAP)

    graph = Graph()
    graph.parse(output_path, format="turtle")

    person = URIRef("https://w3id.org/omop/ontology#Person")
    client = URIRef("http://purl.org/ozo/onz-g#Client")
    assert (person, OWL.equivalentClass, client) in graph


def test_broad_match_becomes_existential_restriction(
    mapping_set: MappingSet, tmp_path: Path
) -> None:
    output_path = tmp_path / "build" / "protege" / "omop-onz-g.combined.ttl"

    write_owl_restrictions(mapping_set, output_path, prefix_map=PREFIX_MAP)

    graph = Graph()
    graph.parse(output_path, format="turtle")

    provider = URIRef("https://w3id.org/omop/ontology#Provider")
    caregiver = URIRef("http://purl.org/ozo/onz-g#Caregiver")
    broad_match = URIRef("http://www.w3.org/2004/02/skos/core#broadMatch")

    restrictions = list(graph.subjects(RDF.type, OWL.Restriction))
    assert len(restrictions) == 1
    restriction = restrictions[0]

    assert (restriction, OWL.onProperty, broad_match) in graph
    assert (restriction, OWL.someValuesFrom, caregiver) in graph
    assert (provider, RDFS.subClassOf, restriction) in graph


def test_used_predicates_declared_as_object_properties(
    mapping_set: MappingSet, tmp_path: Path
) -> None:
    output_path = tmp_path / "build" / "protege" / "omop-onz-g.combined.ttl"

    write_owl_restrictions(mapping_set, output_path, prefix_map=PREFIX_MAP)

    graph = Graph()
    graph.parse(output_path, format="turtle")

    exact_match = URIRef("http://www.w3.org/2004/02/skos/core#exactMatch")
    broad_match = URIRef("http://www.w3.org/2004/02/skos/core#broadMatch")

    assert (exact_match, RDF.type, OWL.ObjectProperty) in graph
    assert (broad_match, RDF.type, OWL.ObjectProperty) in graph


def test_write_owl_restrictions_creates_parent_directories(
    mapping_set: MappingSet, tmp_path: Path
) -> None:
    output_path = tmp_path / "nested" / "dir" / "omop-onz-g.combined.ttl"

    write_owl_restrictions(mapping_set, output_path, prefix_map=PREFIX_MAP)

    assert output_path.parent.is_dir()
    assert output_path.exists()


def test_write_owl_restrictions_requires_subject_and_object_id(
    tmp_path: Path,
) -> None:
    incomplete_set = MappingSet(
        mapping_set_id=URI(MAPPING_SET_ID),
        license=URI(LICENSE),
        mappings=[
            {
                "subject_id": None,
                "predicate_id": "skos:exactMatch",
                "object_id": None,
                "mapping_justification": "semapv:ManualMappingCuration",
            }
        ],
    )
    output_path = tmp_path / "omop-onz-g.combined.ttl"

    with pytest.raises(ValueError, match="missing subject_id/object_id"):
        write_owl_restrictions(incomplete_set, output_path, prefix_map=PREFIX_MAP)
