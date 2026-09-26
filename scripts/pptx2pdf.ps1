# Chuyen .pptx -> .pdf bang chinh PowerPoint (buoc 0 cua duong ong v0).
#
# Vi sao dung PowerPoint ma khong dung LibreOffice: duong ong S0 duoc do va chinh tren PDF
# xuat tu PowerPoint (co text layer, tat OCR van du chu). LibreOffice render lech font.
#
#   powershell -ExecutionPolicy Bypass -File scripts\pptx2pdf.ps1 data\raw\Gen_gap.pptx
#
# Luu y: slide AN (hidden) KHONG duoc xuat -> so trang PDF co the it hon so slide.

param(
    [Parameter(Mandatory = $true)][string]$Pptx,
    [string]$Pdf
)

$src = (Resolve-Path $Pptx).Path
if (-not $Pdf) { $Pdf = [IO.Path]::ChangeExtension($src, ".pdf") }
$Pdf = [IO.Path]::GetFullPath($Pdf)

function Retry([scriptblock]$Action) {
    # PowerPoint hay tu choi lenh ngay sau khi ghi file (RPC_E_CALL_REJECTED) -> doi roi thu lai
    for ($i = 0; $i -lt 20; $i++) {
        try { & $Action; return $true } catch { Start-Sleep -Milliseconds 500 }
    }
    return $false
}

$pp = New-Object -ComObject PowerPoint.Application
# COM bam vao PowerPoint DANG MO neu co. Neu anh dang mo file khac thi KHONG duoc Quit.
$wasOpen = $pp.Presentations.Count

$pres = $pp.Presentations.Open($src, $true, $false, $false)   # ReadOnly, Untitled, WithWindow
$n = $pres.Slides.Count
$hidden = @($pres.Slides | Where-Object { $_.SlideShowTransition.Hidden -eq -1 }).Count
$pres.SaveAs($Pdf, 32)                                          # 32 = ppSaveAsPDF

Retry { $pres.Close() } | Out-Null
if ($wasOpen -eq 0) { Retry { $pp.Quit() } | Out-Null }

if (Test-Path $Pdf) {
    $kb = [math]::Round((Get-Item $Pdf).Length / 1KB)
    Write-Output ("OK  {0} slide ({1} an) -> {2}  ({3} KB)" -f $n, $hidden, $Pdf, $kb)
} else {
    Write-Output "THAT BAI: khong tao duoc $Pdf"
    exit 1
}
