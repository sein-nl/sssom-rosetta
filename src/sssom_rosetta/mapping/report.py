"""Render a mapping set diff to Markdown/HTML for PR review and docs pages.

Per AGENTS.md's design principles, this module reads the *generated*
``.sssom.tsv`` (YAML metadata header + TSV rows written by
``mapping.io.write_sssom_tsv``), not the hand-authored CSV, so the report
reflects the fully resolved/validated data. ``sssom.parsers.parse_sssom_table``
(the reference ``sssom-py`` implementation) does the actual TSV/YAML-header
parsing so we don't reimplement that format ourselves; the resulting rows are
then round-tripped through the generated Pydantic ``MappingSet``/``Mapping``
models via ``mapping.validate.validate_schema_conformance``, keeping this
module aligned with the rest of the codebase's "SSSOM is the wire format,
Pydantic is the authoring interface" convention.

This module is used two ways (by later tasks, not here):

1. As a PR-comment style diff between a "base" and "head" ``.sssom.tsv``
   file (``diff_mapping_sets`` + ``render_markdown``/``render_html``).
2. To render the current mapping set's Markdown for the docs site's
   ``docs/mappings/*.md`` pages (``render_markdown`` with ``base=None``, so
   every mapping shows up as "added").

The diff/render split is deliberate: callers compute the diff once via
``diff_mapping_sets`` and can then request Markdown-only, HTML-only, or both
without recomputing it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args, get_origin

import markdown as markdown_lib
from linkml_runtime.utils.metamodelcore import URI
from sssom.parsers import parse_sssom_table

from sssom_rosetta.mapping.validate import validate_schema_conformance
from sssom_rosetta.models.sssom import Mapping, MappingSet


def _is_list_field(annotation: Any) -> bool:  # noqa: ANN401 - inspects a pydantic field annotation
    """Return True if a ``Mapping`` field annotation is (optionally) ``list[...]``."""
    if get_origin(annotation) is list:
        return True
    return any(get_origin(arg) is list for arg in get_args(annotation))


#: ``Mapping`` fields typed as ``list[str]`` (multivalued SSSOM slots, e.g.
#: ``author_id``). ``write_sssom_tsv`` serializes these as a single
#: ``|``-separated string per SSSOM/TSV convention; we split that string
#: back into an actual list before constructing ``Mapping``, since a raw
#: string fails schema validation.
_LIST_FIELDS = frozenset(
    name
    for name, info in Mapping.model_fields.items()
    if _is_list_field(info.annotation)
)

#: Fields compared to decide whether a matched (subject_id, predicate_id,
#: object_id) row pair counts as "changed" between base and head.
_CHANGE_FIELDS = (
    "subject_label",
    "object_label",
    "mapping_justification",
    "confidence",
    "author_id",
    "comment",
)

#: (key, header) pairs used for the added/removed/changed Markdown tables.
_TABLE_COLUMNS = (
    ("subject_id", "Subject"),
    ("predicate_id", "Predicate"),
    ("object_id", "Object"),
    ("mapping_justification", "Justification"),
    ("confidence", "Confidence"),
)


def load_mapping_set_tsv(path: Path) -> MappingSet:
    """Parse a generated ``.sssom.tsv`` (YAML header + TSV rows) into a ``MappingSet``.

    Args:
        path: Path to a ``.sssom.tsv`` file written by
            ``mapping.io.write_sssom_tsv``.

    Returns:
        A validated ``MappingSet`` containing every TSV row as a ``Mapping``.
    """
    msdf = parse_sssom_table(str(path))
    rows: list[dict[str, Any]] = []
    for row in msdf.df.to_dict("records"):
        rows.append(
            {
                key: _parse_list_cell(key, value)
                for key, value in row.items()
                if value is not None and not _is_nan(value)
            }
        )

    metadata: dict[str, Any] = dict(msdf.metadata)
    metadata.setdefault("curie_map", dict(msdf.prefix_map))
    if "mapping_set_id" in metadata:
        metadata["mapping_set_id"] = URI(metadata["mapping_set_id"])
    if "license" in metadata:
        metadata["license"] = URI(metadata["license"])
    metadata["mappings"] = rows
    return validate_schema_conformance(metadata)


def _is_nan(value: Any) -> bool:  # noqa: ANN401 - value comes from a pandas cell
    """Return True for pandas' float NaN sentinel used for missing TSV cells."""
    return isinstance(value, float) and math.isnan(value)


