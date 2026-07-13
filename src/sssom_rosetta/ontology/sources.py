"""Registry of ontology sources used by sssom-rosetta.

Each entry pins a specific ontology version to a stable download URL so that
``rosetta ontology fetch`` (see ``ontology/loader.py``, a later increment)
can reproducibly retrieve the same bytes every time. Nothing here is scraped
from HTML at mapping time: the download URLs below were manually extracted
from each ontology's publication page and verified reachable.
"""

from __future__ import annotations

from dataclasses import dataclass


class UnknownOntologySourceError(KeyError):
    """Raised when a requested ontology source is not in the registry."""

    def __init__(self, name: str) -> None:
        known = ", ".join(sorted(ONTOLOGY_SOURCES))
        super().__init__(f"Unknown ontology source {name!r}. Known sources: {known}")


@dataclass(frozen=True)
class OntologySource:
    """A pinned ontology source: identity, version, and where to fetch it.

    Attributes:
        name: Short registry key for the ontology (e.g. ``"onz-g"``).
        version: Pinned version string (a release tag or a git commit SHA).
        iri: The ontology's canonical IRI/namespace.
        download_url: Direct, stable URL serving the ontology as Turtle.
        checksum: SHA-256 checksum of the downloaded file, verified by the
            loader. Left as ``None`` until the ``ontology-loader`` task
            implements checksum computation and verification.
    """

    name: str
    version: str
    iri: str
    download_url: str
    checksum: str | None = None


ONTOLOGY_SOURCES: dict[str, OntologySource] = {
    "onz-g": OntologySource(
        name="onz-g",
        version="2.8.1",
        iri="http://purl.org/ozo/onz-g",
        # Published at https://kik-v-publicatieplatform.nl/ontologie/onz-g/2.8.1
        # This widoco-generated URL is regenerated on each ontology republish;
        # re-check the publication page if this link stops resolving.
        download_url=(
            "https://widoco.kik-v-credentialsplatform.nl/"
            "3f22caac-112b-400c-85c4-c4aefa745760/"
            "c623775baf6d15e267179affc997230585bcb0f8f8438d87c280a37b2c4899d6/"
            "ontology.ttl"
        ),
    ),
    "omop-cdm": OntologySource(
        name="omop-cdm",
        version="5.4",
        iri="https://w3id.org/omop/ontology",
        # raw.githubusercontent.com pinned to a commit SHA (rather than the
        # GitHub Pages mirror at plugin-healthcare.github.io/omop-cdm-owl/ontology.ttl)
        # so the download is immutable and reproducible even if `main` moves.
        download_url=(
            "https://raw.githubusercontent.com/plugin-healthcare/omop-cdm-owl/"
            "99d42596d675f0905724883fd35a81775f98bfe5/omop_cdm_v5.ttl"
        ),
    ),
}


def get_source(name: str) -> OntologySource:
    """Look up a registered ontology source by name.

    Args:
        name: Registry key, e.g. ``"onz-g"`` or ``"omop-cdm"``.

    Returns:
        The matching ``OntologySource``.

    Raises:
        UnknownOntologySourceError: If ``name`` is not in ``ONTOLOGY_SOURCES``.
    """
    try:
        return ONTOLOGY_SOURCES[name]
    except KeyError as exc:
        raise UnknownOntologySourceError(name) from exc
