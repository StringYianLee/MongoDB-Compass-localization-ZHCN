# 社区功能配置方案：Issues · Sponsorships · Discussions

本文针对仓库 `StringYianLee/MongoDB-Compass-localization-ZHCN`，给出三项社区功能的用途说明、适用场景、影响评估、前置条件、注意事项与**可逐项照做的设置步骤**。

> 现状快照（2026-10-25）
>
> | 功能 | 当前状态 | 说明 |
> | --- | --- | --- |
> | Issues | ✅ 已启用 | 尚无 Issue 模板、标签体系与分流规则 |
> | Discussions | ✅ 已启用 | 已有默认 6 个分类，尚无欢迎帖与版规 |
> | Sponsorships | ⚠️ 未就绪 | 账号未开通 GitHub Sponsors，仓库无 `FUNDING.yml`，无 Sponsor 按钮 |
> | Projects / Wiki | ✅ 已启用 | 建议按需保留（Wiki 与 `docs/` 可能重复） |

---

## 一、Issues（问题跟踪）

### 用途

- 记录**可复现的缺陷**、**明确的功能需求**与**兼容性回归**；
- 形成可检索、可关闭、可关联提交/PR 的工作项；
- 通过标签、里程碑与指派，建立透明的维护节奏。

### 适用场景

| 适合放进 Issues | 不适合放进 Issues |
| --- | --- |
| Compass 某版本汉化后界面报错/白屏 | “怎么用？”“为什么没中文？”等使用问答 → Discussions Q&A |
| 词条错译、漏译（附截图与位置） | 开放式讨论、方案取舍 → Discussions Ideas |
| 与新版 Compass 不兼容 | 敏感信息（密钥、完整安装路径、备份文件） |
| 构建/安装失败（附日志片段） | 与项目无关的 MongoDB 官方产品缺陷 → 官方渠道 |

### 对协作与社区的影响

- **正面**：问题不丢失、责任清晰；标签与模板让报告质量显著提升；PR 可自动关联关闭 Issue。
- **成本**：需要持续 triage（分流/打标/回复），否则会积累“僵尸 Issue”；问答若不引导到 Discussions，会稀释缺陷跟踪。

### 前置条件

- 仓库为 Public（当前满足），操作者需 Admin 权限（当前满足）；
- 无需额外付费功能。

### 完善建议（本仓库）

1. **Issue 模板**（`.github/ISSUE_TEMPLATE/`）
   - `bug_report.yml`：Compass 版本、Windows 版本、汉化工具版本、复现步骤、期望/实际、日志与截图、是否已还原验证；
   - `feature_request.yml`：使用场景、期望行为、替代方案、是否愿意提交 PR；
   - `config.yml`：关闭空白 Issue，引导到 Discussions Q&A / Ideas，附文档与 Releases 链接。
2. **标签体系**（Settings → Labels）
   `bug`、`enhancement`、`documentation`、`i18n`、`compatibility`、`needs-triage`、`good first issue`、`help wanted`、`wontfix`。
3. **分流规则**：新 Issue 自动打 `needs-triage`（可用默认标签或 Action）；维护者 48 小时内打标/回复/转 Discussion。
4. **置顶 Issue**：一条“如何正确反馈问题”的索引帖，链接模板、日志位置、Discussions。
5. **里程碑**：`v2.0.x`、`v2.1.0`，用于回应“什么时候修”。

### 注意事项

- 模板中明确要求**不要粘贴**备份文件、完整用户路径、Token；
- 兼容性问题必须写清 Compass 版本（1.53.0/1.53.1）与是否使用官方 Squirrel 版；
- 关闭 Issue 时说明原因（已修复/无法复现/转 Discussion），避免“静默关闭”。

### 分步操作（Settings 页面）

1. **确认开关**：Settings → General → Features → 勾选 **Issues**（已勾选，无需改动）。
2. **添加模板**：仓库根新建 `.github/ISSUE_TEMPLATE/`，放入 `bug_report.yml`、`feature_request.yml`、`config.yml`（模板内容见文末附录）。
3. **配置标签**：Issues → Labels → New label，按上表逐个创建（颜色建议：bug `#d73a4a`、enhancement `#a2eeef`、i18n `#00684A`、needs-triage `#fbca04`）。
4. **置顶索引帖**：Issues → New issue → 标题“📌 提问/反馈前请先阅读”，发布后在 Issue 右侧 **Pin issue**。
5. **验证**：打开 New issue，确认出现模板选择页且空白 Issue 被禁用；`gh api repos/StringYianLee/MongoDB-Compass-localization-ZHCN --jq .has_issues` 返回 `true`。

