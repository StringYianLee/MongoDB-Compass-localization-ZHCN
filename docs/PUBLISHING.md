# 发布与维护指南（Maintainer）

本文件说明如何把本仓库发布到 GitHub，以及在受限网络下的替代方案。

## 仓库信息

- 建议仓库名：`MongoDB-Compass-localization-ZHCN`
  （GitHub 仓库名不允许空格，因此将 “MongoDB Compass localization-ZHCN” 规范化为连字符形式）
- 可见性：Public
- 默认分支：`main`
- 描述：`MongoDB Compass 简体中文本地化工具 · 1510 词条 · 桌面 / Web 双端`
- Topics：`mongodb` `compass` `localization` `i18n` `zh-cn` `flet` `python` `windows`

## 方式一：GitHub CLI（推荐）

```bash
gh auth login                       # 浏览器 OAuth，不使用账号密码
gh repo create MongoDB-Compass-localization-ZHCN --public --source . --remote origin --push
```

## 方式二：SSH（无需密码）

1. 在本机生成或使用已有密钥：

   ```bash
   ssh-keygen -t ed25519 -C "stringyianlee@foxmail.com"
   ```

2. 将 `~/.ssh/id_ed25519.pub` 的内容添加到 GitHub：
   `Settings → SSH and GPG keys → New SSH key`。

3. 在 GitHub 网页端先创建**空仓库**（不要勾选 README / .gitignore / License）。

4. 推送：

   ```bash
   git remote add origin git@github.com:stringyianlee/MongoDB-Compass-localization-ZHCN.git
   git push -u origin main
   ```

> 本机若配置了 `url.https://gitclone.com/.insteadof=https://` 之类的镜像重写，
> 推送时应绕过全局配置：`GIT_CONFIG_GLOBAL=/dev/null git push ...`，否则会推到只读镜像。

## 方式三：受限网络（离线打包）

在无法访问 github.com 的网络中，可先导出仓库：

```bash
git bundle create MongoDB-Compass-localization-ZHCN.bundle --all
```

将 `.bundle` 文件复制到可访问 GitHub 的机器：

```bash
git clone MongoDB-Compass-localization-ZHCN.bundle MongoDB-Compass-localization-ZHCN
cd MongoDB-Compass-localization-ZHCN
git remote set-url origin git@github.com:stringyianlee/MongoDB-Compass-localization-ZHCN.git
git push -u origin main
```

## 发布前检查清单

- [ ] `git status` 干净，历史中无密码、Token、私钥；
- [ ] 仓库不包含 `app.asar`、备份、日志、字体、`dist*/`、`installer/Product.wxs`；
- [ ] `README.md` 截图路径正确（`docs/*.png`）；
- [ ] `LICENSE`、`CONTRIBUTING.md`、`SECURITY.md`、`CHANGELOG.md` 存在；
- [ ] 在干净环境执行 `pip install -r requirements.txt && python flet_app.py` 可启动；
- [ ] 若发布二进制，创建 GitHub Release 并附上 `CompassZhCn-2.0.0-x64.msi`、
      `CompassZhCnFlet.exe`、`CompassZhCnWeb.exe` 与 `SHA256SUMS.txt`。

## 安全提醒

- **不要**使用 GitHub 账号密码进行 Git 操作：GitHub 自 2021-08 起已移除密码认证；
- 使用浏览器 OAuth（`gh auth login`）或 SSH 密钥；
- 若密码曾在聊天、日志或文档中明文出现，请立即修改并开启双因素认证（2FA）。
