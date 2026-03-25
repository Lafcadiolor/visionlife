"""Small context builders for the VisionLife command-desk templates.

These functions are intentionally simple. Their job is to name and group
the data that templates need so templates are not fed giant anonymous dicts.

As the front end continues to grow, more of the page/drawer/grid context
assembly should move here and out of results_app.py.
"""

from __future__ import annotations


def build_command_desk_context(**kwargs: str) -> dict[str, str]:
    """Return a template context for the command-desk page shell."""
    return dict(kwargs)


def build_drawer_context(**kwargs: str) -> dict[str, str]:
    """Return a template context for a right-drawer component."""
    return dict(kwargs)


def build_standard_drawer_context(
    *,
    overline: str,
    title: str,
    subline: str,
    top_controls: str,
    summary: str,
    actions_html: str,
    stream_html: str,
    tasks_html: str,
) -> dict[str, str]:
    """Return the context used by the standard artifact-review drawer."""
    return build_drawer_context(
        overline=overline,
        title=title,
        subline=subline,
        top_controls=top_controls,
        summary=summary,
        actions_html=actions_html,
        stream_html=stream_html,
        tasks_html=tasks_html,
    )


def build_todo_drawer_context(
    *,
    overline: str,
    title: str,
    subline: str,
    top_controls: str,
    summary: str,
    stream_html: str,
    tasks_html: str,
) -> dict[str, str]:
    """Return the context used by the to-do capture drawer."""
    return build_drawer_context(
        overline=overline,
        title=title,
        subline=subline,
        top_controls=top_controls,
        summary=summary,
        actions_html="",
        stream_html=stream_html,
        tasks_html=tasks_html,
    )


def build_tracker_grid_context(**kwargs: str) -> dict[str, str]:
    """Return a template context for the tracker grid component."""
    return dict(kwargs)
