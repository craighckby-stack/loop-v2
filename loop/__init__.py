"""loop-v2: a target-agnostic autonomous code-improvement loop.

The engine pulls a target repository into a working copy, applies mutation
strategies, evaluates each mutation with the repo's own test command, and
emits only passing mutations as branches / patches / PRs. It never runs
against a repo that has not explicitly opted in (see loop.etiquette).
"""

__version__ = "0.1.0"

TOOL_NAME = "loop-v2"
TOOL_VERSION = __version__
# Every commit and PR this tool creates carries this trailer so upstream
# maintainers can always see what touched their code and how to stop it.
TOOL_TRAILER = "X-Loop-Tool: loop-v2/0.1.0 (opt-in autonomous code-improvement)"
STOP_KEYWORD = "loop-stop"
