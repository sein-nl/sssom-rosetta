"""Tests for the ontology source registry (no network calls)."""

from __future__ import annotations

import pytest

from sssom_rosetta.ontology.sources import (
    ONTOLOGY_SOURCES,
    OntologySource,
    UnknownOntologySourceError,
    get_source,
)


def test_registry_contains_onz_g() -> None:
    source = ONTOLOGY_SOURCES["onz-g"]
    assert source.name == "onz-g"
    assert source.version == "2.8.1"
    assert source.iri == "http://purl.org/ozo/onz-g"
    assert source.download_url.startswith(
        "https://widoco.kik-v-credentialsplatform.nl/"
    )
    assert source.download_url.endswith("ontology.ttl")
    assert source.checksum is None


def test_registry_contains_omop_cdm() -> None:
    source = ONTOLOGY_SOURCES["omop-cdm"]
    assert source.name == "omop-cdm"
    assert source.iri == "https://w3id.org/omop/ontology"
    assert source.download_url == (
        "https://raw.githubusercontent.com/plugin-healthcare/omop-cdm-owl/"
        "99d42596d675f0905724883fd35a81775f98bfe5/omop_cdm_v5.ttl"
    )
    assert source.checksum is None


def test_registry_has_exactly_two_sources() -> None:
    assert set(ONTOLOGY_SOURCES) == {"onz-g", "omop-cdm"}


def test_get_source_returns_registered_source() -> None:
    source = get_source("onz-g")
    assert isinstance(source, OntologySource)
    assert source is ONTOLOGY_SOURCES["onz-g"]


def test_get_source_unknown_name_raises() -> None:
    with pytest.raises(UnknownOntologySourceError) as exc_info:
        get_source("does-not-exist")
    message = str(exc_info.value)
    assert "does-not-exist" in message
    assert "onz-g" in message
    assert "omop-cdm" in message


def test_ontology_source_is_frozen() -> None:
    source = get_source("onz-g")
    with pytest.raises(AttributeError):
        source.version = "9.9.9"  # type: ignore[misc]