def _parse_list_cell(key: str, value: Any) -> Any:  # noqa: ANN401 - TSV cell values are heterogeneous
    """Parse a multivalued field's TSV cell back into a list, if needed.

    ``write_sssom_tsv`` serializes multivalued ``Mapping`` fields (e.g.
    ``author_id``, typed ``list[str]``) as a single ``|``-separated string
    per SSSOM/TSV convention. Round-tripping that string straight into
    ``Mapping`` fails schema validation, so for known list-typed fields we
    split the string back into an actual list.
    """
    if key not in _LIST_FIELDS or not isinstance(value, str):
        return value
    return value.split("|")


@dataclass
class MappingDiff:
    """The result of diffing two mapping sets, matched by mapping identity."""

    added: list[Mapping] = field(default_factory=list)
    removed: list[Mapping] = field(default_factory=list)
    changed: list[tuple[Mapping, Mapping]] = field(default_factory=list)
    unchanged_count: int = 0


def _mapping_key(mapping: Mapping) -> tuple[str, str, str]:
    """Identity key for matching a mapping across base/head: (subject, predicate, object)."""
    return (
        str(mapping.subject_id),
        str(mapping.predicate_id),
        str(mapping.object_id),
    )


def _differs(before: Mapping, after: Mapping) -> bool:
    """Return True if any of ``_CHANGE_FIELDS`` differs between two matched mappings."""
    return any(getattr(before, name) != getattr(after, name) for name in _CHANGE_FIELDS)


def diff_mapping_sets(base: MappingSet | None, head: MappingSet) -> MappingDiff:
    """Diff two mapping sets, matched by ``(subject_id, predicate_id, object_id)``.

    Args:
        base: The prior version of the mapping set, or ``None`` if there is
            no prior version (every mapping in ``head`` is then "added").
        head: The current version of the mapping set.

    Returns:
        A ``MappingDiff`` describing added, removed, changed, and unchanged
        mappings.
    """
    head_mappings = head.mappings or []
    base_mappings = base.mappings or [] if base is not None else []

    base_by_key = {_mapping_key(mapping): mapping for mapping in base_mappings}
    head_by_key = {_mapping_key(mapping): mapping for mapping in head_mappings}

    added = [mapping for key, mapping in head_by_key.items() if key not in base_by_key]
    removed = [
        mapping for key, mapping in base_by_key.items() if key not in head_by_key
    ]
    changed: list[tuple[Mapping, Mapping]] = []
    unchanged_count = 0
    for key, head_mapping in head_by_key.items():
        base_mapping = base_by_key.get(key)
        if base_mapping is None:
            continue
        if _differs(base_mapping, head_mapping):
            changed.append((base_mapping, head_mapping))
        else:
            unchanged_count += 1

    return MappingDiff(
        added=added, removed=removed, changed=changed, unchanged_count=unchanged_count
    )


