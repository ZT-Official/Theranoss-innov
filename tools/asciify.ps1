<#
    asciify.ps1 — rebuild assets/ascii/ from assets/img-source/

    Converts each deck photograph to ASCII art with ascii-image-converter
    (https://github.com/TheZoraiz/ascii-image-converter, Apache-2.0).

    Four text files are produced per image:

        <slug>-wide.txt         desktop,  light theme
        <slug>-wide-dark.txt    desktop,  dark theme
        <slug>-narrow.txt       phone,    light theme
        <slug>-narrow-dark.txt  phone,    dark theme

    Why two themes. ascii-image-converter maps the DARKEST pixel to the FIRST
    character of the ramp. The page paints the art in one ink colour, so on an
    off-white page the dense glyphs must fall on the dark parts of the photo,
    and on a near-black page they must fall on the light parts. The dark file
    is therefore the same conversion with the ramp reversed (-n for -c).

    Tuning. Everything per-image lives in $Images below. Change one row and
    re-run; nothing else needs touching.

        slug      output name stem (lowercase, hyphenated)
        file      file name inside assets/img-source
        ramp      'complex'  -> the tool's built-in extended set (-c), best for
                              objects, interiors and architecture
                  '<string>' -> explicit ramp, darkest pixel first, better for
                              faces, where a short flat ramp beats glyph noise
        wide      character width for desktop
        narrow    character width for phones
        crop      optional @(left,top,right,bottom) as 0-1 fractions of the
                  source, applied before conversion
        contrast  optional multiplier around mid-grey (1 = unchanged)
        bright    optional offset added after contrast (-1..1, 0 = unchanged)

    Usage:  pwsh -File tools/asciify.ps1 [-Only <slug>] [-KeepPrepared]
#>

[CmdletBinding()]
param(
    [string] $Only,
    [switch] $KeepPrepared
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# --------------------------------------------------------------------------
# Per-image settings
# --------------------------------------------------------------------------
$RampFace  = '@%#*+=-:. '              # 10 flat steps: skin tone reads as tone
$RampFine  = '@%#WX*o+=~-;:,''. '      # 17 steps for the printed cover

$Images = @(
    # fingertip and drop only: full frame is mostly soft grey backdrop and the
    # drop shrinks to two characters
    @{  slug = 'finger-stick-blood-drop'; file = 'finger-stick-blood-drop.jpg'
        ramp = 'complex'; wide = 118; narrow = 52
        crop = @(0.38, 0.22, 0.88, 0.72); contrast = 1.35; bright = 0.00 }

    # head and shoulders only: in the full stage shot her face is ~80px and
    # dissolves into the white chair behind her
    @{  slug = 'holmes-techcrunch-disrupt-2014'; file = 'holmes-techcrunch-disrupt-2014.jpg'
        ramp = $RampFace; wide = 96; narrow = 46
        crop = @(0.16, 0.15, 0.42, 0.58); contrast = 1.25; bright = 0.00 }

    # left third only: the right of the frame is an out-of-focus face that
    # turns into texture and swamps the tube
    @{  slug = 'theranos-nanotainer'; file = 'theranos-nanotainer.jpg'
        ramp = $RampFace; wide = 80; narrow = 40
        crop = @(0.02, 0.10, 0.38, 0.96); contrast = 1.60; bright = 0.06 }

    @{  slug = 'fortune-cover-2014'; file = 'fortune-cover-2014.png'
        ramp = $RampFine; wide = 92; narrow = 42
        crop = $null; contrast = 1.12; bright = 0.00 }

    @{  slug = 'biden-theranos-facility-2015'; file = 'biden-theranos-facility-2015.jpg'
        ramp = 'complex'; wide = 120; narrow = 54
        crop = $null; contrast = 1.20; bright = 0.00 }

    # the hanging sign alone, pushed to near black-and-white: the shelves below
    # are mid-tone clutter that turns the whole frame into noise
    @{  slug = 'walgreens-theranos-check-in'; file = 'walgreens-theranos-check-in.jpg'
        ramp = $RampFace; wide = 112; narrow = 52
        crop = @(0.20, 0.06, 0.60, 0.28); contrast = 1.90; bright = 0.04 }

    # side margins trimmed, footer kept: the "Trial Exh. 5388" line is part of
    # what makes this read as a court document rather than a product shot, but
    # the white borders waste two thirds of the character grid
    @{  slug = 'edison-trial-exhibit-5388'; file = 'edison-trial-exhibit-5388.jpg'
        ramp = 'complex'; wide = 100; narrow = 48
        crop = @(0.21, 0.00, 0.79, 1.00); contrast = 1.05; bright = 0.00 }

    # both heads only, contrast left alone: the red-and-grey plaid backdrop
    # already carries more contrast than the faces do
    @{  slug = 'cheung-shultz'; file = 'cheung-shultz.jpg'
        ramp = $RampFace; wide = 124; narrow = 56
        crop = @(0.24, 0.05, 0.77, 0.41); contrast = 1.00; bright = 0.05 }

    @{  slug = 'carreyrou-bad-blood'; file = 'carreyrou-bad-blood.jpg'
        ramp = $RampFace; wide = 112; narrow = 50
        crop = $null; contrast = 1.25; bright = 0.06 }

    # the entrance monument, not the whole lot: redwoods and rough grass fill
    # the full frame with uniform texture and nothing reads
    @{  slug = 'theranos-headquarters'; file = 'theranos-headquarters.jpg'
        ramp = $RampFace; wide = 104; narrow = 48
        crop = @(0.38, 0.45, 0.72, 0.85); contrast = 1.40; bright = 0.02 }

    @{  slug = 'holmes-federal-courthouse'; file = 'holmes-federal-courthouse.jpg'
        ramp = $RampFace; wide = 104; narrow = 48
        crop = @(0.33, 0.03, 0.75, 0.78); contrast = 1.25; bright = 0.08 }
)

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
$Root     = Split-Path -Parent $PSScriptRoot
$SrcDir   = Join-Path $Root 'assets\img-source'
$OutDir   = Join-Path $Root 'assets\ascii'
$PrepDir  = Join-Path $Root 'assets\img-prepared'
$TmpDir   = Join-Path ([System.IO.Path]::GetTempPath()) ("asciify-" + [guid]::NewGuid().ToString('N').Substring(0, 8))

function Resolve-Converter {
    $cmd = Get-Command 'ascii-image-converter' -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $local = Join-Path $PSScriptRoot 'bin\ascii-image-converter.exe'
    if (Test-Path $local) { return $local }
    throw "ascii-image-converter not found. Put it on PATH, or at tools\bin\ascii-image-converter.exe (https://github.com/TheZoraiz/ascii-image-converter/releases)."
}

$Aic = Resolve-Converter
Write-Host "converter : $Aic"
Write-Host "version   : $(& $Aic --version)"
Write-Host "source    : $SrcDir"
Write-Host "output    : $OutDir`n"

foreach ($d in @($OutDir, $PrepDir, $TmpDir)) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

Add-Type -AssemblyName System.Drawing

# --------------------------------------------------------------------------
# Source preparation: crop, desaturate, stretch contrast
# --------------------------------------------------------------------------
function New-PreparedImage {
    param(
        [string] $InPath,
        [string] $OutPath,
        [double[]] $Crop,
        [double] $Contrast,
        [double] $Bright
    )

    $src = [System.Drawing.Image]::FromFile($InPath)
    try {
        $x = 0; $y = 0; $w = $src.Width; $h = $src.Height
        if ($Crop) {
            $x = [int]([math]::Round($src.Width  * $Crop[0]))
            $y = [int]([math]::Round($src.Height * $Crop[1]))
            $w = [int]([math]::Round($src.Width  * ($Crop[2] - $Crop[0])))
            $h = [int]([math]::Round($src.Height * ($Crop[3] - $Crop[1])))
        }

        $dst = New-Object System.Drawing.Bitmap($w, $h)
        $g   = [System.Drawing.Graphics]::FromImage($dst)
        try {
            $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic

            # Rec. 601 luma, then (v - 0.5) * contrast + 0.5 + bright
            $c = $Contrast
            $t = (0.5 - 0.5 * $c) + $Bright
            $m = New-Object System.Drawing.Imaging.ColorMatrix
            $m.Matrix00 = 0.299 * $c; $m.Matrix01 = 0.299 * $c; $m.Matrix02 = 0.299 * $c
            $m.Matrix10 = 0.587 * $c; $m.Matrix11 = 0.587 * $c; $m.Matrix12 = 0.587 * $c
            $m.Matrix20 = 0.114 * $c; $m.Matrix21 = 0.114 * $c; $m.Matrix22 = 0.114 * $c
            $m.Matrix33 = 1.0
            $m.Matrix40 = $t; $m.Matrix41 = $t; $m.Matrix42 = $t

            $attr = New-Object System.Drawing.Imaging.ImageAttributes
            $attr.SetColorMatrix($m)

            $rect = New-Object System.Drawing.Rectangle(0, 0, $w, $h)
            $g.DrawImage($src, $rect, $x, $y, $w, $h, [System.Drawing.GraphicsUnit]::Pixel, $attr)
            $attr.Dispose()
        } finally {
            $g.Dispose()
        }

        $dst.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $dst.Dispose()
    } finally {
        $src.Dispose()
    }
}

function Reverse-Ramp {
    param([string] $Ramp)
    $a = $Ramp.ToCharArray()
    [array]::Reverse($a)
    return (-join $a)
}

# --------------------------------------------------------------------------
# One conversion: run the tool, then rename its output to our slug
# --------------------------------------------------------------------------
function Invoke-Conversion {
    param(
        [string] $ImagePath,
        [int]    $Width,
        [string] $Ramp,
        [bool]   $DarkTheme,
        [string] $Destination
    )

    $stage = Join-Path $TmpDir ([guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $stage | Out-Null

    $argv = @($ImagePath, '-W', "$Width", '--save-txt', $stage, '--only-save')
    if ($Ramp -eq 'complex') {
        # built-in extended set; -n flips it so dark pixels get the dense glyphs
        $argv += '-c'
        if (-not $DarkTheme) { $argv += '-n' }
    } else {
        $argv += @('-m', $(if ($DarkTheme) { Reverse-Ramp $Ramp } else { $Ramp }))
    }

    & $Aic @argv | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ascii-image-converter failed for $ImagePath" }

    $produced = Get-ChildItem -Path $stage -Filter '*-ascii-art.txt' | Select-Object -First 1
    if (-not $produced) { throw "no .txt produced for $ImagePath" }

    # normalise line endings and strip trailing blank lines
    $lines = [System.IO.File]::ReadAllLines($produced.FullName)
    while ($lines.Count -gt 0 -and $lines[-1].Trim() -eq '') { $lines = $lines[0..($lines.Count - 2)] }
    [System.IO.File]::WriteAllText($Destination, (($lines -join "`n") + "`n"))

    Remove-Item -Recurse -Force $stage
    return $lines.Count
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
$report = @()

try {
    foreach ($img in $Images) {
        if ($Only -and $img.slug -ne $Only) { continue }

        $inPath = Join-Path $SrcDir $img.file
        if (-not (Test-Path $inPath)) {
            Write-Warning "missing source: $($img.file) - skipped"
            continue
        }

        $needsPrep = ($null -ne $img.crop) -or ($img.contrast -ne 1.0) -or ($img.bright -ne 0.0)
        $convertPath = $inPath
        if ($needsPrep) {
            $convertPath = Join-Path $PrepDir ($img.slug + '.png')
            New-PreparedImage -InPath $inPath -OutPath $convertPath `
                              -Crop $img.crop -Contrast $img.contrast -Bright $img.bright
        }

        $rows = @{}
        foreach ($variant in @(
            @{ key = 'wide';        width = $img.wide;   dark = $false },
            @{ key = 'wide-dark';   width = $img.wide;   dark = $true  },
            @{ key = 'narrow';      width = $img.narrow; dark = $false },
            @{ key = 'narrow-dark'; width = $img.narrow; dark = $true  }
        )) {
            $dest = Join-Path $OutDir ("{0}-{1}.txt" -f $img.slug, $variant.key)
            $rows[$variant.key] = Invoke-Conversion -ImagePath $convertPath -Width $variant.width `
                                                    -Ramp $img.ramp -DarkTheme $variant.dark -Destination $dest
        }

        $kind = if ($img.ramp -eq 'complex') { 'complex' } else { 'ramp(' + $img.ramp.Length + ')' }
        Write-Host ("{0,-34} {1,-11} wide {2,3}x{3,-3} narrow {4,3}x{5,-3} {6}" -f `
            $img.slug, $kind, $img.wide, $rows['wide'], $img.narrow, $rows['narrow'],
            $(if ($needsPrep) { 'prepared' } else { 'as-is' }))

        $report += [pscustomobject]@{
            slug = $img.slug; ramp = $kind
            wide = "$($img.wide)x$($rows['wide'])"; narrow = "$($img.narrow)x$($rows['narrow'])"
            prepared = $needsPrep
        }
    }
} finally {
    if (Test-Path $TmpDir) { Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue }
    if (-not $KeepPrepared -and (Test-Path $PrepDir)) {
        Remove-Item -Recurse -Force $PrepDir -ErrorAction SilentlyContinue
    }
}

Write-Host "`n$($report.Count) image(s), $((Get-ChildItem $OutDir -Filter *.txt).Count) text files in $OutDir"
