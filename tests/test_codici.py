import pytest

from app.core.codici import normalizza_circoscrizione, normalizza_sezione


@pytest.mark.parametrize(
    "valore, atteso",
    [("123", "123"), ("0123", "123"), (" 12 ", "12"), (7, "7"), (919.0, "919"), ("45.0", "45")],
)
def test_sezione(valore, atteso):
    assert normalizza_sezione(valore) == atteso


@pytest.mark.parametrize("valore", ["", "0", "-3", "12A", "1.5", "abc"])
def test_sezione_non_valida(valore):
    with pytest.raises(ValueError):
        normalizza_sezione(valore)


@pytest.mark.parametrize(
    "valore, atteso",
    [
        ("3", "3"),
        ("03", "3"),
        (8, "8"),
        (1.0, "1"),
        ("Circoscrizione 3", "3"),
        ("circ. 5", "5"),
        ("Circ. VIII", "8"),
        ("iii", "3"),
    ],
)
def test_circoscrizione(valore, atteso):
    assert normalizza_circoscrizione(valore) == atteso


@pytest.mark.parametrize("valore", ["0", "9", "IX", "", "centro"])
def test_circoscrizione_non_valida(valore):
    with pytest.raises(ValueError):
        normalizza_circoscrizione(valore)
