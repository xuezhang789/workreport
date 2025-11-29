from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe
import re

register = template.Library()


def _linkify(text: str) -> str:
    # 支持 [text](http/https) 形式
    pattern = re.compile(r'\[([^\]]+)\]\((https?://[^)]+)\)')
    def repl(m):
        label, url = m.group(1), m.group(2)
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{escape(label)}</a>'
    return pattern.sub(repl, escape(text))


@register.filter
def safe_md(value: str):
    """
    简易、安全 Markdown 渲染：仅支持标题/无序列表/段落/链接，自动转义其余 HTML。
    """
    if not value:
        return ""
    lines = value.splitlines()
    out = []
    in_list = False
    for raw in lines:
        line = raw.rstrip()
        if line.strip().startswith(('-', '*')):
            if not in_list:
                out.append('<ul>')
                in_list = True
            text = line.lstrip('-* ').strip()
            out.append(f'<li>{_linkify(text)}</li>')
            continue
        if in_list:
            out.append('</ul>')
            in_list = False
        if line.startswith('## '):
            out.append(f'<h4>{_linkify(line[3:].strip())}</h4>')
        elif line.startswith('# '):
            out.append(f'<h3>{_linkify(line[2:].strip())}</h3>')
        elif line.strip():
            out.append(f'<p>{_linkify(line.strip())}</p>')
        else:
            out.append('<br>')
    if in_list:
        out.append('</ul>')
    return mark_safe(''.join(out))
