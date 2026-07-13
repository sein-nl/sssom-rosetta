"""Tests for mapping/io.py: CSVW read + SSSOM/TSV and RDF/TTL derived writes.

Uses small inline CSV + CSVW metadata fixtures written to ``tmp_path`` (never
the real ``mappings/omop-onz-g.csv``, which doesn't exist yet) so tests run
offline and fast, per AGENTS.md's testing conventions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rdflib import Graph, URIRef

from sssom_rosetta.mapping.io import read_mapping_set_csvw, write_sssom_tsv, write_ttl
from sssom_rosetta.mapping.validate import SchemaConformanceError
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
    "subject_id,predicate_id,object_id,mapping_justification,confidence,author_id,"
    "subject_label,object_label\n"
    "omop:Person,skos:exactMatch,onz-g:Client,semapv:ManualMappingCuration,0.9,"
    "orcid:0000-0000-0000-0001|orcid:0000-0000-0000-0002,Person,Client\n"
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
            {"name": "confidence", "datatype": "number"},
            {"name": "author_id", "datatype": "string", "separator": "|"},
            {"name": "subject_label", "datatype": "string"},
            {"name": "object_label", "datatype": "string"},
        ]
    },
}


@pytest.fixture
def csvw_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Write the fixture CSV + CSVW metadata JSON pair to ``tmp_path``."""
    csv_path = tmp_path / "omop-onz-g.csv"
    metadata_path = tmp_path / "omop-onz-g.metadata.json"
    csv_path.write_text(CSV_CONTENT)
    metadata_path.write_text(json.dumps(METADATA_CONTENT))
    return csv_path, metadata_path


@pytest.fixture
def mapping_set(csvw_pair: tuple[Path, Path]) -> MappingSet:
    csv_path, metadata_path = csvw_pair
    return read_mapping_set_csvw(
        csv_path,
        metadata_path,
        mapping_set_id=MAPPING_SET_ID,
        license=LICENSE,
        curie_map=PREFIX_MAP,
    )


def test_read_mapping_set_csvw_parses_rows(mapping_set: MappingSet) -> None:
    assert mapping_set.mapping_set_id == MAPPING_SET_ID
    assert str(mapping_set.license) == LICENSE
    assert mapping_set.mappings is not None
    assert len(mapping_set.mappings) == 1

    mapping = mapping_set.mappings[0]
    assert mapping.subject_id == "omop:Person"
    assert mapping.predicate_id == "skos:exactMatch"
    assert mapping.object_id == "onz-g:Client"
    assert mapping.mapping_justification == "semapv:ManualMappingCuration"
    assert mapping.confidence == pytest.approx(0.9)
    assert mapping.author_id == [
        "orcid:0000-0000-0000-0001",
        "orcid:0000-0000-0000-0002",
    ]
    assert mapping.subject_label == "Person"
    assert mapping.object_label == "Client"


def test_read_mapping_set_csvw_applies_curie_map(mapping_set: MappingSet) -> None:
    assert mapping_set.curie_map is not None
    assert str(mapping_set.curie_map["omop"]) == PREFIX_MAP["omop"]


def test_read_mapping_set_csvw_multiple_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "multi.csv"
    metadata_path = tmp_path / "multi-metadata.json"
    csv_path.write_text(
        "subject_id,predicate_id,object_id,mapping_justification\n"
        "omop:Person,skos:exactMatch,onz-g:Client,semapv:ManualMappingCuration\n"
        "omop:Visit,skos:closeMatch,onz-g:Encounter,semapv:ManualMappingCuration\n"
    )
    metadata = {
        "@context": "http://www.w3.org/ns/csvw",
        "url": "multi.csv",
        "tableSchema": {
            "columns": [
                {"name": "subject_id", "datatype": "string"},
                {"name": "predicate_id", "datatype": "string"},
                {"name": "object_id", "datatype": "string"},
                {"name": "mapping_justification", "datatype": "string"},
            ]
        },
    }
    metadata_path.write_text(json.dumps(metadata))

    result = read_mapping_set_csvw(
        csv_path,
        metadata_path,
        mapping_set_id=MAPPING_SET_ID,
        license=LICENSE,
    )
    assert result.mappings is not None
    assert len(result.mappings) == 2
    assert result.mappings[1].subject_id == "omop:Visit"


def test_read_mapping_set_csvw_rejects_invalid_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    metadata_path = tmp_path / "bad-metadata.json"
    # Missing the required mapping_justification column/value.
    csv_path.write_text(
        "subject_id,predicate_id,object_id\nomop:Person,skos:exactMatch,onz-g:Client\n"
    )
    metadata = {
        "@context": "http://www.w3.org/ns/csvw",
        "url": "bad.csv",
        "tableSchema": {
            "columns": [
                {"name": "subject_id", "datatype": "string"},
                {"name": "predicate_id", "datatype": "string"},
                {"name": "object_id", "datatype": "string"},
            ]
        },
    }
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(SchemaConformanceError):
        read_mapping_set_csvw(
            csv_path,
            metadata_path,
            mapping_set_id=MAPPING_SET_ID,
            license=LICENSE,
        )


def test_write_sssom_tsv_contains_yaml_header_and_rows(
    mapping_set: MappingSet, tmp_path: Path
) -> None:
    output_path = tmp_path / "build" / "mappings" / "omop-onz-g.sssom.tsv"

    write_sssom_tsv(mapping_set, output_path)

    assert output_path.exists()
    content = output_path.read_text()
    lines = content.splitlines()

    header_lines = [line for line in lines if line.startswith("#")]
    assert any("mapping_set_id" in line for line in header_lines)
    assert any("license" in line for line in header_lines)
    assert any("curie_map" in line for line in header_lines)

    body_lines = [line for line in lines if not line.startswith("#")]
    assert (
        body_lines[0].split("\t")
        == [
            "subject_id",
            "predicate_id",
            "object_id",
            "mapping_justification",
            "confidence",
            "author_id",
            "subject_label",
            "object_label",
        ]
        or "subject_id" in body_lines[0]
    )
    assert "omop:Person" in body_lines[1]
    assert "onz-g:Client" in body_lines[1]
    assert "orcid:0000-0000-0000-0001|orcid:0000-0000-0000-0002" in body_lines[1]


def test_write_ttl_creates_expected_triples(
    mapping_set: MappingSet, tmp_path: Path
) -> None:
    output_path = tmp_path / "build" / "mappings" / "omop-onz-g.ttl"

    write_ttl(mapping_set, output_path, prefix_map=PREFIX_MAP)

    assert output_path.exists()
    graph = Graph()
    graph.parse(output_path, format="turtle")

    assert len(graph) == 1
    subject = URIRef("https://w3id.org/omop/ontology#Person")
    predicate = URIRef("http://www.w3.org/2004/02/skos/core#exactMatch")
    obj = URIRef("http://purl.org/ozo/onz-g#Client")
    assert (subject, predicate, obj) in graph


def test_write_ttl_creates_parent_directories(
    mapping_set: MappingSet, tmp_path: Path
) -> None:
    output_path = tmp_path / "nested" / "dir" / "omop-onz-g.ttl"

    write_ttl(mapping_set, output_path, prefix_map=PREFIX_MAP)

    assert output_path.parent.is_dir()
    assert output_path.exists()
