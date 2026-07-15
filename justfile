# justfile for sssom-rosetta.
#
# Run `just` (or `just --list`) to see all recipes. Every recipe delegates to
# `uv run ...`, so this is just a convenience layer over the commands
# documented in README.md; nothing here is required to use the project.
#
# `just` itself is installed as a dev dependency (`rust-just`, see
# pyproject.toml's [dependency-groups].dev) so `uv sync` alone is enough to
# get it: run recipes via `uv run just <recipe>` if `just` isn't also
# installed on your PATH directly.

set dotenv-load := true

mapping_csv := "mappings/omop-onz-g.csv"
mapping_metadata := "mappings/omop-onz-g.metadata.json"
mapping_set_id := "https://raw.githubusercontent.com/plugin-healthcare/sssom-rosetta/main/build/mappings/omop-onz-g.sssom.tsv"
mapping_license := "https://creativecommons.org/publicdomain/zero/1.0/"
curie_map := '{"omop": "https://w3id.org/omop/ontology/", "onz-g": "http://purl.org/ozo/onz-g#", "skos": "http://www.w3.org/2004/02/skos/core#", "semapv": "https://w3id.org/semapv/vocab/", "orcid": "https://orcid.org/"}'

# List all available recipes.
default:
    @just --list

# Install/sync all dependency groups (dev + docs).
install:
    uv sync --all-groups

# Fetch and cache both ontology sources (omop-cdm, onz-g).
fetch:
    uv run rosetta ontology fetch omop-cdm
    uv run rosetta ontology fetch onz-g

# Validate the authored CSV+CSVW mapping set (schema + referential integrity).
validate:
    uv run rosetta mapping validate {{ mapping_csv }} {{ mapping_metadata }} \
        --mapping-set-id "{{ mapping_set_id }}" \
        --license "{{ mapping_license }}" \
        --curie-map '{{ curie_map }}'

# Build the derived SSSOM/TSV + RDF/Turtle artifacts under build/mappings/.
build:
    uv run rosetta mapping build {{ mapping_csv }} {{ mapping_metadata }} \
        --mapping-set-id "{{ mapping_set_id }}" \
        --license "{{ mapping_license }}" \
        --curie-map '{{ curie_map }}'

# Build the combined ontologies + mappings OWL file for Protege (build/protege/).
protege:
    uv run rosetta protege build {{ mapping_csv }} {{ mapping_metadata }} \
        --mapping-set-id "{{ mapping_set_id }}" \
        --license "{{ mapping_license }}" \
        --curie-map '{{ curie_map }}'

# Render the Markdown+HTML mapping report from the generated TSV.
report:
    uv run rosetta mapping report \
        --head build/mappings/omop-onz-g.sssom.tsv \
        --output-markdown build/mappings/omop-onz-g.report.md \
        --output-html build/mappings/omop-onz-g.report.html

# Regenerate docs/mappings/*.md from build/mappings/*.sssom.tsv.
docs-pages:
    uv run rosetta docs generate-mapping-pages

# Build the Zensical documentation site into site/.
docs-build: docs-pages
    uv run zensical build

# Run the test suite.
test:
    uv run pytest

# Lint (ruff check) and verify formatting (ruff format --check), no fixes applied.
# Scoped to this project's own code (src/, tests/); .github/ contains
# vendored wingman skill scripts with pre-existing, unrelated lint issues.
lint:
    uv run ruff check src tests
    uv run ruff format --check src tests

# Auto-fix lint issues and reformat.
format:
    uv run ruff check --fix src tests
    uv run ruff format src tests

# Type-check with ty.
typecheck:
    uv run ty check src

# Run the full local CI-equivalent: lint, typecheck, test.
check: lint typecheck test

# Full local pipeline: fetch ontologies, validate + build + report the
# mapping set, build the Protege export, regenerate docs, and build the site.
build-all: fetch validate build report protege docs-build

# Remove all generated build artifacts (build/, site/).
clean:
    rm -rf build site
