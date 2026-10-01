"""Servidor MCP: só valida entradas e orquestra chamadas ao núcleo em `calculos/`."""

from mcp.server import MCPServer

from calc_financeira_br import __version__

mcp = MCPServer(
    "calc-financeira-br",
    version=__version__,
    instructions=(
        "Cálculos financeiros brasileiros determinísticos, com memória de cálculo. "
        "Os resultados são simulações, não recomendação de investimento."
    ),
)


def main() -> None:
    """Ponto de entrada do comando `calc-financeira-br` (transporte stdio)."""
    mcp.run("stdio")


if __name__ == "__main__":
    main()
