#!/usr/bin/env bash
#
# Avisa por Telegram de que un servicio se ha caido.
#
# POR QUE EXISTE. systemd revive el proceso si MUERE, pero nadie te avisa de
# nada: te enteras tres dias despues, cuando escribes al bot desde el movil y
# no contesta. Esto convierte "me entero cuando le escribo" en "me avisa el".
#
# EL DETALLE QUE LO HACE FUNCIONAR: usa la API HTTP de Telegram directamente
# con curl, NO el bot. Por eso puede avisar de que el bot esta muerto -si
# dependiera del proceso caido, no serviria para nada-. El token es solo una
# credencial de API; funciona igual con el bot parado.
#
# LO QUE ESTO **NO** DETECTA, y conviene saberlo: solo se dispara cuando el
# proceso MUERE. Un bot vivo pero inutil -cuota de Groq agotada, token
# caducado, disco lleno- sigue apareciendo como `active (running)` y esto no
# dira ni mu. Para eso haria falta que el propio bot respondiera a un chequeo
# de salud, que es otra cosa y toca codigo.
#
# POR QUE HAY UN LIMITADOR (probado en real el 21/08/2026). La primera version
# no lo tenia, porque yo daba por hecho que `OnFailure=` salta UNA vez, cuando
# systemd se rinde de reintentar. **Es falso: salta en CADA intento fallido.**
# Al romper el servicio a proposito llegaron cinco mensajes seguidos, uno cada
# 10 segundos -exactamente el RestartSec de la unidad-. Cinco por incidente es
# ruido; y si el bot entra en un ciclo de caerse y levantarse a lo largo de
# horas, son muchisimos mas. Un aviso que satura se acaba silenciando, y
# entonces ya no avisa de nada: el limitador no es comodidad, es lo que hace
# que el aviso siga sirviendo.
#
# Uso:
#   avisar-telegram.sh <unidad-systemd> [motivo]
#
#   AVISAR_FORZAR=1 avisar-telegram.sh ...   <- salta el limitador (pruebas)
#
set -euo pipefail

UNIDAD="${1:?Falta el nombre de la unidad (ej: jimmy.service)}"
MOTIVO="${2:-ha fallado}"

ENV_FILE="/home/bot-jimmy/python-agentes-ia-dq/.env"

# Un solo aviso por unidad cada 15 minutos.
VENTANA_SEGUNDOS=900

# En /run, que es tmpfs: se vacia al reiniciar. Es lo que se quiere - tras un
# reinicio de la maquina, la primera caida vuelve a avisar aunque hubiera
# avisado justo antes de apagarse.
STAMP_DIR="/run/avisar-telegram"
STAMP="${STAMP_DIR}/${UNIDAD//\//_}.stamp"

if [[ "${AVISAR_FORZAR:-0}" != "1" && -f "$STAMP" ]]; then
    transcurrido=$(( $(date +%s) - $(stat -c %Y "$STAMP") ))
    if (( transcurrido < VENTANA_SEGUNDOS )); then
        echo "Ya se aviso de ${UNIDAD} hace ${transcurrido}s. No repito hasta los ${VENTANA_SEGUNDOS}s."
        exit 0
    fi
fi

if [[ ! -r "$ENV_FILE" ]]; then
    echo "No puedo leer $ENV_FILE (¿se ejecuta como root?)" >&2
    exit 1
fi

# Se leen a mano en vez de con `source`: el .env tiene comentarios, comillas y
# una variable multilinea (DOMINIOS_PERMITIDOS_WEB). Un `source` la ejecutaria
# entera y podria romperse por algo que no tiene nada que ver con esto.
leer_var() {
    grep -m1 -E "^$1=" "$ENV_FILE" \
        | cut -d= -f2- \
        | tr -d '"'"'" \
        | xargs 2>/dev/null || true
}

TOKEN="$(leer_var TELEGRAM_BOT_TOKEN)"
# Puede haber varios ids separados por comas: se avisa al primero.
CHAT="$(leer_var TELEGRAM_USER_IDS_PERMITIDOS | cut -d, -f1)"

if [[ -z "$TOKEN" || -z "$CHAT" ]]; then
    echo "Falta TELEGRAM_BOT_TOKEN o TELEGRAM_USER_IDS_PERMITIDOS en el .env" >&2
    exit 1
fi

# Las ultimas lineas del log son casi siempre la respuesta: sin ellas el aviso
# solo dice "algo va mal" y hay que conectarse igual para saber que.
ULTIMAS="$(journalctl -u "$UNIDAD" -n 12 --no-pager -o cat 2>/dev/null | tail -c 2500 || echo '(sin log)')"

MENSAJE="🔴 ${UNIDAD} ${MOTIVO}

Servidor: $(hostname)
Hora:     $(date '+%d/%m/%Y %H:%M:%S %Z')

Ultimas lineas del log:
${ULTIMAS}

Para mirarlo:
  ssh jordi@$(hostname -I | awk '{print $1}')
  sudo systemctl status ${UNIDAD}"

# --data-urlencode y no una URL a pelo: el mensaje lleva saltos de linea,
# dos puntos y acentos; concatenarlo en la URL lo romperia.
# -sS: silencioso pero SIN tragarse los errores (si no llega, quiero saberlo).
curl -sS -X POST \
    "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT}" \
    --data-urlencode "text=${MENSAJE}" \
    --max-time 20 \
    -o /dev/null

# La marca se pone DESPUES de que el curl haya ido bien. Si se pusiera antes y
# el envio fallara (sin red, por ejemplo), el limitador se tragaria los 15
# minutos siguientes de avisos por uno que nunca llego a salir.
mkdir -p "$STAMP_DIR"
touch "$STAMP"

echo "Aviso enviado sobre ${UNIDAD}."
