from app.api.errors import STATUS_BY_ERROR
from app.core.exceptions import DomainError, FileStorageError


def _subclasses(cls: type[Exception]) -> set[type[Exception]]:
    direct = set(cls.__subclasses__())
    return direct.union(*(_subclasses(sub) for sub in direct))


def test_every_concrete_domain_error_has_a_status() -> None:
    mapped = tuple(STATUS_BY_ERROR)
    leaves = {cls for cls in _subclasses(DomainError) if not cls.__subclasses__()}

    assert all(issubclass(cls, mapped) for cls in leaves)


def test_storage_error_is_not_a_client_error() -> None:
    assert not issubclass(FileStorageError, DomainError)