---

## 二、Sponsorships（赞助）

> 重要区分：**仓库 Settings 里的 Sponsorships 开关只负责“是否显示 Sponsor 按钮”**；真正收款需要**账号级开通 GitHub Sponsors**（含收款与税务信息）。两者缺一不可。

### 用途

- 接受个人/企业的小额赞助，支持持续维护（兼容新版 Compass、补充词条、修复回归）；
- 对外传达项目的可持续性与维护者投入；
- 为企业用户提供合规的支持/赞助入口（可另设商业支持说明）。

### 适用场景

- 项目被较多用户日常使用、维护者投入稳定；
- 有明确的资金用途（例如：CI 资源、测试机、时间投入）；
- 已准备好公开的赞助档位与交付边界（**赞助≠购买功能/优先支持**，需写清）。

### 对协作与社区的影响

- **正面**：提升可持续性；赞助者常转化为高质量反馈者；企业赞助可带来真实场景测试。
- **风险**：若承诺不清，容易被理解为“付费定制/付费优先”；需要公开资金用途与响应预期；涉及税务与平台手续费。

### 前置条件与限制

- GitHub 账号需开启 **2FA**；
- 年满 18 岁、拥有可接收付款的银行账户（通过 Stripe Connect）；
- 完成**税务信息**（W-8/W-9 等）与身份验证；
- 所在国家/地区在 GitHub Sponsors 支持范围内（**以官方支持地区列表为准**；若当前地区不支持收款，可仅保留“赞助意向/企业联系”入口，不启用收款）；
- 提交申请后可能需要审核（数天）；
- 仓库需 Public 才能最大化曝光（当前满足）。

### 完善建议（本仓库）

1. 账号侧：开通 GitHub Sponsors，设置 Monthly / One-time 档位（如 ¥15 / ¥50 / ¥200 或等值美元），写明用途与不承诺事项；
2. 仓库侧：新增 `.github/FUNDING.yml`：

   ```yaml
   github: StringYianLee
   # 可选：custom: ["https://example.com/sponsor"]
   ```

3. 仓库开关：Settings → General → Features → 勾选 **Sponsorships**；
4. README 增加“赞助与支持”小节：资金用途、企业合作联系方式、**不包含**的承诺；
5. 可选：在 Issue 模板/讨论区增加“企业支持”指引，避免商业询价混入 bug 跟踪。

### 注意事项

- 不要在未开通收款前就宣传“可赞助”，按钮会指向空页面；
- 赞助不改变项目 **MIT 许可证**，也不应影响 Issue/PR 的公平处理；
- 明确“赞助不提供优先修复/定制开发”，如需商业支持另立协议；
- 公开税务/手续费预期，避免赞助者误解金额去向；
- 定期（如每季度）在 Announcements 公布资金用途。

### 分步操作

1. 打开 <https://github.com/sponsors/accounts> → **Join GitHub Sponsors**；
2. 完成 2FA、Stripe 收款账户、税务信息与个人资料，提交审核；
3. 审核通过后，在 Sponsors Dashboard 创建档位与目标；
4. 仓库根新增 `.github/FUNDING.yml`（内容见上），提交并推送；
5. Settings → General → Features → 勾选 **Sponsorships**；
6. 验证：仓库首页右上出现 **Sponsor** 按钮；`gh api graphql -f query='{user(login:"StringYianLee"){hasSponsorsListing}}'` 返回 `true`。

---

## 三、Discussions（讨论区）

### 用途

- 承载**开放式问答、想法征集、使用展示、投票**等不适合 Issue 的交流；
- 把“如何用/为什么”的对话从 Issue 中分流，保持缺陷列表干净；
- 通过“标记答案”沉淀可检索的知识。

### 适用场景

| 分类（建议） | 用途 | 可标记答案 |
| --- | --- | --- |
| 📣 Announcements | 版本发布、路线图、资金用途（仅维护者发帖） | 否 |
| 💬 General | 综合交流、使用体验 | 否 |
| 💡 Ideas | 功能建议与投票（点赞排序） | 否 |
| 🙏 Q&A | 安装/使用/兼容性问答 | **是** |
| 🛠 Show and tell | 配置示例、教程、截图 | 否 |
| 📊 Polls | 版本偏好、功能取舍投票 | 否 |
| 🌏 i18n（可选） | 词条讨论、术语统一 | 否 |

