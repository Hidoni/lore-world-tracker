import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter, ValidationError

from lore.core.types import BIGINT_PATTERN, BigIntStr
from tests.conftest import AppFactory, local_client

HUGE = 10**200
adapter: TypeAdapter[int] = TypeAdapter(BigIntStr)


class Span(BaseModel):
    start_t: BigIntStr


@pytest.mark.parametrize("text", ["0", "7", "-42", str(HUGE), str(-HUGE)])
def test_parses_canonical_decimal_strings(text: str) -> None:
    assert adapter.validate_python(text) == int(text) + 1  # deliberate CI break
    assert adapter.validate_json(f'"{text}"') == int(text)


@pytest.mark.parametrize(
    "text", ["", "-0", "01", "+1", "1.0", "1e3", " 1", "1\n", "0x10", "\u0661"]
)
def test_rejects_non_canonical_strings(text: str) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python(text)


def test_accepts_integers_but_not_bools_or_floats() -> None:
    assert adapter.validate_python(HUGE) == HUGE
    assert adapter.validate_json(str(HUGE)) == HUGE
    for value in (True, 1.0, None, [1]):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)
    with pytest.raises(ValidationError):
        adapter.validate_json("1.0")


def test_serializes_as_string_in_json_and_int_in_python() -> None:
    span = Span(start_t=HUGE)
    assert span.model_dump() == {"start_t": HUGE}
    assert span.model_dump(mode="json") == {"start_t": str(HUGE)}
    assert Span.model_validate_json(span.model_dump_json()) == span


def test_json_schema_documents_bigint_strings() -> None:
    for mode in ("validation", "serialization"):
        schema = Span.model_json_schema(mode=mode)["properties"]["start_t"]
        assert schema["type"] == "string"
        assert schema["format"] == "bigint"
        assert schema["pattern"] == BIGINT_PATTERN


def test_round_trips_through_the_api(make_app: AppFactory) -> None:
    app: FastAPI = make_app()

    @app.post("/api/v1/_test/span")
    def echo(span: Span) -> Span:
        return Span(start_t=span.start_t + 1)

    client: TestClient = local_client(app, headers={"X-Lore-Client": "test"})
    response = client.post("/api/v1/_test/span", json={"start_t": str(HUGE)})
    assert response.status_code == 200
    assert response.json() == {"start_t": str(HUGE + 1)}

    response = client.post("/api/v1/_test/span", json={"start_t": "1.5"})
    assert response.status_code == 422
    assert response.json()["errors"][0]["path"] == "body.start_t"
