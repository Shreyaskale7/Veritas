# Recreates veritas_demo from veritas_demo_tpl and restarts the API against it (live 'veritas' DB untouched).
$root = "C:\Users\Shreyas\OneDrive\Desktop\DBMS EL"
$psql = "$root\.pg\pgsql\bin\psql.exe"; $env:PGPASSWORD="postgres"
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-Sleep 1
$tpl = & $psql -h 127.0.0.1 -U postgres -d postgres -Atc "select 1 from pg_database where datname='veritas_demo_tpl'"
if (-not $tpl) { & $psql -h 127.0.0.1 -U postgres -d postgres -qc "CREATE DATABASE veritas_demo_tpl TEMPLATE veritas_demo" }
& $psql -h 127.0.0.1 -U postgres -d postgres -qc "DROP DATABASE IF EXISTS veritas_demo WITH (FORCE)" -c "CREATE DATABASE veritas_demo TEMPLATE veritas_demo_tpl"
Remove-Item "$root\brag-output\work\demo_witness.jsonl" -ErrorAction SilentlyContinue
$env:DATABASE_URL="postgresql://veritas_login:veritas@127.0.0.1:5432/veritas_demo"
$env:ADMIN_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/veritas_demo"
$env:WITNESS_PATH="$root\brag-output\work\demo_witness.jsonl"
$env:VERITAS_VERIFY_EVERY="20"; $env:VERITAS_ANCHOR_EVERY="0"; $env:VERITAS_SCORE_EVERY="0"   # real scheduled verification; seal/anchor/score stay manual and deterministic
Start-Process python -ArgumentList "-m","uvicorn","main:app","--port","8000" -WorkingDirectory "$root\web\backend" -WindowStyle Hidden -RedirectStandardError "$root\.pg\api.log"
for ($i=0; $i -lt 20; $i++) { Start-Sleep 2; try { (Invoke-WebRequest http://127.0.0.1:8000/api/health -UseBasicParsing).Content; break } catch {} }
