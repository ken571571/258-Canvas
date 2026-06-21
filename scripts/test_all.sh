#!/bin/bash
set -e

echo "========================================"
echo " 无限画布 — 一键测试脚本"
echo "========================================"
echo ""

PYTHON="./python/python.exe"
PASS=0
FAIL=0

# [1/5] Python compile check
echo "[1/5] Python 编译检查..."
if $PYTHON -m compileall server run.py tests -q 2>&1; then
    echo "  PASS"; ((PASS++))
else
    echo "  FAIL"; ((FAIL++))
fi
echo ""

# [2/5] Backend tests
echo "[2/5] 后端单元测试..."
if $PYTHON -m unittest discover -s tests 2>&1; then
    echo "  PASS"; ((PASS++))
else
    echo "  FAIL"; ((FAIL++))
fi
echo ""

# [3/5] JS syntax check
echo "[3/5] JS 语法检查..."
JS_FAIL=0
for f in static/js/*.js; do
    node --check "$f" 2>&1 || ((JS_FAIL++))
done
if [ $JS_FAIL -eq 0 ]; then
    echo "  PASS"; ((PASS++))
else
    echo "  FAIL ($JS_FAIL files)"; ((FAIL++))
fi
echo ""

# [4/5] Locale JSON validation
echo "[4/5] Locale JSON 验证..."
node -e "JSON.parse(require('fs').readFileSync('static/locales/zh-CN.json','utf8'))" 2>&1 && echo "  zh-CN.json OK" || echo "  zh-CN.json FAIL"
node -e "JSON.parse(require('fs').readFileSync('static/locales/en.json','utf8'))" 2>&1 && echo "  en.json OK" || echo "  en.json FAIL"
echo ""

# [5/5] Locale key matching
echo "[5/5] Locale 键匹配检查..."
if node -e "
var zh=JSON.parse(require('fs').readFileSync('static/locales/zh-CN.json','utf8')),
en=JSON.parse(require('fs').readFileSync('static/locales/en.json','utf8'));
function dk(o,p){var k=[];for(var c in o){var f=p?p+'.'+c:c;if(typeof o[c]==='object'&&o[c]&&!Array.isArray(o[c]))k=k.concat(dk(o[c],f));else k.push(f);}return k;}
var zz=dk(zh),ee=dk(en);
if(zz.length===ee.length){console.log('PASS: '+zz.length+' keys matched');}else{console.log('FAIL: zh='+zz.length+' en='+ee.length);process.exit(1);}
" 2>&1; then
    echo "  PASS"; ((PASS++))
else
    echo "  FAIL"; ((FAIL++))
fi

echo ""
echo "========================================"
echo " 结果: $PASS 通过, $FAIL 失败"
echo "========================================"
[ $FAIL -gt 0 ] && exit 1 || exit 0
