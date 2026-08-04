'''
定义 Symbol、Reference、Parameter 等数据结构

  - SymbolKind — 枚举：符号是类、函数、方法还是变量？
  - SymbolLocation — 符号在哪个文件、哪一行、哪一列？
  - Symbol — 核心结构：一个代码符号的全部信息
  - Parameter — 函数参数：名字、类型、默认值
  - ReferenceKind + Reference — 一次引用：谁在哪里引用了什么？
'''

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class SymbolKind(str, Enum):
    """符号的种类。

    为什么用 Enum 而不是字符串？
    - 避免拼写错误：SymbolKind.CLASS 比 "class" 更安全
    - IDE 可以自动补全
    - 继承 str，可以像字符串一样比较和序列化
    """
    MODULE = "module"        # 模块（文件本身）
    CLASS = "class"          # 类定义
    FUNCTION = "function"    # 函数定义（模块级）
    METHOD = "method"        # 方法定义（类内部）
    PARAMETER = "parameter"  # 函数/方法参数
    VARIABLE = "variable"    # 局部变量


class ReferenceKind(str, Enum):
    """引用的种类。

    SIMPLE:  普通名称引用，如 user_id（在 return user_id 中）
    ATTRIBUTE: 属性访问引用，如 self.repository 中的 repository
    CALL:    函数/方法调用，如 repository.find()
    DECORATOR: 装饰器引用，如 @trace
    TYPE_ANNOTATION: 类型注解中的引用，如 user_id: int 中的 int
    """
    SIMPLE = "simple"
    ATTRIBUTE = "attribute"
    CALL = "call"
    DECORATOR = "decorator"
    TYPE_ANNOTATION = "type_annotation"


@dataclass(frozen=True)
class SymbolLocation:
    """符号在源代码中的位置。

    frozen=True 的原因：
    - 位置信息是事实，创建后不应修改
    - 不可变对象可以安全地作为 dict 的 key
    """
    file: str         # 文件路径，如 "auth/service.py"
    line: int         # 行号（从 0 开始，与 parsing/models.py 保持一致）
    column: int       # 列号（从 0 开始）


@dataclass(frozen=True)
class Parameter:
    """函数/方法的参数定义。

    注意：self 在 AST 中也是普通参数，不会被特殊对待。
    """
    name: str                              # 参数名，如 "user_id"
    type_annotation: str | None = None     # 类型注解，如 "int"、"str | None"
    default_value: str | None = None       # 默认值的源码文本，如 "None"、"0"


@dataclass(frozen=True)
class Symbol:
    """一个代码符号 —— 类、函数、方法、变量等的统称。

    Symbol 是不可变的（frozen=True），因为定义位置是客观事实。

    三层标识系统（解决同名歧义）：
    - name:            简短名字，如 "get_user" —— 不唯一，用于模糊搜索
    - qualified_name:  限定名，如 "UserService.get_user" —— 文件内唯一
    - symbol_id:       全局 ID，如 "auth/service.py::UserService.get_user" —— 全局唯一
    """
    name: str                            # 简短名字
    kind: SymbolKind                     # 符号种类
    location: SymbolLocation             # 定义位置

    qualified_name: str = ""             # 限定名（由 Scope Stack 构建）
    signature: str = ""                  # 签名字符串，如 "(self, user_id: int) -> User"
    decorators: list[str] = field(       # 装饰器名字列表，如 ["trace", "staticmethod"]
        default_factory=list
    )
    parameters: list[Parameter] = field( # 参数列表
        default_factory=list
    )

    @property
    def symbol_id(self) -> str:
        """全局唯一标识符。

        用 @property 而不是存字段的原因：
        它由 file + qualified_name 算出来，不需要冗余存储。
        如果 qualified_name 变了，symbol_id 自动更新。
        """
        qn = self.qualified_name or self.name
        return f"{self.location.file}::{qn}"


@dataclass(frozen=True)
class Reference:
    """对某个符号的一次引用。

    注意：Attribute 链（如 self.repository.find）会产生多个 Reference：
    - Reference(name="self", kind=SIMPLE)
    - Reference(name="repository", kind=ATTRIBUTE)
    - Reference(name="find", kind=ATTRIBUTE)
    """
    name: str               # 被引用的名字
    kind: ReferenceKind     # 引用种类
    location: SymbolLocation  # 引用发生的位置
    scope: str = ""         # 发生在哪个作用域内，如 "UserService.get_user"
