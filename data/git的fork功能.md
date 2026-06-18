## Git & GitHub Fork 全流程关键步骤

---

## 一、Fork 仓库（GitHub 网页操作）

1. 打开原仓库页面
2. 点击右上角 **Fork** 按钮
3. 选择你的账号

---

## 二、克隆到本地

```bash
# 克隆你的 Fork
git clone https://github.com/你的用户名/仓库名.git

# 进入目录
cd 仓库名

# 添加原仓库为 upstream（只需一次）
git remote add upstream https://github.com/原仓库所有者/仓库名.git

# 验证远程仓库配置
git remote -v
```

---

## 三、日常开发流程

### 3.1 同步最新代码（每次开发前做）

```bash
# 切换到 main 分支
git checkout main

# 拉取原仓库更新
git fetch upstream

# 合并到本地 main
git merge upstream/main

# 推送到你的 Fork
git push origin main
```

### 3.2 创建功能分支

```bash
# 从最新的 main 创建分支
git checkout -b feature-分支名

# 或者分两步
git branch feature-分支名
git checkout feature-分支名
```

### 3.3 修改代码并提交

```bash
# 查看修改状态
git status

# 添加修改的文件
git add .                    # 添加所有修改
git add 文件名.py             # 添加指定文件

# 提交到本地
git commit -m "feat: 添加了xxx功能"

# 规范提交信息格式
git commit -m "类型: 简短描述" -m "详细说明"
# 类型：feat/fix/docs/style/refactor/test/chore
```

### 3.4 推送到你的 Fork

```bash
# 第一次推送（设置上游分支）
git push -u origin feature-分支名

# 后续推送
git push origin feature-分支名
```

### 3.5 保持功能分支同步

```bash
# 更新 main 分支（参考 3.1）
# 然后合并到功能分支
git checkout feature-分支名
git merge main

# 或直接合并原仓库
git merge upstream/main

# 推送更新
git push origin feature-分支名
```

---

## 四、合并到自己的 main（可选）

```bash
# 切换到 main
git checkout main

# 合并功能分支
git merge feature-分支名

# 推送到你的 Fork
git push origin main

# 删除本地功能分支
git branch -d feature-分支名

# 删除远程功能分支
git push origin --delete feature-分支名
```

---

## 五、提交 Pull Request（贡献给原仓库）

1. 打开**你的 Fork** 仓库页面
2. 点击 **Pull requests** 标签
3. 点击 **New pull request**
4. 选择：
   - `base repository: 原仓库/main`
   - `head repository: 你的Fork/功能分支`
5. 填写 PR 描述
6. 点击 **Create pull request**

---

## 六、常用命令速查表

### 分支操作
| 命令 | 说明 |
|------|------|
| `git branch` | 查看本地分支 |
| `git branch -r` | 查看远程分支 |
| `git branch -a` | 查看所有分支 |
| `git branch 分支名` | 创建分支 |
| `git checkout 分支名` | 切换分支 |
| `git checkout -b 分支名` | 创建并切换 |
| `git branch -d 分支名` | 删除本地分支 |
| `git push origin --delete 分支名` | 删除远程分支 |
| `git merge 分支名` | 合并分支 |

### 同步与推送
| 命令 | 说明 |
|------|------|
| `git fetch upstream` | 拉取原仓库（不合并） |
| `git pull upstream main` | 拉取并合并（等于 fetch+merge） |
| `git merge upstream/main` | 合并原仓库到当前分支 |
| `git push origin 分支名` | 推送到你的 Fork |
| `git push -u origin 分支名` | 首次推送并设置上游 |
| `git remote -v` | 查看远程仓库配置 |

### 提交与撤销
| 命令 | 说明 |
|------|------|
| `git status` | 查看状态 |
| `git add .` | 添加所有修改 |
| `git add 文件名` | 添加指定文件 |
| `git commit -m "信息"` | 提交 |
| `git log --oneline` | 查看提交历史 |
| `git reset --soft HEAD~1` | 撤销上一次提交（保留修改） |
| `git reset --hard HEAD~1` | 撤销上一次提交（丢弃修改） |
| `git diff` | 查看未暂存的修改 |
| `git diff --staged` | 查看已暂存的修改 |

### 解决冲突
| 命令 | 说明 |
|------|------|
| `git merge --abort` | 放弃合并 |
| `git status` | 查看冲突文件 |
| 手动编辑文件 | 删除 `<<<<<<<` `=======` `>>>>>>>` 标记 |
| `git add 文件名` | 标记冲突已解决 |
| `git commit` | 完成合并 |

---

## 七、完整工作流程图

```
┌─────────────────────────────────────────────────────────────┐
│                    每天开发前（同步）                          │
│  git checkout main                                           │
│  git fetch upstream                                          │
│  git merge upstream/main                                     │
│  git push origin main                                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    创建功能分支                               │
│  git checkout -b feature-xxx                                │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    开发与提交                                 │
│  修改代码 → git add . → git commit -m "message"              │
│  重复多次...                                                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    同步最新代码                               │
│  git checkout main → 拉取更新 → git checkout feature-xxx    │
│  git merge main                                             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    推送并创建 PR                              │
│  git push origin feature-xxx                                │
│  在 GitHub 网页创建 Pull Request                              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    等待合并                                   │
│  维护者审核 → 合并 → 删除功能分支                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 八、最佳实践提醒

✅ **一定要做的**
- 每次开发前同步原仓库
- 创建 PR 前再次同步并测试
- 提交信息清晰规范
- 一个 PR 只做一件事

❌ **避免做的**
- 在 main 分支上直接修改
- 强制推送到 main 分支（`git push --force`）
- 提交敏感信息（密码、密钥）
- 积累太多本地修改才提交

---

## 九、快速参考卡片

```bash
# 克隆并设置 upstream
git clone https://github.com/你的用户名/仓库.git
cd 仓库
git remote add upstream 原仓库地址

# 每日同步
git checkout main && git fetch upstream && git merge upstream/main && git push origin main

# 新功能分支
git checkout -b feature-xxx

# 提交推送
git add . && git commit -m "feat: xxx" && git push origin feature-xxx

# 同步功能分支
git checkout main && git pull origin main && git checkout feature-xxx && git merge main
```

保存这份指南，随时查阅！