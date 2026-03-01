import re
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

def _linkify(text: str) -> str:
    # 简易链接化：[Label](URL)
    # 输入的 text 应当已经是经过转义的
    pattern = re.compile(r'\[([^\]]+)\]\((https?://[^"\s<]+)\)')
    def repl(m):
        label, url = m.group(1), m.group(2)
        # 再次确保 URL 不包含危险字符（虽然正则已限制）
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'
    return pattern.sub(repl, text)

@register.filter
def safe_md(value: str):
    """
    简易、安全 Markdown 渲染。
    核心安全逻辑：
    1. 首先对整个输入进行 HTML 转义 (escape)，防止原始 HTML 标签注入。
    2. 然后基于转义后的文本，使用正则匹配受限的 Markdown 语法并替换为安全的 HTML 标签。
    注意：此方法比使用 bleach 更轻量，适用于仅需支持极简语法的场景。
    """
    if not value:
        return ""
    
    # 第一步：全局转义，杀死所有潜在的 HTML/JS
    safe_value = escape(value)
    
    lines = safe_value.splitlines()
    out = []
    in_list = False
    
    for raw in lines:
        line = raw.rstrip()
        stripped_line = line.strip()
        
        # 处理无序列表
        if stripped_line.startswith(('-', '*')) and len(stripped_line) > 1 and stripped_line[1] == ' ':
            if not in_list:
                out.append('<ul>')
                in_list = True
            # 移除标记符
            text = stripped_line[2:].strip()
            # 链接化处理
            out.append(f'<li>{_linkify(text)}</li>')
            continue
            
        if in_list:
            out.append('</ul>')
            in_list = False
            
        # 处理标题
        if stripped_line.startswith('## '):
            out.append(f'<h4>{_linkify(stripped_line[3:].strip())}</h4>')
        elif stripped_line.startswith('# '):
            out.append(f'<h3>{_linkify(stripped_line[2:].strip())}</h3>')
        # 处理段落
        elif stripped_line:
            out.append(f'<p>{_linkify(stripped_line)}</p>')
        else:
            out.append('<br>')
            
    if in_list:
        out.append('</ul>')
        
    return mark_safe(''.join(out))
