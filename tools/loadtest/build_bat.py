"""把 loadtest.py 打包成独立的 loadtest.bat（Windows 双击/任意目录可运行）。

原理：.bat 前段是批处理（找 Python、把自身内嵌的 Python 源码抽到临时文件再执行），
       后段是完整 Python 源码；批处理用 `exit /b` 提前结束，不会被 cmd 执行到。
修改 loadtest.py 后重新运行本脚本即可更新 .bat。
"""

import io
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(ROOT, 'loadtest.py')
TARGET = os.path.join(ROOT, 'loadtest.bat')

PREAMBLE = r'''@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem ===========================================================================
rem  BCM 独立压测工具（单文件 .bat 版，直接双击或在 cmd 里运行）
rem  用法：
rem    loadtest.bat
rem    loadtest.bat --base-url http://127.0.0.1:8000 --username admin --users 20 --duration 60
rem  说明：只需要系统有 Python 3.10+；交互输入并发数与压测时长；
rem        报告默认写在 bat 同目录 reports\loadtest
rem ===========================================================================

set "SELF=%~f0"
set "REPORT_DIR=%~dp0reports\loadtest"
set "PY="

rem 优先用 py 启动器（避免命中 Microsoft Store 的 python 占位符）
py -3 -c "import sys; sys.exit(0)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo.
    echo [错误] 没有找到 Python 3。
    echo 请先安装 Python 3.10 或更高版本： https://www.python.org/downloads/
    echo 安装时记得勾选 "Add python.exe to PATH"。
    echo.
    pause
    exit /b 1
)

set "TMPPY=%TEMP%\bcm_loadtest_%RANDOM%%RANDOM%.py"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; $src=Get-Content -LiteralPath $env:SELF -Encoding UTF8; $i=[Array]::IndexOf($src,'# ---PYTHON---'); if($i -lt 0){Write-Host '[错误] 未找到内嵌脚本标记'; exit 2}; $src[($i+1)..($src.Count-1)] | Set-Content -LiteralPath $env:TMPPY -Encoding UTF8"
if errorlevel 1 (
    echo [错误] 提取内嵌脚本失败。
    pause
    exit /b 1
)

%PY% -X utf8 "%TMPPY%" --report-dir "%REPORT_DIR%" %*
set "CODE=%ERRORLEVEL%"

if exist "%TMPPY%" del /q "%TMPPY%" >nul 2>nul

if "%~1"=="" pause
exit /b %CODE%

rem ===========================================================================
rem  以下是内嵌的 Python 源码（批处理已在上方 exit，勿手动执行）
rem ===========================================================================
# ---PYTHON---
'''

python_source = io.open(SOURCE, encoding='utf-8').read().replace('\r\n', '\n')

with io.open(TARGET, 'w', encoding='utf-8', newline='') as fh:
    content = PREAMBLE + python_source
    fh.write(content.replace('\n', '\r\n'))

print(f'已生成 {TARGET}（{len(content)} 字符）')
