# macOS 复制路径工具

为 Finder 增加类似 IDE 的「复制路径」右键菜单，方便在 AI 对话、终端、文档中快速粘贴文件路径。

## 功能

- **复制绝对路径**：生成 `~/xingtu/README.md`
- **复制相对路径**：生成 `工作室/xingtu/README.md`（相对于用户主目录）
- **复制文件名**：生成 `README.md`
- **Raycast 脚本**：键盘流一键复制 Finder 当前选中项的绝对路径

## 安装（Automator 服务）

### 方法一：双击安装（推荐）

1. 双击 `复制绝对路径.workflow`
2. 双击 `复制相对路径.workflow`
3. 系统会提示「安装服务」或「打开 Automator」，选择安装/打开后保存即可
4. 服务会自动放到 `~/Library/Services/`

### 方法二：手动复制

```bash
cp -R "复制绝对路径.workflow" "$HOME/Library/Services/"
cp -R "复制相对路径.workflow" "$HOME/Library/Services/"
```

## 使用

### 右键菜单

1. 在 Finder 中选中任意文件或文件夹
2. 右键 → **服务** → **复制绝对路径** / **复制相对路径**
3. 路径已写入剪贴板，直接粘贴即可

> macOS Ventura+ 可能在 **右键 → 快速操作** 子菜单里；旧版 macOS 在 **右键 → 服务** 子菜单里。

### 设置快捷键

1. 打开 **系统设置 → 键盘 → 键盘快捷键 → 服务**（或 **快速操作**）
2. 在 **文件和文件夹** 分类下找到「复制绝对路径」和「复制相对路径」
3. 点击右侧添加快捷键，例如：
   - 复制绝对路径：`⌃⌥⌘C`（Ctrl+Option+Cmd+C）
   - 复制相对路径：`⌃⌥⇧⌘C`
4. 在 Finder 中选中文件，按下快捷键即可复制

## Raycast 脚本（可选）

如果你使用 [Raycast](https://www.raycast.com/)：

1. 打开 Raycast → Settings → Extensions → Add Script Directory
2. 选择本目录 `macos-copy-path`
3. 在 Raycast 中输入 `Copy Finder Absolute Path` 即可复制当前 Finder 选中项的绝对路径

## 自定义

如需修改脚本内容：

1. 打开 `复制绝对路径.workflow`
2. 在 Automator 中编辑「运行 Shell 脚本」步骤
3. 保存后会自动更新 `~/Library/Services/` 中的同名服务

## 文件说明

| 文件 | 说明 |
|------|------|
| `复制绝对路径.workflow` | Finder 右键服务：复制绝对路径 |
| `复制相对路径.workflow` | Finder 右键服务：复制相对路径（相对于主目录） |
| `复制文件名.workflow` | Finder 右键服务：复制文件名 |
| `copy-finder-path-raycast.sh` | Raycast Script Command |
| `generate-workflows.py` | 重新生成 .workflow 的脚本 |
| `README.md` | 本说明 |

## 卸载

```bash
rm -rf "$HOME/Library/Services/复制绝对路径.workflow"
rm -rf "$HOME/Library/Services/复制相对路径.workflow"
rm -rf "$HOME/Library/Services/复制文件名.workflow"
```