> 当前仓库已自带上述前 6 个默认分类，可直接沿用并按需改描述。

### 对协作与社区的影响

- **正面**：Issue 噪音显著下降；问答可被搜索与引用；公告有固定入口；降低重复回答成本。
- **成本**：需要版规与 moderation；若无人回应，会显得冷清；与 Issue 边界不清时会产生“双轨”。

### 前置条件

- Public 仓库免费可用；私有仓库需 GitHub Team 及以上；
- 操作者需 Admin/Maintain 权限；
- 建议先准备好**欢迎帖 + 版规 + 分类描述**再公开。

### 完善建议（本仓库）

1. **欢迎帖（置顶）**：项目定位、如何提问、日志位置、Issue 与 Discussions 的分工、赞助说明；
2. **分类描述**：为 6 个分类补齐一句话说明与发帖指引；
3. **模板**：Q&A 分类启用“问题模板”（版本/系统/现象/已尝试）；
4. **moderation**：设置 Maintainer 角色；对重复问题“转换为 Discussion”而非直接关闭；
5. **入口联动**：README 增加 Discussions 链接；`ISSUE_TEMPLATE/config.yml` 的 `contact_links` 指向 Q&A 与 Ideas；
6. **运营节奏**：每周固定查看未回复帖；每月在 Announcements 汇总版本与常见问题。

### 注意事项

- **不要把可复现缺陷长期留在 Discussions**：确认是 bug 后转 Issue，避免丢失状态；
- 迁移旧 Issue 到 Discussion 会改变链接与订阅关系，需谨慎并公告；
- 版规需明确：不发布破解/盗版资源、不粘贴密钥与备份、不进行与本地化无关的敏感讨论；
- 若不希望承担问答运营，可仅保留 Announcements + Ideas，关闭 Q&A。

### 分步操作

1. 确认开关：Settings → General → Features → 勾选 **Discussions**（当前已启用）；
2. 配置分类：Discussions → 分类旁的 **Edit**，修改名称/描述/格式（Q&A 勾选“Answerable”）；
3. 发布欢迎帖：Discussions → New discussion → Announcements，发布后 **Pin**；
4. 设置版规：Pin 第二条“版规与提问指南”，或在欢迎帖内附上；
5. 联动 Issue：编辑 `.github/ISSUE_TEMPLATE/config.yml`，`contact_links` 增加 Q&A 与 Ideas；
6. 验证：仓库顶部出现 **Discussions** 标签；`gh api graphql -f query='{repository(owner:"StringYianLee",name:"MongoDB-Compass-localization-ZHCN"){hasDiscussionsEnabled}}'` 返回 `true`。

---

## 四、推荐的一次性配置清单

| 顺序 | 操作 | 位置 | 预计耗时 |
| ---: | --- | --- | --- |
| 1 | 创建 Issue 模板与 `config.yml` | `.github/ISSUE_TEMPLATE/` | 10 分钟 |
| 2 | 建立标签体系（9 个） | Issues → Labels | 5 分钟 |
| 3 | 发布并置顶“反馈指南”Issue | Issues | 5 分钟 |
| 4 | 完善 6 个讨论分类描述 | Discussions | 10 分钟 |
| 5 | 发布并置顶欢迎帖/版规 | Discussions | 10 分钟 |
| 6 | 申请 GitHub Sponsors（账号级） | github.com/sponsors/accounts | 20 分钟 + 审核 |
| 7 | 添加 `.github/FUNDING.yml` 并勾选 Sponsorships | 仓库根 + Settings | 3 分钟 |
| 8 | README 增加 Discussions / Sponsor 入口 | README.md | 5 分钟 |
| 9 | 用 `gh api` 验证三项开关 | 终端 | 1 分钟 |

### 验证命令

```bash
gh api repos/StringYianLee/MongoDB-Compass-localization-ZHCN \
  --jq '{issues:.has_issues, discussions:.has_discussions}'

gh api graphql -f query='
{ repository(owner:"StringYianLee", name:"MongoDB-Compass-localization-ZHCN") {
    hasIssuesEnabled hasDiscussionsEnabled
    discussionCategories(first: 10) { nodes { name isAnswerable } }
  }
  user(login:"StringYianLee") { hasSponsorsListing } }'
```

