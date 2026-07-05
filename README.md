# Reference Verifier

**AI 生成参考文献的真伪核验管线** — 从稿件或纯文本列表提取参考文献，经 CrossRef 双重验证（标题搜索 + DOI 精匹配），筛选出 AI 编造的虚假引用，并生成含完整元数据的 RIS 文件供 Zotero、EndNote、Mendeley 等文献管理工具导入。每条题录在 N1 字段自动标注原始参考文献编号（如 `ref#7`），方便回溯文中位置。

**本技能为 AI 助理设计，全程通过对话交互完成。**

---

## 为什么需要这个工具

AI 辅助写作在生成参考文献时，经常会**编造看似真实但实际不存在的论文**——标题像模像样、作者名合理、期刊缩写正确，但 DOI 指向完全不同的文章，或者根本查无此文。手动逐条核实几十条参考文献既耗时又容易遗漏。

Reference Verifier 自动化了这个核验流程：

| 问题 | 解决方案 |
|------|----------|
| AI 编造的参考文献难以肉眼辨别 | CrossRef API 标题搜索 + 四维评分 |
| DOI 存在但指向不同论文 | DOI 反查真实标题 → SequenceMatcher 精确比对 |
| 核实后还要手动整理导入文献管理器 | 自动生成含全元数据的 RIS 文件，兼容主流工具 |
| 无法追溯哪条文献对应文中哪个编号 | 每条 RIS 题录自动标注原始参考文献编号（N1 字段） |

---

## 安装

### 对话式安装（推荐）

对 AI 助理说：

```
从这个地址安装技能：https://github.com/xxiao-git/reference-verifier
```

AI 助理会自动：
1. 从 GitHub 克隆仓库：`git clone https://github.com/xxiao-git/reference-verifier.git`
2. 检查 Python 环境并安装依赖：`pip install python-docx requests`

> **环境要求**：Python ≥ 3.8，网络可访问 `https://api.crossref.org`

### 手动安装

如果对话式安装失败，可手动执行：

```bash
git clone https://github.com/xxiao-git/reference-verifier.git
cd reference-verifier
pip install -r requirements.txt
```

---

## 对话式使用

安装完成后，直接用自然语言对话即可，无需记忆任何命令。

### 基础使用

| 你说 | AI 助理做什么 |
|------|--------------|
| "帮我核实这篇文档的参考文献" [附 .docx] | 走完整 4 步管线，输出 RIS 文件 |
| "检查这个文献列表哪些可能是编造的" [附 .txt 或直接贴文本] | 提取 + 验证 + 输出 |
| "验证后导出 RIS 文件" | 完成验证并生成 RIS |
| "验证这些参考文献" [附 .json 预提取文件] | 跳过解析，直接验证 |

### 参数调整

| 你说 | AI 助理做什么 |
|------|--------------|
| "这次排除关键词加上 review 和 letter" | Step 4 添加 `--exclude ... review letter`（从 RIS 中剔除匹配的文献，不是变成 WARN） |
| "这次也把 WARN 的文献包含进去" | Step 4 添加 `--include-warn` |

### 维护

| 你说 | AI 助理做什么 |
|------|--------------|
| "更新 reference-verifier 到最新版本" | `git pull` 并重新检查依赖 |
| "检查 reference-verifier 依赖是否就绪" | 验证 Python 环境，缺什么补什么 |

---

## 管线架构

```
.docx / .txt / .json 输入
    │
    ▼
┌─────────────────────────────────┐
│  Step 1: 提取参考文献            │
│  · 多格式解析器（不限特定格式）   │
│  · 提取 DOI/作者/标题/期刊/年份   │
│  → references_extracted.json     │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  Step 2: CrossRef 搜索匹配       │
│  · 有 DOI → 快速通道             │
│  · 无 DOI → 逐条标题搜索         │
│  · 四维评分                      │
│  → references_verified.json      │
──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  Step 3: DOI 标题精验证          │
│  · 反查真实标题 → 相似度评分      │
│  · 作者降级机制                  │
│  → references_strict_verified.json│
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  Step 4: 生成 RIS 文件           │
│  · 自动读取 PASS 文献            │
│  · 完整元数据 + 原始编号标注      │
│  · 兼容 Zotero/EndNote/Mendeley  │
│  → verified_references.ris       │
└─────────────────────────────────
```

---

## 核心功能详情

### Step 1 — 多格式参考文献提取

支持三种输入格式：`.docx`（自动定位 References 章节）、`.txt`（逐行解析）、`.json`（预提取，直接透传）。

**不限定特定引用格式**，通过多策略启发式提取核心字段：

