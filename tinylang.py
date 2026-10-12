#!/usr/bin/env python3
"""tinylang — 从零实现的一门小语言。

M1 词法分析:手写 scanner。双引号字符串(\\n \\t \\" \\\\ 转义)、行注释与块注释、
   int/float 数字、关键字表、行列号错误定位。
M2 Pratt 解析:优先级爬升(绑定力表)、左/右结合、一元与后缀调用、
   函数声明与函数表达式、完整语句语法,错误带 token 定位。
M3 树求值器:环境链实现词法作用域、闭包与一等函数、if/while/for、
   return 信号、原生函数(print/len/clock)、REPL 与脚本执行。
M4 字节码 VM:AST → wordcode 编译(名字解析/捕获分析先行的两遍编译)、
   基于栈的虚拟机、函数调用帧、cell + 捕获链实现的 upvalue 闭包,
   `--vm` 开启,与树求值器语义对拍一致。
"""
import enum
import sys
import time
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


# ---------- 求值器(M3) ----------

def format_value(v):
    """值的展示形式(print 与 REPL 共用)。"""
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e16:
            return str(int(v))
        return repr(v)
    if isinstance(v, TinyFunction):
        return "<fun>"
    if isinstance(v, NativeFunction):
        return "<native fun>"
    return str(v)


def truthy(v):
    """tinylang 的真值规则:只有 nil 和 false 为假,0 与空串为真。"""
    return v is not None and v is not False


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def tinylang_eq(a, b):
    """相等性:类型不同的 true/1 不相等,其余同 Python。"""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def apply_binop(op, left, right):
    """二元运算的共享语义(M3 树求值器与 M4 VM 共用)。"""
    if op == "+":
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        if _is_num(left) and _is_num(right):
            return left + right
        raise TinyError(f"{format_value(left)} 与 {format_value(right)} "
                        f"不能相加(仅限数字或两个字符串)")
    if op in ("-", "*", "/", "%"):
        if not (_is_num(left) and _is_num(right)):
            raise TinyError(f"运算符 {op!r} 只能用于数字:"
                            f"{format_value(left)} {op} {format_value(right)}")
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if right == 0:
            raise TinyError("除以零" if op == "/" else "对零取模")
        return left / right if op == "/" else left % right
    if op in ("<", ">", "<=", ">="):
        if not (_is_num(left) and _is_num(right)):
            raise TinyError(f"比较运算只能用于数字:"
                            f"{format_value(left)} {op} {format_value(right)}")
        if op == "<":
            return left < right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        return left >= right
    if op == "==":
        return tinylang_eq(left, right)
    return not tinylang_eq(left, right)  # '!='


def apply_unop(op, v):
    """一元运算的共享语义。"""
    if op == "-":
        if _is_num(v):
            return -v
        raise TinyError(f"一元 '-' 只能用于数字,得到 {format_value(v)}")
    return not truthy(v)  # '!'


class Environment:
    """词法作用域环境链:define 定义在当前层,get/assign 沿父链查找。"""
    __slots__ = ("values", "parent")

    def __init__(self, parent=None):
        self.values = {}
        self.parent = parent

    def define(self, name, value):
        self.values[name] = value

    def get(self, name):
        env = self
        while env is not None:
            if name in env.values:
                return env.values[name]
            env = env.parent
        raise TinyError(f"未定义的变量 {name!r}")

    def assign(self, name, value):
        env = self
        while env is not None:
            if name in env.values:
                env.values[name] = value
                return
            env = env.parent
        raise TinyError(f"未定义的变量 {name!r}")


class TinyFunction:
    """用户函数:参数、函数体、定义时的闭包环境。"""
    __slots__ = ("params", "body", "closure")

    def __init__(self, params, body, closure):
        self.params = params
        self.body = body
        self.closure = closure


class NativeFunction:
    """原生函数:fn(interpreter, args) -> value;arity 为 None 表示不限。"""
    __slots__ = ("name", "arity", "fn")

    def __init__(self, name, arity, fn):
        self.name = name
        self.arity = arity
        self.fn = fn


class ReturnSignal(Exception):
    """return 的非局部退出。"""

    def __init__(self, value):
        super().__init__("return")
        self.value = value