def predicate_counts(mapping_set: MappingSet) -> dict[str, int]:
    """Count mappings per ``predicate_id`` in a mapping set.

    Args:
        mapping_set: The mapping set to summarize.

    Returns:
        A dict mapping each ``predicate_id`` to its count, sorted by
        descending count then predicate for stable output.
    """
    counts: dict[str, int] = {}
    for mapping in mapping_set.mappings or []:
        predicate = str(mapping.predicate_id)
        counts[predicate] = counts.get(predicate, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _format_cell(value: Any) -> str:  # noqa: ANN401 - table cell values are heterogeneous
    """Render a mapping field value for a Markdown table cell."""
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def _render_table(mappings: list[Mapping]) -> list[str]:
    """Render a list of mappings as a Markdown table's lines."""
    if not mappings:
        return ["_None_"]
    headers = [header for _, header in _TABLE_COLUMNS]
    lines = [
        f"| {' | '.join(headers)} |",
        f"| {' | '.join(['---'] * len(headers))} |",
    ]
    for mapping in mappings:
        cells = [_format_cell(getattr(mapping, key, None)) for key, _ in _TABLE_COLUMNS]
        lines.append(f"| {' | '.join(cells)} |")
    return lines


def _render_changed_table(changed: list[tuple[Mapping, Mapping]]) -> list[str]:
    """Render before/after pairs of changed mappings as a Markdown table's lines."""
    if not changed:
        return ["_None_"]
    headers = ["Subject", "Predicate", "Object", "Field", "Before", "After"]
    lines = [
        f"| {' | '.join(headers)} |",
        f"| {' | '.join(['---'] * len(headers))} |",
    ]
    for before, after in changed:
        for field_name in _CHANGE_FIELDS:
            before_value = getattr(before, field_name)
            after_value = getattr(after, field_name)
            if before_value == after_value:
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        _format_cell(after.subject_id),
                        _format_cell(after.predicate_id),
                        _format_cell(after.object_id),
                        _format_cell(field_name),
                        _format_cell(before_value),
                        _format_cell(after_value),
                    ]
                )
                + " |"
            )
    return lines


def render_markdown(
    diff: MappingDiff, *, mapping_set: MappingSet, title: str = "Mapping report"
) -> str:
    """Render a Markdown report: summary counts, per-predicate counts, diff tables.

    Args:
        diff: The pre-computed diff (see ``diff_mapping_sets``).
        mapping_set: The "head" mapping set, used for the per-predicate
            counts and the report's title/id context.
        title: Heading text for the report.

    Returns:
        The rendered Markdown text.
    """
    lines = [f"# {title}", ""]
    if mapping_set.mapping_set_id:
        lines.append(f"Mapping set: `{mapping_set.mapping_set_id}`")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Added: {len(diff.added)}")
    lines.append(f"- Removed: {len(diff.removed)}")
    lines.append(f"- Changed: {len(diff.changed)}")
    lines.append(f"- Unchanged: {diff.unchanged_count}")
    lines.append("")

    lines.append("## Mappings per predicate")
    lines.append("")
    counts = predicate_counts(mapping_set)
    if counts:
        lines.append("| Predicate | Count |")
        lines.append("| --- | --- |")
        lines.extend(
            f"| {_format_cell(predicate)} | {count} |"
            for predicate, count in counts.items()
        )
    else:
        lines.append("_None_")
    lines.append("")

    lines.append("## Added")
    lines.append("")
    lines.extend(_render_table(diff.added))
    lines.append("")

    lines.append("## Removed")
    lines.append("")
    lines.extend(_render_table(diff.removed))
    lines.append("")

    lines.append("## Changed")
    lines.append("")
    lines.extend(_render_changed_table(diff.changed))
    lines.append("")

    return "\n".join(lines)


def render_html(markdown_text: str) -> str:
    """Convert rendered Markdown into a standalone HTML page.

    Uses the ``markdown`` library (already an installed transitive
    dependency, pulled in by ``zensical``/``pymdown-extensions`` -- see
    ``uv tree``) with the ``tables`` extension enabled, since the reports
    generated by ``render_markdown`` are headings, lists, and pipe tables.
    No new project dependency is added for this.

    Args:
        markdown_text: Markdown text, typically from ``render_markdown``.

    Returns:
        A standalone HTML document string.
    """
    body = markdown_lib.markdown(markdown_text, extensions=["tables"])
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head><meta charset="utf-8">'
        "<title>Mapping report</title></head>\n<body>\n"
        f"{body}\n</body>\n</html>\n"
    )
