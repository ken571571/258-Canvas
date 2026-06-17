# -*- coding: utf-8 -*-
"""Fix _t() calls in regular strings (not template literals)"""
import re, os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'js', 'canvas-renderer-nodes.js')
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

pat = re.compile(r"\$\{_t\('([^']+)','([^']+)'\)\}")

new_lines = []
fixed = 0
for i, line in enumerate(lines):
    if '${_t(' in line:
        # Check if this line is inside a backtick template literal
        stripped = line.strip()
        # If it's a single-quoted string (not backtick), fix it
        if not stripped.startswith('`') and '`' not in stripped:
            # Check if the line contains '...${_t(...)}...' (single-quoted or double-quoted string)
            if re.search(r"""['"]\s*\+?\s*\$\{_t\(""", stripped):
                # Already fixed with + _t()
                new_lines.append(line)
                continue
            if re.search(r"""['"].*\$\{_t\(""", stripped):
                new_line = pat.sub(r"' + _t('\1','\2') + '", line)
                if new_line != line:
                    print(f'Line {i+1}: {stripped[:60]}...')
                    line = new_line
                    fixed += 1
    new_lines.append(line)

s = ''.join(new_lines)
with open(path, 'w', encoding='utf-8') as f:
    f.write(s)
print(f'\nFixed {fixed} lines')
