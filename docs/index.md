# sssom-rosetta

sssom-rosetta produces [SSSOM](https://mapping-commons.github.io/sssom/)
mappings between RDF ontologies used in Dutch healthcare. It starts from
existing RDF/OWL ontologies as the source of truth and treats SSSOM as the
interchange format for the mappings themselves, rather than mapping between
schemas.

Mappings are authored as CSV files paired with
[CSVW](https://csvw.org) metadata under `mappings/`. This is the canonical,
human-edited source. Build tooling (`rosetta mapping build`) generates the
derived SSSOM/TSV (with YAML metadata header) and RDF/Turtle representations
from that pair.

## Scope

The first ontology pair covered is:

- [ONZ-G 2.8.1](ontologies/onz-g.md) (Een Ontologie voor de Nederlandse
  Zorg — Generiek)
- [OMOP CDM OWL](ontologies/omop-cdm.md), generated from the OMOP Common
  Data Model v5.4 schema

See [Mappings](mappings/omop-onz-g.md) for the mapping set between these two
ontologies.

## Links

- Source: this repository
- SSSOM specification: https://mapping-commons.github.io/sssom/
- CSVW Metadata Vocabulary: https://www.w3.org/TR/tabular-metadata/
