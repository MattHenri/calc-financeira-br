"""Configuração dos testes: bloqueia a rede, exceto em testes marcados com `rede`.

Conexões locais (loopback) continuam liberadas, porque o asyncio no Windows usa
um par de sockets locais internamente.
"""

import ipaddress
import socket
from collections.abc import Iterator
from typing import Any

import pytest


class RedeBloqueadaError(RuntimeError):
    """Um teste sem o marcador `rede` tentou acessar a rede."""


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--rede",
        action="store_true",
        default=False,
        help="roda também os testes marcados com `rede`, que acessam APIs reais",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--rede"):
        return
    pular = pytest.mark.skip(reason="acessa a rede; use --rede para rodar")
    for item in items:
        if "rede" in item.keywords:
            item.add_marker(pular)


def _eh_local(endereco: Any) -> bool:
    if not isinstance(endereco, tuple) or not endereco:
        return True  # sockets de arquivo/unix
    host = endereco[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _bloquear_rede(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    if "rede" in request.keywords:
        yield
        return

    connect_original = socket.socket.connect

    def connect_bloqueado(self: socket.socket, endereco: Any) -> None:
        if not _eh_local(endereco):
            raise RedeBloqueadaError(f"acesso à rede bloqueado nos testes: {endereco!r}")
        connect_original(self, endereco)

    monkeypatch.setattr(socket.socket, "connect", connect_bloqueado)
    yield


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
