"""页面 DOM 的只读工具。

所有函数都不发起网络请求，只处理已经归档到本地的页面样本。
XPath 全部按“记录区域相对路径”的约定工作，避免把绝对 XPath 当成规则。
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

# 结构不稳定、不能当作定位依据的属性
UNSTABLE_ATTRIBUTES = frozenset({
    'id', 'style', 'class', 'width', 'height', 'src', 'href',
    'data-v-', 'aria-',
})

# 候选类型的稳定度排序，数值越小越优先
CANDIDATE_RANK = {
    'data_attr': 0,
    'text_anchor': 1,
    'position': 2,
    'class_token': 3,
    'bare_tag': 4,
}


def load_tree(path):
    """从本地文件读取 HTML，解析失败时抛出 ValueError 而不是静默返回空树。

    页面自带 charset 时以页面为准；没有声明时按 UTF-8 解析，
    避免 lxml 的 latin-1 兜底把中文锚点解成乱码。
    """
    raw = Path(path).read_bytes()
    parser = etree.HTMLParser(encoding='utf-8', remove_comments=True)
    tree = etree.fromstring(raw, parser=parser)
    if tree is None:
        raise ValueError(f'页面无法解析: {path}')
    return tree


def relative_path(anchor, target):
    """target 相对 anchor（记录区域）的显式层级路径。

    XPath 的 ``strong[3]`` 表示“第三个 strong 兄弟”而不是“第三个子节点”，
    因此用 ``*[n][name()='tag']`` 表达真正的 nth-child 位置，
    例如 ./*[3][name()='strong']，避免布局插入节点后静默错位。
    """
    chain = []
    node = target
    while node is not None and node is not anchor:
        parent = node.getparent()
        if parent is None:
            raise ValueError('目标节点不在记录区域内')
        element_siblings = [child for child in parent if isinstance(child.tag, str)]
        position = element_siblings.index(node) + 1
        chain.append(f"*[{position}][name()='{node.tag}']")
        node = parent
    if node is not anchor:
        raise ValueError('目标节点不在记录区域内')
    if not chain:
        return '.'
    return './' + '/'.join(reversed(chain))


def node_path(root, node):
    """节点相对文档根的可读路径，用于报告实际 DOM 位置，不参与定位。"""
    chain = []
    current = node
    while current is not None and current is not root:
        parent = current.getparent()
        if parent is None:
            break
        element_siblings = [child for child in parent if isinstance(child.tag, str)]
        position = element_siblings.index(current) + 1
        chain.append(f"*[{position}][name()='{current.tag}']")
        current = parent
    return '/' + '/'.join(reversed(chain))


def text_of(node):
    """元素全部文本内容（兼容 etree 与 html 元素）。"""
    return ''.join(node.itertext())


def text_preview(node, limit=40):
    text = ' '.join(' '.join(node.itertext()).split())
    if len(text) > limit:
        text = text[:limit] + '…'
    return text


def stable_attributes(node):
    """返回可作为定位依据的稳定属性，剔除运行时与样式类属性。"""
    result = {}
    for name, value in node.attrib.items():
        if name in UNSTABLE_ATTRIBUTES:
            continue
        if name.startswith(('data-v-', 'aria-')):
            continue
        result[name] = value
    return result


def class_tokens(node):
    return node.get('class', '').split()


def xpath_literal(value):
    """把 Python 字符串安全编码成 XPath 字面量。"""
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return 'concat(' + ", \"'\", ".join(f"'{part}'" for part in parts) + ')'


def anchor_texts(anchor, target, max_words=12):
    """在记录区域内找目标节点周围可作锚点的短文本。

    返回 (文本, 关系, 来源节点) 三元组：``self`` 表示目标自身完整文本
    （精确相等），``sibling`` 表示前置兄弟或同容器邻近元素的文本。
    只返回可人工核对的短纯文本，长度受限，避免把整段内容当锚点。
    来源节点一并返回，调用方可以排除来自负例节点的锚点。
    """
    anchors = []
    seen = set()

    def take(source, text, mode):
        cleaned = ' '.join(text.split())
        if not cleaned or len(cleaned) > 24 or cleaned in seen:
            return
        seen.add(cleaned)
        anchors.append((cleaned, mode, source))

    take(target, text_of(target), 'self')
    for sibling in target.itersiblings(preceding=True):
        take(sibling, text_of(sibling), 'sibling')
        if len(anchors) >= max_words:
            return anchors
    parent = target.getparent()
    while parent is not None and parent is not anchor:
        for sibling in parent.itersiblings(preceding=True):
            take(sibling, text_of(sibling), 'sibling')
            if len(anchors) >= max_words:
                return anchors
        parent = parent.getparent()
    return anchors


def record_signature(record):
    """记录区域内标签构成的结构签名，用于检测布局扰动。"""
    counts = {}
    for node in record.iter():
        if isinstance(node.tag, str):
            counts[node.tag] = counts.get(node.tag, 0) + 1
    return tuple(sorted(counts.items()))


def unique_text(element):
    return ' '.join(' '.join(element.itertext()).split())
