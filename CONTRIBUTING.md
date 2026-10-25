# 贡献指南

感谢你愿意为 MongoDB Compass 简体中文本地化项目做出贡献！本文说明参与方式、开发约定与提交规范。

## 目录

- [行为准则](#行为准则)
- [你可以贡献什么](#你可以贡献什么)
- [开发环境](#开发环境)
- [翻译词表规范](#翻译词表规范)
- [测试清单](#测试清单)
- [提交与 PR 规范](#提交与-pr-规范)
- [禁止提交的内容](#禁止提交的内容)
- [贡献内容的许可](#贡献内容的许可)

---

## 行为准则

- 参与本项目即表示同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)（Contributor Covenant 2.1）；
- 保持尊重、就事论事；不接受人身攻击、歧视或骚扰。违规行为可通过仓库 Security 私密报告或邮件反馈。
- 不讨论与本地化无关的敏感话题。
- 对 Compass / MongoDB 官方产品的缺陷，请向官方反馈，而不是在本项目发泄。

---

## 你可以贡献什么

| 类型 | 说明 |
| --- | --- |
| 补充翻译 | 修正错译、补充未覆盖的界面文本（`lang/zh-CN.json`） |
| 修复规则 | 改进 `patterns` 中的动态文本匹配（计数、变量、复数） |
| 兼容新版 | 适配新版 Compass 的 asar 结构或新增文案 |
| 界面改进 | 桌面 / Web 端的布局、可访问性、响应式问题 |
| 文档 | README、构建说明、截图、FAQ |
| 缺陷报告 | 描述现象、Compass 版本、日志片段与复现步骤 |

---

## 开发环境

- Windows 10 / 11 x64
- Python 3.12+
- MongoDB Compass 官方 Squirrel 版（1.53.x 已验证）

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python flet_app.py          # 桌面界面
python web_app.py           # Web 界面（需先运行 scripts/prepare_font.py）
```

---

## 翻译词表规范

词表位于 `lang/zh-CN.json`，结构如下：

```json
{
  "dict":     { "Connection": "连接", "Create Index": "创建索引" },
  "patterns": [ { "pattern": "^([0-9]+) documents?$", "replacement": "\\1 个文档" } ],
  "menu":     { "File": "文件", "Edit": "编辑" }
}
```

### 翻译原则

1. **以官方术语为准**：MongoDB 概念使用社区通行译法（集合、文档、索引、聚合管道、副本集、分片、写入关注等），保持全项目一致。
2. **保留技术标识**：命令、字段名、数据库/集合名、JSON 键、错误码、产品名（MongoDB、Compass、Atlas、Realm）不翻译。
3. **简洁优先**：按钮与菜单尽量 2–6 个汉字，避免因过长导致布局截断。
4. **不翻译代码**：`pre`/`code`/`textarea`/Monaco/Ace 编辑器、查询栏、文档列表中的内容保持原样。
5. **占位符完整**：`patterns` 中 `\\1`、`{name}`、`%s` 等占位符必须保留且数量一致。
6. **标点统一**：中文使用全角标点；中英文之间保留一个空格（如 `MongoDB 数据库`）。

### 新增词条的判断

- 只出现一次且结构稳定的文本 → 加入 `dict`；
- 含变量、计数、路径的句子 → 加入 `patterns`；
- Electron 原生菜单 → 加入 `menu`。

---

## 测试清单

提交前请至少完成：

- [ ] `python CompassZhCn.py --status` 输出正常；
- [ ] 桌面界面能启动，四张状态卡、日志面板、主题切换正常；
- [ ] 执行一次「一键汉化」，确认日志无 ERROR，Compass 重启后中文生效；
- [ ] 执行一次「一键还原」，确认 Compass 恢复英文且 SHA256 与官方一致；
- [ ] 若改动词表：抽查本次新增/修改的界面位置；
- [ ] 若改动 Web：在 1280 / 700 / 430 三种宽度下无溢出、无灰块；
- [ ] 若改动打包脚本：验证生成的 exe / MSI 能正常启动与卸载。

> 请在正常桌面环境验证 Compass 窗口效果（部分沙箱/GPU 受限环境无法启动 Compass）。

---

## 提交与 PR 规范

- 分支命名：`feat/<简短描述>`、`fix/<简短描述>`、`docs/<简短描述>`。
- 提交信息使用 Conventional Commits：
  - `feat(i18n): 补充聚合管道相关词条`
  - `fix(menu): 修正 macOS 菜单项误译`
  - `docs(readme): 更新构建步骤`
- 一个 PR 只做一件事；词表更新请说明**新增/修改数量**与**验证位置**。
- PR 描述请包含：变更内容、验证方式（截图/日志）、关联 Issue。

---

## 禁止提交的内容

以下内容**不得**出现在提交、Issue 或 PR 中：

- MongoDB Compass 安装包、`app.asar`、解包产物（`_work/` 等）；
- 本工具生成的备份文件、日志、`ui.json`、本地状态；
- 系统字体（如 `msyh.ttc` / `MicrosoftYaHeiUI.ttf`）；
- 任何密码、访问令牌、SSH 私钥、Cookie、GitHub PAT；
- 含本机绝对路径的生成文件（如 `installer/Product.wxs`）；
- 与本地化无关的第三方代码或资源。

`.gitignore` 已默认排除上述大部分内容，提交前仍请用 `git status` 复核。

---

## 贡献内容的许可

你提交的代码与翻译将按本项目的 **MIT License** 授权发布。提交 PR 即表示你确认：

- 内容为原创或你有权按其许可提交；
- 同意以 MIT 许可证分发；
- 不包含他人的专有代码、字体或受限制资源。