class Interpreter:
    """树求值器。output(text) 用于 print 输出,便于测试注入。"""

    def __init__(self, output=None):
        self.globals = Environment()
        self.output = output if output is not None else print
        self._install_natives()

    # ----- 原生函数 -----

    def _install_natives(self):
        self.globals.define("print", NativeFunction("print", None, self._print))
        self.globals.define("len", NativeFunction("len", 1, self._len))
        self.globals.define("clock", NativeFunction("clock", 0, self._clock))

    def _print(self, _interp, args):
        self.output(" ".join(format_value(a) for a in args))
        return None

    @staticmethod
    def _len(_interp, args):
        v = args[0]
        if isinstance(v, str):
            return len(v)
        raise TinyError(f"len 只接受字符串,得到 {format_value(v)}")

    @staticmethod
    def _clock(_interp, _args):
        return time.time()

    # ----- 语句 -----

    def run_program(self, stmts):
        try:
            for stmt in stmts:
                self.exec_stmt(stmt, self.globals)
        except ReturnSignal:
            raise TinyError("return 不能出现在函数体外") from None

    def exec_stmt(self, stmt, env):
        if isinstance(stmt, VarDecl):
            env.define(stmt.name, self.eval(stmt.init, env))
        elif isinstance(stmt, FunDecl):
            env.define(stmt.name,
                       TinyFunction(stmt.fun.params, stmt.fun.body, env))
        elif isinstance(stmt, ExprStmt):
            self.eval(stmt.expr, env)
        elif isinstance(stmt, Block):
            block_env = Environment(env)
            for s in stmt.body:
                self.exec_stmt(s, block_env)
        elif isinstance(stmt, If):
            if truthy(self.eval(stmt.cond, env)):
                self.exec_stmt(stmt.then, env)
            elif stmt.otherwise is not None:
                self.exec_stmt(stmt.otherwise, env)
        elif isinstance(stmt, While):
            while truthy(self.eval(stmt.cond, env)):
                self.exec_stmt(stmt.body, env)
        elif isinstance(stmt, For):
            loop_env = Environment(env)
            if stmt.init is not None:
                self.exec_stmt(stmt.init, loop_env)
            while stmt.cond is None or truthy(self.eval(stmt.cond, loop_env)):
                self.exec_stmt(stmt.body, loop_env)
                if stmt.step is not None:
                    self.eval(stmt.step, loop_env)
        elif isinstance(stmt, Return):
            value = self.eval(stmt.value, env) if stmt.value is not None else None
            raise ReturnSignal(value)
        else:  # pragma: no cover
            raise TinyError(f"未知语句节点 {stmt!r}")

    # ----- 表达式 -----

    def eval(self, expr, env):
        if isinstance(expr, (Num, Str, Bool)):
            return expr.value
        if isinstance(expr, Nil):
            return None
        if isinstance(expr, Var):
            return env.get(expr.name)
        if isinstance(expr, Assign):
            value = self.eval(expr.value, env)
            env.assign(expr.name, value)
            return value
        if isinstance(expr, Logical):
            left = self.eval(expr.left, env)
            if expr.op == "&&":
                return self.eval(expr.right, env) if truthy(left) else left
            return left if truthy(left) else self.eval(expr.right, env)
        if isinstance(expr, Binop):
            return self._binop(expr, env)
        if isinstance(expr, Unop):
            return apply_unop(expr.op, self.eval(expr.operand, env))
        if isinstance(expr, Call):
            return self._call(expr, env)
        if isinstance(expr, FunExpr):
            return TinyFunction(expr.params, expr.body, env)
        raise TinyError(f"未知表达式节点 {expr!r}")  # pragma: no cover

    def _binop(self, expr, env):
        return apply_binop(expr.op,
                           self.eval(expr.left, env),
                           self.eval(expr.right, env))

    def _call(self, expr, env):
        callee = self.eval(expr.callee, env)
        args = [self.eval(a, env) for a in expr.args]
        if isinstance(callee, NativeFunction):
            if callee.arity is not None and len(args) != callee.arity:
                raise TinyError(f"{callee.name} 需要 {callee.arity} 个参数,"
                                f"得到 {len(args)}")
            return callee.fn(self, args)
        if isinstance(callee, TinyFunction):
            if len(args) != len(callee.params):
                raise TinyError(f"函数需要 {len(callee.params)} 个参数,"
                                f"得到 {len(args)}")
            call_env = Environment(callee.closure)
            for name, value in zip(callee.params, args):
                call_env.define(name, value)
            try:
                for s in callee.body:
                    self.exec_stmt(s, call_env)
            except ReturnSignal as sig:
                return sig.value
            return None
        raise TinyError(f"{format_value(callee)} 不可调用")


