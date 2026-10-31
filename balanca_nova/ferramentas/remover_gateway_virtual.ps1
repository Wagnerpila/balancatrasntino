# Retira o "Gateway Virtual" (Weightech) e o WTReadWeight, que seguravam a COM3 da balança.
# Depois disso, quem lê o display direto pela COM3 é o servidor.py do sistema novo.
# Precisa rodar como administrador (o Windows pede confirmação). Backup feito antes em
# C:\Backups\Weightech_GatewayVirtual_2026-10-30 (arquivos, configuração e registro do serviço).
$ErrorActionPreference = "Continue"
$log = "C:\Backups\Weightech_GatewayVirtual_2026-10-30\remocao.log"
function Anotar($t) { $l = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $t"; Write-Host $l; Add-Content -Path $log -Value $l -Encoding UTF8 }

Anotar "Inicio da remocao"
$svc = Get-Service GatewayVirtual -ErrorAction SilentlyContinue
if ($svc) {
    Stop-Service GatewayVirtual -Force -ErrorAction SilentlyContinue
    Set-Service GatewayVirtual -StartupType Disabled -ErrorAction SilentlyContinue
    Anotar "Servico GatewayVirtual parado e desativado ($((Get-Service GatewayVirtual).Status))"
}
Get-Process GatewayVirtual, GatewayVirtualService, WeighNetService -ErrorAction SilentlyContinue | Stop-Process -Force

foreach ($u in @("C:\Program Files (x86)\Weightech\Gateway Virtual\unins000.exe",
                 "C:\Program Files (x86)\Weightech\WTReadWeight\unins000.exe")) {
    if (Test-Path $u) {
        $p = Start-Process $u -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait -PassThru
        Anotar "Desinstalador $u terminou com codigo $($p.ExitCode)"
    }
}
if (Get-Service GatewayVirtual -ErrorAction SilentlyContinue) {
    sc.exe delete GatewayVirtual | Out-Null
    Anotar "Servico GatewayVirtual removido com sc delete"
}
# A reserva do endereco http://*:80/PESO/ some junto com o servico; se sobrou uma reserva fixa, tira.
netsh http delete urlacl url=http://*:80/peso/ 2>$null | Out-Null

# WeighNet e WT-Rodo: nao estao instalados nem rodando, mas sao programas da Weightech que podem
# abrir a COM3. Vao para o backup (nao sao apagados).
$guarda = "C:\Backups\Weightech_GatewayVirtual_2026-10-30\retirados"
New-Item -ItemType Directory -Force $guarda | Out-Null
foreach ($d in @("C:\Program Files (x86)\Weightech\WeighNet", "C:\Program Files (x86)\Weightech\WT-Rodo",
                 "C:\Program Files (x86)\Weightech\Gateway Virtual", "C:\Program Files (x86)\Weightech\WTReadWeight")) {
    if (Test-Path $d) { Move-Item $d $guarda -Force; Anotar "Pasta movida para o backup: $d" }
}

$porta = [System.IO.Ports.SerialPort]::new("COM3", 9600)
try { $porta.Open(); $porta.Close(); Anotar "COM3 livre: abriu e fechou normalmente" }
catch { Anotar "COM3 ainda ocupada: $($_.Exception.Message)" }
Anotar "Fim"
Start-Sleep -Seconds 4
