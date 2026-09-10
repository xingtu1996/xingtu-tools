#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md2html.py · 把 Markdown 转成中文友好、离线可用的单文件 HTML（pandoc 封装）
用法：
  python3 md2html.py 输入.md
  python3 md2html.py 输入.md 输出.html
  python3 md2html.py 输入.md 输出.html --title "自定义标题"
依赖：pandoc（已装于 /usr/local/bin/pandoc）
特点：--standalone --embed-resources，CSS 内联，零外链，双击即可离线浏览。
增强：v1.1 自动把本地图片（![]()）转 base64 data URI 内嵌，单文件真正零外链。
"""
import sys, os, subprocess, pathlib, tempfile, re, base64, mimetypes

HERE = os.path.dirname(os.path.abspath(__file__))
STYLE = os.path.join(HERE, "md_style.html")
PANDOC = "/usr/local/bin/pandoc"


def embed_local_images(src_md: str) -> str:
    """把 md 里的本地图片引用替换为 base64 data URI（pandoc embed-resources 对相对路径不可靠）。"""
    base_dir = os.path.dirname(os.path.abspath(src_md))
    raw = open(src_md, encoding="utf-8").read()

    def repl(m):
        alt = m.group(1).strip()
        path = m.group(2).strip()
        if path.startswith(("http://", "https://", "data:")):
            return m.group(0)
        full = path if os.path.isabs(path) else os.path.join(base_dir, path)
        if not os.path.exists(full):
            return m.group(0)
        with open(full, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        mime = mimetypes.guess_type(full)[0] or "image/png"
        return f"![{alt}](data:{mime};base64,{b64})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]*)\)", repl, raw)


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: python3 md2html.py 输入.md [输出.html] [--title 标题]")
        sys.exit(1)
    src = args[0]
    out = None
    title = None
    rest = args[1:]
    if rest and not rest[0].startswith("--"):
        out = rest.pop(0)
    if "--title" in rest:
        i = rest.index("--title")
        title = rest[i + 1] if i + 1 < len(rest) else None
    if out is None:
        out = str(pathlib.Path(src).with_suffix(".html"))
    if title is None:
        # 从首个一级标题取，否则用文件名
        try:
            with open(src, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
        except Exception:
            pass
        if not title:
            title = pathlib.Path(src).stem

    if not os.path.exists(PANDOC):
        print(f"[md2html] 未找到 pandoc: {PANDOC}")
        sys.exit(2)

    # v1.1: 图片 base64 内嵌，避免 pandoc 相对路径失效
    tmp = None
    working_src = src
    has_local_img = "!["
    if has_local_img in open(src, encoding="utf-8").read():
        processed = embed_local_images(src)
        if processed != open(src, encoding="utf-8").read():
            tmp = tempfile.NamedTemporaryFile(
                "w", suffix=".md", encoding="utf-8", delete=False
            )
            tmp.write(processed)
            tmp.close()
            working_src = tmp.name

    cmd = [
        PANDOC, working_src, "-o", out,
        "--standalone", "--embed-resources", "--self-contained",
        "--from", "markdown+tex_math_dollars+backtick_code_blocks",
        "--metadata", f"title={title}",
        "--include-in-header", STYLE,
        "--toc", "--toc-depth=3",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print("[md2html] pandoc 失败:\n", e.stderr)
        sys.exit(3)
    finally:
        if tmp:
            os.unlink(tmp.name)
    print(f"[md2html] 已生成: {out}  ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
