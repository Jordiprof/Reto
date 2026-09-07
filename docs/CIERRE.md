# Cierre del proyecto — 07/09/2026

Estado al dar el trabajo por terminado. Se escribe aquí y no en el diario porque
el diario registra **decisiones**, y esto es un **inventario**: qué queda hecho,
qué queda pendiente y —lo que más importa— **qué separa al servidor de lo que hay
en `main`**.

---

## 1. Lo único que de verdad falta: actualizar la VPS

**El bot que corre 24/7 está servido desde un commit anterior a todo el trabajo
de septiembre.** Hay que decir con precisión qué significa eso, porque suena peor
de lo que es:

> **`src/` no ha cambiado ni un byte** entre `35f3445` (antes del kit de normas) y
> `b8cd510` (hoy). Comprobado con `git diff --stat 35f3445 main -- src/`: salida
> vacía.

Todo el trabajo de estas semanas ha sido **documentación, tests, CI y
configuración de herramientas de desarrollo**. El comportamiento del bot es
idéntico, así que **no actualizar no rompe nada** y el bot no se va a comportar
distinto.

Con una excepción, y esta sí importa:

| Qué cambió | Antes | Ahora |
|---|---|---|
| `pypdf` en `requirements.txt` y `requirements-lock.txt` | `6.15.0` | **`6.17.0`** |

Esa subida arregla **tres CVE que sí nos tocan**:

- `CVE-2026-84309` — bucle infinito en `TreeObject.insert_child`
- `CVE-2026-84310` — tiempos largos y consumo de memoria al recuperar esquemas
- `CVE-2026-84311` — tiempos largos y consumo de memoria al extraer objetos XForm

Las tres son de la misma clase: **un PDF fabricado dispara consumo de memoria o
de tiempo al extraer texto**, que es exactamente lo que hace `documentos.py` con
los PDF que llegan por Telegram — o sea, **contenido de terceros**. En una VPS
pequeña eso no es una molestia, es una caída.

### Los comandos

```bash
ssh <la-vps>
sudo -u bot-jimmy -i
cd /home/bot-jimmy/python-agentes-ia-dq

git pull origin main
venv/bin/pip install --require-hashes -r requirements-lock.txt

exit
sudo systemctl restart jimmy
sudo systemctl status jimmy        # comprobar que arranca
journalctl -u jimmy -n 30 --no-pager
```

Y después, la única verificación que vale: **escribirle por Telegram y mandarle un
PDF**. Si contesta y lo lee, está.

**Por qué `--require-hashes` y no un `pip install pypdf==6.17.0` a secas:** la
versión dice *qué* paquete quieres, el hash fija el *contenido*. Los dos SHA256
de esta versión se calcularon descargando el paquete, no se copiaron de ningún
sitio (lección del 06/09, anotada en el diario). Instalar sin ellos tira por la
borda esa comprobación justo en la máquina donde importa.

**Riesgo de la operación: bajo.** `src/` es idéntico y el resto del lockfile no
se ha tocado — 111 paquetes, uno solo cambia. Si algo fuera mal, `git checkout
35f3445` y reinstalar deja el servidor exactamente como estaba.

---

## 2. Lo que queda abierto, y por qué

Cuatro no conformidades. Ninguna es «no me dio tiempo»; el detalle completo está
en `normas/09_no_conformidades.md`.

| # | Qué falta | Por qué sigue abierta | Cuesta |
|---|---|---|---|
| **NC-10** | Hashes en `requirements-dev-lock.txt` | Necesita `pip-compile` bajo **Python 3.13**, que no había en el entorno donde se preparó. Las dependencias de **producción** sí los tienen, que son las que instala la VPS | Media hora en la máquina correcta |
| **NC-12** | `pytest` y `ruff` viven en `requirements.txt`, así que **se instalan en la VPS** | **Es una decisión, no una limitación.** Sacarlos deja el servidor más limpio, pero cambia lo que instala `jimmy.service` y hay que reinstalar allí. Se dejó a propósito para no tocar la VPS a última hora | Decisión del autor |
| **NC-15** | No hay revisión independiente de seguridad | Estructural: un solo autor. Las tres auditorías las hizo él sobre su propio código y, por bien que estén, **no son independientes**. Queda declarado como lo que es | No cerrable en solitario |
| **NC-16** | Las acciones del CI apuntan a Node.js 20, que GitHub retira | Contrapartida honesta de fijarlas por SHA (`DEP-05`): ganas reproducibilidad y pierdes las actualizaciones automáticas. **Hoy no rompe nada** —GitHub las fuerza sobre Node 24— pero el día que quiten esa compatibilidad, el CI se cae solo sin que nadie haya tocado el proyecto | Resolver los SHA nuevos contra la API de GitHub y actualizar **también** el comentario `# v4` de al lado |

### Y una tarea que no es una no conformidad

**Lanzar a mano el job `Mutacion`** desde la pestaña Actions, ahora que la
invocación está arreglada. La medición del 06/09 cubrió tres de los cuatro
módulos críticos (**167 mutantes, 100 muertos**); `documentos.py` se quedó fuera
porque sus tests descargan el modelo de *embeddings* y el entorno de medición no
tenía red. En el CI, que sí la tiene, entran los cuatro. Es la única cifra del
proyecto que todavía está incompleta por un motivo de entorno y no de criterio.

---

## 3. Lo que sí queda cerrado

| | |
|---|---|
| Niveles del reto | Los cuatro, con su tag |
| Tests | **831**, todos en verde |
| Cobertura de rama | **79,86 %**, medida y con umbral en el CI |
| Trazabilidad | **31 de 46** identificadores, con control que se pone rojo si miente |
| Validación por mutación | Automatizada. 167 mutantes, 100 muertos, y **un control sin test encontrado** |
| No conformidades | 16 detectadas · **10 cerradas** · 2 a medias · 4 abiertas y explicadas |
| Secretos filtrados | **0** en 105 commits |
| Licencia | Propietaria. Todos los derechos reservados |
| Documento para DataQuantum | `presentacion/JIMMY_para_DataQuantum.pdf`, 31 páginas |

---

## 4. Una nota sobre cómo se cierra esto

Este proyecto tiene una norma que ha aguantado desde el primer día: *ninguna
decisión sin fila fechada*. Cerrarlo diciendo «ya está» habría sido romperla en
la última página.

Así que queda escrito lo incómodo: **el servidor va un commit por detrás en una
dependencia con tres vulnerabilidades reales**, y eso no se arregla escribiéndolo
aquí — se arregla con los comandos de la sección 1. Mientras no se ejecuten,
este documento es la anotación honesta de una tarea pendiente, no su solución.
