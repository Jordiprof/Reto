# 05 — Declaración de aplicabilidad

Referencia: **ISO/IEC 27001:2022**, Anexo A (93 controles en cuatro temas).

Una declaración de aplicabilidad (*Statement of Applicability*) dice, control a
control: si aplica, si está implantado, con qué evidencia, y —cuando no aplica—
por qué. Lo segundo importa tanto como lo primero: una SoA donde todo aplica y
todo está en verde es una SoA que nadie ha escrito en serio.

**Alcance**: el definido en `00_alcance.md`. **Sin independencia**: el evaluador
es el autor (`00_alcance.md` §3, y `NC-15`).

## 1. Resumen

| Tema del Anexo A | Controles | Aplican | Implantados | Parciales | No implantados |
|---|---|---|---|---|---|
| A.5 Organizativos | 37 | 14 | 8 | 4 | 2 |
| A.6 Personas | 8 | 2 | 0 | 1 | 1 |
| A.7 Físicos | 14 | 1 | 1 | 0 | 0 |
| A.8 Tecnológicos | 34 | 19 | 13 | 6 | 0 |
| **Total** | **93** | **36** | **22** | **11** | **3** |

**36 de 93 controles aplican.** Los 57 restantes no lo hacen porque presuponen
una organización: personal, contratos, proveedores gestionados, instalaciones,
continuidad de negocio. Este es un proyecto académico de un autor, y fingir lo
contrario invalidaría el documento entero.

## 2. Controles aplicables

Leyenda: ✅ implantado · 🟡 parcial · ❌ no implantado

### A.5 — Organizativos

| Control | Estado | Evidencia |
|---|---|---|
| A.5.1 Políticas de seguridad | 🟡 | "Normas del proyecto" en `README.md:297-302` y política de privacidad en `E1 §3.1`. Cumplen la función, pero no hay un documento con ese nombre |
| A.5.7 Inteligencia de amenazas | ✅ | `pip-audit` en CI sobre el lockfile; OWASP Top 10 for LLM como marco (`E3 §6`) |
| A.5.9 Inventario de activos | ✅ | 111 dependencias con hash en `requirements-lock.txt`; catálogo de 7 herramientas en `E1 §2.6`; datos inventariados en `00_alcance.md` §5 |
| A.5.10 Uso aceptable | ✅ | `ADR-006`: activación de herramientas por categorías, con `memoria` y `web` **apagadas al arrancar** |
| A.5.12 Clasificación de la información | ✅ | `00_alcance.md` §5: cada tipo de dato con su sensibilidad y su destino real |
| A.5.14 Transferencia de información | 🟡 | Se sabe y se declara qué sale de la máquina (`E4 §1.0`), pero no está cifrado extremo a extremo — límite aceptado, no control |
| A.5.15 Control de acceso | ✅ | `RF-11`: lista blanca de `user_id` en `TypeHandler` de grupo −1, **antes** del rate limit. 7 tests anclados |
| A.5.16 Gestión de identidades | ✅ | Identidad por token de bot, nunca por teléfono personal (`RNF-05`) |
| A.5.17 Información de autenticación | ✅ | `RF-02`: claves solo de variables de entorno. `.env` fuera del repo, `.env.example` dentro |
| A.5.23 Seguridad en servicios en la nube | 🟡 | Los proveedores LLM están evaluados en `ADR-001` con criterio de privacidad primero, pero no hay acuerdo de tratamiento de datos con ninguno |
| A.5.28 Recogida de evidencias | ✅ | Registro de llamadas a herramientas con solo metadatos y saneado anti log-injection (`RNF-07`) |
| A.5.31 Requisitos legales | ❌ | No hay análisis de RGPD. Se trata un dato biométrico (la voz) y datos personales, aunque sean del propio autor. Ver §4 |
| A.5.34 Privacidad y datos personales | ✅ | `RNF-06` es el requisito rector del proyecto, con `E1 §3.1` entera dedicada y una incidencia real registrada en `E1 §3.2` |
| A.5.35 Revisión independiente | ❌ | No existe y no puede existir aquí. `NC-15` |

### A.6 — Personas

| Control | Estado | Evidencia |
|---|---|---|
| A.6.3 Concienciación y formación | 🟡 | No aplica en su forma organizativa. Su equivalente real es el diario de decisiones: 177 entradas que explican por qué está cada cosa como está |
| A.6.8 Notificación de eventos de seguridad | ❌ | No hay `SECURITY.md` ni canal declarado. `NC-13` |

Los otros 6 (selección de personal, condiciones de empleo, medidas
disciplinarias, fin del empleo, acuerdos de confidencialidad, trabajo remoto) no
aplican: no hay empleados.

### A.7 — Físicos

| Control | Estado | Evidencia |
|---|---|---|
| A.7.9 Seguridad de activos fuera de las instalaciones | ✅ | La VPS es el único activo físico relevante. Cada bot corre con su propio usuario de Linux y su carpeta a 700, para que un bot no pueda leer el `.env` de otro (`scripts/jimmy.service`) |

Los otros 13 presuponen instalaciones propias, y aquí el centro de datos es de
Hetzner. Se declaran fuera de alcance en `00_alcance.md` §2.

### A.8 — Tecnológicos

