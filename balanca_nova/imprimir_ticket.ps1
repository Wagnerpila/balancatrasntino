# Imprime a imagem do ticket direto na impressora, sem janela (usado pelo servidor.py).
# Uso: powershell -File imprimir_ticket.ps1 -Imagem ticket.png -Impressora "EPSON L395 Series" -Copias 2
param(
    [Parameter(Mandatory = $true)][string]$Imagem,
    [string]$Impressora = "",
    [int]$Copias = 1,
    [string]$Arquivo = ""   # so para teste: grava em arquivo (ex.: impressora "Microsoft Print to PDF")
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

try {
$img = [System.Drawing.Image]::FromFile($Imagem)
try {
    $doc = New-Object System.Drawing.Printing.PrintDocument
    if ($Impressora) { $doc.PrinterSettings.PrinterName = $Impressora }
    if (-not $doc.PrinterSettings.IsValid) { throw "Impressora '$Impressora' nao encontrada." }
    $doc.PrinterSettings.Copies = [int16][Math]::Max(1, $Copias)
    if ($Arquivo) { $doc.PrinterSettings.PrintToFile = $true; $doc.PrinterSettings.PrintFileName = $Arquivo }
    $doc.DocumentName = "Ticket de pesagem"
    $doc.PrintController = New-Object System.Drawing.Printing.StandardPrintController  # sem janela de progresso
    $doc.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins(20, 20, 20, 20)
    $doc.add_PrintPage({
        param($s, $e)
        # a imagem e uma pagina A4 inteira: encaixa na area util mantendo a proporcao
        $area = $e.MarginBounds
        $escala = [Math]::Min($area.Width / $img.Width, $area.Height / $img.Height)
        $w = [int]($img.Width * $escala); $h = [int]($img.Height * $escala)
        $e.Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $e.Graphics.DrawImage($img, $area.X + [int](($area.Width - $w) / 2), $area.Y, $w, $h)
        $e.HasMorePages = $false
    })
    $doc.Print()
    Write-Output "OK"
}
finally {
    $img.Dispose()
}
}
catch {
    # mensagem curta para o log de falhas do sistema
    Write-Output ("ERRO: " + $_.Exception.Message)
    exit 1
}
