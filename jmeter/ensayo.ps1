param(
  [Parameter(Mandatory)][int]$Users,
  [int]$RampUp = 10,
  [int]$Duration = 60,
  [string]$Tag = ""
)
$ErrorActionPreference = "Stop"
$jm = "$env:LOCALAPPDATA\Programs\JMeter\bin\jmeter.bat"
$root = Split-Path $PSScriptRoot
$name = if ($Tag) { "N$Users-$Tag" } else { "N$Users" }
$out = Join-Path $PSScriptRoot "resultados\$name"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory $out | Out-Null
$env:JVM_ARGS = "-Xms512m -Xmx2g"
& $jm -n -t (Join-Path $PSScriptRoot "radar_carga.jmx") `
  "-Jusers=$Users" "-Jrampup=$RampUp" "-Jduration=$Duration" `
  -l "$out\resultados.jtl" -e -o "$out\informe" `
  "-Jjmeter.save.saveservice.output_format=csv" 2>&1 | Select-Object -Last 4
# Resumen: muestras, errores, % error, promedio, p95
$rows = Import-Csv "$out\resultados.jtl" | Where-Object { $_.label -ne "POST /auth/login" }
$n = $rows.Count
$err = ($rows | Where-Object { $_.success -ne "true" }).Count
$t = $rows | ForEach-Object { [int]$_.elapsed } | Sort-Object
$p95 = $t[[math]::Min($n - 1, [int][math]::Floor($n * 0.95))]
$avg = [math]::Round(($t | Measure-Object -Average).Average)
$secs = ([int64]$rows[-1].timeStamp - [int64]$rows[0].timeStamp) / 1000
$line = "N={0,-5} muestras={1,-6} errores={2,-5} error%={3,-6} prom={4}ms p95={5}ms rps={6}" -f $Users, $n, $err, ([math]::Round(100 * $err / [math]::Max($n,1), 2)), $avg, $p95, ([math]::Round($n / [math]::Max($secs,1), 1))
$line
$line | Add-Content (Join-Path $PSScriptRoot "resultados\resumen.txt")
