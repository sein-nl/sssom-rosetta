"""Tests for the ``rosetta`` typer CLI (cli.py).

All ontology fetch/load calls and filesystem I/O are mocked or redirected to
``tmp_path``: no network calls, no real ONZ-G/OMOP downloads. CSVW mapping
fixtures are small inline CSV + CSVW metadata JSON pairs written to
``tmp_path``, paired with tiny in-memory ``rdflib.Graph`` fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rdflib import Graph
from typer.testing import CliRunner

from sssom_rosetta import cli

runner = CliRunner()

MAPPING_SET_ID = "https://example.org/mappings/omop-onz-g"
LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"

PREFIX_MAP = {
    "omop": "https://w3id.org/omop/ontology#",
    "onz-g": "http://purl.org/ozo/onz-g#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "semapv": "https://w3id.org/semapv/vocab/",
}

CSV_CONTENT = (
    "subject_id,predicate_id,object_id,mapping_justification,confidence,"
    "subject_label,object_label\n"
    "omop:Person,skos:exactMatch,onz-g:Client,semapv:ManualMappingCuration,0.9,"
    "Person,Client\n"
)

CSV_CONTENT_BAD = (
    "subject_id,predicate_id,object_id,mapping_justification,confidence,"
    "subject_label,object_label\n"
    "omop:Nonexistent,skos:exactMatch,onz-g:Client,semapv:ManualMappingCuration,0.9,"
    "Nonexistent,Client\n"
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
            {"name": "subject_label", "datatype": "string"},
            {"name": "object_label", "datatype": "string"},
        ]
    },
}

OMOP_TTL = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix omop: <https://w3id.org/omop/ontology#> .

omop:Person a owl:Class ;
    rdfs:label "Person" .
"""

ONZ_G_TTL = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix onz-g: <http://purl.org/ozo/onz-g#> .

onz-g:Client a owl:Class ;
    rdfs:label "Client" .
"""


def _write_csvw_pair(tmp_path: Path, csv_content: str) -> tuple[Path, Path]:
    csv_path = tmp_path / "omop-onz-g.csv"
    metadata_path = tmp_path / "omop-onz-g.metadata.json"
    csv_path.write_text(csv_content)
    metadata_path.write_text(json.dumps(METADATA_CONTENT))
    return csv_path, metadata_path


def _patch_load_ontology(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch cli's load_ontology to return fixture graphs, no network/cache I/O."""
    omop_graph = Graph()
    omop_graph.parse(data=OMOP_TTL, format="turtle")
    onz_g_graph = Graph()
    onz_g_graph.parse(data=ONZ_G_TTL, format="turtle")

    graphs_by_name = {"omop-cdm": omop_graph, "onz-g": onz_g_graph}

    def _fake_load_ontology(source, cache_dir):  # noqa: ANN001, ARG001
        return graphs_by_name[source.name]

    monkeypatch.setattr(cli, "load_ontology", _fake_load_ontology)


# --- ontology fetch --------------------------------------------------------


def test_ontology_fetch_unknown_source_exits_nonzero() -> None:
    result = runner.invoke(cli.app, ["ontology", "fetch", "not-a-real-source"])
    assert result.exit_code != 0
    assert "Unknown ontology source" in result.output


