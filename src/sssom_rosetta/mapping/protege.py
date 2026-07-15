"""Write a Protege-friendly OWL representation of a mapping set.

``mapping.io.write_ttl`` emits one flat triple per mapping (``subject_id
predicate_id object_id``), which is correct SSSOM/RDF but does not work well
once opened in Protege together with the two source ontologies: SKOS mapping
properties (``skos:exactMatch``, ``skos:broadMatch``, ``skos:narrowMatch``,
``skos:relatedMatch``) are annotation properties, and in OWL 2 DL an object
property can only ever connect individuals, never two classes directly. When
a flat triple connects two classes with such a predicate, Protege treats it
as an annotation assertion regardless of how the predicate is typed, and
OntoGraf -- which only draws edges for structural class relationships
(subclassing and object-property restrictions) -- silently ignores it.

``write_owl_restrictions`` sidesteps this for a *Protege-specific* combined
export only (the canonical ``build/mappings/*.ttl`` produced by
``mapping.io.write_ttl`` is untouched) by representing each mapping as an
OWL class-level axiom instead of a flat triple:

- ``skos:exactMatch`` becomes ``owl:equivalentClass`` -- a native OWL DL
  class-to-class axiom, the most precise fit for an exact match.
- every other predicate becomes an existential restriction:
  ``subject_class rdfs:subClassOf [ a owl:Restriction ; owl:onProperty
  <predicate> ; owl:someValuesFrom object_class ]``.

Each predicate IRI used is also declared ``rdf:type owl:ObjectProperty`` in
the emitted graph, since SKOS itself declares them as annotation properties
and OntoGraf only renders edges for typed object properties.
"""

from __future__ import annotations

from pathlib import Path

from rdflib import OWL, RDF, RDFS, BNode, Graph, URIRef

from sssom_rosetta.mapping.author import expand_curie
from sssom_rosetta.models.sssom import MappingSet

_EXACT_MATCH_SUFFIXES = ("skos/core#exactMatch",)


def _is_exact_match(predicate_iri: str) -> bool:
    return predicate_iri.endswith(_EXACT_MATCH_SUFFIXES)


def write_owl_restrictions(
    mapping_set: MappingSet, output_path: Path, *, prefix_map: dict[str, str]
) -> None:
    """Write an OWL graph of the mapping set using class-level axioms.

    Args:
        mapping_set: The mapping set to serialize.
        output_path: Destination ``.ttl`` path (parent directories are
            created if missing, e.g. ``build/protege/``).
        prefix_map: Maps CURIE prefixes (for subject, predicate, and object)
            to namespace IRIs, same convention as ``mapping.io.write_ttl``.

    Raises:
        ValueError: If a mapping is missing ``subject_id``/``object_id``.
    """
    graph = Graph()
    for prefix, namespace in prefix_map.items():
        graph.bind(prefix, namespace)

    declared_predicates: set[str] = set()

    for index, mapping in enumerate(mapping_set.mappings or []):
        if mapping.subject_id is None or mapping.object_id is None:
            raise ValueError(
                f"Mapping at index {index} is missing subject_id/object_id required to emit an axiom"
            )
        subject_iri = expand_curie(mapping.subject_id, prefix_map)
        predicate_iri = expand_curie(mapping.predicate_id, prefix_map)
        object_iri = expand_curie(mapping.object_id, prefix_map)

        if predicate_iri not in declared_predicates:
            graph.add((URIRef(predicate_iri), RDF.type, OWL.ObjectProperty))
            declared_predicates.add(predicate_iri)

        subject_node = URIRef(subject_iri)
        object_node = URIRef(object_iri)

        if _is_exact_match(predicate_iri):
            graph.add((subject_node, OWL.equivalentClass, object_node))
            continue

        restriction = BNode()
        graph.add((restriction, RDF.type, OWL.Restriction))
        graph.add((restriction, OWL.onProperty, URIRef(predicate_iri)))
        graph.add((restriction, OWL.someValuesFrom, object_node))
        graph.add((subject_node, RDFS.subClassOf, restriction))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(output_path), format="turtle")
