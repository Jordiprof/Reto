# 03 — Calidad de producto

Referencia: **ISO/IEC 25010:2023**, modelo de calidad de producto software, nueve
características.

## 1. Cómo leer este documento

La regla de esta carpeta es que **ningún ✅ sin evidencia ejecutable**. Aplicada a
25010, que es un modelo lleno de características tentadoras de marcar en verde,
significa que aquí hay tres veredictos posibles:

| Veredicto | Qué significa |
|---|---|
| ✅ **Medido** | Hay una cifra, y al lado el comando que la reproduce |
| 🟡 **Evidencia parcial** | Hay pruebas que lo respaldan, pero no una métrica |
| ⬜ **No medido** | No se ha medido. No es un suspenso: es un hueco declarado |

Un 25010 con nueve ✅ en un proyecto que nunca había medido su cobertura sería
exactamente el "audit pegado" del que `E3 §6.2` dice desconfiar.

## 2. Condiciones de la medición

Todas las cifras salen de la ejecución del **04/09/2026** sobre el commit
`35f3445`, en la **plataforma objetivo del proyecto** (Windows, Python 3.13.15),
con este comando:

```bash
python -m pytest -q --cov=src --cov-report=term
```

Resultado (06/09, tras cerrar `NC-06`): **831 casos**, con **79,86 % de cobertura
de rama**. La medición del 04/09 daba 815 casos y 78,01 %.

*Nota metodológica, porque el camino importa.* Una primera medición se hizo en un
entorno con Python 3.11 y sin salida a internet, donde 5 casos de
`test_documentos.py` no pudieron ejecutarse: descargan el modelo de embeddings y
fallaban con `httpx.ProxyError: 403`. Aquella medición daba 78,01 % con 675
sentencias sin cubrir, y el informe declaró esos 5 como **no ejecutables por el
entorno, no como defectos**. Repetir la medición en 3.13 con red lo confirma:
pasan los 815, y la cobertura sube ligeramente (668 sin cubrir). Se deja escrito
porque una afirmación así solo vale cuando alguien la comprueba, y aquí se
comprobó.

## 3. Resumen por característica

| # | Característica (25010:2023) | Veredicto | Evidencia |
|---|---|---|---|
| 1 | Idoneidad funcional | 🟡 Evidencia parcial | 831 casos; 31 de 46 requisitos trazados (§4) |
| 2 | Eficiencia de desempeño | ⬜ No medido | Sin instrumentación de latencia ni de memoria (§9) |
| 3 | Compatibilidad | 🟡 Evidencia parcial | CLI y bot comparten memoria, con test de invariante |
| 4 | Interacción (usabilidad) | 🟡 Evidencia parcial | 15 fallos de UX hallados probando en real (`E4 §3.4`) |
| 5 | Fiabilidad | ✅ Medido | 79,86 % de rama; degradación entre proveedores probada (§6) |
| 6 | Seguridad | ✅ Medido | 11 de 12 controles de `E2 §8` con test que los ancla (§7) |
| 7 | Mantenibilidad | ✅ Medido | Ratio test/código 1,08:1; `ruff` limpio; 6 ADR (§8) |
| 8 | Flexibilidad | 🟡 Evidencia parcial | 4 proveedores LLM intercambiables por configuración |
| 9 | Protección (*safety*) | 🟡 Evidencia parcial | Avisos anti-alucinación; sin tool con efectos externos |

**Tres medidas, cinco parciales, una sin medir.** Ese reparto es el estado real
del proyecto, no una nota.

## 4. Idoneidad funcional — 🟡

| Métrica | Valor | Cómo se reproduce |
|---|---|---|
| Casos de prueba | **831** en 35 ficheros | `python -m pytest --collect-only -q` |
| Requisitos con verificación trazada | **31 de 46** (67 %) | `python scripts/trazabilidad.py` |
| Requisitos críticos trazados | **5 de 5** (100 %) | ídem; el script falla si baja de ahí |
| Casos de uso trazados | **3 de 7** | ídem |

No sube a ✅ por lo que dice `NC-05`: ningún objetivo (OBJ-01..05) y solo tres de
los siete casos de uso tienen verificación asociada. La funcionalidad está
probada; lo que no está es demostrado que lo probado sea lo que se pidió.

## 5. Cobertura medida, por módulo

