"""tinylang M3(树求值器)的单元测试:python test_eval.py -v"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tinylang import TinyError, run_source  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def run(src):
    """执行源码,返回 print 输出的行列表。"""
    out = []
    run_source(src, output=out.append)
    return out


class ArithmeticTests(unittest.TestCase):
    def test_precedence_and_types(self):
        self.assertEqual(run("print(1 + 2 * 3);"), ["7"])
        self.assertEqual(run("print(10 / 4);"), ["2.5"])
        self.assertEqual(run("print(7 % 3);"), ["1"])
        self.assertEqual(run("print((1 + 2) * 3);"), ["9"])
        self.assertEqual(run("print(-5 + 2);"), ["-3"])

    def test_string_concat(self):
        self.assertEqual(run('print("foo" + "bar");'), ["foobar"])

    def test_concat_type_error(self):
        with self.assertRaises(TinyError) as ctx:
            run('print("a" + 1);')
        self.assertIn("不能相加", ctx.exception.message)

    def test_comparison_and_equality(self):
        self.assertEqual(run("print(1 < 2, 2 <= 2, 3 > 2, 3 >= 4);"),
                         ["true true true false"])
        self.assertEqual(run("print(nil == nil, nil != 1);"), ["true true"])
        # true 和 1 类型不同,不相等
        self.assertEqual(run("print(true == 1);"), ["false"])

    def test_logical_short_circuit(self):
        src = """
        var calls = 0;
        fun f() { calls = calls + 1; return true; }
        var a = false && f();
        var b = true || f();
        print(calls);
        """
        self.assertEqual(run(src), ["0"])

    def test_truthiness(self):
        # tinylang 规则:只有 nil 和 false 为假
        src = 'if (0) print("zero-truthy"); if ("") print("str-truthy");'
        self.assertEqual(run(src), ["zero-truthy", "str-truthy"])


class ScopeAndFunctionTests(unittest.TestCase):
    def test_block_shadowing(self):
        src = """
        var x = "outer";
        {
            var x = "inner";
            print(x);
        }
        print(x);
        """
        self.assertEqual(run(src), ["inner", "outer"])

    def test_closure_counter(self):
        src = """
        var make_counter = fun() {
            var count = 0;
            return fun() { count = count + 1; return count; };
        };
        var next = make_counter();
        print(next()); print(next()); print(next());
        """
        self.assertEqual(run(src), ["1", "2", "3"])

    def test_recursion_fibonacci(self):
        src = """
        fun fib(n) {
            if (n < 2) return n;
            return fib(n - 1) + fib(n - 2);
        }
        print(fib(20));
        """
        self.assertEqual(run(src), ["6765"])

    def test_first_class_functions(self):
        src = """
        fun apply(f, x) { return f(x); }
        fun double(n) { return n * 2; }
        print(apply(double, 21));
        """
        self.assertEqual(run(src), ["42"])

    def test_closure_captures_definition_env_not_caller(self):
        src = """
        var n = 10;
        fun outer() {
            var n = 1;
            return fun() { return n; };
        }
        var f = outer();
        print(f());
        """
        self.assertEqual(run(src), ["1"])

    def test_default_return_is_nil(self):
        self.assertEqual(run("fun f() {} print(f());"), ["nil"])

    def test_return_without_value(self):
        self.assertEqual(run("fun f() { return; } print(f());"), ["nil"])

    def test_while_and_for(self):
        src = """
        var s = 0;
        var i = 1;
        while (i <= 10) { s = s + i; i = i + 1; }
        print(s);
        var t = 0;
        for (var j = 1; j <= 10; j = j + 1) t = t + j;
        print(t);
        """
        self.assertEqual(run(src), ["55", "55"])

    def test_for_scope_is_isolated(self):
        src = """
        var i = 100;
        for (var i = 0; i < 3; i = i + 1) print(i);
        print(i);
        """
        self.assertEqual(run(src), ["0", "1", "2", "100"])


class NativeAndErrorTests(unittest.TestCase):
    def test_print_multiple_args(self):
        self.assertEqual(run('print("a", 1, true, nil);'),
                         ["a 1 true nil"])

    def test_len_and_clock(self):
        self.assertEqual(run('print(len("hello"));'), ["5"])
        out = run("var t = clock(); print(t > 0);")
        self.assertEqual(out, ["true"])

    def test_len_rejects_non_string(self):
        with self.assertRaises(TinyError):
            run("print(len(42));")

    def test_undefined_variable(self):
        with self.assertRaises(TinyError) as ctx:
            run("print(missing);")
        self.assertIn("未定义的变量", ctx.exception.message)

    def test_assign_undefined_variable(self):
        with self.assertRaises(TinyError):
            run("nope = 1;")

    def test_call_non_function(self):
        with self.assertRaises(TinyError) as ctx:
            run('var x = 1; x("arg");')
        self.assertIn("不可调用", ctx.exception.message)

    def test_wrong_arity(self):
        with self.assertRaises(TinyError) as ctx:
            run("fun f(a) { return a; } f(1, 2);")
        self.assertIn("参数", ctx.exception.message)

    def test_division_by_zero(self):
        with self.assertRaises(TinyError):
            run("print(1 / 0);")

    def test_top_level_return(self):
        with self.assertRaises(TinyError) as ctx:
            run("return 1;")
        self.assertIn("函数体外", ctx.exception.message)


class CliTests(unittest.TestCase):
    def test_run_script_file(self):
        script = """
        fun greet(name) { return "hi " + name; }
        print(greet("tinylang"));
        print(6 * 7);
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.ty")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            result = subprocess.run(
                [sys.executable, os.path.join(HERE, "tinylang.py"), path],
                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["hi tinylang", "42"])

    def test_script_error_reports_to_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.ty")
            with open(path, "w", encoding="utf-8") as f:
                f.write("print(oops);\n")
            result = subprocess.run(
                [sys.executable, os.path.join(HERE, "tinylang.py"), path],
                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn("未定义的变量", result.stderr)


if __name__ == "__main__":
    unittest.main()
