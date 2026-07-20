"""Timeline source providers (multi-source plan 2.3).

Each provider module exposes the same surface over its own storage:
``fetch_page`` / ``fetch_new`` returning ``SourceUnit`` lists (see base.py),
plus ``days`` and unread counting. The merge layer in ``condenser.timeline``
k-way merges provider pages by unit timestamp with per-source cursors.
"""