La cifra global es **79,86 % de cobertura de rama**: 3.251 sentencias con 622 sin
cubrir, y 924 ramas con 83 parcialmente cubiertas.

> Ojo al leer la tabla de `coverage`: imprime **80 %** porque redondea. El valor
> real es 79,86, y por eso el umbral del CI es 79 y no 80 — ver `NC-06`.

| Módulo | Cobertura | Lectura |
|---|---|---|
| `storage.py` | **100 %** | Cifrado en reposo, completo |
| `llm_errors.py` | **100 %** | Clasificación de errores, completa |
| `resumen_largo.py` | 98 % | |
| `documentos.py` | 97 % | PDF/Word, bomba de descompresión |
| `llm_router.py` | 96 % | |
| `rag.py` | 95 % | |
| `llm_types.py` | 95 % | |
| `config.py` | 94 % | |
| `red_segura.py` | 94 % | El guardián anti-SSRF |
| `tools.py` | 94 % | |
| `agent.py` | 88 % | |
| `noticias.py` | 84 % | El módulo más nuevo |
| `cerrojo.py` | 82 % | Las ramas sin cubrir son de error del SO |
| `llm_client.py` | 78 % | |
| `telegram_bot.py` | 77 % | 927 sentencias, el módulo más grande |
| `voz.py` | 77 % | |
| **`main.py`** | **34 %** | Era el agujero: del 17 % al 34 % con `test_main_cli.py` (`NC-06` cerrada). Lo que queda es `_sesion()`, el bucle interactivo |

Se mide **cobertura de rama y no de línea** a propósito, y está razonado en
`pyproject.toml`: casi todos los controles de este proyecto son un `if` que
rechaza. Con cobertura de línea basta con pasar por el `if` una vez; la de rama
exige haber probado también el camino que **no** rechaza, que es justo donde se
cuelan los fallos de "falla abierto" — el mismo tipo de fallo que `E1 §3.2`
documenta como incidencia real.

**Qué NO demuestra este 78 %.** Que los tests comprueben algo útil. Una línea
ejecutada por un test que no afirma nada cuenta igual que una bien probada. Eso
lo demuestra la mutación, no la cobertura (§6 de `04_ISO-29119_pruebas.md`), y es
la razón por la que este documento no propone perseguir el 100 %.

## 6. Fiabilidad — ✅

| Métrica | Valor | Evidencia |
|---|---|---|
| Cobertura de rama | 79,86 % | §5 |
| Tests de degradación entre proveedores | 24 | `test_llm_router.py` |
| Tests de tolerancia a fallo de API | 19 | `test_avisos_caida.py` |
| Recuperación tras caída del proceso | Probada | `test_cerrojo.py::test_un_proceso_muerto_NO_deja_el_cerrojo_colgado` |
| Reinicio automático en producción | `systemd` con `StartLimitBurst=5` | `scripts/jimmy.service` |

