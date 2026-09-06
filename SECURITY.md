# Política de seguridad

Cierra la no conformidad **NC-13** de la auditoría del 04/09/2026, y el control
**A.6.8** del Anexo A de ISO/IEC 27001 (notificación de eventos de seguridad).

## Alcance

Este es un proyecto **académico y personal**, de un solo autor, sin usuarios
terceros. No hay equipo de seguridad, ni acuerdo de nivel de servicio, ni
programa de recompensas. Decirlo primero evita que nadie espere de aquí lo que
esto no puede dar.

Lo que sí hay es un compromiso concreto: **si encuentras un fallo, se mira y se
responde**.

## Cómo reportar

Abre una incidencia en el repositorio:
<https://github.com/Jordiprof/Reto/issues>

Si el fallo es **explotable y no está publicado**, no lo detalles en la
incidencia: escribe una que diga solo que has encontrado algo y por qué canal
prefieres dar el detalle.

Plazo realista de primera respuesta: **una semana**. No es un compromiso
contractual, es lo que una persona sola puede sostener.

## Qué está en alcance

| En alcance | Fuera de alcance |
|---|---|
| El código de `src/` | Los proveedores de LLM (Groq, Gemini, OpenRouter, Ollama) |
| La cadena de dependencias de `requirements-lock.txt` | Telegram como plataforma |
| El CI de `.github/workflows/` | La infraestructura de Hetzner |
| Las unidades systemd de `scripts/` | El navegador o el sistema operativo de quien lo ejecute |

El alcance completo, con sus motivos, está en
[`docs/normas/00_alcance.md`](docs/normas/00_alcance.md).

## Lo que este proyecto NO garantiza

Está declarado sin adornos en [`docs/E4_Entrega_Final.md`](docs/E4_Entrega_Final.md) §1.0,
y se repite aquí porque es lo primero que debería saber quien vaya a usarlo:

- **Seguro frente a terceros: sí.** Lista blanca de `user_id` que falla cerrado,
  solo chat privado, guardián anti-SSRF, validación de argumentos.
- **Privado: a medias, por diseño.** El texto de cada turno **viaja al proveedor
  del LLM**. El cifrado protege el disco, no la conversación.
- **Confidencial: no.** La clave de cifrado vive en la misma carpeta que los
  datos que cifra. Protege contra el descuido, no contra alguien con acceso a la
  máquina.

Reportar cualquiera de esos tres puntos como vulnerabilidad no aporta nada: ya
están declarados como limitaciones aceptadas.

## Vulnerabilidades conocidas y aceptadas

Hay **cuatro CVE de `chromadb`** que `pip-audit` detecta y el CI ignora **con
motivo escrito**, porque todas exigen el modo servidor HTTP y este proyecto usa
`PersistentClient` embebido sin abrir puertos:

| CVE | Severidad | Por qué no aplica |
|---|---|---|
| CVE-2026-45829 | — | Inyección de código previa a autenticación en el endpoint HTTP del servidor |
| CVE-2026-45833 | Crítica (9,4) | Inyección de código vía `/api/v2/`, requiere atacante autenticado y `trust_remote_code=true` |
| CVE-2026-45830 | Alta | Un usuario autenticado accede a colecciones de otro *tenant* |
| CVE-2026-45831 | Alta | `SimpleRBACAuthorizationProvider` no comprueba a qué *tenant* aplica un permiso |

Ninguna tiene parche publicado: `chromadb 1.5.9` sigue siendo la última versión.
La justificación completa está en el propio
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) y en
[`docs/normas/05_ISO-27001_declaracion_aplicabilidad.md`](docs/normas/05_ISO-27001_declaracion_aplicabilidad.md) §3.

**Si algún día se levantara un servidor de Chroma, esas cuatro excepciones dejan
de ser válidas de golpe.**

## Cómo se verifica la seguridad aquí

No es una promesa: son controles que se ejecutan.

- **`pip-audit` en cada push**, sin `continue-on-error`. Una CVE nueva tumba el
  CI — ha pasado dos veces (14/08 y 06/09) y las dos se arreglaron subiendo la
  librería, no ignorando el aviso.
- **~204 casos de prueba de seguridad**, una cuarta parte de la batería.
- **Validación por mutación** de los controles críticos: se rompen a propósito y
  se comprueba que un test se pone rojo (`RNF-08`).
- **Dependencias fijadas con hash SHA256** (`--require-hashes`): la versión dice
  *qué* paquete quieres, el hash fija su *contenido*.
- **Acciones de GitHub fijadas por SHA**, no por etiqueta.

El detalle control a control está en
[`docs/normas/05_ISO-27001_declaracion_aplicabilidad.md`](docs/normas/05_ISO-27001_declaracion_aplicabilidad.md).
