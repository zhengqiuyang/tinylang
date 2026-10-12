#!/usr/bin/env python3
"""tinylang — 从零实现的一门小语言。

M1 词法分析:手写 scanner。双引号字符串(\\n \\t \\" \\\\ 转义)、行注释与块注释、
   int/float 数字、关键字表、行列号错误定位。
M2 Pratt parser → AST
M3 树求值器:词法作用域、闭包、控制流
"""
import enum


class TinyError(Exception):
    """tinylang 所有错误(词法/语法/运行时)。"""

    def __init__(self, message, line=None, col=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col

    def where(self):
        if self.line is None:
            return self.message
        return f"{self.line}:{self.col}: {self.message}"


class TokenType(enum.Enum):
    # 单字符符号
    LPAREN = "("
    RPAREN = ")"
    LBRACE = "{"
    RBRACE = "}"
    COMMA = ","
    SEMICOLON = ";"
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    PERCENT = "%"
    LT = "<"
    GT = ">"
    ASSIGN = "="
    BANG = "!"
    # 双字符符号
    EQ = "=="
    NEQ = "!="
    LE = "<="
    GE = ">="
    AND = "&&"
    OR = "||"
    # 字面量与标识符
    NUMBER = "number"
    STRING = "string"
    IDENT = "ident"
    # 关键字
    VAR = "var"
    FUN = "fun"
    RETURN = "return"
    IF = "if"
    ELSE = "else"
    WHILE = "while"
    FOR = "for"
    TRUE = "true"
    FALSE = "false"
    NIL = "nil"
    # 结束
    EOF = "eof"


KEYWORDS = {t.value: t for t in (
    TokenType.VAR, TokenType.FUN, TokenType.RETURN,
    TokenType.IF, TokenType.ELSE, TokenType.WHILE, TokenType.FOR,
    TokenType.TRUE, TokenType.FALSE, TokenType.NIL,
)}

ONE_CHAR = {
    "(": TokenType.LPAREN, ")": TokenType.RPAREN,
    "{": TokenType.LBRACE, "}": TokenType.RBRACE,
    ",": TokenType.COMMA, ";": TokenType.SEMICOLON,
    "+": TokenType.PLUS, "-": TokenType.MINUS,
    "*": TokenType.STAR, "/": TokenType.SLASH,
    "%": TokenType.PERCENT,
    "<": TokenType.LT, ">": TokenType.GT,
    "=": TokenType.ASSIGN, "!": TokenType.BANG,
}

TWO_CHAR = {
    "==": TokenType.EQ, "!=": TokenType.NEQ,
    "<=": TokenType.LE, ">=": TokenType.GE,
    "&&": TokenType.AND, "||": TokenType.OR,
}

ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}

DIGITS = "0123456789"


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type_, value, line, col):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"


def _is_ident_start(c):
    return ("a" <= c <= "z") or ("A" <= c <= "Z") or c == "_"


def _is_ident_char(c):
    return _is_ident_start(c) or (c in DIGITS)


def tokenize(src):
    """把源码扫描成 token 列表(以 EOF 结尾)。

    行列号从 1 开始;token 的位置记录其起始点。
    词法错误抛 TinyError,带定位信息。
    """
    tokens = []
    i, line, col = 0, 1, 1
    n = len(src)
    while i < n:
        c = src[i]
        if c in " \t\r":
            i += 1
            col += 1
            continue
        if c == "\n":
            i += 1
            line += 1
            col = 1
            continue
        if src.startswith("//", i):  # 行注释
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):  # 块注释(不可嵌套,可跨行)
            start_line, start_col = line, col
            end = src.find("*/", i + 2)
            if end < 0:
                raise TinyError("未闭合的块注释", start_line, start_col)
            skipped = src[i:end + 2]
            newlines = skipped.count("\n")
            if newlines:
                line += newlines
                col = len(skipped) - skipped.rfind("\n")
            else:
                col += len(skipped)
            i = end + 2
            continue
        if c == '"':  # 字符串(不可跨行)
            start_line, start_col = line, col
            i += 1
            col += 1
            out = []
            while True:
                if i >= n or src[i] == "\n":
                    raise TinyError("未闭合的字符串", start_line, start_col)
                ch = src[i]
                if ch == '"':
                    i += 1
                    col += 1
                    break
                if ch == "\\":
                    if i + 1 >= n:
                        raise TinyError("未闭合的字符串", start_line, start_col)
                    esc = src[i + 1]
                    if esc not in ESCAPES:
                        raise TinyError(f"非法转义 \\{esc}", line, col)
                    out.append(ESCAPES[esc])
                    i += 2
                    col += 2
                    continue
                out.append(ch)
                i += 1
                col += 1
            tokens.append(Token(TokenType.STRING, "".join(out),
                                start_line, start_col))
            continue
        if c in DIGITS:  # 数字:int 或含小数点的 float
            start, start_col = i, col
            while i < n and src[i] in DIGITS:
                i += 1
                col += 1
            if src[i:i + 2][0:1] == "." and i + 1 < n and src[i + 1] in DIGITS:
                i += 1
                col += 1
                while i < n and src[i] in DIGITS:
                    i += 1
                    col += 1
                value = float(src[start:i])
            else:
                value = int(src[start:i])
            tokens.append(Token(TokenType.NUMBER, value, line, start_col))
            continue
        if _is_ident_start(c):  # 标识符 / 关键字
            start, start_col = i, col
            while i < n and _is_ident_char(src[i]):
                i += 1
                col += 1
            text = src[start:i]
            tokens.append(Token(KEYWORDS.get(text, TokenType.IDENT),
                                text, line, start_col))
            continue
        two = src[i:i + 2]
        if two in TWO_CHAR:
            tokens.append(Token(TWO_CHAR[two], two, line, col))
            i += 2
            col += 2
            continue
        if c in ONE_CHAR:
            tokens.append(Token(ONE_CHAR[c], c, line, col))
            i += 1
            col += 1
            continue
        raise TinyError(f"非法字符 {c!r}", line, col)
    tokens.append(Token(TokenType.EOF, None, line, col))
    return tokens
