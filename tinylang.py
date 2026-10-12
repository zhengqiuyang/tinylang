#!/usr/bin/env python3
"""tinylang — 从零实现的一门小语言。

M1 词法分析:手写 scanner。双引号字符串(\\n \\t \\" \\\\ 转义)、行注释与块注释、
   int/float 数字、关键字表、行列号错误定位。
M2 Pratt 解析:优先级爬升(绑定力表)、左/右结合、一元与后缀调用、
   函数声明与函数表达式、完整语句语法,错误带 token 定位。
M3 树求值器:环境链实现词法作用域、闭包与一等函数、if/while/for、
   return 信号、原生函数(print/len/clock)、REPL 与脚本执行。
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
            v = self.eval(expr.operand, env)
            if expr.op == "-":
                if _is_num(v):
                    return -v
                raise TinyError(f"一元 '-' 只能用于数字,得到 {format_value(v)}")
            return not truthy(v)  # '!'
        if isinstance(expr, Call):
            return self._call(expr, env)
        if isinstance(expr, FunExpr):
            return TinyFunction(expr.params, expr.body, env)
        raise TinyError(f"未知表达式节点 {expr!r}")  # pragma: no cover

    def _binop(self, expr, env):
        left = self.eval(expr.left, env)
        right = self.eval(expr.right, env)
        op = expr.op
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


# ---------- 入口:脚本执行与 REPL ----------

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


def repl():
    interp = Interpreter()
    buffer = ""
    print("tinylang REPL —— 语句以 ; 结尾;Ctrl-C / Ctrl-D 退出")
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
            for s in stmts:
                if isinstance(s, ExprStmt):
                    print(format_value(interp.eval(s.expr, interp.globals)))
                else:
                    interp.exec_stmt(s, interp.globals)
        except ReturnSignal:
            print("运行错误: return 不能出现在函数体外")
        except TinyError as e:
            print(f"运行错误: {e.where()}")


def main(argv):
    if len(argv) > 2:
        print("用法: python tinylang.py [script.ty]", file=sys.stderr)
        return 2
    if len(argv) == 2:
        try:
            with open(argv[1], encoding="utf-8") as f:
                src = f.read()
        except OSError as e:
            print(f"无法读取脚本: {e}", file=sys.stderr)
            return 2
        try:
            run_source(src)
        except TinyError as e:
            print(f"错误: {e.where()}", file=sys.stderr)
            return 1
        return 0
    return repl()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
