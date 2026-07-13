"""Tests for the first curated mapping set, ``mappings/omop-onz-g.csv``.

Only checks CSVW parsing + SSSOM schema conformance of the real, hand-authored
file (no network calls). Referential integrity against the live ONZ-G/OMOP
ontology graphs is exercised manually / in CI via ``rosetta mapping validate``
(see AGENTS.md), since that requires fetching the real ontologies.
"""

from __future__ import annotations

from pathlib import Path

from sssom_rosetta.mapping.io import read_mapping_set_csvw
from sssom_rosetta.models.sssom import MappingSet

MAPPINGS_DIR = Path(__file__).resolve().parents[2] / "mappings"

MAPPING_SET_ID = (
    "https://raw.githubusercontent.com/plugin-healthcare/sssom-rosetta/"
    "main/build/mappings/omop-onz-g.sssom.tsv"
)
LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"

PREFIX_MAP = {
    "omop": "https://w3id.org/omop/ontology/",
    "onz-g": "http://purl.org/ozo/onz-g#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "semapv": "https://w3id.org/semapv/vocab/",
    "orcid": "https://orcid.org/",
}


def _load() -> MappingSet:
    return read_mapping_set_csvw(
        MAPPINGS_DIR / "omop-onz-g.csv",
        MAPPINGS_DIR / "omop-onz-g.metadata.json",
        mapping_set_id=MAPPING_SET_ID,
        license=LICENSE,
        curie_map=PREFIX_MAP,
    )


def test_omop_onz_g_mapping_set_parses() -> None:
    mapping_set = _load()
    assert mapping_set.mappings is not None
    assert len(mapping_set.mappings) == 8


def test_omop_onz_g_mapping_set_first_row_is_person_to_patient_in_care() -> None:
    mapping_set = _load()
    assert mapping_set.mappings is not None
    mapping = mapping_set.mappings[0]
    assert mapping.subject_id == "omop:Person"
    assert mapping.predicate_id == "skos:exactMatch"
    assert mapping.object_id == "onz-g:PatientInCare"
    assert mapping.mapping_justification == "semapv:ManualMappingCuration"
    assert mapping.confidence == 0.9
    assert mapping.author_id == ["orcid:0000-0001-8979-9194"]
    assert mapping.author_label == ["sssom-rosetta contributors"]
