<#
.SYNOPSIS
    Trae a este ordenador las conversaciones guardadas del bot que corre en la VPS.

.DESCRIPTION
    QUE COPIA Y QUE NO, Y POR QUE.

    Copia SOLO `conversations/`. Es el unico dato irreemplazable del servidor:

      - `chroma_db/`      NO se copia. Es un indice DERIVADO de conversations/.
                          Si se pierde, el bot lo reconstruye solo al arrancar
                          (ver src/rag.py: los ids son deterministas, asi que
                          reindexar no duplica nada).
      - `conversations.db` NO se copia. Guarda metadatos que ya viven en los
                          propios .json, y el bot ni la usa para listar las
                          conversaciones - eso lo saca mirando la carpeta
                          (`listar_conversaciones` hace un glob).
      - El codigo          NO se copia. Esta en GitHub.

    LA CLAVE NO VA AQUI, Y ES DELIBERADO. Los .json estan cifrados con
    CONVERSATIONS_KEY. Guardar la clave junto a la copia seria repetir el
    problema que ya tenemos en el servidor -la caja y la llave en el mismo
    sitio-, y ademas cada backup semanal seria una copia mas de la clave
    rodando por ahi. La clave se guarda UNA VEZ en el gestor de contrasenas.

    Sin esa clave, esta copia es basura cifrada para siempre: Fernet no tiene
    recuperacion. Si no la has guardado todavia, hazlo ANTES de fiarte de este
    script.

.PARAMETER VpsHost
    usuario@ip de la VPS.

.PARAMETER Destino
    Carpeta local donde dejar las copias. Una subcarpeta por fecha.

.EXAMPLE
    .\scripts\backup-vps.ps1

.NOTES
    Pide la contrasena de sudo una vez: las conversaciones son del usuario
    `bot-jimmy`, cuya carpeta esta a 700 para que ningun otro bot pueda
    leerla. `jordi` llega con sudo, que es lo que se usa aqui.
#>
[CmdletBinding()]
param(
    [string]$VpsHost = "jordi@178.104.69.244",
    [string]$Destino = "$env:USERPROFILE\Backups\jimmy",
    [int]$Conservar = 8
)

$ErrorActionPreference = "Stop"

$RutaRemota = "/home/bot-jimmy/python-agentes-ia-dq"
$Fecha      = Get-Date -Format "yyyy-MM-dd_HH-mm"
$Fichero    = "conversations_$Fecha.tar.gz"
$TempRemoto = "/tmp/$Fichero"

Write-Host ""
Write-Host "  Copia de seguridad de las conversaciones de Jimmy" -ForegroundColor Cyan
Write-Host "  $VpsHost  ->  $Destino"
Write-Host ""

if (-not (Test-Path $Destino)) {
    New-Item -ItemType Directory -Path $Destino -Force | Out-Null
    Write-Host "  Creada la carpeta $Destino"
}

# --- 1. Empaquetar en el servidor -------------------------------------------
# `sudo` porque /home/bot-jimmy esta a 700. El chown posterior es para que
# `jordi` pueda descargarselo despues (el tar lo crea root).
# `ssh -t` reserva un terminal: sin el, sudo no puede pedir la contrasena.
Write-Host "  [1/4] Empaquetando en el servidor (te pedira la contrasena de sudo)..."
$comando = "sudo tar czf $TempRemoto -C $RutaRemota conversations && sudo chown jordi:jordi $TempRemoto"
ssh -t $VpsHost $comando
if ($LASTEXITCODE -ne 0) { throw "Fallo al empaquetar en el servidor (codigo $LASTEXITCODE)." }

# --- 2. Descargar -----------------------------------------------------------
Write-Host "  [2/4] Descargando..."
$destinoFichero = Join-Path $Destino $Fichero
scp "${VpsHost}:$TempRemoto" $destinoFichero
if ($LASTEXITCODE -ne 0) { throw "Fallo al descargar (codigo $LASTEXITCODE)." }

# --- 3. Limpiar el servidor -------------------------------------------------
# El temporal lleva conversaciones cifradas, pero no tiene por que quedarse
# en /tmp, que es legible por cualquier usuario de la maquina.
Write-Host "  [3/4] Borrando el temporal del servidor..."
ssh $VpsHost "rm -f $TempRemoto"

# --- 4. Comprobar que lo descargado sirve -----------------------------------
# Un scp que "va bien" y deja un fichero de 0 bytes es un backup que descubres
# roto el dia que lo necesitas. Se comprueba aqui, no entonces.
Write-Host "  [4/4] Comprobando la copia..."
if (-not (Test-Path $destinoFichero)) { throw "El fichero no llego a $destinoFichero." }
$tam = (Get-Item $destinoFichero).Length
if ($tam -lt 100) { throw "La copia pesa $tam bytes: algo fue mal." }

Write-Host ""
Write-Host "  OK  $Fichero  ($([math]::Round($tam/1KB,1)) KB)" -ForegroundColor Green

# --- Rotacion ---------------------------------------------------------------
# Sin esto la carpeta crece para siempre. Se conservan las N mas recientes.
$copias = Get-ChildItem $Destino -Filter "conversations_*.tar.gz" |
          Sort-Object Name -Descending
if ($copias.Count -gt $Conservar) {
    $sobran = $copias | Select-Object -Skip $Conservar
    foreach ($vieja in $sobran) {
        Remove-Item $vieja.FullName -Force
        Write-Host "  Borrada copia antigua: $($vieja.Name)" -ForegroundColor DarkGray
    }
}

Write-Host "  Copias guardadas: $([math]::Min($copias.Count, $Conservar)) de $Conservar"
Write-Host ""
Write-Host "  Recuerda: sin CONVERSATIONS_KEY esto no se puede descifrar." -ForegroundColor Yellow
Write-Host ""
