"""tinylang M2(Pratt 解析)的单元测试:python test_parser.py -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tinylang import (  # noqa: E402
    Assign, Binop, Block, Bool, Call, ExprStmt, For, FunDecl, FunExpr, If,
    Logical, NIL, Num, Return, Str, TinyError, Unop, Var, VarDecl, While,
    parse_program,
)


def first_expr(src):
    """解析后取第一条语句里的表达式,便于断言。"""
    stmt = parse_program(src)[0]
    assert isinstance(stmt, ExprStmt), f"期望表达式语句,得到 {stmt!r}"
    return stmt.expr


class PrecedenceTests(unittest.TestCase):
    def test_mul_binds_tighter_than_add(self):
        self.assertEqual(
            first_expr("1 + 2 * 3;"),
            Binop("+", Num(1), Binop("*", Num(2), Num(3))))

    def test_left_associative_minus(self):
        self.assertEqual(
            first_expr("1 - 2 - 3;"),
            Binop("-", Binop("-", Num(1), Num(2)), Num(3)))

    def test_right_associative_assignment(self):
        self.assertEqual(
            first_expr("a = b = 1;"),
            Assign("a", Assign("b", Num(1))))

    def test_equality_looser_than_comparison(self):
        self.assertEqual(
            first_expr("1 < 2 == 3 < 4;"),
            Binop("==", Binop("<", Num(1), Num(2)), Binop("<", Num(3), Num(4))))

    def test_logical_precedence(self):
        # && 比 || 紧
        self.assertEqual(
            first_expr("a && b || c;"),
            Logical("||", Logical("&&", Var("a"), Var("b")), Var("c")))
        # || 比 == 松
        self.assertEqual(
            first_expr("a == b || c;"),
            Logical("||", Binop("==", Var("a"), Var("b")), Var("c")))

    def test_grouping_overrides(self):
        self.assertEqual(
            first_expr("(1 + 2) * 3;"),
            Binop("*", Binop("+", Num(1), Num(2)), Num(3)))

    def test_unary(self):
        self.assertEqual(first_expr("-x;"), Unop("-", Var("x")))
        self.assertEqual(first_expr("!x;"), Unop("!", Var("x")))
        self.assertEqual(first_expr("--x;"), Unop("-", Unop("-", Var("x"))))
        # 一元比 * 紧:-x * y 是 (-x) * y
        self.assertEqual(
            first_expr("-x * y;"),
            Binop("*", Unop("-", Var("x")), Var("y")))


class CallTests(unittest.TestCase):
    def test_call_chain(self):
        self.assertEqual(
            first_expr("f(1)(2, 3);"),
            Call(Call(Var("f"), [Num(1)]), [Num(2), Num(3)]))

    def test_call_binds_tighter_than_unary(self):
        self.assertEqual(
            first_expr("-f();"),
            Unop("-", Call(Var("f"), [])))

    def test_call_binds_tighter_than_factor(self):
        self.assertEqual(
            first_expr("f(1) * g(2);"),
            Binop("*", Call(Var("f"), [Num(1)]), Call(Var("g"), [Num(2)])))

    def test_fun_expression(self):
        self.assertEqual(
            parse_program("var f = fun(a, b) { return a; };"),
            [VarDecl("f", FunExpr(["a", "b"], [Return(Var("a"))]))])


class StatementTests(unittest.TestCase):
    def test_var_decl_with_and_without_init(self):
        self.assertEqual(parse_program("var x;"), [VarDecl("x", NIL)])
        self.assertEqual(parse_program("var x = 1;"), [VarDecl("x", Num(1))])

    def test_fun_decl(self):
        stmts = parse_program("fun add(a, b) { return a + b; }")
        self.assertEqual(stmts, [
            FunDecl("add", FunExpr(["a", "b"],
                                   [Return(Binop("+", Var("a"), Var("b")))])),
        ])

    def test_if_else_and_dangling_else(self):
        stmts = parse_program("if (a) if (b) x; else y;")
        # else 归属最近的 if
        self.assertEqual(stmts, [
            If(Var("a"), If(Var("b"), ExprStmt(Var("x")),
                            ExprStmt(Var("y"))), None),
        ])

    def test_while_and_block(self):
        stmts = parse_program("while (i < 10) { i = i + 1; }")
        self.assertEqual(stmts, [
            While(Binop("<", Var("i"), Num(10)),
                  Block([ExprStmt(Assign("i", Binop("+", Var("i"), Num(1))))])),
        ])

    def test_for_all_clauses(self):
        stmts = parse_program("for (var i = 0; i < n; i = i + 1) print(i);")
        self.assertEqual(stmts, [
            For(VarDecl("i", Num(0)),
                Binop("<", Var("i"), Var("n")),
                Assign("i", Binop("+", Var("i"), Num(1))),
                ExprStmt(Call(Var("print"), [Var("i")]))),
        ])

    def test_for_empty_clauses(self):
        self.assertEqual(parse_program("for (;;) break;")[:1], [
            For(None, None, None, ExprStmt(Var("break"))),
        ])

    def test_return_with_and_without_value(self):
        self.assertEqual(parse_program("fun f() { return; }"),
                         [FunDecl("f", FunExpr([], [Return(None)]))])

    def test_literals(self):
        self.assertEqual(first_expr('"hi";'), Str("hi"))
        self.assertEqual(first_expr("true;"), Bool(True))
        self.assertEqual(first_expr("nil;"), NIL)
        self.assertEqual(first_expr("3.14;"), Num(3.14))


class ParseErrorTests(unittest.TestCase):
    def assert_error(self, src, fragment):
        with self.assertRaises(TinyError) as ctx:
            parse_program(src)
        self.assertIn(fragment, ctx.exception.message)

    def test_missing_semicolon(self):
        self.assert_error("var x = 1", "';'")

    def test_missing_paren(self):
        self.assert_error("if x { }", "'('")

    def test_missing_close_brace(self):
        self.assert_error("fun f() { var x = 1;", "'}'")

    def test_assign_to_literal(self):
        self.assert_error("1 = 2;", "非法赋值目标")

    def test_duplicate_parameter(self):
        self.assert_error("fun f(a, a) { }", "重复的参数名")

    def test_unexpected_token(self):
        self.assert_error("var = 1;", "变量名")

    def test_error_has_position(self):
        with self.assertRaises(TinyError) as ctx:
            parse_program("var ok = 1;\nvar = 2;")
        self.assertEqual((ctx.exception.line, ctx.exception.col), (2, 5))


if __name__ == "__main__":
    unittest.main()
