# =====================================================================
#  run_collection.ps1 — Orchestration de la collecte de données
#  Project Resilience-Alpha
#
#  Ce script enchaîne automatiquement les phases de collecte :
#  il bascule label.txt, lance chaque charge, attend, puis revient
#  au normal entre chaque phase. Le collecteur (collect.py) doit déjà
#  tourner dans un autre terminal.
#
#  Il N'exécute PAS d'attaque offensive lourde (sqlmap, nmap) : pour
#  celles-là, il affiche la commande à lancer à la main et attend que
#  l'équipe cyber appuie sur Entrée. Le reste (charge HTTP, brute
#  force de login, panne de conteneur) est enchaîné automatiquement.
#
#  Usage :
#     cd resilience-alpha
#     .\traffic\run_collection.ps1
# =====================================================================

$ErrorActionPreference = "Continue"
$API = "http://localhost:8000"
$LABEL = "collector/label.txt"

# --- Durées (secondes) — ajuste si besoin ---
$NORMAL_WARMUP = 60  # normal avant de commencer
$ATTACK_DUR    =   60  # durée de chaque attaque
$COOLDOWN      = 60  # retour au normal entre deux attaques

function Set-Label($name) {
    Set-Content -Path $LABEL -Value $name -NoNewline -Encoding ascii
    Write-Host "  [label] -> $name" -ForegroundColor Cyan
}

function Wait-Phase($seconds, $msg) {
    Write-Host "  $msg ($seconds s)..." -ForegroundColor DarkGray
    Start-Sleep -Seconds $seconds
}

function Check-Api {
    try { Invoke-RestMethod "$API/health" -TimeoutSec 3 | Out-Null; return $true }
    catch { return $false }
}

Write-Host "`n=== COLLECTE RESILIENCE-ALPHA ===" -ForegroundColor Green
if (-not (Check-Api)) {
    Write-Host "ERREUR : l'API ne répond pas sur $API. Lance 'docker compose up -d' d'abord." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path ".\hey.exe")) {
    Write-Host "ERREUR : hey.exe introuvable dans le dossier courant." -ForegroundColor Red
    exit 1
}
Write-Host "API OK. Assure-toi que collect.py et normal_traffic.py tournent dans d'autres terminaux.`n"
Read-Host "Appuie sur Entrée pour démarrer"

# --- Phase 0 : normal de référence ---
Set-Label "normal"
Wait-Phase $NORMAL_WARMUP "Collecte du trafic normal de référence"

# --- Phase 1 : DDoS / DoS (charge HTTP automatique, forte) ---
# -c 500 : 500 connexions simultanées ; cible /transaction (POST) qui
# touche la base de données, donc sature bien plus que /accounts.
Write-Host "`n--- Phase 1 : DDoS (forte charge) ---" -ForegroundColor Yellow
Set-Label "ddos"
$body = '{"from_acc":1,"to_acc":2,"amount":10}'
.\hey.exe -z "$($ATTACK_DUR)s" -c 500 -m POST -T "application/json" -d $body "$API/transaction" | Out-Null
Set-Label "normal"
Wait-Phase $COOLDOWN "Retour au normal"

# --- Phase 2 : Brute force (boucle de login automatique) ---
Write-Host "`n--- Phase 2 : Brute force ---" -ForegroundColor Yellow
Set-Label "brute_force"
$end = (Get-Date).AddSeconds($ATTACK_DUR)
while ((Get-Date) -lt $end) {
    1..50 | ForEach-Object {
        try {
            Invoke-RestMethod -Uri "$API/login" -Method Post `
                -ContentType "application/json" `
                -Body '{"username":"admin","password":"wrong"}' -TimeoutSec 2 | Out-Null
        } catch {}
    }
}
Set-Label "normal"
Wait-Phase $COOLDOWN "Retour au normal"

# --- Phase 3 : Panne de service (chaos automatique) ---
Write-Host "`n--- Phase 3 : Panne de service ---" -ForegroundColor Yellow
$dbName = (docker ps --format "{{.Names}}" | Select-String "db").ToString().Trim()
if ($dbName) {
    Set-Label "service_down"
    Write-Host "  Arrêt du conteneur $dbName" -ForegroundColor DarkYellow
    docker stop $dbName | Out-Null
    Wait-Phase $ATTACK_DUR "Service arrêté (on observe les erreurs)"
    docker start $dbName | Out-Null
    Write-Host "  Conteneur redémarré" -ForegroundColor DarkYellow
    Start-Sleep 15   # laisse la base redevenir disponible
    Set-Label "normal"
    Wait-Phase $COOLDOWN "Retour au normal"
} else {
    Write-Host "  Conteneur db introuvable, phase ignorée." -ForegroundColor Red
}

# --- Phase 4 : attaques manuelles (sqlmap / nmap) ---
Write-Host "`n--- Phase 4 : attaques manuelles (équipe cyber) ---" -ForegroundColor Yellow
Write-Host "  Les attaques suivantes se lancent à la main dans UN AUTRE terminal."
Write-Host "  Ce script gère seulement le label et le chrono.`n"

$manuelles = @(
    @{ label = "sql_injection"; cmd = "sqlmap -u `"$API/accounts/1`" --batch --level=2" },
    @{ label = "port_scan";     cmd = "nmap -sS -p 1-10000 localhost" }
)

foreach ($m in $manuelles) {
    Write-Host "  >> Prépare la commande : $($m.cmd)" -ForegroundColor White
    Read-Host "     Appuie sur Entrée QUAND tu es prêt à lancer (le label passera à '$($m.label)')"
    Set-Label $m.label
    Write-Host "     Lance maintenant la commande dans l'autre terminal." -ForegroundColor Green
    Read-Host "     Appuie sur Entrée QUAND l'attaque est TERMINEE"
    Set-Label "normal"
    Wait-Phase $COOLDOWN "Retour au normal"
}

Set-Label "normal"
Write-Host "`n=== COLLECTE TERMINEE ===" -ForegroundColor Green
Write-Host "Vérifie la répartition avec :"
Write-Host '  Import-Csv collector/dataset.csv | Group-Object label | Select-Object Name, Count' -ForegroundColor Cyan