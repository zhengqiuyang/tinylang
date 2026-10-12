"""tinylang M1(词法分析)的单元测试:python test_lexer.py -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tinylang import TinyError, Token, TokenType, tokenize  # noqa: E402

T = TokenType


def types_of(src):
    return [t.type for t in tokenize(src)]


class LexerTests(unittest.TestCase):
    def test_simple_declaration(self):
        tokens = tokenize("var x = 1 + 2.5;")
        self.assertEqual([t.type for t in tokens],
                         [T.VAR, T.IDENT, T.ASSIGN, T.NUMBER, T.PLUS,
                          T.NUMBER, T.SEMICOLON, T.EOF])
        self.assertEqual(tokens[1].value, "x")
        self.assertEqual(tokens[3].value, 1)
        self.assertIsInstance(tokens[3].value, int)
        self.assertEqual(tokens[5].value, 2.5)
        self.assertIsInstance(tokens[5].value, float)

    def test_keywords_vs_identifiers(self):
        self.assertEqual(types_of("var variable vary"),
                         [T.VAR, T.IDENT, T.IDENT, T.EOF])
        self.assertEqual(types_of("true truex false"),
                         [T.TRUE, T.IDENT, T.FALSE, T.EOF])
        self.assertEqual(types_of("fun return if else while for nil"),
                         [T.FUN, T.RETURN, T.IF, T.ELSE, T.WHILE, T.FOR,
                          T.NIL, T.EOF])
        self.assertEqual(types_of("_private c99"),
                         [T.IDENT, T.IDENT, T.EOF])

    def test_string_escapes(self):
        tokens = tokenize(r'"a\tb\"c\\d\ne"')
        self.assertEqual(tokens[0].type, T.STRING)
        self.assertEqual(tokens[0].value, 'a\tb"c\\d\ne')

    def test_string_unterminated(self):
        with self.assertRaises(TinyError) as ctx:
            tokenize('"oops')
        self.assertIn("未闭合的字符串", ctx.exception.message)
        self.assertEqual((ctx.exception.line, ctx.exception.col), (1, 1))

    def test_string_cannot_span_lines(self):
        with self.assertRaises(TinyError):
            tokenize('"line1\nline2"')

    def test_bad_escape(self):
        with self.assertRaises(TinyError) as ctx:
            tokenize(r'"bad \q"')
        self.assertIn("非法转义", ctx.exception.message)

    def test_line_comment(self):
        self.assertEqual(
            types_of("var x = 1; // 忽略这一行 = + ( \n var y;"),
            [T.VAR, T.IDENT, T.ASSIGN, T.NUMBER, T.SEMICOLON,
             T.VAR, T.IDENT, T.SEMICOLON, T.EOF])

    def test_block_comment(self):
        tokens = tokenize("var a; /* 多行\n注释 { } */ var b;")
        self.assertEqual([t.type for t in tokens],
                         [T.VAR, T.IDENT, T.SEMICOLON, T.VAR, T.IDENT,
                          T.SEMICOLON, T.EOF])
        # 块注释跨行后行号正确推进
        self.assertEqual(tokens[3].line, 2)

    def test_block_comment_unterminated(self):
        with self.assertRaises(TinyError):
            tokenize("var a; /* 永不结束")

    def test_all_operators(self):
        src = "() {} , ; + - * / % < > = == != <= >= && || !"
        self.assertEqual(types_of(src), [
            T.LPAREN, T.RPAREN, T.LBRACE, T.RBRACE, T.COMMA, T.SEMICOLON,
            T.PLUS, T.MINUS, T.STAR, T.SLASH, T.PERCENT,
            T.LT, T.GT, T.ASSIGN, T.EQ, T.NEQ, T.LE, T.GE,
            T.AND, T.OR, T.BANG, T.EOF,
        ])

    def test_maximal_munch(self):
        # == 不会被扫成两个 =,< = 也不该粘成 <=
        self.assertEqual(types_of("=="), [T.EQ, T.EOF])
        self.assertEqual(types_of("< ="), [T.LT, T.ASSIGN, T.EOF])
        self.assertEqual(types_of("a<=b"), [T.IDENT, T.LE, T.IDENT, T.EOF])

    def test_position_tracking(self):
        tokens = tokenize("var x = 1;\nvar yy = x;")
        # tokens: VAR IDENT(x) ASSIGN NUM SEMI VAR IDENT(yy) ASSIGN IDENT(x) SEMI EOF
        self.assertEqual((tokens[1].value, tokens[1].line, tokens[1].col),
                         ("x", 1, 5))
        self.assertEqual((tokens[6].value, tokens[6].line, tokens[6].col),
                         ("yy", 2, 5))
        self.assertEqual((tokens[8].value, tokens[8].line, tokens[8].col),
                         ("x", 2, 10))

    def test_illegal_character(self):
        with self.assertRaises(TinyError) as ctx:
            tokenize("var £ = 1;")
        self.assertIn("非法字符", ctx.exception.message)

    def test_leading_dot_number_rejected(self):
        with self.assertRaises(TinyError):
            tokenize("x = .5;")

    def test_empty_and_whitespace_only(self):
        self.assertEqual(types_of(""), [T.EOF])
        self.assertEqual(types_of("  \n\t \n"), [T.EOF])


if __name__ == "__main__":
    unittest.main()
