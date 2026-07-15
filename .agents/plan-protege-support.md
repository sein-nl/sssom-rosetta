# Plan: combined Protege-ready TTL export

## Problem

The existing `write_ttl` (`src/sssom_rosetta/mapping/io.py`) emits one flat
triple per mapping: `subject_id predicate_id object_id`. This is correct
SSSOM/RDF and fine for `build/mappings/omop-onz-g.ttl`, but it does not work
well when the combined ontologies + mappings are opened in Protege:

- SKOS mapping properties (`skos:exactMatch`, `skos:broadMatch`,
  `skos:narrowMatch`, `skos:relatedMatch`) are typed as annotation
  properties by SKOS itself. In OWL 2 DL, object properties may only
  connect individuals, never two classes directly.
- Since our mappings connect two OWL *classes* (an OMOP CDM class and an
  ONZ-G class), Protege's structural reasoner treats the flat triple as an
  annotation assertion, regardless of how the predicate is typed.
- OntoGraf only draws edges for structural relationships (subclassing and
  object properties between classes via restrictions); it ignores
  annotation assertions entirely. Result: mapping edges are invisible in
  OntoGraf even though the triples are present in the graph.

## Fix

For a Protege-specific combined export only (not the canonical SSSOM TTL),
represent each mapping as an OWL existential restriction axiom instead of a
flat triple:

```
Class_A rdfs:subClassOf [
  a owl:Restriction ;
  owl:onProperty <predicate> ;
  owl:someValuesFrom Class_B
] .
```

and explicitly declare each SKOS predicate used as `owl:ObjectProperty` in
the emitted graph. `skos:exactMatch` may instead be emitted as
`owl:equivalentClass`, since that is a valid, more precise OWL DL class-level
axiom for an exact match (decide during implementation).

This keeps `build/mappings/*.ttl` (the canonical SSSOM artifact, flat
triples) untouched, and adds a new, separate, additive artifact purely for
interactive exploration in Protege/OntoGraf.

## Steps

1. **Restriction writer** (`protege-restriction-writer`)
   Add a new function (e.g. `mapping/protege.py`: `write_owl_restrictions` or
   `write_protege_ttl`) that, for each `Mapping` in a `MappingSet`, emits an
   OWL existential-restriction axiom instead of a flat triple, and declares
   each distinct predicate IRI used as `rdf:type owl:ObjectProperty` in the
   emitted graph. Keep the existing `write_ttl` (flat triple) function
   untouched for the standard `build/mappings/*.ttl` artifact; this is a
   separate, additive writer for the Protege-specific combined export.

2. **CLI command** (`protege-combine-cli`, depends on step 1)
   Add a new CLI subcommand, e.g. `rosetta protege build`, under a new
   `protege_app` Typer sub-app (or under `docs_app`), that:
   - loads the two cached ontology graphs from
     `data/ontologies/<name>/<version>/ontology.ttl` (omop-cdm, onz-g) via
     rdflib,
   - loads/validates the mapping set from `mappings/omop-onz-g.csv` +
     `.metadata.json` the same way `mapping build` does,
   - calls the new restriction-writer to produce mapping axioms instead of
     flat triples,
   - merges all graphs (ontologies + restriction axioms + ObjectProperty
     declarations) into one `rdflib.Graph`,
   - serializes to `build/protege/omop-onz-g.combined.ttl` (parent dirs
     created; `build/` already gitignored).
   Print the output path on success, matching existing CLI command
   conventions (see `ontology_fetch`, `mapping_build` in `cli.py`).

3. **Tests** (`protege-tests`, depends on steps 1 and 2)
   Add `tests/mapping/test_protege.py` (or similar) with a small fixture
   `MappingSet` (2-3 rows covering `exactMatch` and `broadMatch`) asserting:
   - the emitted graph contains a blank-node `owl:Restriction` with correct
     `owl:onProperty`/`owl:someValuesFrom` for each non-`exactMatch`
     mapping,
   - `exactMatch` is emitted via `owl:equivalentClass` (or restriction, per
     the decision made in step 1),
   - each used predicate IRI is asserted as `owl:ObjectProperty`.
   Add a CLI test (`tests/test_cli.py`) invoking the new `rosetta protege
   build` command against fixture ontologies + mapping CSVs and asserting
   the combined TTL file is written and parses cleanly with rdflib.

4. **README documentation** (`protege-readme-section`, depends on step 2)
   Add a new README.md subsection "Exploring the combined graph in Protege"
   (peer to the existing "Exploring the graph in GraphDB" subsection)
   explaining:
   - how to build the combined file (`rosetta protege build`, output at
     `build/protege/omop-onz-g.combined.ttl`),
   - opening it in Protege (File > Open),
   - why flat SKOS mapping triples between two classes get silently demoted
     to annotation-property assertions in OWL 2 DL (object properties can
     only connect individuals, not classes), causing OntoGraf to ignore
     them entirely,
   - how this project avoids that by emitting existential restriction
     axioms (`Class_A rdfs:subClassOf (predicate some Class_B)`) instead of
     flat triples for the Protege export specifically,
   - how to configure OntoGraf itself in Protege to show these edges:
     Window > Views > Ontology Views > OntoGraf, then in OntoGraf's
     filter/arc-types panel enable the
     `skos:exactMatch`/`broadMatch`/`narrowMatch`/`relatedMatch` object
     properties so edges render between the OMOP and ONZ-G class nodes.
