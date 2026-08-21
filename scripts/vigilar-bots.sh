#!/usr/bin/env bash
#
# Comprueba una vez al dia que los bots siguen corriendo, y avisa si no.
#
# POR QUE, SI YA ESTA EL AVISO DE OnFailure. Porque `OnFailure` se dispara UNA
# vez, en el momento del fallo. Si en ese instante no habia red, o el movil
# estaba sin cobertura, o simplemente no viste la notificacion, el bot puede
# quedarse parado dias sin que nadie lo note. Esto es la segunda red: si
# manana sigue caido, vuelve a avisar.
#
# Tambien cubre el caso en que alguien -tu- lo para a mano para depurar algo
# y se olvida de volver a arrancarlo.
#
# NO avisa cuando todo va bien, a proposito: un mensaje diario de "todo
# correcto" se convierte en ruido que se deja de leer en una semana, y
# entonces el dia que llegue el de verdad tampoco lo leeras.
#
set -euo pipefail

# Los bots vigilados. Cuando subas el multiagente, se añade aqui su unidad.
UNIDADES=(
    "jimmy.service"
)

AVISAR="/usr/local/bin/avisar-telegram.sh"

for unidad in "${UNIDADES[@]}"; do
    # `is-enabled` primero: si la unidad no esta habilitada es que la
    # desactivaste tu queriendo, y avisar de eso seria un falso positivo
    # diario para siempre.
    if ! systemctl is-enabled --quiet "$unidad" 2>/dev/null; then
        echo "$unidad no esta habilitada: no se vigila."
        continue
    fi

    if systemctl is-active --quiet "$unidad"; then
        echo "$unidad: activa."
    else
        estado="$(systemctl is-active "$unidad" 2>/dev/null || true)"
        echo "$unidad: NO activa (estado: $estado). Avisando..."
        "$AVISAR" "$unidad" "lleva parada y deberia estar corriendo (estado: $estado)"
    fi
done