`RNF-02` ("ante un fallo de API o un fichero corrupto, el programa avisa y sigue
vivo") está trazado desde `test_llm_router.py`. La degradación se probó además
contra las APIs reales: `E4 §3.4` documenta 15 fallos encontrados así, que
ninguna suite automática habría encontrado.

## 7. Seguridad — ✅

| Métrica | Valor |
|---|---|
| Controles de `E2 §8` con test que los ancla | **11 de 12** |
| Requisitos críticos de seguridad trazados | 5 de 5 |
| Controles validados por mutación | 8 documentados (`E3 §6.1`), **0 automatizados** (`NC-07`) |
| Riesgos OWASP LLM cerrados | 8 + SSRF; 2 sin declarar (`NC-08`) |
| CVE abiertas en el lockfile | 1, evaluada y aceptada con motivo (`CVE-2026-45829`) |

El único control de `E2 §8` sin ancla en un test es **cadena de suministro**, y
por un motivo legítimo: lo verifica el propio CI (`pip-audit` sin
`continue-on-error`), no un test de Python. Queda anotado en la matriz.

El detalle control a control está en `05_ISO-27001_declaracion_aplicabilidad.md`.

## 8. Mantenibilidad — ✅

| Métrica | Valor | Cómo se reproduce |
|---|---|---|
| Líneas de código | 11.205 en 18 módulos | `wc -l src/*.py` |
| Líneas de test | 12.478 en 35 ficheros | `wc -l tests/*.py` |
| Proporción test:código | **1,11 : 1** | — |
| Incidencias de lint | **0** | `ruff check src tests scripts` |
| Decisiones de arquitectura registradas | 6 ADR | `docs/ADR/` |
| Decisiones fechadas en el diario | 177 | `docs/diario_decisiones.md` |
| Dependencias fijadas con hash | 111 de 111 | `requirements-lock.txt` |

La proporción 1,08:1 sustituye al 1,10:1 que declaraba `E4 §1.1`: la diferencia
es que el código creció desde entonces. Es una medida de **volumen**, no de
calidad — 12.000 líneas de test pueden ejercitar el 30 % del código. Por eso el
dato que manda es el 78 % de §5 y no esta proporción.

Lo que sí es un activo de mantenibilidad poco común y conviene decirlo: el diario
de decisiones con 177 entradas fechadas explica **por qué** está cada cosa como
está. Eso es lo que ISO 12207 llama gestión de la configuración y de la decisión,
y aquí existe desde antes de que nadie lo pidiera.

## 9. Eficiencia de desempeño — ⬜ No medido

No hay ninguna métrica de latencia, uso de memoria ni rendimiento. No hay
instrumentación, ni presupuesto de tiempo de respuesta, ni prueba de carga.

**Y es una decisión defendible**, no un olvido: el tiempo de respuesta lo domina
por completo la llamada al LLM remoto, que está fuera del alcance
(`00_alcance.md` §2). Medir el resto sería medir el ruido.

Lo que sí existe y hace de límite de recursos, aunque no se midiera para eso:

- Presupuesto de **15 llamadas al LLM por turno** (`RF-16`, `E2 §8` capa Coste).
  Nació de un caso real en que un mensaje disparaba 45 llamadas.
- **Timeout de 8 s** en herramientas, y de 90 s solo para Ollama.
- Compactación del historial para que el contexto no crezca sin freno (`RF-26`).

**Acción propuesta**: no medir latencia. Sí declarar el presupuesto de llamadas
como lo que es —un requisito de eficiencia— y trazarlo. Ya está: `RF-16` tiene
ancla en `test_llm_router.py`.

## 10. Las tres características que quedan en 🟡

**Compatibilidad.** CLI y bot comparten memoria, y hay un test de invariante que
lo comprueba en los dos sentidos
(`test_rag.py::test_lo_guardado_por_una_via_lo_encuentra_la_otra`, `RF-18`).
Falta la otra mitad: no se prueba en más de un sistema operativo. El desarrollo
es en Windows y el despliegue en Ubuntu, y esa diferencia ya causó un fallo real
—un lockfile generado en Windows que no veía `uvloop`, commit `a381bc9`—. Un CI
con matriz de sistemas operativos lo habría cazado.

**Interacción.** No hay métrica de usabilidad, y para un bot de un solo usuario
tampoco tendría mucho sentido inventarla. La evidencia es cualitativa y es buena:
`E4 §3.4` documenta 15 fallos de interacción encontrados probando en real, con su
causa raíz. Entre ellos, el mejor hallazgo del proyecto: un mensaje de error que
**bloqueaba correctamente** un acceso a la red interna pero **explicaba cómo
saltarse la protección**.

**Protección (*safety*).** Los avisos anti-alucinación van dentro del resultado
de cada herramienta, en forma de prohibición, y no en el prompt general — lo que
es una decisión de diseño acertada y probada. El límite real está declarado:
ninguna herramienta tiene efectos externos todavía, así que la agencia excesiva
(LLM08) no se ha llegado a probar de verdad. La idempotencia por turno está lista
para cuando la haya, y trazada (`RF-22`, `E2-IDEMPOTENCIA`).

## 11. Qué haría falta para subir de nivel

Por orden de valor, y sin adornos:

1. **Mutación en CI** (`NC-07`). Convertiría el 78 % de cobertura en una cifra
   con significado. Es lo único de esta lista que cambia la naturaleza del dato,
   no su magnitud.
2. **Anclar los 17 identificadores sin traza** (`NC-05`). Sube idoneidad
   funcional de 🟡 a ✅.
3. **Matriz de sistemas operativos en el CI**. Sube compatibilidad, y cierra la
   clase de fallo que ya ocurrió una vez.
4. **Cobertura de `main.py`** (`NC-06`). Sube el número global; es el punto con
   menos valor por hora invertida de los cuatro.
