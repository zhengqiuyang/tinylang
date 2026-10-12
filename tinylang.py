#!/usr/bin/env python3
"""tinylang — 从零实现的一门小语言。

M1 词法分析:手写 scanner。双引号字符串(\\n \\t \\" \\\\ 转义)、行注释与块注释、
   int/float 数字、关键字表、行列号错误定位。
M2 Pratt 解析:优先级爬升(绑定力表)、左/右结合、一元与后缀调用、
   函数声明与函数表达式、完整语句语法,错误带 token 定位。
M3 树求值器:词法作用域、闭包、控制流
"""
import enum
from dataclasses import dataclass


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


# ---------- AST(M2) ----------

@dataclass
class Num:
    value: object  # int | float


@dataclass
class Str:
    value: str


@dataclass
class Bool:
    value: bool


@dataclass
class Nil:
    pass


NIL = Nil()


@dataclass
class Var:
    name: str


@dataclass
class Assign:
    name: str
    value: object


@dataclass
class Binop:
    op: str
    left: object
    right: object


@dataclass
class Unop:
    op: str
    operand: object


@dataclass
class Logical:
    op: str  # "&&" | "||"
    left: object
    right: object


@dataclass
class Call:
    callee: object
    args: list


@dataclass
class FunExpr:
    params: list
    body: list  # 语句列表(函数体是一个隐式块)


@dataclass
class VarDecl:
    name: str
    init: object


@dataclass
class FunDecl:
    name: str
    fun: FunExpr


@dataclass
class ExprStmt:
    expr: object


@dataclass
class Block:
    body: list


@dataclass
class If:
    cond: object
    then: object
    otherwise: object  # 可能为 None


@dataclass
class While:
    cond: object
    body: object


@dataclass
class For:
    init: object  # VarDecl | ExprStmt | None
    cond: object  # 可能为 None(恒真)
    step: object   # 可能为 None
    body: object


@dataclass
class Return:
    value: object  # 可能为 None


# ---------- Pratt 解析器(M2) ----------

