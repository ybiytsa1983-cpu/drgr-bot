<#
.SYNOPSIS
    Создаёт структуру каталогов «VM Training Archive» для обучения моделей
    психодиагностики (FER, age estimation, невербика) и скачивает открытые
    ресурсы (статьи, описания датасетов, утилиты).

.DESCRIPTION
    Скрипт:
      1. Создаёт дерево каталогов под C:\VM_training_archive (или путь из -RootDir).
      2. Скачивает перечень открытых ресурсов из встроенного списка.
      3. Ведёт журнал скачиваний в logs\download_log.csv.
      4. Поддерживает добавление своих ссылок через -ExtraUrls или CSV-файл -UrlFile.

    ВАЖНО: крупные датасеты (AffectNet, RAF-DB, EmoSet и др.) требуют
    академической/некоммерческой лицензии. Скрипт НЕ зашивает их напрямую --
    добавляйте ссылки после получения доступа.

.PARAMETER RootDir
    Корень архива. По умолчанию: C:\VM_training_archive

.PARAMETER ExtraUrls
    Массив дополнительных URL для скачивания (кладутся в datasets\custom\).

.PARAMETER UrlFile
    CSV-файл (url,subfolder,filename) с дополнительными ресурсами.

.EXAMPLE
    .\setup_training_archive.ps1
    .\setup_training_archive.ps1 -RootDir D:\ML_Archive
    .\setup_training_archive.ps1 -ExtraUrls @("https://example.com/data.zip")
#>

[CmdletBinding()]
param(
    [string]$RootDir = "C:\VM_training_archive",
    [string[]]$ExtraUrls = @(),
    [string]$UrlFile = ""
)

