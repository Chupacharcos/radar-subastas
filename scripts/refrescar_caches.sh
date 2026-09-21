#!/bin/bash
# Refresca las cachés que hayan pasado su plazo y recarga la API si algo cambió.
#
# Por qué existe: `refresco.py` mide la edad de cada caché y sabe volver a
# descargar lo caducado, y `/subastas/vigencia` lo canta en rojo… pero hasta el
# 2026-09-21 NADIE lo ejecutaba. Cuatro cachés llevaban 43 días con un plazo de
# 40, así que la herramienta servía el trimestre anterior "con total aplomo",
# que es justo el fallo que este proyecto persigue en todo lo demás.
#
# Por qué recarga la API: los módulos memorizan los datos en variables de
# módulo (_MUNICIPIOS_MEMORIA, _FIANZAS_MEMORIA, _GVA_MEMORIA). El refresco
# corre en OTRO proceso, así que el uvicorn que está en marcha seguiría
# sirviendo las cifras viejas aunque el disco ya tenga las nuevas.
#
# Quién lo vigila: `demo_smoke` (NeuralOps, martes 05:00) pide
# /subastas/vigencia y avisa por Telegram si `todo_ok` no es true.
set -uo pipefail

cd /var/www/subastas-radar || exit 1

salida=$(runuser -u ubuntu -- /var/www/subastas-radar/venv/bin/python refresco.py --refrescar 2>&1)
codigo=$?
echo "$salida"

if [ $codigo -ne 0 ]; then
    echo "[refresco] FALLÓ con código $codigo — no recargo la API"
    exit $codigo
fi

if echo "$salida" | grep -q "Nada que refrescar"; then
    echo "[refresco] nada caducado; la API sigue con sus datos en memoria"
    exit 0
fi

echo "[refresco] se ha descargado algo nuevo → recargo la API para que lo lea"
systemctl restart subastas-radar.service
sleep 4

if curl -sf --max-time 15 http://127.0.0.1:8010/health >/dev/null; then
    echo "[refresco] API arriba tras la recarga"
else
    echo "[refresco] la API NO responde tras la recarga"
    exit 1
fi