| 格式 | 示例 | 解析策略 |
|------|------|----------|
| Vancouver | `Caplin ME, et al. Title. J Thorac Oncol. 2020;15(2):211-222.` | et al. 后截取标题 |
| APA | `Caplin, M. E. (2024). Title. Journal, 12(3), 1-10.` | `(YYYY).` 后提取标题 |
| AMA | `Caplin ME. Title. J Thorac Oncol. 2020;15(2):211-222.` | 第一句点后提取标题 |
| MLA / Chicago | `Caplin, M. E. "Title." Journal, vol. 15, 2020.` | 引号内提取标题 |
| Harvard | `Caplin, M.E. (2024) 'Title', Journal, 12(3), pp. 1-10.` | `(YYYY) 'Title'` 模式 |
| 含 DOI | `... https://doi.org/10.1016/j.jtho.2019.11.001` | DOI 正则提取 → 走快速通道 |

### Step 2 — CrossRef 搜索匹配

- **DOI 快速通道**：Step 1 已提取到 DOI 的文献跳过搜索，直接标记 OK
- 无 DOI 的文献逐条标题搜索 CrossRef（Top 5 候选）
- **四维评分**：标题重叠(40) + 年份(20) + 第一作者(15) + 期刊(10) = 满分 85
- 分级：**OK**(≥40) / **WARN**(20–39) / **FAIL**(<20)

### Step 3 — DOI 标题精验证

用 DOI 反查 CrossRef 获取真实标题，三级相似度计算（SequenceMatcher 50% + 词重叠 30% + 首 N 词精确匹配 20%）：
- **PASS**(≥0.70) / **WARN**(0.50–0.69) / **FAIL**(<0.50)
- 作者姓氏不匹配 → PASS 自动降级为 WARN

### Step 4 — 生成 RIS 文件

- 自动读取 PASS 文献（`--include-warn` 可纳入 WARN）
- RIS 字段：标题(TI)、全作者(AU)、年份(PY)、期刊(JF/JO)、卷(VL)、期(IS)、起止页(SP/EP)、DOI(DO)、ISSN(SN)、出版社(PB)、摘要(AB)、URL(UR)、备注(N1)
- **N1 字段**：`RefVer verified | ref#X`，X 为原始参考文献编号
- 默认排除 `biorxiv` / `meeting abstract` / `preprint`（`--exclude` 可自定义）
- RIS 兼容 Zotero、EndNote、Mendeley、Papers、Citavi 等

---

## 结果解读

| 状态 | 含义 | 建议操作 |
|------|------|----------|
| **OK / PASS** | CrossRef 确认匹配，DOI 指向正确论文 | 可放心导入文献管理器 |
| **WARN** | 部分匹配，需人工确认 | 点开 DOI 链接核对 |
| **FAIL** | 无匹配或 DOI 指向不同论文 | 大概率 AI 编造，删除或替换 |

---

## RIS 导入

| 工具 | 导入方式 |
|------|----------|
| **Zotero** | 文件 → 导入 → 选择 RIS 文件 |
| **EndNote** | File → Import → File → 选择 RIS 文件 |
| **Mendeley** | File → Import → RIS |
| **Papers** | File → Import → Reference File |

---

## 输出文件说明

| 文件 | 内容 |
|------|------|
| `references_extracted.json` | 从输入文件提取的结构化文献列表 |
| `references_verified.json` | 含 CrossRef 搜索结果和 DOI 的验证结果 |
| `found_dois.txt` | 已匹配到的 DOI 列表 |
| `flagged_suspicious.txt` | 疑似编造文献的可读报告 |
| `references_strict_verified.json` | 含 DOI 精验证结果 |
| `found_dois_strict.txt` | 精验证通过的有效 DOI 列表 |
| `dois_mismatch.txt` | DOI 指向错误论文的详情报告 |
| `verified_references.ris` | 可导入文献管理器的 RIS 文件 |
| `verification_summary.txt` | 每条文献的最终去向（KEPT/EXCLUDED/WARN/FAIL/NO_DOI） |

---

## 限制与注意事项

1. **解析器启发式**：非标准排版可能提取不完整。使用 `.json` 输入（预提取）可绕过解析
2. **CrossRef 覆盖范围**：部分期刊（如某些中文期刊、会议摘要）可能不在 CrossRef 索引中，导致无法匹配。未来可扩展 PubMed Entrez API 作为补充数据源
3. **章节定位**：`.docx` 输入时自动识别 References / 参考文献 / Bibliography 等标题
4. **预印本排除**：Step 4 默认排除预印本，可通过对话调整
5. **API 限速**：大规模验证（>100 条）时建议分批处理

---

## 项目结构

```
reference-verifier/
├── README.md                          # 本文件
── SKILL.md                           # AI 助理 Skill 元数据
├── requirements.txt                   # Python 依赖
├── LICENSE                            # MIT
── .gitignore
├── scripts/
│   ├── step1_extract.py               # 多格式参考文献提取
│   ├── step2_crossref_search.py       # CrossRef 搜索匹配
│   ├── step3_strict_verify.py         # DOI 标题精验证
│   └── step4_generate_ris.py          # 生成 RIS 文件
└── examples/
    └── sample_output/                 # 示例输出文件
```

---

## License

MIT License — 详见 [LICENSE](LICENSE) 文件。

---

## 致谢

- [CrossRef](https://www.crossref.org/) — 提供免费的元数据搜索与 DOI 解析 API