class Parser:
    """优先级爬升(Pratt)解析器。

    中缀运算符的绑定力(左, 右):左结合用 (n, n+1),右结合用 (n, n)。
    调用 `f(x)` 作为后缀,绑定力最高(13);一元运算符 13。
    """

    INFIX = {
        TokenType.ASSIGN: (1, 1),  # 右结合,绑定力最低
        TokenType.OR: (1, 2),
        TokenType.AND: (3, 4),
        TokenType.EQ: (5, 6), TokenType.NEQ: (5, 6),
        TokenType.LT: (7, 8), TokenType.GT: (7, 8),
        TokenType.LE: (7, 8), TokenType.GE: (7, 8),
        TokenType.PLUS: (9, 10), TokenType.MINUS: (9, 10),
        TokenType.STAR: (11, 12), TokenType.SLASH: (11, 12),
        TokenType.PERCENT: (11, 12),
    }
    CALL_BP = 13

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # ----- token 游标 -----

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.type is not TokenType.EOF:
            self.pos += 1
        return tok

    def check(self, ttype):
        return self.peek().type is ttype

    def match(self, *ttypes):
        if self.peek().type in ttypes:
            return self.advance()
        return None

    def expect(self, ttype, what=None):
        tok = self.peek()
        if tok.type is ttype:
            return self.advance()
        raise TinyError(f"期望 {what or ttype.value},但得到 {self._describe(tok)}",
                        tok.line, tok.col)

    @staticmethod
    def _describe(tok):
        if tok.type is TokenType.EOF:
            return "文件结尾"
        return repr(tok.value)

    # ----- 语句 -----

    def program(self):
        stmts = []
        while not self.check(TokenType.EOF):
            stmts.append(self.declaration())
        return stmts

    def declaration(self):
        if self.match(TokenType.VAR):
            return self.var_decl()
        if self.check(TokenType.FUN) and \
                self.tokens[self.pos + 1].type is TokenType.IDENT:
            self.advance()
            return self.fun_decl()
        return self.statement()

    def var_decl(self):
        name = self.expect(TokenType.IDENT, "变量名")
        if self.match(TokenType.ASSIGN):
            init = self.expression()
        else:
            init = NIL
        self.expect(TokenType.SEMICOLON, "';'")
        return VarDecl(name.value, init)

    def fun_decl(self):
        name = self.expect(TokenType.IDENT, "函数名")
        return FunDecl(name.value, self.fun_body())

    def fun_body(self):
        self.expect(TokenType.LPAREN, "'('")
        params = []
        if not self.check(TokenType.RPAREN):
            while True:
                p = self.expect(TokenType.IDENT, "参数名")
                if p.value in params:
                    raise TinyError(f"重复的参数名 {p.value!r}", p.line, p.col)
                params.append(p.value)
                if not self.match(TokenType.COMMA):
                    break
        self.expect(TokenType.RPAREN, "')'")
        return FunExpr(params, self.block().body)

    def statement(self):
        if self.check(TokenType.LBRACE):
            return self.block()
        if self.match(TokenType.IF):
            return self.if_stmt()
        if self.match(TokenType.WHILE):
            return self.while_stmt()
        if self.match(TokenType.FOR):
            return self.for_stmt()
        if self.match(TokenType.RETURN):
            return self.return_stmt()
        return self.expr_stmt()

    def block(self):
        """消费一对花括号之间的语句列表(含花括号本身)。"""
        self.expect(TokenType.LBRACE, "'{'")
        stmts = []
        while not self.check(TokenType.RBRACE) and not self.check(TokenType.EOF):
            stmts.append(self.declaration())
        self.expect(TokenType.RBRACE, "'}'")
        return Block(stmts)

    def if_stmt(self):
        self.expect(TokenType.LPAREN, "'('")
        cond = self.expression()
        self.expect(TokenType.RPAREN, "')'")
        then = self.statement()
        otherwise = None
        if self.match(TokenType.ELSE):
            otherwise = self.statement()
        return If(cond, then, otherwise)

    def while_stmt(self):
        self.expect(TokenType.LPAREN, "'('")
        cond = self.expression()
        self.expect(TokenType.RPAREN, "')'")
        return While(cond, self.statement())

    def for_stmt(self):
        self.expect(TokenType.LPAREN, "'('")
        if self.match(TokenType.SEMICOLON):
            init = None
        elif self.match(TokenType.VAR):
            init = self.var_decl()
        else:
            init = self.expr_stmt()
        cond = None
        if not self.check(TokenType.SEMICOLON):
            cond = self.expression()
        self.expect(TokenType.SEMICOLON, "';'")
        step = None
        if not self.check(TokenType.RPAREN):
            step = self.expression()
        self.expect(TokenType.RPAREN, "')'")
        return For(init, cond, step, self.statement())

    def return_stmt(self):
        value = None
        if not self.check(TokenType.SEMICOLON):
            value = self.expression()
        self.expect(TokenType.SEMICOLON, "';'")
        return Return(value)

    def expr_stmt(self):
        expr = self.expression()
        self.expect(TokenType.SEMICOLON, "';'")
        return ExprStmt(expr)

    # ----- 表达式(Pratt) -----

    def expression(self, min_bp=0):
        lhs = self.unary()
        while True:
            tok = self.peek()
            if tok.type is TokenType.LPAREN:
                if self.CALL_BP < min_bp:
                    break
                self.advance()
                args = []
                if not self.check(TokenType.RPAREN):
                    while True:
                        args.append(self.expression())
                        if not self.match(TokenType.COMMA):
                            break
                self.expect(TokenType.RPAREN, "')'")
                lhs = Call(lhs, args)
                continue
            bp = self.INFIX.get(tok.type)
            if bp is None or bp[0] < min_bp:
                break
            op = self.advance()
            if op.type is TokenType.ASSIGN:
                if not isinstance(lhs, Var):
                    raise TinyError("非法赋值目标", op.line, op.col)
                value = self.expression(bp[0])  # 右结合
                lhs = Assign(lhs.name, value)
            else:
                right = self.expression(bp[1])
                if op.type in (TokenType.AND, TokenType.OR):
                    lhs = Logical(op.value, lhs, right)
                else:
                    lhs = Binop(op.value, lhs, right)
        return lhs

    def unary(self):
        tok = self.peek()
        if tok.type in (TokenType.BANG, TokenType.MINUS):
            self.advance()
            return Unop(tok.value, self.expression(self.CALL_BP))
        return self.primary()

    def primary(self):
        tok = self.advance()
        if tok.type is TokenType.NUMBER:
            return Num(tok.value)
        if tok.type is TokenType.STRING:
            return Str(tok.value)
        if tok.type is TokenType.TRUE:
            return Bool(True)
        if tok.type is TokenType.FALSE:
            return Bool(False)
        if tok.type is TokenType.NIL:
            return NIL
        if tok.type is TokenType.IDENT:
            return Var(tok.value)
        if tok.type is TokenType.FUN:
            return self.fun_body()
        if tok.type is TokenType.LPAREN:
            expr = self.expression()
            self.expect(TokenType.RPAREN, "')'")
            return expr
        raise TinyError(f"意外的 {self._describe(tok)}", tok.line, tok.col)


def parse_program(src):
    """把源码解析成语句列表(AST 顶层)。"""
    return Parser(tokenize(src)).program()
