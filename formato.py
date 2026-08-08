"""
Formato de números para leerlos en castellano.

Parece una tontería y no lo es: `f"{49916:,.0f} €"` produce «49,916 €», que un
lector español lee como cuarenta y nueve euros con noventa y seis céntimos. En
una herramienta que habla de cientos de miles de euros, esa coma cuesta la
credibilidad de todo lo demás.
"""
from __future__ import annotations


def euros(valor: float | int | None, decimales: int = 0) -> str:
    """1234567.5 → '1.234.568'. Con el punto de millares y la coma decimal."""
    if valor is None:
        return "—"
    texto = f"{valor:,.{decimales}f}"
    # Se cambian los dos separadores a la vez usando un carácter puente, porque
    # hacerlo en dos pasos convertiría los puntos recién puestos otra vez en comas.
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