# ---------- 字节码 VM(M4) ----------
# wordcode 风格(同 CPython):code 是整数列表,操作码后跟操作数字。

class Op:
    CONST = 0            # k:push constants[k]
    NIL = 1
    TRUE = 2
    FALSE = 3
    POP = 4
    GET_GLOBAL = 5       # k(名字常量)
    DEFINE_GLOBAL = 6    # k:弹出值并定义全局变量
    SET_GLOBAL = 7       # k:窥视栈顶赋值(未定义则报错)
    GET_LOCAL = 8        # slot
    SET_LOCAL = 9        # slot:窥视栈顶写入
    NEW_CELL = 10        # slot:弹出值,装箱为 cell 存入槽位
    GET_CELL = 11        # slot
    SET_CELL = 12        # slot:窥视栈顶写入 cell
    GET_FREE = 13        # idx:读闭包捕获的第 idx 个 cell
    SET_FREE = 14        # idx
    CLOSURE = 15         # k(函数原型), n, 之后 n 对 (来源, 索引)
    CALL = 16            # argc
    RETURN = 17          # 弹出返回值
    JUMP = 18            # target
    JUMP_IF_FALSE = 19   # target:弹出条件,假则跳
    JUMP_IF_FALSE_PEEK = 20  # && 用:不弹出
    JUMP_IF_TRUE_PEEK = 21   # || 用:不弹出
    ADD = 22
    SUB = 23
    MUL = 24
    DIV = 25
    MOD = 26
    EQ = 27
    NEQ = 28
    LT = 29
    GT = 30
    LE = 31
    GE = 32
    NOT = 33
    NEG = 34


BINOP_CODE = {
    "+": Op.ADD, "-": Op.SUB, "*": Op.MUL, "/": Op.DIV, "%": Op.MOD,
    "==": Op.EQ, "!=": Op.NEQ, "<": Op.LT, ">": Op.GT, "<=": Op.LE,
    ">=": Op.GE,
}


class FuncProto:
    """编译产物:一个函数(或模块顶层)的字节码与元数据。"""
    __slots__ = ("name", "params", "code", "constants",
                 "slot_count", "slot_is_cell", "n_free")

    def __init__(self, name, params, slot_count):
        self.name = name
        self.params = params
        self.code = []
        self.constants = []
        self.slot_count = slot_count
        self.slot_is_cell = [False] * slot_count
        self.n_free = 0


class VmClosure:
    """运行期函数:原型 + 捕获的 cell 列表。"""
    __slots__ = ("proto", "cells")

    def __init__(self, proto, cells):
        self.proto = proto
        self.cells = cells


# ----- 第一遍:名字解析与捕获分析 -----

