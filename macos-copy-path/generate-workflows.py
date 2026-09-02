#!/usr/bin/env python3
"""
生成 macOS Finder 右键服务：复制绝对路径 / 相对路径
运行后会生成两个 .workflow bundle，双击即可安装到 ~/Library/Services
"""
import os
import plistlib
import shutil
import uuid

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def make_run_shell_script_action(name: str, script: str, shell: str = "/bin/zsh") -> dict:
    action_uuid = str(uuid.uuid4()).upper()
    input_uuid = str(uuid.uuid4()).upper()
    output_uuid = str(uuid.uuid4()).upper()
    return {
        "action": {
            "AMAccepts": {
                "Container": "List",
                "Optional": True,
                "Types": ["com.apple.cocoa.string"],
            },
            "AMActionVersion": "2.0.3",
            "AMApplication": ["自动操作"],
            "AMParameterProperties": {
                "COMMAND_STRING": {},
                "CheckedForUserDefaultShell": {},
                "inputMethod": {},
                "shell": {},
                "source": {},
            },
            "AMProvides": {
                "Container": "List",
                "Types": ["com.apple.cocoa.string"],
            },
            "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
            "ActionName": "运行Shell脚本",
            "ActionParameters": {
                "COMMAND_STRING": script,
                "CheckedForUserDefaultShell": True,
                "inputMethod": 1,  # 1 = as arguments
                "shell": shell,
                "source": "",
            },
            "BundleIdentifier": "com.apple.RunShellScript",
            "CFBundleVersion": "2.0.3",
            "CanShowSelectedItemsWhenRun": False,
            "CanShowWhenRun": True,
            "Category": ["AMCategoryUtilities"],
            "Class Name": "RunShellScriptAction",
            "InputUUID": input_uuid,
            "Keywords": ["Shell", "脚本", "命令", "运行", "Unix"],
            "OutputUUID": output_uuid,
            "UUID": action_uuid,
            "UnlocalizedApplications": ["Automator"],
            "arguments": {
                "0": {
                    "default value": 0,
                    "name": "inputMethod",
                    "required": "0",
                    "type": "0",
                    "uuid": "0",
                },
                "1": {
                    "default value": False,
                    "name": "CheckedForUserDefaultShell",
                    "required": "0",
                    "type": "0",
                    "uuid": "1",
                },
                "2": {
                    "default value": "",
                    "name": "source",
                    "required": "0",
                    "type": "0",
                    "uuid": "2",
                },
                "3": {
                    "default value": "",
                    "name": "COMMAND_STRING",
                    "required": "0",
                    "type": "0",
                    "uuid": "3",
                },
                "4": {
                    "default value": "/bin/sh",
                    "name": "shell",
                    "required": "0",
                    "type": "0",
                    "uuid": "4",
                },
            },
            "isViewVisible": 1,
            "location": "309.000000:305.000000",
            "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib",
        },
        "isViewVisible": 1,
    }


def make_service_workflow(name: str, script: str, shell: str = "/bin/zsh") -> dict:
    return {
        "AMApplicationBuild": "512",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [make_run_shell_script_action(name, script, shell)],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleID": "com.apple.finder",
            "applicationBundleIDsByPath": {
                "/System/Library/CoreServices/Finder.app": "com.apple.finder"
            },
            "applicationPath": "/System/Library/CoreServices/Finder.app",
            "applicationPaths": ["/System/Library/CoreServices/Finder.app"],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15,
            "processesInput": False,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": False,
            "systemImageName": "NSTouchBarSend",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


def write_workflow(bundle_name: str, workflow_data: dict):
    bundle_path = os.path.join(OUT_DIR, bundle_name)
    if os.path.exists(bundle_path):
        shutil.rmtree(bundle_path)
    os.makedirs(os.path.join(bundle_path, "Contents"))

    wflow_path = os.path.join(bundle_path, "Contents", "document.wflow")
    with open(wflow_path, "wb") as f:
        plistlib.dump(workflow_data, f)

    print(f"✅ 已生成: {bundle_path}")


def main():
    # 复制绝对路径
    abs_script = '''#!/bin/zsh
# 复制选中文件/文件夹的绝对路径到剪贴板
for f in "$@"; do
    realpath "$f"
done | pbcopy

osascript -e "display notification \"已复制 $# 个绝对路径\" with title \"复制绝对路径\""
'''

    # 复制相对路径（相对于用户主目录）
    rel_script = '''#!/bin/zsh
# 复制选中文件/文件夹相对于主目录的相对路径到剪贴板
for f in "$@"; do
    realpath --relative-to="$HOME" "$f"
done | pbcopy

osascript -e "display notification \"已复制 $# 个相对路径\" with title \"复制相对路径\""
'''

    # 复制文件名
    filename_script = '''#!/bin/zsh
# 复制选中文件/文件夹的文件名到剪贴板
for f in "$@"; do
    basename "$f"
done | pbcopy

osascript -e "display notification \"已复制 $# 个文件名\" with title \"复制文件名\""
'''

    write_workflow("复制绝对路径.workflow", make_service_workflow("复制绝对路径", abs_script))
    write_workflow("复制相对路径.workflow", make_service_workflow("复制相对路径", rel_script))
    write_workflow("复制文件名.workflow", make_service_workflow("复制文件名", filename_script))


if __name__ == "__main__":
    main()
