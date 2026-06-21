@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ========================================
echo  无限画布 — 一键测试脚本
echo ========================================
echo.

set PYTHON=..\python\python.exe
set PASS=0
set FAIL=0

echo [1/5] Python 编译检查...
%PYTHON% -m compileall server run.py tests -q 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   PASS
    set /a PASS+=1
) else (
    echo   FAIL
    set /a FAIL+=1
)
echo.

echo [2/5] 后端单元测试...
%PYTHON% -m unittest discover -s tests 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   PASS
    set /a PASS+=1
) else (
    echo   FAIL
    set /a FAIL+=1
)
echo.

echo [3/5] JS 语法检查...
set JS_FAIL=0
for %%f in (static\js\*.js) do (
    node --check "%%f" 2>&1
    if !ERRORLEVEL! NEQ 0 set /a JS_FAIL+=1
)
if %JS_FAIL% EQU 0 (
    echo   PASS
    set /a PASS+=1
) else (
    echo   FAIL (%JS_FAIL% files)
    set /a FAIL+=1
)
echo.

echo [4/5] Locale JSON 验证...
node -e "JSON.parse(require('fs').readFileSync('static/locales/zh-CN.json','utf8'))" 2>&1
if %ERRORLEVEL% EQU 0 (echo   zh-CN.json OK) else echo   zh-CN.json FAIL
node -e "JSON.parse(require('fs').readFileSync('static/locales/en.json','utf8'))" 2>&1
if %ERRORLEVEL% EQU 0 (echo   en.json OK) else echo   en.json FAIL
echo.

echo [5/5] Locale 键匹配检查...
node -e "var zh=JSON.parse(require('fs').readFileSync('static/locales/zh-CN.json','utf8')),en=JSON.parse(require('fs').readFileSync('static/locales/en.json','utf8'));function dk(o,p){var k=[];for(var c in o){var f=p?p+'.'+c:c;if(typeof o[c]==='object'&&o[c]&&!Array.isArray(o[c]))k=k.concat(dk(o[c],f));else k.push(f);}return k;}var zz=dk(zh),ee=dk(en);var zs=new Set(zz),es=new Set(ee);var onlyZh=zz.filter(function(k){return!es.has(k)});var onlyEn=ee.filter(function(k){return!zs.has(k)});if(onlyZh.length===0&&onlyEn.length===0){console.log('PASS: '+zz.length+' keys matched');}else{onlyZh.forEach(function(k){console.log('Only in zh-CN: '+k)});onlyEn.forEach(function(k){console.log('Only in en: '+k)});console.log('FAIL: zh='+zz.length+' en='+ee.length+' diff='+(onlyZh.length+onlyEn.length));process.exit(1);}" 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   PASS
    set /a PASS+=1
) else (
    echo   FAIL
    set /a FAIL+=1
)

echo.
echo ========================================
echo  结果: %PASS% 通过, %FAIL% 失败
echo ========================================
if %FAIL% GTR 0 exit /b 1