def test_ontology_fetch_known_source_prints_cached_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected_path = tmp_path / "onz-g" / "2.8.1" / "ontology.ttl"

    def _fake_fetch_ontology(source, cache_dir, *, force=False):  # noqa: ANN001, ARG001
        return expected_path

    monkeypatch.setattr(cli, "fetch_ontology", _fake_fetch_ontology)

    result = runner.invoke(
        cli.app, ["ontology", "fetch", "onz-g", "--cache-dir", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert str(expected_path) in result.output


def test_ontology_fetch_omop_cdm_also_works(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected_path = tmp_path / "omop-cdm" / "abc123" / "ontology.ttl"

    def _fake_fetch_ontology(source, cache_dir, *, force=False):  # noqa: ANN001, ARG001
        return expected_path

    monkeypatch.setattr(cli, "fetch_ontology", _fake_fetch_ontology)

    result = runner.invoke(
        cli.app, ["ontology", "fetch", "omop-cdm", "--cache-dir", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert str(expected_path) in result.output


def test_ontology_fetch_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sssom_rosetta.ontology.loader import OntologyFetchError

    def _fake_fetch_ontology(source, cache_dir, *, force=False):  # noqa: ANN001, ARG001
        raise OntologyFetchError(
            "http://example.org/ontology.ttl", RuntimeError("boom")
        )

    monkeypatch.setattr(cli, "fetch_ontology", _fake_fetch_ontology)

    result = runner.invoke(
        cli.app, ["ontology", "fetch", "onz-g", "--cache-dir", str(tmp_path)]
    )
    assert result.exit_code != 0
    assert "Failed to fetch ontology" in result.output


# --- mapping validate --------------------------------------------------------


def test_mapping_validate_passes_for_valid_mapping_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_load_ontology(monkeypatch)
    csv_path, metadata_path = _write_csvw_pair(tmp_path, CSV_CONTENT)

    result = runner.invoke(
        cli.app,
        [
            "mapping",
            "validate",
            str(csv_path),
            str(metadata_path),
            "--mapping-set-id",
            MAPPING_SET_ID,
            "--license",
            LICENSE,
            "--curie-map",
            json.dumps(PREFIX_MAP),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Parsed 1 mapping(s)." in result.output
    assert "Validation passed." in result.output


def test_mapping_validate_reports_referential_integrity_issues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_load_ontology(monkeypatch)
    csv_path, metadata_path = _write_csvw_pair(tmp_path, CSV_CONTENT_BAD)

    result = runner.invoke(
        cli.app,
        [
            "mapping",
            "validate",
            str(csv_path),
            str(metadata_path),
            "--mapping-set-id",
            MAPPING_SET_ID,
            "--license",
            LICENSE,
            "--curie-map",
            json.dumps(PREFIX_MAP),
        ],
    )
    assert result.exit_code != 0
    assert "referential integrity issue" in result.output
    assert "subject_id" in result.output


def test_mapping_validate_missing_curie_map_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_load_ontology(monkeypatch)
    csv_path, metadata_path = _write_csvw_pair(tmp_path, CSV_CONTENT)

    result = runner.invoke(
        cli.app,
        [
            "mapping",
            "validate",
            str(csv_path),
            str(metadata_path),
            "--mapping-set-id",
            MAPPING_SET_ID,
            "--license",
            LICENSE,
            "--curie-map",
            "{}",
        ],
    )
    assert result.exit_code != 0
    assert "curie_map" in result.output


def test_mapping_validate_invalid_curie_map_json_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_load_ontology(monkeypatch)
    csv_path, metadata_path = _write_csvw_pair(tmp_path, CSV_CONTENT)

    result = runner.invoke(
        cli.app,
        [
            "mapping",
            "validate",
            str(csv_path),
            str(metadata_path),
            "--mapping-set-id",
            MAPPING_SET_ID,
            "--license",
            LICENSE,
            "--curie-map",
            "not-json",
        ],
    )
    assert result.exit_code != 0
    assert "not valid JSON" in result.output


def test_mapping_validate_unknown_ontology_source_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    csv_path, metadata_path = _write_csvw_pair(tmp_path, CSV_CONTENT)

    result = runner.invoke(
        cli.app,
        [
            "mapping",
            "validate",
            str(csv_path),
            str(metadata_path),
            "--mapping-set-id",
            MAPPING_SET_ID,
            "--license",
            LICENSE,
            "--curie-map",
            json.dumps(PREFIX_MAP),
            "--subject-source",
            "not-a-real-source",
        ],
    )
    assert result.exit_code != 0
    assert "Unknown ontology source" in result.output


# --- mapping build --------------------------------------------------------


def test_mapping_build_writes_tsv_and_ttl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_load_ontology(monkeypatch)
    csv_path, metadata_path = _write_csvw_pair(tmp_path, CSV_CONTENT)
    output_dir = tmp_path / "build" / "mappings"

    result = runner.invoke(
        cli.app,
        [
            "mapping",
            "build",
            str(csv_path),
            str(metadata_path),
            "--mapping-set-id",
            MAPPING_SET_ID,
            "--license",
            LICENSE,
            "--curie-map",
            json.dumps(PREFIX_MAP),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    expected_tsv = output_dir / "omop-onz-g.sssom.tsv"
    expected_ttl = output_dir / "omop-onz-g.ttl"
    assert expected_tsv.exists()
    assert expected_ttl.exists()
    assert str(expected_tsv) in result.output
    assert str(expected_ttl) in result.output


def test_mapping_build_fails_before_writing_when_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_load_ontology(monkeypatch)
    csv_path, metadata_path = _write_csvw_pair(tmp_path, CSV_CONTENT_BAD)
    output_dir = tmp_path / "build" / "mappings"

    result = runner.invoke(
        cli.app,
        [
            "mapping",
            "build",
            str(csv_path),
            str(metadata_path),
            "--mapping-set-id",
            MAPPING_SET_ID,
            "--license",
            LICENSE,
            "--curie-map",
            json.dumps(PREFIX_MAP),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code != 0
    assert not output_dir.exists()


# --- mapping report --------------------------------------------------------


def test_mapping_report_no_base_shows_everything_added(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_load_ontology(monkeypatch)
    csv_path, metadata_path = _write_csvw_pair(tmp_path, CSV_CONTENT)
    output_dir = tmp_path / "build" / "mappings"
    runner.invoke(
        cli.app,
        [
            "mapping",
            "build",
            str(csv_path),
            str(metadata_path),
            "--mapping-set-id",
            MAPPING_SET_ID,
            "--license",
            LICENSE,
            "--curie-map",
            json.dumps(PREFIX_MAP),
            "--output-dir",
            str(output_dir),
        ],
    )
    head_tsv = output_dir / "omop-onz-g.sssom.tsv"

    result = runner.invoke(cli.app, ["mapping", "report", "--head", str(head_tsv)])

    assert result.exit_code == 0, result.output
    assert "added" in result.output.lower()


def test_mapping_report_writes_markdown_and_html_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_load_ontology(monkeypatch)
    csv_path, metadata_path = _write_csvw_pair(tmp_path, CSV_CONTENT)
    output_dir = tmp_path / "build" / "mappings"
    runner.invoke(
        cli.app,
        [
            "mapping",
            "build",
            str(csv_path),
            str(metadata_path),
            "--mapping-set-id",
            MAPPING_SET_ID,
            "--license",
            LICENSE,
            "--curie-map",
            json.dumps(PREFIX_MAP),
            "--output-dir",
            str(output_dir),
        ],
    )
    head_tsv = output_dir / "omop-onz-g.sssom.tsv"
    markdown_path = tmp_path / "report.md"
    html_path = tmp_path / "report.html"

    result = runner.invoke(
        cli.app,
        [
            "mapping",
            "report",
            "--head",
            str(head_tsv),
            "--output-markdown",
            str(markdown_path),
            "--output-html",
            str(html_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert markdown_path.exists()
    assert html_path.exists()
    assert "<html" in html_path.read_text().lower()