# ── TLS 1.2 (Windows может использовать устаревший TLS по умолчанию) ──
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ── Цвета-помощники ─────────────────────────────────────────────────────
function Write-Step  { param([string]$msg) Write-Host "▸ $msg" -ForegroundColor Cyan }
function Write-Ok    { param([string]$msg) Write-Host "  ✔ $msg" -ForegroundColor Green }
function Write-Warn  { param([string]$msg) Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Fail  { param([string]$msg) Write-Host "  ✖ $msg" -ForegroundColor Red }

# ═══════════════════════════════════════════════════════════════════════════
#  1. СОЗДАНИЕ СТРУКТУРЫ КАТАЛОГОВ
# ═══════════════════════════════════════════════════════════════════════════
Write-Host "`n╔══════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║  DRGR -- Настройка архива для обучения ВМ         ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════════════╝`n" -ForegroundColor Magenta

$dirs = @(
    # Датасеты
    "datasets\fer"                   # Facial Emotion Recognition datasets
    "datasets\age_estimation"        # Age estimation datasets
    "datasets\nonverbal"             # Body language / gesture datasets
    "datasets\custom"                # Ваши собственные данные
    # Научные статьи и методички
    "papers\fer_2021_2026"           # Статьи по FER 2021-2026
    "papers\classic_nonverbal"       # Дарвин, Пиз и др.
    "papers\psychocorrection"        # Психокоррекция / психопрофилактика
    "papers\clinical_apps"           # Клинические приложения FER
    # Материалы Пузенко
    "methods_puzenko\theory"         # Теоретические работы
    "methods_puzenko\presentations"  # Презентации
    "methods_puzenko\methods"        # Методики (дыхательные, когнитивные и т.п.)
    # Бэкап сайта
    "site_backup\html"
    "site_backup\api_dumps"
    # Модели
    "models\fer"                     # Предобученные FER-модели
    "models\age"                     # Предобученные age-estimation модели
    "models\face_detect"             # Детекторы лиц (MTCNN, RetinaFace и т.п.)
    # Логи
    "logs"
)

Write-Step "Создание структуры каталогов в: $RootDir"
foreach ($d in $dirs) {
    $full = Join-Path $RootDir $d
    if (-not (Test-Path $full)) {
        New-Item -ItemType Directory -Path $full -Force | Out-Null
        Write-Ok $d
    } else {
        Write-Warn "$d -- уже существует"
    }
}

# ═══════════════════════════════════════════════════════════════════════════
#  2. ЖУРНАЛ СКАЧИВАНИЙ
# ═══════════════════════════════════════════════════════════════════════════
$logFile = Join-Path $RootDir "logs\download_log.csv"
if (-not (Test-Path $logFile)) {
    "timestamp,url,destination,status" | Out-File -Encoding utf8 $logFile
}

function Log-Download {
    param([string]$Url, [string]$Dest, [string]$Status)
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$ts,$Url,$Dest,$Status" | Out-File -Encoding utf8 -Append $logFile
}

# ═══════════════════════════════════════════════════════════════════════════
#  3. УНИВЕРСАЛЬНАЯ ФУНКЦИЯ СКАЧИВАНИЯ
# ═══════════════════════════════════════════════════════════════════════════
function Download-Resource {
    param(
        [string]$Url,
        [string]$SubFolder,   # относительно $RootDir
        [string]$FileName = ""
    )
    if ([string]::IsNullOrWhiteSpace($FileName)) {
        # Берём имя файла из URL
        $uri = [System.Uri]::new($Url)
        $FileName = [System.IO.Path]::GetFileName($uri.LocalPath)
        if ([string]::IsNullOrWhiteSpace($FileName)) { $FileName = "index.html" }
    }
    $destDir  = Join-Path $RootDir $SubFolder
    $destPath = Join-Path $destDir  $FileName

    if (Test-Path $destPath) {
        Write-Warn "Пропуск (файл есть): $FileName"
        Log-Download -Url $Url -Dest $destPath -Status "skipped_exists"
        return
    }

    try {
        Write-Step "Скачивание: $FileName"
        Invoke-WebRequest -Uri $Url -OutFile $destPath -UseBasicParsing -ErrorAction Stop
        Write-Ok "$FileName → $SubFolder"
        Log-Download -Url $Url -Dest $destPath -Status "ok"
    }
    catch {
        Write-Fail "Не удалось скачать $Url -- $_"
        Log-Download -Url $Url -Dest $destPath -Status "error: $_"
    }
}

# ═══════════════════════════════════════════════════════════════════════════
#  4. ВСТРОЕННЫЙ СПИСОК ОТКРЫТЫХ РЕСУРСОВ
# ═══════════════════════════════════════════════════════════════════════════
#  Формат: @{ Url; SubFolder; FileName (опционально) }
#  Добавляйте свои ссылки после получения лицензий на датасеты.
# ─────────────────────────────────────────────────────────────────────────

$builtinResources = @(
    # --- Статьи по FER (открытые) ---
    @{
        # "A Survey of Face Recognition" (2022) -- обзор методов FER
        Url       = "https://arxiv.org/pdf/2203.13531v2"
        SubFolder = "papers\fer_2021_2026"
        FileName  = "fer_survey_2022.pdf"
    },
    @{
        # "Deep Learning for Facial Expression Recognition" (2023) -- AffectNet
        Url       = "https://arxiv.org/pdf/2307.04420v1"
        SubFolder = "papers\fer_2021_2026"
        FileName  = "affectnet_deep_learning_2023.pdf"
    },

    # --- Классика невербики (описание, не полные книги -- соблюдаем авторское право) ---
    @{
        Url       = "https://en.wikipedia.org/wiki/The_Expression_of_the_Emotions_in_Man_and_Animals"
        SubFolder = "papers\classic_nonverbal"
        FileName  = "darwin_expression_emotions_wiki.html"
    },
    @{
        Url       = "https://en.wikipedia.org/wiki/Allan_Pease"
        SubFolder = "papers\classic_nonverbal"
        FileName  = "allan_pease_wiki.html"
    },

    # --- Клинические приложения FER ---
    @{
        # "Facial Expression Recognition in Clinical Settings" (2024)
        Url       = "https://arxiv.org/pdf/2401.05831v1"
        SubFolder = "papers\clinical_apps"
        FileName  = "fer_clinical_review_2024.pdf"
    },

    # --- Предобученные модели (ссылки на Hugging Face model cards) ---
    @{
        Url       = "https://huggingface.co/api/models/trpakov/vit-face-expression"
        SubFolder = "models\fer"
        FileName  = "vit_face_expression_info.json"
    },
    @{
        Url       = "https://huggingface.co/api/models/nateraw/vit-age-classifier"
        SubFolder = "models\age"
        FileName  = "vit_age_classifier_info.json"
    }
)

Write-Host "`n── Скачивание встроенных ресурсов ──" -ForegroundColor Cyan
foreach ($r in $builtinResources) {
    Download-Resource -Url $r.Url -SubFolder $r.SubFolder -FileName $r.FileName
}

# ═══════════════════════════════════════════════════════════════════════════
#  5. ДОПОЛНИТЕЛЬНЫЕ ССЫЛКИ (через параметры)
# ═══════════════════════════════════════════════════════════════════════════
if ($ExtraUrls.Count -gt 0) {
    Write-Host "`n── Скачивание дополнительных URL ──" -ForegroundColor Cyan
    foreach ($u in $ExtraUrls) {
        Download-Resource -Url $u -SubFolder "datasets\custom"
    }
}

if ($UrlFile -and (Test-Path $UrlFile)) {
    Write-Host "`n── Скачивание из CSV-файла: $UrlFile ──" -ForegroundColor Cyan
    Import-Csv $UrlFile | ForEach-Object {
        Download-Resource -Url $_.url -SubFolder $_.subfolder -FileName $_.filename
    }
}

# ═══════════════════════════════════════════════════════════════════════════
#  6. README В КОРНЕ АРХИВА
# ═══════════════════════════════════════════════════════════════════════════
$readmePath = Join-Path $RootDir "README.txt"
if (-not (Test-Path $readmePath)) {
@"
╔══════════════════════════════════════════════════════════════╗
║              VM TRAINING ARCHIVE -- DRGR Platform             ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  datasets\         -- Датасеты (FER, age, nonverbal, custom)  ║
║  papers\           -- Научные статьи и обзоры                 ║
║  methods_puzenko\  -- Материалы Пузенко В.Ю.                  ║
║  site_backup\      -- Бэкап сайта (HTML / API дампы)          ║
║  models\           -- Предобученные модели                    ║
║  logs\             -- Журнал скачиваний                       ║
║                                                              ║
║  Добавляйте датасеты после получения лицензий.               ║
║  Крупные FER-датасеты (AffectNet, RAF-DB, EmoSet)            ║
║  требуют академической лицензии.                             ║
║                                                              ║
║  Повторный запуск скрипта -- безопасен (пропускает            ║
║  существующие файлы и папки).                                ║
╚══════════════════════════════════════════════════════════════╝
"@ | Out-File -Encoding utf8 $readmePath
    Write-Ok "README.txt создан"
}

# ═══════════════════════════════════════════════════════════════════════════
#  ГОТОВО
# ═══════════════════════════════════════════════════════════════════════════
Write-Host "`n══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Архив создан: $RootDir" -ForegroundColor Green
Write-Host "  Журнал: $logFile" -ForegroundColor Green
Write-Host "══════════════════════════════════════════════════`n" -ForegroundColor Green
