"""Actions that must wait until the request transaction has committed."""

from collections.abc import Awaitable, Callable

type Action = Callable[[], Awaitable[None]]


class AfterCommit:
    """Collected during a request, run by get_session once the commit has succeeded."""

    def __init__(self) -> None:
        self._actions: list[Action] = []

    def add(self, action: Action) -> None:
        self._actions.append(action)

    async def run(self) -> None:
        for action in self._actions:
            await action()
        self._actions.clear()


def get_after_commit() -> AfterCommit:
    """FastAPI caches a dependency per request, so the session and the storage share one."""
    return AfterCommit()
