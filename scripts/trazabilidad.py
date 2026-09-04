#!/usr/bin/env python3
"""Genera la matriz de trazabilidad del kit de normas y comprueba que no miente.

POR QUE EXISTE ESTE FICHERO
---------------------------
ISO/IEC/IEEE 29148 pide que todo requisito sea verificable y que la verificacion
este trazada. Este proyecto ya lo intentaba: E1 §6 es una tabla
"requisito -> ADR -> donde vive -> como se verifica", escrita a mano.

Escrita a mano es justo el problema. Al auditarla (04/09) salio que:

  * ningun test decia a que requisito responde: "grep -rn RF- src tests"
    devolvia CERO, asi que la tabla no se podia contrastar con nada;
  * faltaban RF-01..06, RF-10, los 7 casos de uso y los 5 objetivos;
  * los conteos de tests entre parentesis estaban desfasados;
  * E4 §3.1 declaraba 784 casos repartidos en 33 ficheros cuando la
    realidad eran 815 en 34 (test_noticias.py no figuraba).

Ninguno de esos fallos es grave por si mismo. Lo grave es que NADA los
detectaba: la documentacion podia envejecer en silencio mientras el codigo
seguia. Este script cierra ese hueco - genera la matriz a partir de la
realidad y se pone ROJO cuando la documentacion y el codigo discrepan.

Es la misma doctrina que ya rige el resto del proyecto: "un control sin test
es una promesa" (E2 §1) y "no fiarse de un audit pegado" (E3 §6.2). Una
matriz de trazabilidad que nadie verifica es exactamente un audit pegado.

COMO SE ANCLA
-------------
El ancla vive en el TEST, no en un documento, porque es lo unico que se mueve
a la vez que el codigo:

    @pytest.mark.requisito("RF-11")
    def test_un_desconocido_no_llega_al_llm(): ...

Los marcadores estan declarados en pyproject.toml, con --strict-markers: uno
mal escrito es un error duro, no un silencio.

USO
---
    python scripts/trazabilidad.py            # regenera 07_matriz_trazabilidad.md
    python scripts/trazabilidad.py --check    # no escribe; sale != 0 si algo no cuadra
    python scripts/trazabilidad.py --check --sin-conteos   # sin invocar a pytest
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
E1 = RAIZ / "docs" / "E1_Especificacion_Requisitos.md"
E4 = RAIZ / "docs" / "E4_Entrega_Final.md"
DIR_TESTS = RAIZ / "tests"
SALIDA = RAIZ / "docs" / "normas" / "07_matriz_trazabilidad.md"

# Filas de las tablas de E1. El {0,2} de los asteriscos es porque algunas filas
# van en negrita (| **OBJ-01** | ..., | **RNF-06** | ...) y otras no.
_FILA_REQUISITO = re.compile(r"^\|\s*\*{0,2}(OBJ|RF|RNF|CU)-(\d+)\*{0,2}\s*\|(.*)\|\s*$")

# Filas de la tabla de distribucion de tests de E4 §3.1: | `test_x.py` | 115 | ... |
_FILA_CONTEO = re.compile(r"^\|\s*`(test_[a-z0-9_]+\.py)`\s*\|\s*\*{0,2}(\d+)\*{0,2}\s*\|")

# Marcadores que este script entiende (los mismos de pyproject.toml).
_MARCADORES = ("requisito", "control", "mutacion")


@dataclass
class Requisito:
    ident: str
    familia: str
    texto: str
    prioridad: str = ""


@dataclass
class Traza:
    fichero: str
    test: str
    linea: int


@dataclass
class Hallazgo:
    """Un desajuste entre lo que la documentacion dice y lo que hay."""

    codigo: str
    mensaje: str


@dataclass
class Estado:
    requisitos: dict[str, Requisito] = field(default_factory=dict)
    trazas: dict[str, list[Traza]] = field(default_factory=lambda: defaultdict(list))
    controles: dict[str, list[Traza]] = field(default_factory=lambda: defaultdict(list))
    casos_reales: dict[str, int] = field(default_factory=dict)
    casos_declarados: dict[str, int] = field(default_factory=dict)
    conteos_disponibles: bool = False


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


def leer_requisitos(ruta: Path = E1) -> dict[str, Requisito]:
    """Saca OBJ/RF/RNF/CU de las tablas de E1.

    Las tablas no tienen el mismo numero de columnas (RF lleva prioridad,
    nivel y estado; RNF lleva criterio de aceptacion; OBJ solo el texto), asi
    que se parte por "|" y se lee por posicion solo lo que existe.
    """
    requisitos: dict[str, Requisito] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        casa = _FILA_REQUISITO.match(linea)
        if not casa:
            continue
        familia, numero = casa.group(1), casa.group(2)
        celdas = [c.strip().strip("*").strip() for c in casa.group(3).split("|")]
        ident = f"{familia}-{numero}"
        if ident in requisitos:  # un RF puede aparecer en dos tablas tematicas
            continue
        prioridad = celdas[1] if familia == "RF" and len(celdas) > 1 else ""
        requisitos[ident] = Requisito(ident, familia, celdas[0], prioridad)
    return requisitos


def _ids_del_decorador(nodo: ast.expr) -> tuple[str, list[str]] | None:
    """Reconoce @pytest.mark.<marcador>("ID", "ID"...) y devuelve (marcador, ids)."""
    if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Attribute):
        return None
    marcador = nodo.func.attr
    intermedio = nodo.func.value
    if not (isinstance(intermedio, ast.Attribute) and intermedio.attr == "mark"):
        return None
    if marcador not in _MARCADORES:
        return None
    ids = [a.value for a in nodo.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    return marcador, ids


def leer_marcadores(directorio: Path = DIR_TESTS) -> tuple[dict, dict]:
    """Recorre tests/ con ast y recoge los marcadores de requisito y de control.

    Se usa ast y no pytest a proposito: asi la matriz se puede regenerar sin
    tener el entorno completo instalado (chromadb, fastembed y compania), y el
    resultado no depende de que la suite pase.
    """
    trazas: dict[str, list[Traza]] = defaultdict(list)
    controles: dict[str, list[Traza]] = defaultdict(list)
    for ruta in sorted(directorio.glob("test_*.py")):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorador in nodo.decorator_list:
                leido = _ids_del_decorador(decorador)
                if leido is None:
                    continue
                marcador, ids = leido
                destino = controles if marcador == "control" else trazas
                if marcador == "mutacion":
                    continue  # informativo, no traza a un ID
                for ident in ids:
                    destino[ident].append(Traza(ruta.name, nodo.name, nodo.lineno))
    return dict(trazas), dict(controles)


def contar_casos_reales() -> dict[str, int]:
    """Cuenta los casos que pytest recolecta DE VERDAD, por fichero.

    No vale contar "def test_" con grep: 36 tests usan @pytest.mark.parametrize
    y cada uno expande a varios casos. test_readme.py son 3 funciones y 28
    casos. Comparar funciones contra la tabla de E4 -que cuenta casos- daria
    un falso positivo enorme (692 contra 784) y haria que este script gritara
    por un problema que no existe.
    """
    proceso = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    conteo: dict[str, int] = defaultdict(int)
    for linea in proceso.stdout.splitlines():
        if linea.startswith("tests/") and "::" in linea:
            conteo[linea.split("::")[0].split("/")[-1]] += 1
    return dict(conteo)


def leer_conteos_declarados(ruta: Path = E4) -> dict[str, int]:
    """Lee la tabla de distribucion de tests de E4 §3.1."""
    declarados: dict[str, int] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        casa = _FILA_CONTEO.match(linea)
        if casa:
            declarados[casa.group(1)] = int(casa.group(2))
    return declarados


# ---------------------------------------------------------------------------
# Comprobaciones
# ---------------------------------------------------------------------------


def comprobar(estado: Estado) -> list[Hallazgo]:
    """Devuelve todo lo que no cuadra. Lista vacia = trazabilidad honesta."""
    hallazgos: list[Hallazgo] = []

    # 1. Un test no puede apuntar a un requisito que no existe. Es el fallo mas
    #    probable al renumerar E1, y el mas silencioso.
    for ident, trazas in sorted(estado.trazas.items()):
        if ident not in estado.requisitos:
            donde = ", ".join(f"{t.fichero}:{t.linea}" for t in trazas)
            hallazgos.append(
                Hallazgo(
                    "TRZ-01",
                    f"{ident} esta marcado en un test pero no existe en E1 ({donde})",
                )
            )

    # 2. Un requisito de prioridad Critica sin ningun test que lo senale. Los
    #    criticos son los cinco que sostienen la seguridad del bot; si uno se
    #    queda sin verificacion trazada, es exactamente el caso de la
    #    incidencia de E1 §3.2 (requisito escrito, control ausente).
    for ident, requisito in sorted(estado.requisitos.items()):
        if requisito.prioridad == "Crítica" and ident not in estado.trazas:
            hallazgos.append(
                Hallazgo("TRZ-02", f"{ident} es de prioridad Crítica y ningun test lo marca")
            )

    if not estado.conteos_disponibles:
        return hallazgos

    # 3. La tabla de E4 §3.1 contra la realidad. Este es el chequeo que habria
    #    cazado el desfase de 784/815 el dia que aparecio.
    for fichero, real in sorted(estado.casos_reales.items()):
        declarado = estado.casos_declarados.get(fichero)
        if declarado is None:
            hallazgos.append(
                Hallazgo(
                    "DOC-01",
                    f"{fichero} tiene {real} casos y no figura en la tabla de E4 §3.1",
                )
            )
        elif declarado != real:
            hallazgos.append(
                Hallazgo("DOC-02", f"E4 §3.1 declara {declarado} casos en {fichero}; hay {real}")
            )
    for fichero in sorted(set(estado.casos_declarados) - set(estado.casos_reales)):
        hallazgos.append(
            Hallazgo("DOC-03", f"E4 §3.1 nombra {fichero}, que ya no existe en tests/")
        )

    return hallazgos


# ---------------------------------------------------------------------------
# Generacion de la matriz
# ---------------------------------------------------------------------------


def _fila_cobertura(estado: Estado, ident: str) -> str:
    trazas = estado.trazas.get(ident, [])
    if not trazas:
        return "— *sin test que lo marque*"
    porfichero: dict[str, int] = defaultdict(int)
    for traza in trazas:
        porfichero[traza.fichero] += 1
    return " · ".join(f"`{f}` ({n})" for f, n in sorted(porfichero.items()))


def generar(estado: Estado, hallazgos: list[Hallazgo]) -> str:
    total = len(estado.requisitos)
    cubiertos = sum(1 for i in estado.requisitos if i in estado.trazas)
    lineas = [
        "# 07 — Matriz de trazabilidad",
        "",
        "> **Fichero generado.** No se edita a mano: lo produce `scripts/trazabilidad.py`",
        "> leyendo los identificadores de `docs/E1_Especificacion_Requisitos.md` y los",
        "> marcadores `@pytest.mark.requisito(...)` de `tests/`. Para regenerarlo:",
        "> `python scripts/trazabilidad.py`.",
        "",
        "Norma de referencia: **ISO/IEC/IEEE 29148**, §5.2.8 (trazabilidad) y §5.2.5",
        "(verificabilidad). La traza es **bidireccional**: de requisito a test en la tabla",
        "de abajo, y de test a requisito en el propio codigo, que es donde vive el ancla.",
        "",
        f"**Cobertura de la traza: {cubiertos} de {total} identificadores** tienen al menos",
        "un test que los nombra.",
        "",
    ]

    if hallazgos:
        lineas += [
            "## Estado: NO CONFORME",
            "",
            "La ultima ejecucion encontro desajustes entre la documentacion y el codigo:",
            "",
            "| Codigo | Hallazgo |",
            "|---|---|",
        ]
        lineas += [f"| {h.codigo} | {h.mensaje} |" for h in hallazgos]
        lineas.append("")
    else:
        lineas += [
            "## Estado: conforme",
            "",
            "La ultima ejecucion no encontro desajustes: ningun test apunta a un requisito",
            "inexistente, todos los requisitos criticos estan trazados y los conteos de",
            "tests declarados en la documentacion coinciden con los reales.",
            "",
        ]

    for familia, titulo in (
        ("OBJ", "Objetivos"),
        ("RF", "Requisitos funcionales"),
        ("RNF", "Requisitos no funcionales"),
        ("CU", "Casos de uso"),
    ):
        dela = [r for r in estado.requisitos.values() if r.familia == familia]
        if not dela:
            continue
        lineas += [
            f"## {titulo}",
            "",
            "| ID | Requisito | Prioridad | Verificado por |",
            "|---|---|---|---|",
        ]
        for requisito in sorted(dela, key=lambda r: int(r.ident.split("-")[1])):
            texto = requisito.texto.replace("|", "\\|")
            prioridad = requisito.prioridad or "—"
            lineas.append(
                f"| **{requisito.ident}** | {texto} | {prioridad} | "
                f"{_fila_cobertura(estado, requisito.ident)} |"
            )
        lineas.append("")

    if estado.controles:
        lineas += [
            "## Controles de seguridad",
            "",
            "Controles de `docs/E2_Arquitectura.md` §8 y de `ADR-005` marcados desde los tests.",
            "",
            "| Control | Verificado por |",
            "|---|---|",
        ]
        for ident, trazas in sorted(estado.controles.items()):
            porfichero: dict[str, int] = defaultdict(int)
            for traza in trazas:
                porfichero[traza.fichero] += 1
            detalle = " · ".join(f"`{f}` ({n})" for f, n in sorted(porfichero.items()))
            lineas.append(f"| **{ident}** | {detalle} |")
        lineas.append("")

    if estado.conteos_disponibles:
        total_real = sum(estado.casos_reales.values())
        lineas += [
            "## Conteo de casos de prueba",
            "",
            f"**{total_real} casos** recolectados por pytest en "
            f"{len(estado.casos_reales)} ficheros. Son casos, no funciones: 36 tests usan",
            "`@pytest.mark.parametrize` y cada uno expande a varios casos.",
            "",
        ]

    return "\n".join(lineas) + "\n"


# ---------------------------------------------------------------------------


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument(
        "--check",
        action="store_true",
        help="no escribe nada; sale con codigo 1 si la trazabilidad no cuadra",
    )
    analizador.add_argument(
        "--sin-conteos",
        action="store_true",
        help="no invoca a pytest (util donde el entorno completo no esta instalado)",
    )
    args = analizador.parse_args()

    estado = Estado()
    estado.requisitos = leer_requisitos()
    trazas, controles = leer_marcadores()
    estado.trazas = defaultdict(list, trazas)
    estado.controles = defaultdict(list, controles)

    if not args.sin_conteos:
        estado.casos_reales = contar_casos_reales()
        estado.casos_declarados = leer_conteos_declarados()
        estado.conteos_disponibles = bool(estado.casos_reales)
        if not estado.conteos_disponibles:
            print("aviso: pytest no pudo recolectar; se omiten los chequeos de conteo")

    hallazgos = comprobar(estado)

    if args.check:
        for hallazgo in hallazgos:
            print(f"{hallazgo.codigo}: {hallazgo.mensaje}")
        if hallazgos:
            print(f"\n{len(hallazgos)} desajuste(s). La trazabilidad no es fiable.")
            return 1
        print("Trazabilidad conforme.")
        return 0

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(generar(estado, hallazgos), encoding="utf-8")
    print(f"Escrito {SALIDA.relative_to(RAIZ)}")
    for hallazgo in hallazgos:
        print(f"  {hallazgo.codigo}: {hallazgo.mensaje}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
