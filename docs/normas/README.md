# Kit de normas ISO

Evaluación de este proyecto contra cuatro familias de normas ISO, en formato de
auditoría. Doce documentos, uno de ellos generado por script.

## Antes de leer nada: qué es esto y qué no es

**Esto es** una autoevaluación. La hace el propio autor sobre su propio proyecto,
con evidencia citada por fichero y línea para que cualquiera pueda ir a
comprobarla.

**Esto no es** una certificación, ni una auditoría independiente, ni una
declaración de conformidad. Un proyecto académico de un solo autor no se
certifica, y decirlo aquí arriba vale más que insinuar lo contrario en 300
líneas. Por eso ningún documento de esta carpeta dice "conforme a ISO 27001":
dicen **"evaluado contra"**, que es lo que de verdad ha pasado.

El criterio lo marca el propio proyecto, que ya lo tenía escrito antes de que
existiera esta carpeta:

> *Un control sin test es una promesa.* — `E2 §1`
>
> *No fiarse de un "audit" pegado.* — `E3 §6.2`
>
> *Seguro sí, privado a medias, confidencial no.* — `E4 §1.0`

Aplicado aquí: **ningún ✅ sin evidencia que se pueda ejecutar**. Donde no hay
evidencia, el documento dice "no medido" o abre una no conformidad. Hay **16**
en `09_no_conformidades.md` — **10 cerradas, 2 a medias y 4 abiertas** tras la
segunda pasada del 06/09. Ese número es el dato más honesto del kit.

## Los documentos

| # | Documento | Norma | Qué contiene |
|---|---|---|---|
| 00 | [Alcance](00_alcance.md) | 27001 cl.4 · 42001 cl.4 | Qué entra, qué no, y quién asume cada papel |
| 01 | [Requisitos](01_ISO-29148_requisitos.md) | ISO/IEC/IEEE 29148 | Los 46 identificadores de E1 auditados uno a uno |
| 02 | [Procesos](02_ISO-12207_procesos.md) | ISO/IEC/IEEE 12207 | Procesos de ciclo de vida ejecutados y N/A declarados |
| 03 | [Calidad de producto](03_ISO-25010_calidad.md) | ISO/IEC 25010 | Las 9 características, con métricas medidas |
| 04 | [Pruebas](04_ISO-29119_pruebas.md) | ISO/IEC/IEEE 29119 | Política, estrategia y reporte sobre 831 casos |
| 05 | [Declaración de aplicabilidad](05_ISO-27001_declaracion_aplicabilidad.md) | ISO/IEC 27001 Anexo A | Controles aplicables, implantados y descartados |
| 06 | [Gestión de IA](06_ISO-42001_gestion_IA.md) | ISO/IEC 42001 · 23894 | Riesgos propios de un sistema con LLM |
| 07 | [Matriz de trazabilidad](07_matriz_trazabilidad.md) | 29148 §5.2.8 | **Generado**. Requisito → test, en los dos sentidos |
| 08 | [Registro de riesgos](08_registro_riesgos.md) | 27005 · 23894 | Riesgos con ID, probabilidad, impacto y residual |
| 09 | [No conformidades](09_no_conformidades.md) | 19011 cl.6 | Los 16 hallazgos, con plan de acción |
| 10 | [Índice de identificadores](10_indice_de_identificadores.md) | — | Las familias AUD-, SEG-, DEP-, LOG-, AUT- |

## Lo único que aquí es ejecutable

La trazabilidad. El resto son documentos; esto es un control:

```bash
python scripts/trazabilidad.py --check
```

Sale con código distinto de cero si un test apunta a un requisito que no existe,
si un requisito crítico se queda sin verificación trazada, o si un conteo de
tests declarado en la documentación deja de cuadrar con la realidad.

Se ejecuta en el CI, en el job `normas`. Está validado por mutación (se rompe a
propósito y se comprueba que se pone rojo), como pide `RNF-08`: ver
`04_ISO-29119_pruebas.md` §5.

## Qué encontró esta auditoría

Lo resumido; el detalle en `09_no_conformidades.md`.

- **La documentación envejecía en silencio.** `E4 §3.1` declaraba 784 casos de
  prueba en 33 ficheros; había 815 en 34, y `test_noticias.py` no figuraba.
  Corregido, y ahora hay un control que lo impide.
- **Ningún test decía a qué requisito responde.** `grep -rn "RF-" src tests`
  devolvía cero. Ahora 103 tests llevan ancla y 31 de los 46 identificadores
  están trazados.
- **Los cinco requisitos críticos** (RF-02, RF-08, RF-11, RF-17, RF-23) están
  los cinco trazados, y el script se pone rojo si uno se queda sin test.
- **La cobertura nunca se había medido**: ahora **79,86 % de rama**. `src/main.py`
  era el agujero al 17 %; con `test_main_cli.py` sube al 34 % (`NC-06`).
- **La validación por mutación era manual.** `RNF-08` la exige y se hacía a
  mano, ocho mutaciones escritas en prosa en `E3 §6.1`. Un requisito verificado
  a mano no se vuelve a verificar nunca. Automatizada el 06/09: **167 mutantes,
  100 muertos**. Y en la primera ejecución encontró un **control sin test** en
  el guardián anti-SSRF (`NC-07`).
- **`ADR-006` define una fórmula de riesgo que el código no calcula.** Vive solo
  en el documento.

## Fecha y alcance temporal

Auditoría del **04/09/2026** sobre el commit `35f3445`, con una **segunda pasada
el 06/09** que cerró NC-06, NC-08, NC-13 y NC-14 y abrió NC-16. Las cifras de
cobertura y de conteo de tests se regeneran solas en cada CI.
