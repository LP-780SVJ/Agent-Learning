# Tree rendering helpers will turn scanned repository structure into compact directory summaries for repo maps and model context.
from dataclasses import dataclass, field
from codeteam.repository.models import RepositorySnapshot

@dataclass
class TreeNode:
    name: str
    file_count: int = 0
    children: dict[str, "TreeNode"] = field(default_factory=dict)

class DirectoryTreeRenderer:
    def __init__(self, max_depth: int = 2) -> None:
        self.max_depth = max_depth

    def render(self, snapshot: RepositorySnapshot) -> str:
        ...

    def render_directory_tree(self, snapshot: RepositorySnapshot, max_depth: int = 2) -> str:
        return DirectoryTreeRenderer(max_depth=max_depth).render(snapshot)

    def _build_tree(self, snapshot: RepositorySnapshot) -> TreeNode:
        root = TreeNode(name=snapshot.root.name)

        for file in snapshot.files:
            parts = file.path.split("/")
            current = root

            for directory_name in parts[:-1]:# 除了最后一个文件名以外的所有目录
                current.file_count += 1

                if directory_name not in current.children:
                    current.children[directory_name] = TreeNode(name=directory_name)

                current = current.children[directory_name]

            current.file_count += 1

        return root


    # 渲染时建议先不要打印具体文件，只打印目录和数量
    def render(self, snapshot: RepositorySnapshot) -> str:
        root = self._build_tree(snapshot)
        lines = [f"{root.name}/ [{snapshot.total_files} files]"]

        self._render_children(
            node=root,
            lines=lines,
            prefix="",
            depth=1,
        )

        return "\n".join(lines)

    # 递归渲染子目录
    def _render_children(
        self,
        node: TreeNode,
        lines: list[str],
        prefix: str,
        depth: int,
    ) -> None:
        children = sorted(node.children.values(), key=lambda child: child.name)

        for index, child in enumerate(children):
            is_last = index == len(children) - 1
            connector = "└── " if is_last else "├── "
            next_prefix = "    " if is_last else "│   "

            lines.append(
                f"{prefix}{connector}{child.name}/ [{child.file_count} files]"
            )

            if depth < self.max_depth:
                self._render_children(
                    node=child,
                    lines=lines,
                    prefix=prefix + next_prefix,
                    depth=depth + 1,
                )