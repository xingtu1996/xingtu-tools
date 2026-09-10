#!/bin/zsh

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Copy Finder Absolute Path
# @raycast.mode silent
# @raycast.packageName File Utils
# @raycast.icon 📁
# @raycast.description Copy the absolute path of the currently selected Finder item to the clipboard.

# 获取 Finder 当前选中的第一个文件/文件夹
selected=$(osascript <<'APPLESCRIPT'
tell application "Finder"
    set theSelection to selection as alias list
    if (count of theSelection) > 0 then
        return POSIX path of (item 1 of theSelection as alias)
    else
        return ""
    end if
end tell
APPLESCRIPT
)

if [ -z "$selected" ]; then
    echo "Finder 中未选中任何文件"
    exit 1
fi

abs_path=$(realpath "$selected")
echo "$abs_path" | pbcopy
echo "已复制: $abs_path"
