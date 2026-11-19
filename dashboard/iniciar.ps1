# Inicia el dashboard de TimeTrack en segundo plano (sin ventana) en http://127.0.0.1:8000
# Uso: doble clic en iniciar.cmd, o:  powershell -ExecutionPolicy Bypass -File dashboard\iniciar.ps1
# Solo escucha en 127.0.0.1 (el dashboard no tiene autenticacion: no lo exponga a la red).
# NOTA: un proceso en segundo plano solo ve las variables de entorno PERSISTENTES del usuario
# (AZURE_DEV_KEY, SIGES_USER, SIGES_PASS, ANTHROPIC_API_KEY), no las puestas con $env: en una terminal.
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot      # dashboard\ -> raiz del proyecto
$puerto = 8000

# Socket que escucha en 127.0.0.1:$puerto. No se filtra por -State Listen: en algunos Windows el estado
# aparece vacio; el socket que escucha es el que no tiene conexion remota (RemotePort 0).
function Get-Escucha {
    Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $puerto -ErrorAction SilentlyContinue |
        Where-Object { $_.RemotePort -eq 0 } | Select-Object -First 1
}

if (Get-Escucha) {
    Write-Host "Ya hay un servidor escuchando en http://127.0.0.1:$puerto - no se inicia otro."
    exit 0
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Write-Error "No se encontro 'python' en el PATH."; exit 1 }

$datos = Join-Path $raiz "data"
New-Item -ItemType Directory -Force -Path $datos | Out-Null
$log = Join-Path $datos "dashboard.log"
$logErr = Join-Path $datos "dashboard.err.log"

Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "dashboard.app.main:app", "--host", "127.0.0.1", "--port", "$puerto" `
    -WorkingDirectory $raiz -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError $logErr

# Espera hasta 15 s a que el puerto responda.
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (Get-Escucha) {
        Write-Host "TimeTrack esta corriendo en http://127.0.0.1:$puerto"
        exit 0
    }
}
Write-Error "El servidor no arranco a tiempo. Revise $logErr"
exit 1
