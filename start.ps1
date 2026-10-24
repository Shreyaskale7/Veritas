# Starts PostgreSQL (portable, in .pg), the API (8000) and the frontend (5173). Re-run safely.
$root = $PSScriptRoot
$pg = "$root\.pg\pgsql\bin"
& "$pg\pg_ctl.exe" -D "$root\.pg\data" status *> $null
if ($LASTEXITCODE -ne 0) { & "$pg\pg_ctl.exe" -D "$root\.pg\data" -l "$root\.pg\server.log" -o "-p 5432" -w start }
if (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process python -ArgumentList "-m","uvicorn","main:app","--port","8000" -WorkingDirectory "$root\web\backend" -WindowStyle Hidden -RedirectStandardError "$root\.pg\api.log"
}
if (-not (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process npm.cmd -ArgumentList "run","dev","--","--host","127.0.0.1" -WorkingDirectory "$root\web\frontend" -WindowStyle Hidden -RedirectStandardOutput "$root\.pg\vite.log"
}
"Veritas: http://127.0.0.1:5173  (API :8000, Postgres :5432)"