| Control | Estado | Evidencia |
|---|---|---|
| A.8.2 Derechos de acceso privilegiado | ✅ | Usuario propio por bot, sin privilegios; carpeta a 700 |
| A.8.3 Restricción de acceso a la información | ✅ | Lista blanca + solo chat privado (`RF-11`, `RF-23`), ambos validados por mutación |
| A.8.5 Autenticación segura | ✅ | Token de bot en `.env`; validación de la clave Fernet al arrancar (`test_clave_cifrado.py`) |
| A.8.7 Protección frente a código malicioso | 🟡 | No hay antivirus (no procede), pero sí control del contenido externo: saneado y delimitación (`SEG-07`) |
| A.8.8 Gestión de vulnerabilidades técnicas | ✅ | `pip-audit` en CI **sin** `continue-on-error`; una CVE evaluada y aceptada con motivo escrito. Ver §3 |
| A.8.9 Gestión de la configuración | ✅ | `.env.example` con 16 claves comentadas; lockfile con hashes; unidades systemd versionadas |
| A.8.12 Prevención de fuga de datos | ✅ | Logs de solo metadatos; test que reproduce la fuga real del 27/07 |
| A.8.15 Registro de eventos | ✅ | `RNF-07`, trazado desde `test_logging.py` |
| A.8.16 Actividades de seguimiento | ✅ | `vigilar-bots.timer` + aviso por Telegram al caer, con limitador de uno cada 15 min. Probado en real el 21/08 |
| A.8.20 Seguridad de redes | ✅ | Guardián anti-SSRF propio: lista blanca, bloqueo de IPs internas **antes** de la lista blanca, sin redirecciones. 5 tests anclados |
| A.8.24 Uso de criptografía | ✅ | Fernet para las conversaciones en reposo. `storage.py` al **100 % de cobertura** |
| A.8.25 Ciclo de vida de desarrollo seguro | ✅ | 6 ADR, diario de decisiones, tests por control |
| A.8.26 Requisitos de seguridad de la aplicación | ✅ | `RNF-01` a `RNF-08` en `E1 §3` |
| A.8.27 Arquitectura de sistemas seguros | ✅ | `E2 §8` y §8.1: las 12 capas y, sobre todo, **el orden de las puertas** |
| A.8.28 Codificación segura | ✅ | Validación Pydantic con `extra="forbid"` antes de ejecutar nada; `ruff` limpio |
| A.8.29 Pruebas de seguridad | ✅ | ~204 casos de seguridad (25 % de la suite) + validación por mutación |
| A.8.31 Separación de entornos | 🟡 | Desarrollo en Windows y producción en Ubuntu, sin CI que pruebe los dos. Ya causó un fallo real (lockfile de Windows sin `uvloop`, commit `a381bc9`) |
| A.8.32 Gestión de cambios | ✅ | Git con ramas por nivel, tags por entrega, ADR para lo estructural |
| A.8.33 Información de prueba | ✅ | Ninguna prueba usa datos reales ni gasta cuota: `ProveedorFalso` en `conftest.py` |

## 3. Excepción de seguridad registrada

Una SoA sin sus excepciones no vale nada. Hay exactamente una:

| Campo | Valor |
|---|---|
| **Vulnerabilidad** | `CVE-2026-45829` / `GHSA-f4j7-r4q5-qw2c` en `chromadb 1.5.9` |
| **Naturaleza** | Inyección de código previa a autenticación en el endpoint HTTP del **servidor** de Chroma |
| **Por qué se acepta** | Este proyecto usa `PersistentClient`, modo embebido, **sin abrir ningún puerto**. La superficie vulnerable no se instancia. Verificado, no supuesto |
| **Cómo se materializa** | `--ignore-vuln CVE-2026-45829` en `ci.yml:82`, con el ID explícito |
| **Condición de revisión** | En cuanto se publique parche, se quita la línea |
| **Riesgo residual** | Bajo |
| **Problema** | La justificación completa apunta a `Tareas_Pendientes.md`, **que no está en el repositorio** (`NC-14`). Una excepción de seguridad cuyo motivo remite a un documento ausente no se sostiene sola. Por eso se transcribe aquí |

## 4. El hueco que más pesa: A.5.31 (requisitos legales)

No hay ningún análisis de RGPD, y el sistema:

- trata **datos personales** (conversaciones que pueden incluir salud, familia,
  trabajo),
- trata un **dato biométrico** (la voz — el propio `E4 §1.0` lo señala),
- y **los transfiere a terceros** (Groq, Google, OpenRouter), algunos fuera del
  EEE.

El atenuante real es fuerte: el único titular de los datos es el propio autor, que
es también el responsable del tratamiento, así que el escenario de una brecha con
afectados terceros no se da hoy.

Pero es una propiedad del uso actual, no del sistema. En cuanto la lista blanca
tuviera un segundo `user_id`, el análisis haría falta. Conviene dejarlo escrito
antes de que eso pase, no después.

**Acción propuesta**: una sección corta en `E1 §3` que declare base jurídica,
categorías de datos, destinatarios y plazo de conservación. Media página, y
convierte un hueco en una decisión.

## 5. Controles que este kit añade

| Control | A.x | Qué aporta |
|---|---|---|
| `scripts/trazabilidad.py --check` en CI | A.8.29 | Verificación automática de que la documentación de seguridad no envejece |
| Umbral de cobertura en CI | A.8.29 | Impide que la cobertura baje del 78 % sin que nadie se entere |
| Job de mutación (`mutmut`) | A.8.29 | Preparado, **sin estrenar**: a mano por ahora, no es puerta (`NC-07`) |
| SBOM (`cyclonedx-bom`) | A.5.9 | Inventario de activos en formato estándar |
| `pip-audit` fijado con hash | A.8.8 | Cierra `NC-10`: la herramienta que audita la cadena entraba sin auditar |
