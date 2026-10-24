# Prepara, UNA vez, el Chrome con el que el motor de escena renderiza las mallas en WebGPU (F6.1, fila 199).
#
# Por qué hace falta: el chrome-headless-shell que descarga HyperFrames 0.8.78 trae WebGPU pero NO las
# librerías del compilador de sombreadores de Direct3D 12 (dxil.dll y dxcompiler.dll). Sin ellas el adaptador
# existe pero requestDevice falla: «DynamicLib.Open: dxil.dll Windows Error: 87 at EnsureDXCLibraries»
# (medido el 28-09-2026). El Chrome completo de Google sí las trae.
#
# Qué hace, sin tocar ni la caché de HyperFrames ni el Chrome del sistema:
#   1. copia el chrome-headless-shell de HyperFrames a <Destino>\<versión>\
#   2. le añade dxil.dll y dxcompiler.dll de -ChromeSistema: una carpeta con subcarpetas de versión que las traen
#   3. escribe manifiesto.json con las versiones y el sha256 de cada librería
# Lo lanza `instala.py` (paso escena, OC1.7) con -ChromeSistema apuntando a las dos DLL del Chrome for Testing de la
# misma versión que el headless. El valor por defecto, el Google Chrome instalado, ya no sirve desde su versión 155, que
# no trae dxil.dll (medido el 24-10-2026).
# El render lo usa con HYPERFRAMES_BROWSER_PATH (lib/escena, F6.2). Requisito previo, con red y a propósito:
#   cd motor; npx hyperframes browser ensure
# El destino no tiene valor por defecto (OC1.3): es una carpeta fuera del repositorio que elige quien instala.
# Después, en el .env: CHROME_WEBGPU_MANIFIESTO=<Destino>\manifiesto.json
#   .\scripts\instala_chrome_webgpu.ps1 -Destino <carpeta>
param(
    [Parameter(Mandatory = $true)][string]$Destino,
    [string]$ChromeSistema = "C:\Program Files\Google\Chrome\Application"
)
$ErrorActionPreference = "Stop"

# Ordena por número de versión, no por texto («152…» antes que «99…» como texto, al revés como versión).
function Version($nombre) { $m = [regex]::Match($nombre, '\d+(\.\d+)+'); if ($m.Success) { [version]$m.Value } else { [version]'0.0' } }

$cache = Join-Path $env:USERPROFILE ".cache\hyperframes\chrome\chrome-headless-shell"
$origen = Get-ChildItem $cache -Directory | Sort-Object { Version $_.Name } | Select-Object -Last 1
if (-not $origen) { throw "No está el Chrome de HyperFrames en $cache. Antes: cd motor; npx hyperframes browser ensure" }
$shell = Get-ChildItem $origen.FullName -Directory | Where-Object { Test-Path (Join-Path $_.FullName "chrome-headless-shell.exe") } | Select-Object -First 1
if (-not $shell) { throw "No encuentro chrome-headless-shell.exe dentro de $($origen.FullName)" }

$dxc = Get-ChildItem $ChromeSistema -Directory | Where-Object { Test-Path (Join-Path $_.FullName "dxil.dll") } | Sort-Object { Version $_.Name } | Select-Object -Last 1
if (-not $dxc) { throw "No encuentro dxil.dll en ninguna versión de ${ChromeSistema}: hace falta el Chrome completo de Google instalado" }

$final = Join-Path $Destino $origen.Name
if (Test-Path $final) { Remove-Item $final -Recurse -Force }
New-Item -ItemType Directory -Force $final | Out-Null
Copy-Item (Join-Path $shell.FullName "*") $final -Recurse
foreach ($dll in "dxil.dll", "dxcompiler.dll") { Copy-Item (Join-Path $dxc.FullName $dll) $final }

$manifiesto = [ordered]@{
    fecha = (Get-Date).ToString("yyyy-MM-dd HH:mm")
    chrome_headless = $origen.Name
    dxc_de = "Chrome $($dxc.Name)"
    exe = (Join-Path $final "chrome-headless-shell.exe")
    sha256 = [ordered]@{}
}
foreach ($f in "chrome-headless-shell.exe", "dxil.dll", "dxcompiler.dll") { $manifiesto.sha256[$f] = (Get-FileHash (Join-Path $final $f) -Algorithm SHA256).Hash.ToLower() }
# UTF-8 sin BOM también en Windows PowerShell 5.1, donde -Encoding utf8 pone BOM y rompe JSON.parse.
[IO.File]::WriteAllText((Join-Path $Destino "manifiesto.json"), ($manifiesto | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
$manifiesto | ConvertTo-Json
