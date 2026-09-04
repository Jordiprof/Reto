# 00 — Alcance de la evaluación

Referencia: **ISO/IEC 27001** cláusula 4 (contexto de la organización y alcance
del SGSI) y **ISO/IEC 42001** cláusula 4 (contexto del sistema de gestión de IA).

## 1. Qué se evalúa

El sistema evaluado es **Jimmy**: un asistente conversacional con LLM, accesible
por CLI y por un bot de Telegram, con memoria semántica local, lectura de
documentos, voz y siete herramientas.

Entra en el alcance todo lo que vive en este repositorio y lo que hace falta
para ejecutarlo:

| Elemento | Dónde |
|---|---|
| Código de la aplicación | `src/` — 18 módulos, 11.205 líneas |
| Batería de pruebas | `tests/` — 34 ficheros, 815 casos, 12.111 líneas |
| Cadena de suministro | `requirements-lock.txt` — 111 paquetes con hash SHA256 |
| Integración continua | `.github/workflows/ci.yml` |
| Despliegue | `scripts/jimmy.service` y unidades systemd asociadas, en una VPS Hetzner CX23 (Ubuntu 26.04) |
| Datos en reposo | Conversaciones cifradas con Fernet, índice ChromaDB, índice SQLite |
| Documentación de ingeniería | `docs/` — E1 a E4, 6 ADR y el diario de decisiones |

## 2. Qué NO entra, y por qué

Declararlo importa: un alcance que no dice dónde termina no sirve para nada.

| Fuera del alcance | Motivo |
|---|---|
| Los proveedores de LLM (Groq, Gemini, OpenRouter, Ollama) | Son terceros. Se evalúa **la decisión de usarlos** y los controles alrededor, no su seguridad interna |
| Telegram como plataforma | Ídem. No es cifrado de extremo a extremo, y eso se declara como limitación en `E4 §1.0`, no como control |
| La seguridad física y del sistema operativo de la VPS | Está fuera del repositorio. Se documentan las decisiones que sí toca el proyecto: usuario propio por bot, carpeta a 700 |
| Continuidad de negocio y recuperación ante desastres | No aplica a un proyecto académico personal. Sí hay copia de seguridad (`scripts/backup-vps.ps1`), evaluada en `08` |
| Interfaz web, multiusuario público, fine-tuning | Fuera de alcance del propio proyecto, ya declarado en `E1 §1.3` |

## 3. Roles

Aquí es donde una autoevaluación puede volverse una mentira cómoda, así que se
dice claro.

**Este proyecto tiene un solo autor: Jordi.** Asume a la vez el papel de
desarrollador, de responsable de seguridad, de responsable de calidad y de
auditor.

Eso tiene una consecuencia que ninguna norma permite esquivar: **no hay
independencia entre quien construye y quien audita**. ISO 19011 pide que el
auditor sea objetivo e independiente del área auditada, e ISO 27001 A.5.35 pide
revisión independiente de la seguridad de la información. Ninguna de las dos se
cumple, y no se puede cumplir en este contexto.

Lo que sí se ha hecho para compensarlo, dentro de lo posible:

- **La evidencia se cita por fichero y línea**, para que la comprobación no
  dependa de creerse el documento.
- **Los controles se validan por mutación**: se rompen a propósito y se
  comprueba que un test se pone rojo (`RNF-08`). Es lo más parecido a un
  contradictorio que un autor único se puede aplicar a sí mismo.
- **Las no conformidades se publican**, incluidas las que no se han cerrado.

Donde una norma exige un rol organizativo que aquí no existe (comité de
seguridad, propietario del riesgo distinto del desarrollador, función de
auditoría interna), este kit **declara el hueco** en vez de inventarse el rol.

## 4. Partes interesadas

| Parte | Qué espera |
|---|---|
| El usuario del bot (el propio autor) | Que sus conversaciones no se filtren y que el bot no obedezca a desconocidos |
| El evaluador académico | Poder verificar lo que el proyecto afirma |
| Quien clone el repositorio | Que la documentación no mienta sobre lo que el código hace |

## 5. Datos tratados y su sensibilidad

Determina casi todo lo demás, así que va aquí y no escondido en un anexo.

| Dato | Sensibilidad | Dónde acaba |
|---|---|---|
| Texto de las conversaciones | Alta — puede contener datos personales de salud, familia, trabajo | Disco cifrado (Fernet) **y** el proveedor del LLM, en claro |
| Títulos de conversación | Media | Metadatos **en claro** en el índice SQLite |
| Notas de voz | Alta — la voz es un dato biométrico | Se transcriben en Groq; el audio no se conserva |
| Documentos adjuntos | Variable, la elige el usuario | Memoria del proceso; **no** entran en la memoria permanente |
| `user_id` de Telegram | Identificador personal | Nunca en claro en los logs (`RNF-07`) |
| Claves de API y clave Fernet | Crítica | `.env`, fuera del repositorio |

La consecuencia está aceptada y escrita en `E4 §1.0`: **el sistema es seguro
frente a terceros, privado a medias por diseño, y no es confidencial**, porque
el texto viaja al proveedor del LLM y la clave de cifrado vive en la misma
máquina que los datos que cifra.

## 6. Normas usadas como referencia

Se usan como **marco de evaluación**, no como objetivo de certificación.

| Norma | Para qué se usa aquí |
|---|---|
| ISO/IEC/IEEE 29148:2018 | Calidad y trazabilidad de los requisitos de E1 |
| ISO/IEC/IEEE 12207:2017 | Procesos de ciclo de vida realmente ejecutados |
| ISO/IEC 25010:2023 | Modelo de calidad de producto, 9 características |
| ISO/IEC/IEEE 29119 (partes 1-4) | Política, estrategia, documentación y técnicas de prueba |
| ISO/IEC 27001:2022 + Anexo A | Controles de seguridad de la información |
| ISO/IEC 27005:2022 | Método del registro de riesgos |
| ISO/IEC 42001:2023 | Gestión de sistemas de IA |
| ISO/IEC 23894:2023 | Gestión del riesgo específico de IA |
| ISO 19011:2018 | Formato del informe de no conformidades |
| OWASP Top 10 for LLM Applications | Ya usado por el proyecto en `E3 §6`; se completa aquí |

**Advertencia sobre el texto de las normas.** Este kit se ha escrito aplicando
la estructura y los conceptos de esas normas, no copiando su articulado: el
texto ISO es material con derechos y no se reproduce aquí. Los números de
cláusula sirven para que quien tenga la norma pueda ir al sitio correcto.
