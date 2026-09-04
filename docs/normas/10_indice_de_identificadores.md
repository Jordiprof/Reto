# 10 — Índice de identificadores

Este proyecto usa **nueve familias de identificadores**. Cinco de ellas —las de
auditoría— no están declaradas en ninguna tabla: solo existen como comentarios
repartidos por el código, el diario y el CI, y hasta hoy la única forma de
reconstruirlas era hacer `grep`.

Es un problema pequeño con una consecuencia concreta: cuando `ci.yml:78` justifica
una excepción de seguridad citando `DEP-01`, quien lee el CI no tiene dónde mirar
qué es `DEP-01`. Esta tabla es ese sitio.

## Familias declaradas en E1

| Familia | Rango | Dónde se define |
|---|---|---|
| `OBJ-nn` | 01–05 | `E1 §1.2` — objetivos del proyecto |
| `RF-nn` | 01–26 | `E1 §2` — requisitos funcionales |
| `RNF-nn` | 01–08 | `E1 §3` — requisitos no funcionales |
| `CU-nn` | 01–07 | `E1 §4` — casos de uso |

Trazabilidad de estos cuatro: `07_matriz_trazabilidad.md`, generado.

## Familias de auditoría (no declaradas hasta ahora)

Nacen de las tres auditorías de seguridad del proyecto (23/07, 27/07 y 04-07/08).
La columna "usos" es el recuento real en el repositorio a 04/09/2026.

### `AUD-` — Hallazgos de auditoría general · 8 identificadores, 63 usos

| ID | Usos | Qué fue |
|---|---|---|
| `AUD-01` | 2 | Un patrón de saneado se comía contenido legítimo del modelo |
| `AUD-02` | 2 | Ninguna llamada de red tenía *timeout* |
| `AUD-03` | 32 | El historial crecía sin freno en cada mensaje y se comía la cuota diaria. Origen de `RF-26` |
| `AUD-04` | 10 | `CONVERSATIONS_KEY` rota se trataba como clave ausente. Ahora una clave rota **para el arranque** |
| `AUD-05` | 7 | No había tope de herramientas ejecutadas en una sola respuesta. Origen de `RF-16` |
| `AUD-06` | 4 | Sin API key en `.env`, el aviso no era claro |
| `AUD-07` | 4 | El error del SDK se enseñaba crudo en Telegram |
| `AUD-08` | 2 | Cerrada sin tocar nada tras evaluarla |

### `SEG-` — Hallazgos de seguridad · 6 identificadores, 78 usos

| ID | Usos | Qué es |
|---|---|---|
| `SEG-02` | 1 | Partición del RAG. Descartado con motivo escrito |
| `SEG-03` | 27 | Presupuesto de llamadas al LLM por turno |
| `SEG-06` | 7 | `if _voz is None` no es atómico: condición de carrera al cargar la voz |
| `SEG-07` | 38 | **Defensa contra inyección de prompt**: delimitar, sanear y declarar que lo citado es dato, nunca orden. El identificador más usado del proyecto |
| `SEG-10` | 3 | `continue-on-error: true` hacía que `pip-audit` saliera siempre en verde |
| `SEG-11` | 2 | El CI instalaba `requirements.txt` mientras el lockfile existía sin que nadie lo instalara |

### `DEP-` — Cadena de suministro · 4 identificadores, 14 usos

| ID | Usos | Qué es |
|---|---|---|
| `DEP-01` | 4 | `CVE-2026-45829` en `chromadb 1.5.9`: evaluada, aceptada con motivo. Ver `05` §3 |
| `DEP-04` | 5 | `--require-hashes`: la versión dice *qué* paquete, el hash fija su *contenido* |
| `DEP-05` | 3 | Acciones de GitHub fijadas por SHA y no por tag (un tag es móvil) |
| `DEP-06` | 2 | `permissions: contents: read` en el workflow: mínimo privilegio |

### `LOG-` — Registro y trazas · 4 identificadores, 51 usos

| ID | Usos | Qué es |
|---|---|---|
| `LOG-01` | 4 | Patrón de saneado del log |
| `LOG-02` | 6 | No fiarse del campo `file_size` de la cabecera: medir la descompresión real |
| `LOG-03` | 3 | La escritura va **bajo el cerrojo**, no suelta |
| `LOG-07` | 38 | Estado que vive lo que dura un turno |

### `AUT-` — Autorización · 1 identificador, 7 usos

| ID | Usos | Qué fue |
|---|---|---|
| `AUT-01` | 7 | El bot respondía dentro de un grupo a un usuario de la lista blanca. Origen de `RF-23`, y según el diario **el hallazgo más valioso de las dos auditorías** |

## Familias de este kit

| Familia | Dónde | Qué identifica |
|---|---|---|
| `NC-nn` | `09_no_conformidades.md` | Las 15 no conformidades |
| `R-nn` | `08_registro_riesgos.md` | Los 16 riesgos |
| `IA-nn` | `06_ISO-42001_gestion_IA.md` | Los 8 riesgos de IA |
| `E2-<CAPA>` | Marcador `@pytest.mark.control(...)` | Los 12 controles de `E2 §8` |
| `TRZ-`, `DOC-` | `scripts/trazabilidad.py` | Códigos de los desajustes que detecta |

## Identificadores de fase

`F3.1`, `F4.4`, `F5.0`, `F5.2`, `F5.5`… aparecen en comentarios del código y
marcan **en qué fase del proyecto** se escribió algo. No son hallazgos ni
requisitos: son marcas temporales, útiles para leer el diario. No se inventarían
aquí.

## Observación

Que `SEG-07` aparezca 38 veces y `LOG-07` otras 38, sin que ninguna tabla los
defina, dice algo bueno y algo malo del proyecto. Lo bueno: el código **cita sus
hallazgos** donde los corrige, que es exactamente donde sirve saberlo. Lo malo:
esa información solo era accesible por `grep`, y los tres informes de auditoría
que los originaron no están en el repositorio (`NC-14`).

Esta tabla resuelve lo segundo sin tocar lo primero.
