# Cómo se trabaja en este proyecto

Cierra parte de la no conformidad **NC-13**. No inventa nada: recoge las reglas
que ya existían repartidas entre `README.md`, `E2 §1` y los ADR, y les da un
sitio canónico.

Es un proyecto de **un solo autor**. Esto no es una guía para colaboradores
externos: es la norma que se aplica el autor a sí mismo, escrita para que se
pueda comprobar que la cumple.

## Las cuatro normas del proyecto

De `README.md`, y son las que mandan:

1. **Ninguna decisión sin una fila fechada** en `docs/diario_decisiones.md`, con
   sus alternativas consideradas y su porqué. 170 filas a día de hoy.
2. **Toda utilidad sin IA tiene tests.**
3. **Toda excepción queda registrada** en `logs/`.
4. **Los secretos viven en `.env`**; el repositorio solo lleva `.env.example`.

## Las dos doctrinas de verificación

Estas dos son la parte que de verdad distingue a este proyecto, y están en
`E2 §1` y `E3 §6.1`:

> **Un control sin test es una promesa.**
> Si un control de seguridad no tiene un test que lo ejerza, no cuenta como
> implantado. Da igual lo bien escrito que esté el comentario.

> **Un test que nunca has visto fallar no demuestra nada.**
> Los controles críticos se rompen a propósito y se comprueba que un test se
> pone rojo. Es `RNF-08`, y de las ocho mutaciones documentadas, **dos
> sobrevivieron** — no encontraron fallos en el código, encontraron tests que no
> comprobaban lo que decían comprobar.

Corolario, escrito en `tests/conftest.py`: **un control que hay que acordarse de
aplicar no es un control**. Por eso las dos fixtures de aislamiento son
`autouse`.

## Antes de empujar nada

```bash
ruff check src tests scripts          # lo mismo que el CI
python -m pytest -q                    # 880 casos, todos en verde
python scripts/trazabilidad.py --check # la documentacion no miente
```

Los tres tienen que salir limpios. El tercero es nuevo del kit de normas: se
pone rojo si un test apunta a un requisito que no existe, si un requisito
crítico pierde su ancla, o si un conteo declarado en la documentación deja de
cuadrar con la realidad.

## Al tocar un requisito

Si añades o cambias un control que responde a un requisito de
`docs/E1_Especificacion_Requisitos.md`, **ánclalo desde el test**:

```python
@pytest.mark.requisito("RF-11")
def test_un_desconocido_no_llega_al_llm(): ...
```

Los marcadores están declarados en `pyproject.toml` con `--strict-markers`: uno
mal escrito es un error duro, no un silencio. Los cinco requisitos de prioridad
Crítica (RF-02, RF-08, RF-11, RF-17, RF-23) **no pueden quedarse sin ancla**: el
script tumba el CI si pasa.

## Al añadir una dependencia

1. Ponla en `requirements.txt` con versión exacta.
2. Regenera `requirements-lock.txt` con `pip-compile --generate-hashes`.
3. **Lee la cabecera de ese fichero antes**: la entrada de `uvloop` está escrita
   a mano y regenerar en Windows la borra. Ya rompió el CI una vez (14/08).

Si la dependencia es solo de desarrollo o de auditoría, va en
`requirements-dev.txt`, **nunca** en `requirements.txt`: el bot corre 24/7 en una
VPS que instala el lock de producción, y cada paquete de más es superficie y
CVEs que vigilar.

## Al arreglar una CVE

El procedimiento está establecido desde el 14/08 y se repitió el 06/09:

1. **Analizarlas una a una antes de tocar nada.** Verificado, no supuesto.
2. Si nos afecta → **subir la librería**, no ignorar el aviso.
3. Si no nos afecta y no hay parche → `--ignore-vuln` con el ID explícito y
   **el motivo escrito entero en el propio `ci.yml`**, no en un documento aparte
   que puede desaparecer (esa fue `NC-14`).
4. Editar el lockfile **quirúrgicamente**, solo el bloque afectado.
5. Comprobar en local con el mismo comando que ejecuta el CI.

## Git

- Ramas `feature/*` hacia `main`; un tag por nivel de entrega.
- Mensajes de commit: frases narrativas en castellano que expliquen **el
  porqué**, no solo el qué. Mira el historial: no se usa Conventional Commits, y
  es deliberado.

## Las normas ISO

`docs/normas/` evalúa el proyecto contra 29148, 12207, 25010, 29119, 27001 y
42001. Si tocas algo que esos documentos citan —conteos de tests, cobertura,
número de decisiones del diario— **actualízalo ahí también**. Ese desfase es
justo lo que el kit existe para evitar, y `scripts/trazabilidad.py` solo vigila
una parte.
