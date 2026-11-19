# Detiene el dashboard de TimeTrack (el proceso que escucha en 127.0.0.1:8000).
# Solo lo detiene si es un proceso de Python, para no cerrar por error otro programa.
$puerto = 8000

# Socket que escucha en 127.0.0.1:$puerto. No se filtra por -State Listen: en algunos Windows el estado
# aparece vacio; el socket que escucha es el que no tiene conexion remota (RemotePort 0).
function Get-Escucha {
    Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $puerto -ErrorAction SilentlyContinue |
        Where-Object { $_.RemotePort -eq 0 } | Select-Object -First 1
}
$conexion = Get-Escucha
if (-not $conexion) {
    Write-Host "No hay ningun servidor escuchando en 127.0.0.1:$puerto."
    exit 0
}
$proceso = Get-Process -Id $conexion.OwningProcess -ErrorAction SilentlyContinue
if ($proceso -and $proceso.ProcessName -like "python*") {
    Stop-Process -Id $proceso.Id -Force
    Write-Host "Servidor detenido (PID $($proceso.Id))."
} else {
    Write-Host "El puerto $puerto lo usa '$($proceso.ProcessName)', que no es Python: no se toca."
    exit 1
}
