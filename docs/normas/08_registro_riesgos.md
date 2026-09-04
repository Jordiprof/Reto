# 08 — Registro de riesgos

Referencia: **ISO/IEC 27005:2022** (gestión del riesgo de seguridad de la
información) e **ISO/IEC 23894:2023** (riesgo en IA).

Sustituye y amplía la tabla de `E1 §5`, que tenía 9 riesgos y tres columnas
(riesgo, impacto, mitigación) pero **ni identificador, ni probabilidad, ni
severidad, ni riesgo residual, ni fecha de revisión**. Sin esas columnas no se
puede priorizar, que es para lo único que sirve un registro de riesgos.

## Escalas

**Probabilidad**: Baja (improbable en un año de uso) · Media (verosímil) · Alta
(ha pasado o pasará).
**Impacto**: Bajo (molestia) · Medio (pérdida de datos o de servicio
recuperable) · Alto (fuga de datos personales, o el sistema deja de ser fiable).

| | Impacto Bajo | Impacto Medio | Impacto Alto |
|---|---|---|---|
| **Prob. Alta** | Medio | Alto | **Crítico** |
| **Prob. Media** | Bajo | Medio | Alto |
| **Prob. Baja** | Bajo | Bajo | Medio |

**Propietario**: Jordi en todos los casos — autor único (`00_alcance.md` §3).

## Resumen

| Nivel residual | Riesgos |
|---|---|
| Alto | 1 — `R-05` (aceptado por diseño) |
| Medio | 4 |
| Bajo | 11 |
| **Total** | **16** |

Ningún riesgo queda en Crítico tras tratamiento. El único que queda en Alto está
**aceptado explícitamente** y es el mismo que `E4 §1.0` declara en su veredicto:
la conversación viaja al proveedor del LLM.

## Registro

### Seguridad

| ID | Riesgo | P | I | Inherente | Tratamiento | Control y evidencia | Residual |
|---|---|---|---|---|---|---|---|
| **R-01** | Un desconocido usa el bot | Alta | Alto | **Crítico** | Reducir | Lista blanca de `user_id` en grupo −1, **antes** del rate limit; falla cerrado. 7 tests anclados a `RF-11`; validado por mutación | **Bajo** |
| **R-02** | SSRF: el modelo elige un destino en la red interna o el endpoint de metadatos de la nube | Media | Alto | **Alto** | Reducir | `red_segura.py`: IP interna comprobada **antes** que la lista blanca, sin redirecciones. 5 tests anclados a `E2-RED` | **Bajo** |
| **R-03** | Inyección de prompt vía contenido externo | Alta | Medio | **Alto** | Reducir | `SEG-07` en tres capas. Ver `IA-01` | **Medio** |
| **R-04** | Filtración de una clave de API | Baja | Alto | Medio | Reducir | `.gitignore` antes que la clave; `RF-02`; `gitleaks` sobre 81 commits — **a mano** (`NC-05`) | **Bajo** |
| **R-05** | El texto de la conversación viaja al proveedor del LLM | Alta | Alto | **Crítico** | **Aceptar** | No hay control que lo elimine. Se reduce (`memoria` apagada al arrancar, Ollama local disponible) y **se declara** (`E4 §1.0`) | **Alto — aceptado** |
| **R-06** | Log injection: el nombre de la tool lo elige el modelo | Media | Medio | Medio | Reducir | Saneado a identificador y longitud acotada. 4 tests anclados a `RNF-07` / `E2-TRAZAS` | **Bajo** |
| **R-07** | Bomba de descompresión en un `.docx` | Media | Medio | Medio | Reducir | Comprobación de tamaño descomprimido; probada con una bomba real de 60 MB. `LOG-02`: no se fía del campo `file_size` de la cabecera | **Bajo** |
| **R-08** | La clave de cifrado vive junto a los datos que cifra | Alta | Medio | **Alto** | **Aceptar** | Protege contra el descuido, no contra alguien con acceso a la máquina. Declarado en `E4 §1.0` ("confidencial: no") | **Medio — aceptado** |
| **R-09** | Un mensaje de error enseña a saltarse una protección | Media | Medio | Medio | Reducir | **Ocurrió** (07/08): el bot nombraba la variable de la lista blanca al rechazar una IP interna. Corregido: la IP interna se mira antes y el mensaje no nombra la variable ni para prohibirla. 2 tests | **Bajo** |

### Cadena de suministro y operación

