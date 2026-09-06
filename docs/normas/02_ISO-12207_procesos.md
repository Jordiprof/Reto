# 02 — Procesos de ciclo de vida

Referencia: **ISO/IEC/IEEE 12207:2017**.

## Advertencia sobre este documento

12207 es la norma de este kit que **menos aporta** a este proyecto, y conviene
decirlo antes que nada en vez de disimularlo con treinta tablas.

La norma describe los procesos de ciclo de vida de una **organización** que
desarrolla software: adquisición, suministro, gestión de recursos humanos,
gestión de proveedores, infraestructura, gestión de la cartera de proyectos. En
un proyecto académico de un autor, la mayoría de esos procesos no es que se hagan
mal: es que no existen, y no deberían.

Así que este documento es **corto a propósito**. Recorre los procesos que sí se
ejecutan, y declara los demás como no aplicables con su motivo. Rellenarlo entero
sería exactamente el "audit pegado" del que `E3 §6.2` dice desconfiar.

## 1. Procesos técnicos (12207 §6.4)

Los que sí se ejecutan, y con qué evidencia.

| Proceso | Estado | Evidencia |
|---|---|---|
| **Análisis de requisitos de negocio/misión** | ✅ | `E1 §1.2` (5 objetivos) y `E1 §1.3` (fuera de alcance declarado) |
| **Definición de requisitos de las partes interesadas** | 🟡 | Los requisitos existen y son buenos; la parte interesada es una sola persona y no está formalizada. Recogida en `00_alcance.md` §4 |
| **Definición de requisitos del sistema/software** | ✅ | `E1`: 26 RF y 8 RNF con prioridad, nivel y estado. Auditados en `01_ISO-29148_requisitos.md` |
| **Definición de la arquitectura** | ✅ | `E2` completo: vista de capas, componentes, flujo de un turno, modelo de datos, y **el orden de las puertas** en §8.1 |
| **Definición del diseño** | ✅ | 6 ADR con contexto, alternativas, decisión y consecuencias |
| **Análisis** | ✅ | `E3`: comparativa medida de proveedores, no supuesta. `ADR-001` documenta que se verificó contra documentación oficial antes de decidir |
| **Implementación** | ✅ | `src/` — 18 módulos, 11.205 líneas |
| **Integración** | ✅ | CI en cada push; memoria compartida entre CLI y bot con test de invariante |
| **Verificación** | ✅ | 815 casos, 78 % de cobertura de rama, mutación. Ver `04_ISO-29119_pruebas.md` |
| **Transición (despliegue)** | ✅ | `scripts/jimmy.service`, desplegado y probado en real el 21/08 en una VPS Hetzner; sobrevivió a dos reinicios arrancando solo |
| **Validación** | 🟡 | Pruebas manuales contra APIs reales (`E4 §3.4`, 15 fallos hallados), no repetibles automáticamente |
| **Operación** | ✅ | `vigilar-bots.timer` + avisos por Telegram independientes del bot |
| **Mantenimiento** | ✅ | El diario de decisiones con 174 entradas fechadas es el registro de mantenimiento |
| **Retirada** | ⬜ | No aplica: el sistema está en operación |

## 2. Procesos de gestión técnica (12207 §6.3)

| Proceso | Estado | Comentario |
|---|---|---|
| **Planificación** | ✅ | `E3 §7`: plan de fases con diagrama de ejecución **planeado contra real**, incluida la explicación del adelanto (§7.2). Poca gente documenta la desviación cuando va a favor |
| **Evaluación y control** | ✅ | Tres auditorías de seguridad y esta evaluación |
| **Gestión de decisiones** | ✅ | 6 ADR + 174 decisiones fechadas con alternativas y motivo. **Es el proceso mejor ejecutado del proyecto** |
| **Gestión de riesgos** | 🟡 | Existía como tabla de 9 filas sin ID ni severidad (`E1 §5`). Sustituida por `08_registro_riesgos.md` |
| **Gestión de la configuración** | ✅ | Git con ramas por nivel y tags por entrega; lockfile con 111 hashes; `.env.example` versionado |
| **Gestión de la información** | ✅ | `docs/` con E1-E4, ADR y diario |
| **Medición** | 🟡 | Antes de este kit no se medía nada salvo el conteo de tests. Ahora: cobertura, trazabilidad y (propuesto) score de mutación |
| **Aseguramiento de la calidad** | 🟡 | CI con lint, pruebas y auditoría de dependencias. Sin revisión independiente (`NC-15`) |

## 3. Procesos no aplicables

Se declaran, en vez de omitirlos, porque una tabla que solo enseña lo que sale
bien no es una evaluación.

| Proceso | Por qué no aplica |
|---|---|
| Adquisición y Suministro (§6.1) | No hay cliente ni contrato. El proyecto no se entrega a un tercero |
| Gestión del modelo de ciclo de vida (§6.2.1) | No hay organización que defina modelos de ciclo de vida |
| Gestión de infraestructura (§6.2.2) | La infraestructura es una VPS y un portátil |
| Gestión de la cartera de proyectos (§6.2.3) | Hay un proyecto |
| Gestión de recursos humanos (§6.2.4) | Hay una persona |
| Gestión de la calidad organizativa (§6.2.5) | Ídem |
| Gestión del conocimiento (§6.2.6) | Su función la cumple el diario de decisiones, sin proceso formal |

## 4. Lo que 12207 sí destapa

A pesar de la advertencia inicial, el recorrido deja tres cosas útiles:

1. **La gestión de decisiones está por encima de lo esperable.** 174 decisiones
   fechadas con alternativas consideradas y motivo es más de lo que documentan
   muchos equipos con proceso formal. En términos de 12207 es el proceso de
   Gestión de Decisiones (§6.3.3) ejecutado en serio, y existía antes de que
   nadie lo pidiera.

2. **La validación es el eslabón flojo.** La verificación (¿está bien
   construido?) está muy bien cubierta: 815 tests, cobertura, mutación. La
   validación (¿es lo que hacía falta?) depende de pruebas manuales que no se
   repiten. Es el mismo hueco que señala `06_ISO-42001_gestion_IA.md` §5 desde
   otro ángulo, y que las dos normas coincidan apuntando ahí es la señal de que
   es real.

3. **La medición no existía.** Hasta esta auditoría, el único indicador del
   proyecto era el número de tests — que mide volumen, no calidad. Ahora hay
   cobertura y trazabilidad medidas, y ambas se recalculan solas.
