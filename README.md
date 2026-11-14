# 页面样本引导的字段定位规则生成与歧义检出

这个 Python 项目把人工圈选转成可比较、可验证、带负例约束的字段定位规则，
并让“规则生成”和“日常执行”保持清楚边界。它只处理已保存到本地的页面样本，
不联网抓站；旧选择器“返回一个数字就算成功”的问题，在这里被多命中、无命中、
负例命中和结构漂移等显式未决状态取代，宁可暂缓一个价格字段，也不把划线原价
当售价输出。

## 模块划分

- `selector_lab/labio.py`：本地页面解析与只读 DOM 工具（nth-child 相对路径、
  稳定属性、文本锚点、结构签名）。
- `selector_lab/samples.py`：加载并校验圈选资料，路径失效或正负例同节点立即报错。
- `selector_lab/candidates.py`：生成记录区域与字段候选，并在全部样本与同页
  全部同构记录上复算，负例命中、多重命中即淘汰。
- `selector_lab/generate.py`：编排生成，产出内容寻址的候选草稿（draft）。
- `selector_lab/verify.py`：对未参与生成的页面复算全部候选，展示覆盖情况与
  实际 DOM 位置，模板拿不准或候选分歧时给出未决结论。
- `selector_lab/store.py`：草稿、不可变规则包（pack）与激活指针的版本存储。
- `selector_lab/execute.py`：只按激活的规则包执行，任何歧义都返回 undecided。
- `selector_lab/archive.py`：原始字节的内容寻址归档；`core.py` 提供资料预览。
- `fixtures/` 保存本地演练资料，`tests/` 检查上述承诺。

## 环境

Python 3.11.2。依赖及其间接依赖固定在 `requirements.txt`：

```sh
python3 -m pip install -r requirements.txt
```

## 生成、验证与发布流程

```sh
# 1. 从人工圈选生成候选草稿（只写草稿，不触碰任何已发布规则）
python3 -m selector_lab generate fixtures/annotations.json --lab .work/lab

# 2. 对资料中的页面（含没有标签的 changed.html）复算全部候选
python3 -m selector_lab verify fixtures/annotations.json \
    --draft <草稿id> --lab .work/lab

# 3. 一个字段有多个一致候选时，运营显式选择后才能发布
python3 -m selector_lab publish --draft <草稿id> --lab .work/lab \
    --select list/price=<候选id> --select detail/price=<候选id>

# 4. 固定运行版本，然后执行页面
python3 -m selector_lab activate <规则包id> --lab .work/lab
python3 -m selector_lab run fixtures/changed.html --lab .work/lab

python3 -m selector_lab status --lab .work/lab
```

字段存在样本冲突（`samples_conflict`）或发布时未对多候选显式选择，命令直接
失败，不产生空成功结果。运行结果携带规则包 id；结构扰动、多命中、无命中、
负例命中或模板拿不准时 `verdict` 为 `undecided`、字段值为 `null`。

## 版本边界

草稿与规则包分目录存放，文件以内容 SHA-256 命名、原子写入、不可变。
新增标签只能生成新草稿，无法悄悄改动已确认规则；规则包内容与摘要不一致时
拒绝执行。激活指针保证正在运行的采集重复得到同一版定位结果。

## 开发检查

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q selector_lab tests
```

## 本地演示

```sh
python3 -m selector_lab demo
```

演示在临时目录内走通归档、生成、未标注页验证、发布、激活与执行全链路，
最后对布局扰动页面返回未决而不是输出划线价。所有示例身份与业务数值均为
虚构，不需要外部账号，也不发起网络请求。
