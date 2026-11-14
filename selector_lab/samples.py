"""人工圈选资料的加载与校验。

资料约定见 docs/data.md：record 是记录区域 XPath，positive/negative
相对该区域。加载阶段就把 XPath 解析成真实节点，路径失效立即报错，
不让坏标签流进生成阶段。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .labio import load_tree, record_signature, relative_path


@dataclass
class Label:
    field: str
    record: object
    record_xpath: str
    positive: object
    positive_relative: str
    negatives: list
    negative_relatives: list
    signature: tuple


@dataclass
class PageBundle:
    file: str
    template: str
    tree: object
    labels: list
    labeled: bool


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_bundle(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    _require(isinstance(data, dict) and isinstance(data.get('pages'), list),
             '资料缺少 pages 列表')
    pages = []
    for entry in data['pages']:
        _require(isinstance(entry, dict), '页面条目必须是对象')
        file_name = entry.get('file')
        template = entry.get('template')
        _require(isinstance(file_name, str) and isinstance(template, str),
                 '页面必须同时提供 file 与 template')
        tree = load_tree(path.parent / file_name)
        labels = []
        raw_labels = entry.get('labels', [])
        _require(isinstance(raw_labels, list), 'labels 必须是列表')
        for raw in raw_labels:
            _require(isinstance(raw, dict), '圈选条目必须是对象')
            field = raw.get('field')
            record_xpath = raw.get('record')
            positive_xpath = raw.get('positive')
            negative_xpaths = raw.get('negative', [])
            _require(isinstance(field, str) and field, '圈选缺少 field')
            _require(isinstance(record_xpath, str), f'{field} 缺少 record XPath')
            _require(isinstance(positive_xpath, str), f'{field} 缺少 positive XPath')
            _require(isinstance(negative_xpaths, list), f'{field} 的 negative 必须是列表')

            records = tree.xpath(record_xpath)
            _require(records, f'{file_name}/{field}: record 未命中任何节点: {record_xpath}')
            positives = records[0].xpath(positive_xpath)
            _require(len(positives) == 1,
                     f'{file_name}/{field}: positive 必须在记录内唯一命中，实际 {len(positives)} 个')
            positive = positives[0]

            negatives = []
            negative_relatives = []
            for neg_xpath in negative_xpaths:
                _require(isinstance(neg_xpath, str), f'{field} 的 negative 必须是 XPath 字符串')
                hits = records[0].xpath(neg_xpath)
                _require(hits, f'{file_name}/{field}: negative 未命中: {neg_xpath}')
                for hit in hits:
                    negatives.append(hit)
                    negative_relatives.append(relative_path(records[0], hit))
                if positive in hits:
                    raise ValueError(
                        f'{file_name}/{field}: 负例节点与正例是同一节点，圈选自相矛盾')

            labels.append(Label(
                field=field,
                record=records[0],
                record_xpath=record_xpath,
                positive=positive,
                positive_relative=relative_path(records[0], positive),
                negatives=negatives,
                negative_relatives=negative_relatives,
                signature=record_signature(records[0]),
            ))
        pages.append(PageBundle(
            file=file_name,
            template=template,
            tree=tree,
            labels=labels,
            labeled=bool(labels),
        ))
    _require(any(page.labeled for page in pages), '资料中没有任何人工圈选，无法生成规则')
    return pages


def group_labels(pages):
    """按 (模板, 字段) 聚合圈选，保留来源页面，便于报告冲突。"""
    groups = {}
    for page in pages:
        if not page.labeled:
            continue
        for label in page.labels:
            groups.setdefault((page.template, label.field), []).append((page, label))
    return groups