| ID | Riesgo | P | I | Inherente | Tratamiento | Control y evidencia | Residual |
|---|---|---|---|---|---|---|---|
| **R-10** | Dependencia comprometida en PyPI | Baja | Alto | Medio | Reducir | `--require-hashes` sobre 111 paquetes: el hash fija el contenido, no solo la versión (`DEP-04`). `pip-audit` en CI sin `continue-on-error` | **Bajo** |
| **R-11** | Una acción de GitHub reapuntada a otro commit | Baja | Alto | Medio | Reducir | Acciones fijadas por SHA, no por tag (`DEP-05`); `permissions: contents: read` (`DEP-06`) | **Bajo** |
| **R-12** | El bot se cae y nadie se entera | Media | Medio | Medio | Reducir | `systemd` con reinicio y `StartLimitBurst=5`; `vigilar-bots.timer`; aviso por Telegram **independiente del bot** (curl), con limitador de uno cada 15 min. Probado en real el 21/08 | **Bajo** |
| **R-13** | Pérdida de las conversaciones | Baja | Alto | Medio | Reducir | `backup-vps.ps1`: solo `conversations/`, y la clave por separado | **Bajo** |

### Proceso y documentación

| ID | Riesgo | P | I | Inherente | Tratamiento | Control y evidencia | Residual |
|---|---|---|---|---|---|---|---|
| **R-14** | Un requisito de seguridad escrito sin control automático | Media | Alto | **Alto** | Reducir | **Ocurrió** (`E1 §3.2`). `RNF-08`: test por invariante + mutación. Ahora además `trazabilidad.py` se pone rojo si un requisito crítico pierde su ancla | **Bajo** |
| **R-15** | La documentación envejece y deja de describir el sistema | Alta | Medio | **Alto** | Reducir | **Ocurrió** (`NC-01`: `E4 §3.1` declaraba 784 casos donde había 815). `trazabilidad.py --check` en CI compara la documentación contra la realidad en cada push | **Bajo** |
| **R-16** | Una herramienta nueva entra sin evaluar su riesgo | Media | Medio | Medio | **Reducir — pendiente** | `ADR-006` define la fórmula, pero **el código no la calcula** (`NC-11`): `Herramienta` no tiene campo de capacidades ni de nivel | **Medio** |

## Riesgos de IA

Detalle completo en `06_ISO-42001_gestion_IA.md` §2. Resumen:

| ID | Riesgo | Residual |
|---|---|---|
| IA-01 | Inyección de prompt | Medio |
| IA-02 | Alucinación presentada como dato | Bajo |
| IA-03 | Envenenamiento de la memoria (cierra LLM03) | Bajo |
| IA-04 | Robo del modelo (cierra LLM10) | No aplica |
| IA-05 | Fuga al proveedor del LLM | **Alto — aceptado** |
| IA-06 | Dependencia de un proveedor | Bajo |
| IA-07 | La voz es un dato biométrico | Medio |
| IA-08 | Agencia excesiva | Bajo hoy |

## Los tres riesgos que ya se materializaron

Vale la pena señalarlos, porque un registro de riesgos donde ninguno ha ocurrido
suele ser un registro escrito a posteriori:

- **R-09** — el mensaje de error que enseñaba a saltarse la protección. Se pidió
  resumir `https://192.168.1.1/` (el router del autor) y el bot contestó nombrando
  la variable de la lista blanca. Bloqueaba bien y **explicaba cómo saltárselo**.
- **R-14** — un requisito de seguridad escrito sin control automático.
  Documentado como incidencia de privacidad en `E1 §3.2`, y el origen directo de
  `RNF-08`.
- **R-15** — la documentación desactualizada. Es `NC-01`, encontrada en esta
  misma auditoría.

Los tres tienen ahora un control automático. Los tres lo tienen **porque
ocurrieron**, no porque alguien los previera, y eso también conviene decirlo.

## Revisión

| Cuándo | Qué revisar |
|---|---|
| Al añadir una herramienta | `R-16`, `IA-08`, y recalcular el nivel de riesgo según `ADR-006` |
| Al añadir un `user_id` a la lista blanca | `R-05`, `R-08` y el análisis legal ausente (`05` §4) |
| Al cambiar de proveedor LLM | `IA-05`, `IA-06` |
| Cuando se publique parche de `CVE-2026-45829` | Quitar `--ignore-vuln` de `ci.yml` |
| En cada CI | `R-15`, automáticamente |
