import pytest
from pydantic import ValidationError

from app.schemas.project import ProjectCreate


def test_text_fields_are_stripped() -> None:
    project = ProjectCreate(name="   BRCA cohort   ", lead_scientist="   Rosalind Franklin   ")

    assert project.name == "BRCA cohort"
    assert project.lead_scientist == "Rosalind Franklin"


def test_description_is_optional() -> None:
    project = ProjectCreate(name="BRCA cohort", lead_scientist="Rosalind Franklin")

    assert project.description is None


@pytest.mark.parametrize("field", ["name", "lead_scientist"])
@pytest.mark.parametrize("value", ["", "   ", "x" * 101])
def test_invalid_required_text_is_rejected(field: str, value: str) -> None:
    data = {"name": "BRCA cohort", "lead_scientist": "Rosalind Franklin", field: value}

    with pytest.raises(ValidationError):
        ProjectCreate.model_validate(data)


def test_client_cannot_set_server_fields() -> None:
    project = ProjectCreate.model_validate(
        {
            "name": "BRCA cohort",
            "lead_scientist": "Rosalind Franklin",
            "project_id": "x",
            "completed_at": "2026-01-01T00:00:00Z",
        }
    )

    assert set(project.model_dump()) == {"name", "lead_scientist", "description"}