---

## 五、附录：可直接使用的模板

### `.github/ISSUE_TEMPLATE/bug_report.yml`

```yaml
name: 🐞 缺陷报告
description: 汉化后界面异常、构建/安装失败或兼容性问题
labels: ["bug", "needs-triage"]
body:
  - type: markdown
    attributes:
      value: |
        感谢反馈！请先确认已阅读 README 与 Discussions 中的常见问题。
        **请勿粘贴备份文件、完整用户路径、Token 等敏感信息。**
  - type: input
    id: compass
    attributes: { label: MongoDB Compass 版本, placeholder: "1.53.1" }
    validations: { required: true }
  - type: input
    id: tool
    attributes: { label: 汉化工具版本, placeholder: "2.0.0（MSI / 绿色版 / Web）" }
    validations: { required: true }
  - type: dropdown
    id: os
    attributes:
      label: 操作系统
      options: ["Windows 11", "Windows 10", "其他（请说明）"]
    validations: { required: true }
  - type: textarea
    id: steps
    attributes: { label: 复现步骤, placeholder: "1. ...\n2. ...\n3. ..." }
    validations: { required: true }
  - type: textarea
    id: expected
    attributes: { label: 期望结果 / 实际结果 }
    validations: { required: true }
  - type: textarea
    id: logs
    attributes:
      description: 日志位置 `%LOCALAPPDATA%\CompassZhCn\logs\tool-YYYYMMDD.log`，请只粘贴相关片段。
      label: 日志片段（可选）
      render: text
  - type: checkboxes
    id: checks
    attributes:
      label: 自查
      options:
        - label: 已尝试「一键还原」后问题仍存在（或仅汉化后出现）
        - label: 已搜索现有 Issue 与 Discussions
          required: true
```

### `.github/ISSUE_TEMPLATE/feature_request.yml`

```yaml
name: ✨ 功能建议
description: 提出新功能或改进建议
labels: ["enhancement", "needs-triage"]
body:
  - type: textarea
    id: scenario
    attributes: { label: 使用场景, description: 你希望解决什么问题？ }
    validations: { required: true }
  - type: textarea
    id: proposal
    attributes: { label: 期望的方案 }
    validations: { required: true }
  - type: textarea
    id: alternatives
    attributes: { label: 考虑过的替代方案（可选） }
  - type: checkboxes
    id: pr
    attributes:
      label: 参与意愿
      options:
        - label: 我愿意提交 PR 实现该功能
```

### `.github/ISSUE_TEMPLATE/config.yml`

```yaml
blank_issues_enabled: false
contact_links:
  - name: 🙏 使用问答
    url: https://github.com/StringYianLee/MongoDB-Compass-localization-ZHCN/discussions/categories/q-a
    about: 安装、使用、兼容性问题请先在 Discussions 提问
  - name: 💡 想法与投票
    url: https://github.com/StringYianLee/MongoDB-Compass-localization-ZHCN/discussions/categories/ideas
    about: 开放式建议与取舍讨论
  - name: 📦 下载与更新
    url: https://github.com/StringYianLee/MongoDB-Compass-localization-ZHCN/releases
    about: 获取最新安装包与校验值
```

### `.github/FUNDING.yml`

```yaml
github: StringYianLee
```

### 讨论区欢迎帖（Announcements，置顶）

```markdown
# 👋 欢迎来到 Discussions

这里用于**使用问答、想法征集、配置展示与公告**；可复现的缺陷请提交 Issue。

## 提问前
1. 阅读 [README](https://github.com/StringYianLee/MongoDB-Compass-localization-ZHCN#readme) 与 [Releases](https://github.com/StringYianLee/MongoDB-Compass-localization-ZHCN/releases)；
2. 搜索是否已有相同问题；
3. 提问请附：Compass 版本、工具版本、Windows 版本、现象截图、日志相关片段。

## 分工
- 🐞 缺陷 / 兼容性回归 → Issue（模板会自动带上所需信息）
- 🙏 安装与使用 → Q&A（可标记答案）
- 💡 新功能与取舍 → Ideas
- 🛠 配置/教程/截图 → Show and tell

## 版规
- 不发布破解、盗版或与本项目无关的敏感内容；
- 不粘贴备份文件、完整用户路径、Token 等敏感信息；
- 赞助不改变 MIT 许可证，也不承诺优先修复或定制开发。
```
