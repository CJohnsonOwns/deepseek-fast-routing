@echo off
rem Start DeepSeek V4.1 Flash in Strata with the fast-routing engine.
rem   launch-deepseek-fast.cmd <model folder> [more strata launch options]
rem   example: launch-deepseek-fast.cmd D:\models\deepseek-v4.1-flash --speed full --port 8080
rem Change the three bonuses by setting them before running this (0 turns one off); see README.md.
setlocal
if "%~1"=="" ( echo usage: launch-deepseek-fast.cmd ^<model folder^> [strata launch options] & exit /b 2 )
set "STRATA_DSV41_EXE=%~dp0engine\strata-dsv41.exe"
if not exist "%STRATA_DSV41_EXE%" ( echo No engine at %STRATA_DSV41_EXE%. Build it with build-windows.cmd. & exit /b 2 )
if not defined DS4_CACHE_ROUTE set "DS4_CACHE_ROUTE=0.06"
if not defined DS4_CACHE_ROUTE_VRAM set "DS4_CACHE_ROUTE_VRAM=0.06"
if not defined DS4_CACHE_ROUTE_STICKY set "DS4_CACHE_ROUTE_STICKY=0.04"
echo Fast routing: warm +%DS4_CACHE_ROUTE%, VRAM +%DS4_CACHE_ROUTE_VRAM%, previous word +%DS4_CACHE_ROUTE_STICKY%
strata launch --model-path %*
