"""tinylang M4(字节码 VM)的单元测试:python test_vm.py -v

核心思路是"双后端对拍":同一批程序分别用树求值器(run_source)
和字节码 VM(run_source_vm)执行,输出必须逐行一致。
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tinylang import TinyError, run_source, run_source_vm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def tree_run(src):
    out = []
    run_source(src, output=out.append)
    return out


def vm_run(src):
    out = []
    run_source_vm(src, output=out.append)
    return out


PARITY_PROGRAMS = [
    # 算术与优先级
    'print(1 + 2 * 3 - 4 / 2); print(7 % 3); print((1 + 2) * 3);',
    # 字符串与转义
    'print("foo" + "bar"); print(len("hello"));',
    # 比较与相等语义
    'print(1 < 2, 2 <= 2, true == 1, nil == nil, "a" != "b");',
    # 逻辑与短路
    """
    var calls = 0;
    fun f() { calls = calls + 1; return true; }
    var a = false && f();
    var b = true || f();
    print(calls, a == false, b == true);
    """,
    # 真值规则(0 与空串为真)
    'if (0) print("zero"); if ("") print("empty"); if (nil) print("no");',
    # 词法作用域与遮蔽
    """
    var x = "outer";
    { var x = "inner"; print(x); }
    print(x);
    """,
    # 闭包计数器(共享捕获变量)
    """
    var mk = fun() {
        var count = 0;
        return fun() { count = count + 1; return count; };
    };
    var n = mk();
    print(n()); print(n()); print(n());
    """,
    # 两个闭包共享同一个 cell
    """
    fun pair() {
        var v = 0;
        var inc = fun() { v = v + 1; return v; };
        var get = fun() { return v; };
        print(inc()); print(get());
        print(inc()); print(get());
    }
    pair();
    """,
    # 递归
    """
    fun fib(n) { if (n < 2) return n; return fib(n-1) + fib(n-2); }
    print(fib(15));
    """,
    # 局部命名函数的递归(cell 自捕获)
    """
    fun outer() {
        fun fact(n) { if (n <= 1) return 1; return n * fact(n - 1); }
        return fact(5);
    }
    print(outer());
    """,
    # 三层嵌套的跨层捕获(upvalue 链)
    """
    fun level1() {
        var x = 10;
        fun level2() {
            fun level3() { x = x + 1; return x; }
            return level3;
        }
        return level2;
    }
    var l3 = level1()();
    print(l3()); print(l3());
    """,
    # 一等函数与调用链
    """
    fun apply(f, x) { return f(x); }
    fun double(n) { return n * 2; }
    print(apply(double, 21));
    var add = fun(a) { return fun(b) { return a + b; }; };
    print(add(40)(2));
    """,
    # 控制流
    """
    var s = 0;
    var i = 1;
    while (i <= 10) { s = s + i; i = i + 1; }
    print(s);
    var t = 0;
    for (var j = 1; j <= 100; j = j + 1) t = t + j;
    print(t);
    for (var k = 0; k < 3; k = k + 1) print(k);
    """,
    # for 变量作用域隔离
    """
    var i = 100;
    for (var i = 0; i < 3; i = i + 1) print(i);
    print(i);
    """,
    # return 变体与默认 nil
    """
    fun nothing() {}
    fun early(n) { if (n > 0) return "pos"; return "nonpos"; }
    fun bare() { return; }
    print(nothing()); print(early(1), early(0)); print(bare());
    """,
    # 多参数 print
    'print("a", 1, true, nil, 2.5);',
]


class ParityTests(unittest.TestCase):
    def test_tree_and_vm_agree(self):
        for src in PARITY_PROGRAMS:
            with self.subTest(src=src.strip()[:60]):
                expected = tree_run(src)
                self.assertEqual(vm_run(src), expected)

    def test_programs_produce_output(self):
        # 防御:对拍程序本身必须有输出,避免"双双空输出"假阳性
        for src in PARITY_PROGRAMS:
            self.assertTrue(tree_run(src), src)


class VmErrorParityTests(unittest.TestCase):
    def assert_vm_error(self, src, fragment):
        with self.assertRaises(TinyError) as ctx:
            vm_run(src)
        self.assertIn(fragment, str(ctx.exception))

    def test_undefined_variable(self):
        self.assert_vm_error("print(missing);", "未定义的变量")

    def test_assign_undefined_variable(self):
        self.assert_vm_error("nope = 1;", "未定义的变量")

    def test_call_non_function(self):
        self.assert_vm_error('var x = 1; x("arg");', "不可调用")

    def test_wrong_arity(self):
        self.assert_vm_error("fun f(a) { return a; } f(1, 2);", "参数")

    def test_division_by_zero(self):
        self.assert_vm_error("print(1 / 0);", "除以零")

    def test_string_plus_number(self):
        self.assert_vm_error('print("a" + 1);', "不能相加")

    def test_unary_minus_on_string(self):
        self.assert_vm_error('print(-"x");', "一元")

    def test_len_on_number(self):
        self.assert_vm_error("print(len(42));", "len 只接受字符串")

    def test_top_level_return_is_compile_error(self):
        self.assert_vm_error("return 1;", "函数体外")

    def test_native_arity(self):
        self.assert_vm_error("print(len());", "参数")


class CliTests(unittest.TestCase):
    def test_vm_flag_runs_script(self):
        script = """
        fun fib(n) { if (n < 2) return n; return fib(n-1) + fib(n-2); }
        print(fib(10));
        var mk = fun() { var c = 0; return fun() { c = c + 1; return c; }; };
        var n = mk();
        print(n()); print(n());
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.ty")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            result = subprocess.run(
                [sys.executable, os.path.join(HERE, "tinylang.py"), "--vm", path],
                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["55", "1", "2"])

    def test_vm_script_error_to_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.ty")
            with open(path, "w", encoding="utf-8") as f:
                f.write("print(oops);\n")
            result = subprocess.run(
                [sys.executable, os.path.join(HERE, "tinylang.py"), "--vm", path],
                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn("未定义的变量", result.stderr)


if __name__ == "__main__":
    unittest.main()
