@echo off
rem Build Strata's DeepSeek engine (strata-dsv41.exe) with the fast-routing patch, for NVIDIA RTX 30 / 40 / 50 on Windows.
rem
rem   build-windows.cmd                 clone Strata into .\strata-src, apply the patch, build, copy the engine to .\engine
rem   build-windows.cmd D:\my\strata    use an existing Strata checkout (the patch must already be applied)
rem
rem Needs: Git, Visual Studio 2022 (or Build Tools) with "Desktop development with C++" (includes CMake and Ninja),
rem        CUDA Toolkit 13.0. Settings (optional): CUDA_ROOT, ARCHS (default 86-real;89-real;120), JOBS (default 8).
rem Takes 20 to 60 minutes and a lot of RAM; the build runs at below-normal priority.
setlocal
set "HERE=%~dp0"
set "SRC=%~1"
set "BASE=54828c7efbcdf9474697e70922d851f6707f4b32"
if "%SRC%"=="" set "SRC=%HERE%strata-src"
if "%CUDA_ROOT%"=="" set "CUDA_ROOT=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0"
if "%ARCHS%"=="" set "ARCHS=86-real;89-real;120"
if "%JOBS%"=="" set "JOBS=8"
if not exist "%CUDA_ROOT%\bin\nvcc.exe" ( echo CUDA 13.0 not found at "%CUDA_ROOT%". Install it, or set CUDA_ROOT. & exit /b 2 )

if not exist "%SRC%\CMakeLists.txt" (
  echo == Cloning Strata at %BASE%
  git clone https://github.com/Niko1221/Strata "%SRC%" || exit /b 1
  git -C "%SRC%" checkout -q %BASE% || exit /b 1
  echo == Applying the fast-routing patch
  git -C "%SRC%" apply "%HERE%patches\strata-fast-routing.patch" || ( echo The patch did not apply. & exit /b 1 )
)

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS=%%i"
if "%VS%"=="" ( echo Visual Studio 2022 with C++ tools not found. & exit /b 2 )
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set "PATH=%CUDA_ROOT%\bin;%PATH%"

echo == Configuring (CUDA %ARCHS%)
cmake -G Ninja -S "%SRC%" -B "%SRC%\build-release" -DCMAKE_BUILD_TYPE=Release -DSTRATA_ENABLE_CUDA=ON -DSTRATA_BUILD_TESTS=OFF ^
  -DSTRATA_BUILD_DSV41=ON -DSTRATA_PORTABLE=ON "-DCMAKE_CUDA_ARCHITECTURES=%ARCHS%" ^
  "-DCMAKE_CUDA_COMPILER=%CUDA_ROOT%/bin/nvcc.exe" "-DCUDAToolkit_ROOT=%CUDA_ROOT%" || exit /b 1
echo == Building (this takes a while)
if exist "%SRC%\build-release\strata-dsv41.exe" del /q "%SRC%\build-release\strata-dsv41.exe"
start "" /belownormal /wait /b cmake --build "%SRC%\build-release" -j %JOBS% --target strata-dsv41
if not exist "%SRC%\build-release\strata-dsv41.exe" ( echo The build failed; see the messages above. & exit /b 1 )

if not exist "%HERE%engine" mkdir "%HERE%engine"
copy /y "%SRC%\build-release\strata-dsv41.exe" "%HERE%engine\" >nul
for %%d in (cublas64_13.dll cublasLt64_13.dll) do (
  if exist "%CUDA_ROOT%\bin\x64\%%d" ( copy /y "%CUDA_ROOT%\bin\x64\%%d" "%HERE%engine\" >nul ) else if exist "%CUDA_ROOT%\bin\%%d" copy /y "%CUDA_ROOT%\bin\%%d" "%HERE%engine\" >nul
)
echo == Done: %HERE%engine\strata-dsv41.exe
exit /b 0
