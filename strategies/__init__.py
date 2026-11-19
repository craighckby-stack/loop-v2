"""Mutation strategies. Each module exposes ``mutate(worktree, rel_files) -> MutationResult``.

A strategy decides WHAT to change; it never decides whether the change ships
(that is the gates' job) and never touches git (that is the client's job).
"""
