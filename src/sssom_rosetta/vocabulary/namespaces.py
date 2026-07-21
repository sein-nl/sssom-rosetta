"""Shared RDF namespaces and IRI-minting helpers for the vocabulary pipeline.

Centralised so ``loinc_snomed``, ``omop`` and ``merge`` all mint identical IRIs
for the same underlying concept — that shared identity is what lets an OMOP
``concept_id`` node connect to the LOINC-SNOMED ontology graph after merging.

IRI schemes (see the plan's namespace-decisions table):
    sct          http://snomed.info/id/                          SNOMED/LOINC-ext SCTIDs
    omopconcept  https://w3id.org/omop/concept/                  OMOP integer concept_id
    loinc        https://loinc.org/                              LOINC Num codes
    rxnorm       http://purl.bioontology.org/ontology/RXNORM/    RxNorm RXCUIs
    icd10        http://hl7.org/fhir/sid/icd-10/                 WHO ICD-10 codes
    icd10cm      http://hl7.org/fhir/sid/icd-10-cm/              ICD-10-CM codes
"""

from __future__ import annotations

from urllib.parse import quote

from rdflib import Namespace, URIRef

SCT = Namespace("http://snomed.info/id/")
OMOP_CONCEPT = Namespace("https://w3id.org/omop/concept/")
LOINC = Namespace("https://loinc.org/")
RXNORM = Namespace("http://purl.bioontology.org/ontology/RXNORM/")
ICD10 = Namespace("http://hl7.org/fhir/sid/icd-10/")
ICD10CM = Namespace("http://hl7.org/fhir/sid/icd-10-cm/")

#: CURIE prefix -> namespace, bound on every graph produced by this package.
PREFIX_MAP: dict[str, Namespace] = {
    "sct": SCT,
    "omopconcept": OMOP_CONCEPT,
    "loinc": LOINC,
    "rxnorm": RXNORM,
    "icd10": ICD10,
    "icd10cm": ICD10CM,
}

#: OMOP ``vocabulary_id`` -> the namespace its native ``concept_code`` lives in.
#: ``RxNorm Extension`` concepts have no native code, so they stay OMOP-minted
#: (handled by returning ``None`` from :func:`source_concept_iri`).
_VOCABULARY_NAMESPACES: dict[str, Namespace] = {
    "SNOMED": SCT,
    "LOINC": LOINC,
    "RxNorm": RXNORM,
    "ICD10": ICD10,
    "ICD10CM": ICD10CM,
}

#: The OMOP ``vocabulary_id`` values this pipeline integrates.
TARGET_VOCABULARIES: frozenset[str] = frozenset(
    {"SNOMED", "LOINC", "RxNorm", "RxNorm Extension", "ICD10", "ICD10CM"}
)


def sct_iri(sctid: str) -> URIRef:
    """Return the SNOMED CT IRI for an SCTID string."""
    return SCT[sctid]


def omop_iri(concept_id: str) -> URIRef:
    """Return the OMOP concept IRI for an integer ``concept_id`` (as a string)."""
    return OMOP_CONCEPT[concept_id]


def source_concept_iri(vocabulary_id: str, concept_code: str) -> URIRef | None:
    """Mint the native source-vocabulary IRI for an OMOP row, or ``None``.

    Returns ``None`` for vocabularies without a native code namespace (e.g.
    ``RxNorm Extension``), signalling the caller to keep the OMOP-minted node
    as the concept's only identity.
    """
    namespace = _VOCABULARY_NAMESPACES.get(vocabulary_id)
    if namespace is None:
        return None
    # Concept codes can contain characters that are illegal in an IRI path
    # (e.g. LOINC class codes like "H&P.SURG PROC" or "NR STATS" with spaces
    # and ampersands). Percent-encode them so rdflib can serialize the IRI.
    return URIRef(str(namespace) + quote(concept_code, safe=""))
