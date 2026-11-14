"""可比较的定位候选生成与评价。

候选只表达三类信息：记录内相对位置、稳定属性、文本锚点；
绝对 XPath 与页面摘要不参与。每个候选都要在同组的全部人工
样本上复算，负例命中或多重命中即被淘汰，不靠“取第一个节点”兜底。
"""
from __future__ import annotations

from .labio import (
    CANDIDATE_RANK,
    anchor_texts,
    class_tokens,
    relative_path,
    stable_attributes,
    xpath_literal,
)


def _attr_clause(name, value):
    return f'@{name}={xpath_literal(value)}'


def _inside_any(node, containers):
    """node 是否就是某个容器节点或位于其内部。"""
    for container in containers:
        current = node
        while current is not None:
            if current is container:
                return True
            current = current.getparent()
    return False


def _record_clause(node, skip_attrs=()):
    clauses = []
    for name, value in stable_attributes(node).items():
        if name in skip_attrs:
            continue
        clauses.append(_attr_clause(name, value))
    if clauses:
        return node.tag + '[' + ' and '.join(clauses) + ']'
    return node.tag


def record_locator_candidates(record):
    """为记录区域生成泛化定位候选。

    只用属性是否存在而不绑定具体业务值（如具体 SKU），避免换商品后
    规则整体失效；类名与裸标签作为低稳定度兜底。候选之间是否能区分
    模板，由生成阶段在全部模板样本上复核。
    """
    candidates = []
    seen = set()

    def add(kind, xpath, feature):
        if xpath in seen:
            return
        seen.add(xpath)
        candidates.append({'kind': kind, 'xpath': '//' + xpath, 'feature': feature})

    for name in stable_attributes(record):
        add('data_attr', f'{record.tag}[@{name}]', f'tag={record.tag}, 存在属性 {name}')
    for token in class_tokens(record):
        add('class_token',
            f'{record.tag}[contains(concat(" ",@class," "),{xpath_literal(" " + token + " ")})]',
            f'tag={record.tag}, class~={token}')
    add('bare_tag', record.tag, f'tag={record.tag}')
    candidates.sort(key=lambda item: CANDIDATE_RANK[item['kind']])
    return candidates


def field_candidates(record, target, negatives):
    """针对一条正例生成字段候选，候选相对记录区域，且不与负例同路径。"""
    candidates = []
    seen = set()
    negative_paths = {relative_path(record, node) for node in negatives}

    def add(kind, xpath, feature):
        if xpath in seen or xpath in negative_paths:
            return
        seen.add(xpath)
        candidates.append({
            'kind': kind,
            'xpath': xpath,
            'feature': feature,
        })

    # 1. 记录内显式层级位置
    position = relative_path(record, target)
    add('position', position, f'相对位置 {position}')

    # 2. 稳定数据属性
    for name, value in stable_attributes(target).items():
        add('data_attr', f'.//{target.tag}[{_attr_clause(name, value)}]',
            f'{name}={value}')

    # 3. 类名标记（布局变动后最容易漂移到旧价节点）
    for token in class_tokens(target):
        add('class_token',
            f'.//{target.tag}[contains(concat(" ",@class," "),{xpath_literal(" " + token + " ")})]',
            f'tag={target.tag}, class~={token}')

    # 4. 裸标签（歧义最高，仅用于暴露多命中）
    add('bare_tag', f'.//{target.tag}', f'tag={target.tag}')

    # 5. 邻近文本锚点：按锚点与目标的真实结构关系构造
    tag = target.tag
    for anchor, mode, source in anchor_texts(record, target):
        # 负例节点或其内部文本不能当锚点，避免规则把划线价当成定位依据
        if _inside_any(source, negatives):
            continue
        literal = xpath_literal(anchor)
        if mode == 'self':
            xpath = f'.//{tag}[normalize-space(.)={literal}]'
        else:
            # 锚点是前置元素：同容器内的目标标签；或前置兄弟为文本型节点
            xpath = (
                f'.//*[*[contains(normalize-space(.),{literal})]]/{tag} '
                f'| .//{tag}[preceding-sibling::*[1][contains(normalize-space(.),{literal})]]'
            )
        add('text_anchor', xpath,
            f'文本锚点（{"自身文本" if mode == "self" else "前置文本"}）{anchor!r}')

    candidates.sort(key=lambda item: CANDIDATE_RANK[item['kind']])
    return candidates


def evaluate_on_labels(candidate, labels_with_pages, record_locators=None):
    """在组内全部人工样本上复算候选。

    返回逐样本证据与是否一致：每条样本都必须唯一命中正例、
    不碰任何负例，否则候选被淘汰并写明原因。此外还要在同一页面的
    其它同构记录上恰好命中一次，否则候选只是“记住了被圈选那条”，
    换一条记录（如另一个商品的不同价格）就会失效。

    record_locators 提供每个页面的泛化记录定位 XPath，用于找到同页
    全部同构记录；缺省时退回该标签自己的 record XPath。
    """
    record_locators = record_locators or {}
    evidence = []
    consistent = True
    for page, label in labels_with_pages:
        hits = label.record.xpath(candidate['xpath'])
        negative_set = set(label.negative_relatives)
        hit_paths = {relative_path(label.record, node) for node in hits}
        status = 'unique'
        if not hits:
            status = 'no_hit'
            consistent = False
        elif len(hits) > 1:
            status = 'multi_hit'
            consistent = False
        elif hits[0] is not label.positive:
            status = 'wrong_node'
            consistent = False
        if status == 'unique' and hit_paths & negative_set:
            status = 'negative_hit'
            consistent = False
        evidence.append({
            'file': page.file,
            'template': page.template,
            'status': status,
            'hits': len(hits),
        })
        if status != 'unique':
            continue
        # 同页其它同构记录：候选必须在每条记录上恰好命中一次，
        # 证明它描述的是记录内通用结构而非具体业务文本。
        locator_xpath = record_locators.get(page.file, label.record_xpath)
        for other in page.tree.xpath(locator_xpath):
            if other is label.record:
                continue
            other_hits = other.xpath(candidate['xpath'])
            if len(other_hits) != 1:
                evidence.append({
                    'file': page.file,
                    'template': page.template,
                    'status': 'sibling_' + ('no_hit' if not other_hits else 'multi_hit'),
                    'hits': len(other_hits),
                })
                consistent = False
    return consistent, evidence


def evaluate_on_record(candidate, record, negative_relatives, positive=None):
    """在未参与生成的记录上复算候选，返回命中情况与实际 DOM 位置。"""
    hits = record.xpath(candidate['xpath'])
    if not hits:
        return {'status': 'no_hit', 'hits': 0, 'nodes': []}
    nodes = []
    status = 'unique'
    if len(hits) > 1:
        status = 'multi_hit'
    hit_paths = {relative_path(record, node) for node in hits}
    if hit_paths & set(negative_relatives):
        status = 'negative_hit'
    if positive is not None and status == 'unique' and hits[0] is not positive:
        status = 'wrong_node'
    return {'status': status, 'hits': len(hits), 'nodes': sorted(hit_paths)}
