"""
SymbolExtractor: 从 Python AST 中提取符号定义和名称引用。

核心机制：
- Scope Stack：维护 (name, kind) 栈，区分 METHOD vs FUNCTION，构建 Qualified Name
- ctx 字段：Store = Definition, Load = Reference
- Attribute 链展开：self.repo.find 产生 3 个 Reference
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

from codeteam.symbols.models import (
    Symbol,
    SymbolKind,
    SymbolLocation,
    Parameter,
    Reference,
    ReferenceKind,
)


@dataclass
class _ScopeFrame:
    """栈帧：记录当前所在的作用域名和种类。

    这不是公开 API，所以类名以下划线开头。
    """
    name: str       # 作用域名，如 "UserService"、"get_user"
    kind: str       # "class" 或 "function"


class SymbolExtractor(ast.NodeVisitor):
    """遍历 Python AST，提取 Symbol（定义）和 Reference（引用）。

    用法：
        tree = ast.parse(source_code)
        extractor = SymbolExtractor("path/to/file.py")
        symbols, references = extractor.extract(tree)
    """

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self.file_path: str = file_path
        self._scope_stack: list[_ScopeFrame] = []
        self._symbols: list[Symbol] = []
        self._references: list[Reference] = []

    # ── 公开入口 ─────────────────────────────────────────────

    def extract(self, tree: ast.AST) -> tuple[list[Symbol], list[Reference]]:
        """提取入口。遍历 AST 树，返回 (symbols, references)。"""
        self.visit(tree)
        return self._symbols, self._references

    # ── Scope Stack 辅助方法 ─────────────────────────────────

    @property
    def _in_class(self) -> bool:
        """当前是否在类内部？"""
        return bool(self._scope_stack) and self._scope_stack[-1].kind == "class"

    def _qualified_name(self, name: str) -> str:
        """构建当前作用域下的限定名。

        例：scope_stack = [(TokenStore, class), (get, function)]
            当前 name = "key"
            → qualified_name = "TokenStore.get.key"
        """
        parts = [f.name for f in self._scope_stack] + [name]
        return ".".join(parts)

    def _current_scope(self) -> str:
        """当前作用域的限定名（不含当前实体名）。

        例：scope_stack = [(TokenStore, class)]
            → "TokenStore"
        """
        return ".".join(f.name for f in self._scope_stack)

    def _make_location(self, node: ast.AST) -> SymbolLocation:
        """从 AST 节点提取位置信息，将 1-based 转为 0-based。

        Python AST 的行号从 1 开始、列号从 0 开始。
        我们的模型约定所有位置从 0 开始（与 parsing/models.py 一致）。
        所以 lineno 需要减 1。
        """
        line = node.lineno - 1 if hasattr(node, "lineno") and node.lineno is not None else 0
        col = node.col_offset if hasattr(node, "col_offset") and node.col_offset is not None else 0
        return SymbolLocation(file=self.file_path, line=line, column=col)

    # ── 顶层节点处理 ─────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """处理类定义：记录 Symbol，推入 Scope，遍历子节点，退出 Scope。"""
        qn = self._qualified_name(node.name)
        decorators = self._extract_decorator_names(node.decorator_list)

        # 装饰器是引用
        for d in node.decorator_list:
            self._extract_decorator_refs(d)

        # 基类是引用（class UserService(BaseService): BaseService 是引用）
        for base in node.bases:
            self._extract_annotation_refs(base)

        sym = Symbol(
            name=node.name,
            kind=SymbolKind.CLASS,
            location=self._make_location(node),
            qualified_name=qn,
            decorators=decorators,
        )
        self._symbols.append(sym)

        # 推入 Scope → 遍历子节点 → 弹出 Scope
        self._scope_stack.append(_ScopeFrame(name=node.name, kind="class"))
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool
    ) -> None:
        """处理函数/方法定义的通用逻辑。

        FunctionDef 和 AsyncFunctionDef 的 AST 结构几乎相同，
        只是节点类型不同，这里统一处理。
        """
        kind = SymbolKind.METHOD if self._in_class else SymbolKind.FUNCTION
        qn = self._qualified_name(node.name)

        # 提取参数
        params = self._extract_parameters(node.args)

        # 装饰器
        decorators = self._extract_decorator_names(node.decorator_list)
        for d in node.decorator_list:
            self._extract_decorator_refs(d)

        # 返回类型注解中的引用，如 -> User 中的 User
        if node.returns:
            self._extract_annotation_refs(node.returns)

        # 构架签名字符串
        sig = self._build_signature(node, is_async)

        sym = Symbol(
            name=node.name,
            kind=kind,
            location=self._make_location(node),
            qualified_name=qn,
            signature=sig,
            decorators=decorators,
            parameters=params,
        )
        self._symbols.append(sym)

        # 推入 Scope → 遍历函数体 → 弹出 Scope
        self._scope_stack.append(_ScopeFrame(name=node.name, kind="function"))
        self.generic_visit(node)
        self._scope_stack.pop()

    # ── 名称和属性引用处理 ───────────────────────────────────

    def visit_Name(self, node: ast.Name) -> None:
        """处理单个名字节点：ctx=Store → Definition, ctx=Load → Reference。

        注意：类型注解中的 Name（如 user_id: int 中的 int）虽然也是 ctx=Load，
        但我们不在 visit_Name 中单独处理——annotation 的提取由
        _extract_annotation_refs 专门处理，它会递归遍历注解子树。
        所以这里会出现"重复引用"：int 既被 visit_Name 标记为 SIMPLE，
        又被 _extract_annotation_refs 标记为 TYPE_ANNOTATION。

        这是可以接受的行为：同一个名字在不同上下文中可能扮演不同角色。
        如果希望去重，可以在后续的 SymbolIndex 层做。
        """
        loc = self._make_location(node)
        scope = self._current_scope()

        if isinstance(node.ctx, ast.Store):
            # 变量定义：x = 5 中的 x
            qn = self._qualified_name(node.id)
            sym = Symbol(
                name=node.id,
                kind=SymbolKind.VARIABLE,
                location=loc,
                qualified_name=qn,
            )
            self._symbols.append(sym)

        elif isinstance(node.ctx, ast.Load):
            # 名称引用：print(x) 中的 x
            ref = Reference(
                name=node.id,
                kind=ReferenceKind.SIMPLE,
                location=loc,
                scope=scope,
            )
            self._references.append(ref)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """处理属性访问：self.repository 中的 repository。

        每个 Attribute 节点的 .attr 部分是一条 ATTRIBUTE 引用。
        generic_visit 会继续展开 node.value 中的 Name 节点。
        """
        loc = self._make_location(node)
        scope = self._current_scope()
        ref = Reference(
            name=node.attr,
            kind=ReferenceKind.ATTRIBUTE,
            location=loc,
            scope=scope,
        )
        self._references.append(ref)
        self.generic_visit(node)  # 继续遍历 node.value，可能是 Name 或 Attribute

    def _extract_decorator_names(
        self, decorator_list: list[ast.expr]
    ) -> list[str]:
        """提取装饰器名字列表。

        @trace         → "trace"
        @auth.require  → "auth.require"
        @app.route("/") → "app.route"

        使用 ast.unparse() 获取装饰器的源码文本，然后去掉参数部分。
        """
        names: list[str] = []
        for d in decorator_list:
            if isinstance(d, ast.Call):
                # @app.route("/") → 取 "app.route"
                names.append(ast.unparse(d.func))
            else:
                names.append(ast.unparse(d))
        return names

    def _extract_decorator_refs(self, node: ast.expr) -> None:
        """从装饰器节点中提取所有 DECORATOR 类型的引用。

        递归遍历装饰器子树，找出所有 Name 节点。
        @auth.require 中包含对 auth 和 require 的引用。
        """
        scope = self._current_scope()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                ref = Reference(
                    name=child.id,
                    kind=ReferenceKind.DECORATOR,
                    location=self._make_location(child),
                    scope=scope,
                )
                self._references.append(ref)

    def _extract_annotation_refs(self, node: ast.expr) -> None:
        """从类型注解节点中提取所有 TYPE_ANNOTATION 类型的引用。

        递归遍历注解子树，找出所有 Name 节点。
        user_id: int | None 中包含对 int 和 None 的引用。
        """
        scope = self._current_scope()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                ref = Reference(
                    name=child.id,
                    kind=ReferenceKind.TYPE_ANNOTATION,
                    location=self._make_location(child),
                    scope=scope,
                )
                self._references.append(ref)

    def _build_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> str:
        """构建函数/方法的签名字符串。

        例：
        def get_user(self, user_id: int) -> User:
            → "(self, user_id: int) -> User"
        """
        parts = []
        for arg in node.args.args:
            part = arg.arg
            if arg.annotation:
                part += f": {ast.unparse(arg.annotation)}"
            parts.append(part)

        # 处理 *args 和 **kwargs
        if node.args.vararg:
            vararg = f"*{node.args.vararg.arg}"
            if node.args.vararg.annotation:
                vararg += f": {ast.unparse(node.args.vararg.annotation)}"
            parts.append(vararg)
        if node.args.kwarg:
            kwarg = f"**{node.args.kwarg.arg}"
            if node.args.kwarg.annotation:
                kwarg += f": {ast.unparse(node.args.kwarg.annotation)}"
            parts.append(kwarg)

        sig = f"({', '.join(parts)})"
        if node.returns:
            sig += f" -> {ast.unparse(node.returns)}"
        return sig