class FuncInfo:
    """解析器里一个函数上下文:槽位表、被捕获集合、自由变量链。"""

    def __init__(self, parent, name, params):
        self.parent = parent
        self.name = name
        self.params = params
        self.scopes = []          # 栈式作用域:list[dict name->slot]
        self.slot_count = 0
        self.captured_slots = set()
        self.freevars = []        # [("cellslot", slot) | ("free", idx)]
        self.free_by_name = {}
        self.local_uses = []      # [(ast节点, slot)] 全部解析完成后定 kind
        self.children = []        # 嵌套函数的 FuncInfo
        self.proto = None

    def begin_scope(self):
        self.scopes.append({})

    def end_scope(self):
        self.scopes.pop()

    def declare(self, name):
        """在当前作用域声明一个槽位,返回槽号。模块层返回 None(走全局)。"""
        if not self.scopes:
            return None
        slot = self.slot_count
        self.slot_count += 1
        self.scopes[-1][name] = slot
        return slot

    def find_local(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None


def resolve_program(stmts):
    """第一遍:名字解析与捕获分析。

    Var/Assign 节点获得 .res ∈ ("local", slot) ("cell", slot)
    ("free", idx) ("global", None);VarDecl/FunDecl 获得 .slot(模块层为 None);
    Return 在模块层获得 .top_level;FunExpr 获得所属 FuncInfo(.info)。
    返回模块层 FuncInfo。
    """
    module = FuncInfo(None, "<module>", [])
    _resolve_stmts(stmts, module)
    _finalize(module)
    return module


def _finalize(info):
    info.proto = FuncProto(info.name, info.params, info.slot_count)
    info.proto.n_free = len(info.freevars)
    info.proto.slot_is_cell = [s in info.captured_slots
                               for s in range(info.slot_count)]
    for node, slot in info.local_uses:
        kind = "cell" if slot in info.captured_slots else "local"
        node.res = (kind, slot)
    for child in info.children:
        _finalize(child)


def _new_function(info, name, params):
    child = FuncInfo(info, name, params)
    info.children.append(child)
    child.begin_scope()
    for p in params:
        child.declare(p)
    return child


def _resolve_stmts(stmts, info):
    for s in stmts:
        _resolve_stmt(s, info)


def _resolve_stmt(s, info):
    if isinstance(s, VarDecl):
        _resolve_expr(s.init, info)
        s.slot = info.declare(s.name)
    elif isinstance(s, FunDecl):
        # 先占位再解析函数体,函数体内递归引用自身才能解析到该槽位
        s.slot = info.declare(s.name)
        child = _new_function(info, s.name, s.fun.params)
        s.fun.info = child
        _resolve_stmts(s.fun.body, child)
        child.end_scope()
    elif isinstance(s, ExprStmt):
        _resolve_expr(s.expr, info)
    elif isinstance(s, Block):
        info.begin_scope()
        _resolve_stmts(s.body, info)
        info.end_scope()
    elif isinstance(s, If):
        _resolve_expr(s.cond, info)
        _resolve_stmt(s.then, info)
        if s.otherwise is not None:
            _resolve_stmt(s.otherwise, info)
    elif isinstance(s, While):
        _resolve_expr(s.cond, info)
        _resolve_stmt(s.body, info)
    elif isinstance(s, For):
        info.begin_scope()
        if s.init is not None:
            _resolve_stmt(s.init, info)
        if s.cond is not None:
            _resolve_expr(s.cond, info)
        if s.step is not None:
            _resolve_expr(s.step, info)
        _resolve_stmt(s.body, info)
        info.end_scope()
    elif isinstance(s, Return):
        s.top_level = info.parent is None
        if s.value is not None:
            _resolve_expr(s.value, info)
    else:  # pragma: no cover
        raise TinyError(f"未知语句节点 {s!r}")


def _resolve_expr(e, info):
    if isinstance(e, (Num, Str, Bool, Nil)):
        return
    if isinstance(e, Var):
        _use_name(e, e.name, info)
        return
    if isinstance(e, Assign):
        _resolve_expr(e.value, info)
        _use_name(e, e.name, info)
        return
    if isinstance(e, (Binop, Logical)):
        _resolve_expr(e.left, info)
        _resolve_expr(e.right, info)
        return
    if isinstance(e, Unop):
        _resolve_expr(e.operand, info)
        return
    if isinstance(e, Call):
        _resolve_expr(e.callee, info)
        for a in e.args:
            _resolve_expr(a, info)
        return
    if isinstance(e, FunExpr):
        child = _new_function(info, "<fun>", e.params)
        e.info = child
        _resolve_stmts(e.body, child)
        child.end_scope()
        return
    raise TinyError(f"未知表达式节点 {e!r}")  # pragma: no cover


def _use_name(node, name, info):
    """解析一次名字使用:局部 / 自由变量(触发捕获链)/ 全局。"""
    slot = info.find_local(name)
    if slot is not None:
        info.local_uses.append((node, slot))
        return
    # 沿函数链向外找声明者,从最外层向内逐层登记捕获链
    chain = []
    ctx = info
    holder = None
    while ctx is not None:
        if ctx is not info:
            found = ctx.find_local(name)
            if found is not None:
                holder = (ctx, found)
                break
        chain.append(ctx)
        ctx = ctx.parent
    if holder is None:
        node.res = ("global", None)
        return
    owner, slot = holder
    owner.captured_slots.add(slot)
    for c in reversed(chain):  # 外层优先:内层的描述符依赖外层的登记
        if name in c.free_by_name:
            continue
        if c.parent is owner:
            descriptor = ("cellslot", slot)
        else:
            descriptor = ("free", c.parent.free_by_name[name])
        c.free_by_name[name] = len(c.freevars)
        c.freevars.append(descriptor)
    node.res = ("free", info.free_by_name[name])


# ----- 第二遍:编译为 wordcode -----

class Compiler:
    """把(已解析的)AST 编译成 FuncProto.code。"""

    def __init__(self, info):
        self.info = info
        self.proto = info.proto

    def konst(self, value):
        for i, c in enumerate(self.proto.constants):
            if c is value or (type(c) is type(value) and c == value):
                return i
        self.proto.constants.append(value)
        return len(self.proto.constants) - 1

    def emit(self, *words):
        self.proto.code.extend(words)

    def emit_jump(self, op):
        self.emit(op, 0)
        return len(self.proto.code) - 1

    def patch_jump(self, at):
        self.proto.code[at] = len(self.proto.code)

    # --- 语句 ---
    def stmts(self, stmts):
        for s in stmts:
            self.stmt(s)

    def stmt(self, s):
        if isinstance(s, VarDecl):
            self.expr(s.init)
            if s.slot is None:
                self.emit(Op.DEFINE_GLOBAL, self.konst(s.name))
            elif self.proto.slot_is_cell[s.slot]:
                self.emit(Op.NEW_CELL, s.slot)  # 创建 cell 并以栈顶初始化
            else:
                self.emit(Op.SET_LOCAL, s.slot, Op.POP)
        elif isinstance(s, FunDecl):
            self._reserve_decl(s.slot)
            self.expr(s.fun)   # CLOSURE 压栈
            if s.slot is None:
                self.emit(Op.DEFINE_GLOBAL, self.konst(s.name))
            elif self.proto.slot_is_cell[s.slot]:
                # 写入 _reserve_decl 预留的那个 cell(闭包已捕获它)
                self.emit(Op.SET_CELL, s.slot, Op.POP)
            else:
                self.emit(Op.SET_LOCAL, s.slot, Op.POP)
        elif isinstance(s, ExprStmt):
            self.expr(s.expr)
            self.emit(Op.POP)
        elif isinstance(s, Block):
            self.stmts(s.body)
        elif isinstance(s, If):
            self.expr(s.cond)
            to_else = self.emit_jump(Op.JUMP_IF_FALSE)
            self.stmt(s.then)
            to_end = self.emit_jump(Op.JUMP)
            self.patch_jump(to_else)
            if s.otherwise is not None:
                self.stmt(s.otherwise)
            self.patch_jump(to_end)
        elif isinstance(s, While):
            start = len(self.proto.code)
            self.expr(s.cond)
            to_end = self.emit_jump(Op.JUMP_IF_FALSE)
            self.stmt(s.body)
            self.emit(Op.JUMP, start)
            self.patch_jump(to_end)
        elif isinstance(s, For):
            if s.init is not None:
                self.stmt(s.init)
            start = len(self.proto.code)
            to_end = None
            if s.cond is not None:
                self.expr(s.cond)
                to_end = self.emit_jump(Op.JUMP_IF_FALSE)
            self.stmt(s.body)
            if s.step is not None:
                self.expr(s.step)
                self.emit(Op.POP)
            self.emit(Op.JUMP, start)
            if to_end is not None:
                self.patch_jump(to_end)
        elif isinstance(s, Return):
            if getattr(s, "top_level", False):
                raise TinyError("return 不能出现在函数体外")
            if s.value is not None:
                self.expr(s.value)
            else:
                self.emit(Op.NIL)
            self.emit(Op.RETURN)
        else:  # pragma: no cover
            raise TinyError(f"未知语句节点 {s!r}")

    def _reserve_decl(self, slot):
        """FunDecl 先把槽位初始化成 cell/空值,再压入闭包。"""
        if slot is None:
            return
        if self.proto.slot_is_cell[slot]:
            self.emit(Op.NIL, Op.NEW_CELL, slot)
        else:
            self.emit(Op.NIL, Op.SET_LOCAL, slot, Op.POP)

    # --- 表达式 ---
    def expr(self, e):
        if isinstance(e, Num):
            self.emit(Op.CONST, self.konst(e.value))
        elif isinstance(e, Str):
            self.emit(Op.CONST, self.konst(e.value))
        elif isinstance(e, Bool):
            self.emit(Op.TRUE if e.value else Op.FALSE)
        elif isinstance(e, Nil):
            self.emit(Op.NIL)
        elif isinstance(e, Var):
            self._load(e.res, e.name)
        elif isinstance(e, Assign):
            self.expr(e.value)
            kind, idx = e.res
            if kind == "local":
                self.emit(Op.SET_LOCAL, idx)
            elif kind == "cell":
                self.emit(Op.SET_CELL, idx)
            elif kind == "free":
                self.emit(Op.SET_FREE, idx)
            else:
                self.emit(Op.SET_GLOBAL, self.konst(e.name))
        elif isinstance(e, Logical):
            if e.op == "&&":
                self.expr(e.left)
                skip = self.emit_jump(Op.JUMP_IF_FALSE_PEEK)
                self.emit(Op.POP)
                self.expr(e.right)
            else:
                self.expr(e.left)
                skip = self.emit_jump(Op.JUMP_IF_TRUE_PEEK)
                self.emit(Op.POP)
                self.expr(e.right)
            self.patch_jump(skip)
        elif isinstance(e, Binop):
            self.expr(e.left)
            self.expr(e.right)
            self.emit(BINOP_CODE[e.op])
        elif isinstance(e, Unop):
            self.expr(e.operand)
            self.emit(Op.NEG if e.op == "-" else Op.NOT)
        elif isinstance(e, Call):
            self.expr(e.callee)
            for a in e.args:
                self.expr(a)
            self.emit(Op.CALL, len(e.args))
        elif isinstance(e, FunExpr):
            child = e.info
            sub = Compiler(child)
            sub.stmts(e.body)
            sub.proto.code.extend([Op.NIL, Op.RETURN])  # 函数隐式返回 nil
            self.emit(Op.CLOSURE, self.konst(child.proto), len(child.freevars))
            for kind, idx in child.freevars:
                self.emit(0 if kind == "cellslot" else 1, idx)
        else:  # pragma: no cover
            raise TinyError(f"未知表达式节点 {e!r}")

    def _load(self, res, name):
        kind, idx = res
        if kind == "local":
            self.emit(Op.GET_LOCAL, idx)
        elif kind == "cell":
            self.emit(Op.GET_CELL, idx)
        elif kind == "free":
            self.emit(Op.GET_FREE, idx)
        else:
            self.emit(Op.GET_GLOBAL, self.konst(name))


def compile_program(stmts):
    """AST → 模块 FuncProto(入口)。"""
    module = resolve_program(stmts)
    Compiler(module).stmts(stmts)
    module.proto.code.extend([Op.NIL, Op.RETURN])  # 模块隐式返回
    return module.proto


def compile_source(src):
    """源码 → 模块 FuncProto(入口)。"""
    return compile_program(parse_program(src))

# ----- 虚拟机 -----

class Frame:
    __slots__ = ("proto", "closure", "ip", "locals", "stack_base")

    def __init__(self, proto, closure, stack_base):
        self.proto = proto
        self.closure = closure
        self.ip = 0
        self.locals = [None] * proto.slot_count
        self.stack_base = stack_base


BINOP_NAME = {
    Op.ADD: "+", Op.SUB: "-", Op.MUL: "*", Op.DIV: "/", Op.MOD: "%",
    Op.EQ: "==", Op.NEQ: "!=", Op.LT: "<", Op.GT: ">",
    Op.LE: "<=", Op.GE: ">=",
}


class Vm:
    """基于栈的字节码虚拟机。output(text) 供 print 输出注入。"""

    def __init__(self, output=None):
        self.globals = {}
        self.output = output if output is not None else print
        self.stack = []
        self.frames = []
        self._install_natives()

    def _install_natives(self):
        def native(name, arity, fn):
            self.globals[name] = NativeFunction(name, arity, fn)

        def do_print(_vm, args):
            self.output(" ".join(format_value(a) for a in args))
            return None

        def do_len(_vm, args):
            v = args[0]
            if isinstance(v, str):
                return len(v)
            raise TinyError(f"len 只接受字符串,得到 {format_value(v)}")

        native("print", None, do_print)
        native("len", 1, do_len)
        native("clock", 0, lambda _vm, _a: time.time())

    def run(self, proto):
        self.frames.append(Frame(proto, None, 0))
        stack = self.stack
        while True:
            f = self.frames[-1]
            code = f.proto.code
            op = code[f.ip]
            f.ip += 1
            if op == Op.CONST:
                stack.append(f.proto.constants[code[f.ip]])
                f.ip += 1
            elif op == Op.NIL:
                stack.append(None)
            elif op == Op.TRUE:
                stack.append(True)
            elif op == Op.FALSE:
                stack.append(False)
            elif op == Op.POP:
                stack.pop()
            elif op == Op.GET_GLOBAL:
                name = f.proto.constants[code[f.ip]]
                f.ip += 1
                if name not in self.globals:
                    raise TinyError(f"未定义的变量 {name!r}")
                stack.append(self.globals[name])
            elif op == Op.DEFINE_GLOBAL:
                name = f.proto.constants[code[f.ip]]
                f.ip += 1
                self.globals[name] = stack.pop()
            elif op == Op.SET_GLOBAL:
                name = f.proto.constants[code[f.ip]]
                f.ip += 1
                if name not in self.globals:
                    raise TinyError(f"未定义的变量 {name!r}")
                self.globals[name] = stack[-1]  # 窥视,不弹出
            elif op == Op.GET_LOCAL:
                stack.append(f.locals[code[f.ip]])
                f.ip += 1
            elif op == Op.SET_LOCAL:
                f.locals[code[f.ip]] = stack[-1]
                f.ip += 1
            elif op == Op.NEW_CELL:
                f.locals[code[f.ip]] = [stack.pop()]
                f.ip += 1
            elif op == Op.GET_CELL:
                stack.append(f.locals[code[f.ip]][0])
                f.ip += 1
            elif op == Op.SET_CELL:
                f.locals[code[f.ip]][0] = stack[-1]
                f.ip += 1
            elif op == Op.GET_FREE:
                stack.append(f.closure.cells[code[f.ip]][0])
                f.ip += 1
            elif op == Op.SET_FREE:
                f.closure.cells[code[f.ip]][0] = stack[-1]
                f.ip += 1
            elif op == Op.CLOSURE:
                proto = f.proto.constants[code[f.ip]]
                f.ip += 1
                n = code[f.ip]
                f.ip += 1
                cells = []
                for _ in range(n):
                    kind = code[f.ip]
                    idx = code[f.ip + 1]
                    f.ip += 2
                    if kind == 0:      # 从本帧局部槽捕获(cell)
                        cells.append(f.locals[idx])
                    else:              # 从本闭包的自由变量继续传递
                        cells.append(f.closure.cells[idx])
                stack.append(VmClosure(proto, cells))
            elif op == Op.CALL:
                argc = code[f.ip]
                f.ip += 1
                self._call(argc)
            elif op == Op.RETURN:
                rv = stack.pop()
                del stack[f.stack_base:]
                stack.append(rv)
                self.frames.pop()
                if not self.frames:
                    return
            elif op == Op.JUMP:
                f.ip = code[f.ip]
            elif op == Op.JUMP_IF_FALSE:
                target = code[f.ip]
                f.ip += 1
                if not truthy(stack.pop()):
                    f.ip = target
            elif op == Op.JUMP_IF_FALSE_PEEK:
                target = code[f.ip]
                f.ip += 1
                if not truthy(stack[-1]):
                    f.ip = target
            elif op == Op.JUMP_IF_TRUE_PEEK:
                target = code[f.ip]
                f.ip += 1
                if truthy(stack[-1]):
                    f.ip = target
            elif Op.ADD <= op <= Op.GE:
                right = stack.pop()
                left = stack.pop()
                stack.append(apply_binop(BINOP_NAME[op], left, right))
            elif op == Op.NOT:
                stack.append(apply_unop("!", stack.pop()))
            elif op == Op.NEG:
                stack.append(apply_unop("-", stack.pop()))
            else:  # pragma: no cover
                raise TinyError(f"未知操作码 {op}")

    def _call(self, argc):
        stack = self.stack
        callee = stack[-argc - 1]
        if isinstance(callee, NativeFunction):
            if callee.arity is not None and argc != callee.arity:
                raise TinyError(f"{callee.name} 需要 {callee.arity} 个参数,"
                                f"得到 {argc}")
            args = stack[-argc:]
            del stack[-argc - 1:]
            stack.append(callee.fn(self, args))
            return
        if isinstance(callee, VmClosure):
            proto = callee.proto
            if argc != len(proto.params):
                raise TinyError(f"函数需要 {len(proto.params)} 个参数,"
                                f"得到 {argc}")
            base = len(stack) - argc - 1
            frame = Frame(proto, callee, base)
            for i, value in enumerate(stack[base + 1:]):
                if proto.slot_is_cell[i]:
                    frame.locals[i] = [value]
                else:
                    frame.locals[i] = value
            del stack[base + 1:]  # 弹出参数,被调函数留在栈底标记位置
            self.frames.append(frame)
            return
        raise TinyError(f"{format_value(callee)} 不可调用")


def run_source_vm(src, output=None):
    """用字节码 VM 执行一段源码,返回 Vm 实例。"""
    vm = Vm(output)
    vm.run(compile_source(src))
    return vm


def run_source(src, output=None):
    """编译并执行一段源码,返回解释器实例。"""
    interp = Interpreter(output)
    interp.run_program(parse_program(src))
    return interp


def _is_complete(src):
    """REPL 用:括号/花括号不闭合时继续等待输入。"""
    try:
        tokens = tokenize(src)
    except TinyError:
        return True  # 词法错误直接交给解析器报告
    depth = 0
    for t in tokens:
        if t.type in (TokenType.LBRACE, TokenType.LPAREN):
            depth += 1
        elif t.type in (TokenType.RBRACE, TokenType.RPAREN):
            depth -= 1
    return depth <= 0


def repl(use_vm=False):
    engine = Vm() if use_vm else Interpreter()
    buffer = ""
    print("tinylang REPL —— 语句以 ; 结尾;Ctrl-C / Ctrl-D 退出"
          + ("(VM 模式)" if use_vm else ""))
    while True:
        try:
            line = input("... " if buffer else ">>> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        buffer += line + "\n"
        if not _is_complete(buffer):
            continue
        src, buffer = buffer, ""
        try:
            stmts = parse_program(src)
        except TinyError as e:
            print(f"解析错误: {e.where()}")
            continue
        try:
            if use_vm:
                # 单条表达式语句 → 打印其值(对齐树求值器 REPL 的回显)
                if len(stmts) == 1 and isinstance(stmts[0], ExprStmt):
                    stmts = [ExprStmt(Call(Var("print"), [stmts[0].expr]))]
                engine.run(compile_program(stmts))
            else:
                for s in stmts:
                    if isinstance(s, ExprStmt):
                        print(format_value(engine.eval(s.expr, engine.globals)))
                    else:
                        engine.exec_stmt(s, engine.globals)
        except ReturnSignal:
            print("运行错误: return 不能出现在函数体外")
        except TinyError as e:
            print(f"运行错误: {e.where()}")


def main(argv):
    args = [a for a in argv[1:]]
    use_vm = "--vm" in args
    args = [a for a in args if a != "--vm"]
    if len(args) > 1:
        print("用法: python tinylang.py [--vm] [script.ty]", file=sys.stderr)
        return 2
    backend = run_source_vm if use_vm else run_source
    if len(args) == 1:
        try:
            with open(args[0], encoding="utf-8") as f:
                src = f.read()
        except OSError as e:
            print(f"无法读取脚本: {e}", file=sys.stderr)
            return 2
        try:
            backend(src)
        except TinyError as e:
            print(f"错误: {e.where()}", file=sys.stderr)
            return 1
        return 0
    return repl(use_vm)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
