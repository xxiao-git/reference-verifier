---
name: reference-verifier
description: Verify AI-generated reference lists against CrossRef, filter out fabricated citations, and generate RIS with full metadata for import into Zotero, EndNote, Mendeley, and other reference managers. Designed for AI assistant interaction — users interact via natural language dialogue. Triggers include "verify references", "check if these citations are real", "validate bibliography", "reference verification", "核实参考文献", "验证文献真伪", "安装 reference-verifier".
agent_created: true
---

# Reference Verifier — AI文献核验工作流

**本技能为 AI 助理设计，全程通过对话交互完成，用户无需记忆任何命令。**

4步管线：从 .docx/.txt/.json 提取参考文献（多格式兼容） → CrossRef 搜索 → DOI 标题精验证 → 生成 RIS 文件（兼容 Zotero / EndNote / Mendeley 等）。每条题录 N1 字段自动标注原始参考文献编号（如 `ref#7`）。

## 依赖安装（AI 助理自动执行）

首次使用本技能时，AI 助理**必须自动**检查并安装依赖：

```bash
pip install python-docx requests
```

如已安装则跳过。如安装失败，告知用户手动执行上述命令。

## 使用触发

当用户说以下任意一句时直接走管线：
- "帮我核实这篇文章的参考文献"
- "检查哪些引用可能是编造的"
- "验证参考文献真伪"
- "验证后导出 RIS"
- "安装 reference-verifier 技能" → 克隆仓库 + 安装依赖

## 管线流程

所有脚本均通过 `argparse` 接收参数，无任何硬编码路径。

### Step 1: 提取参考文献 (`scripts/step1_extract.py`)

**输入**: `.docx`（自动定位 References / 参考文献 等章节）/ `.txt`（逐行解析）/ `.json`（预提取，跳过解析）
**输出**: `references_extracted.json`

**多格式兼容**：不限特定引用格式，通过多策略启发式提取 DOI / 作者 / 标题 / 期刊 / 年份。支持 Vancouver、APA、AMA、MLA、Chicago、Harvard 及无标准格式的纯文本。有 DOI 的文献自动提取，后续走快速通道。

```bash
python scripts/step1_extract.py --input manuscript.docx --output-dir ./output/
python scripts/step1_extract.py --input refs.txt --output-dir ./output/
```

### Step 2: CrossRef 搜索匹配 (`scripts/step2_crossref_search.py`)

**输入**: `references_extracted.json`
**输出**: `references_verified.json` / `found_dois.txt` / `flagged_suspicious.txt`

```bash
python scripts/step2_crossref_search.py --input ./output/references_extracted.json --output-dir ./output/
```

- **DOI 快速通道**：Step 1 已提取到 DOI 的文献跳过标题搜索，直接标记 OK
- 无 DOI 的文献逐条标题搜索 CrossRef，四维评分（标题/年份/作者/期刊）
- 分级：**OK**(≥40) / **WARN**(20-39) / **FAIL**(<20)

### Step 3: DOI 标题精验证 (`scripts/step3_strict_verify.py`)

**输入**: `references_verified.json`
**输出**: `references_strict_verified.json` / `found_dois_strict.txt` / `dois_mismatch.txt`

```bash
python scripts/step3_strict_verify.py --input ./output/references_verified.json --output-dir ./output/
```

用 DOI 反查 CrossRef 真实标题 → SequenceMatcher + 词重叠 + 首N词匹配计算相似度：
- **PASS**(≥0.70): 标题匹配
- **WARN**(0.50-0.69): 部分匹配需人工确认
- **FAIL**(<0.50): DOI 指向不同文章

作者姓氏不匹配时 PASS → WARN 自动降级。

### Step 4: 生成 RIS 文件 (`scripts/step4_generate_ris.py`)

**输入**: `references_strict_verified.json`
**输出**: `verified_references.ris` / `verification_summary.txt`

```bash
python scripts/step4_generate_ris.py --input ./output/references_strict_verified.json --output ./output/verified_references.ris
```

- **自动读取** `pass2_status == "PASS"` 的文献（`--include-warn` 可加入 WARN）
- 逐条用 DOI 取 CrossRef 完整元数据（全作者、卷、期、起止页、ISSN、摘要）
- **N1 字段**：`RefVer verified | ref#X`，标注原始参考文献编号
- 默认排除 biorxiv / meeting-abstract / preprint（`--exclude` 可自定义）
- **`verification_summary.txt`**：记录每条文献的最终去向，五种状态：
  - **KEPT**：通过验证，写入 RIS（含元数据详情或 fallback 说明）
  - **EXCLUDED**：通过验证但类型不符（如预印本/会议摘要），从 RIS 剔除，注明匹配到的排除关键词
  - **WARN**：部分匹配，未纳入 RIS，建议人工确认
  - **FAIL**：DOI 指向不同论文（信息虚假），不纳入 RIS
  - **NO_DOI**：未找到 DOI，无法验证
- RIS 兼容 Zotero / EndNote / Mendeley / Papers 等主流文献管理工具

## RIS 导入

| 工具 | 导入方式 |
|------|----------|
| Zotero | 文件 → 导入 → 选 RIS 文件 |
| EndNote | File → Import → File → 选 RIS |
| Mendeley | File → Import → RIS |
| Papers | File → Import → Reference File |

## 注意事项

1. **依赖**: `pip install python-docx requests`（AI 助理首次使用时自动安装）
2. **格式兼容**: Step 1 支持 Vancouver / APA / AMA / MLA / Chicago / Harvard 及纯文本，不限特定格式
3. **CrossRef API 限速**: 脚本内置 0.3-0.5s 延迟和 429 重试
4. **编码**: Windows GBK 环境已做 `errors='replace'` 处理
5. **覆盖范围**: CrossRef 未收录的文献（如部分中文期刊、会议摘要等）无法匹配，未来可扩展 PubMed Entrez API 补充
6. **结果解读**:
   - PASS = DOI 标题匹配 → 可放心导入
   - WARN = 部分匹配 → 建议人工确认
   - FAIL = 不匹配/无结果 → 大概率 AI 编造
