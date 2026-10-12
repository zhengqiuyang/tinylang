# tinylang — 从零实现的一门小语言

[![CI](https://github.com/zhengqiuyang/tinylang/actions/workflows/ci.yml/badge.svg)](https://github.com/zhengqiuyang/tinylang/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-informational.svg)](./LICENSE)

用纯 Python 依次实现词法分析、Pratt 解析、树求值器——一门有词法作用域、
闭包、一等函数、完整控制流的小语言。全部手写,不依赖任何解析库。

## 目标语言长这样

```javascript
fun fib(n) {
  if (n < 2) return n;
  return fib(n - 1) + fib(n - 2);
}
print(fib(20));   // 6765

var make_counter = fun() {
  var count = 0;
  return fun() { count = count + 1; return count; };
};
var next = make_counter();
print(next()); print(next()); print(next());   // 1 2 3
```

## 运行

```bash
python tinylang.py demo.ty        # 执行脚本(树求值器)
python tinylang.py --vm demo.ty   # 执行脚本(字节码 VM)
python tinylang.py [--vm]         # REPL
```

## 里程碑

- [x] **M1 词法分析器**:手写 scanner。双引号字符串(`\n \t \" \\` 转义)、
  行注释与块注释、int/float 数字、关键字表、所有运算符的最长匹配、
  行列号错误定位(15 个单测)。
- [x] **M2 Pratt 解析器 → AST**:优先级爬升(绑定力表驱动)、左结合/右结合(赋值)、
  一元运算、后缀调用链 `f(1)(2)`、函数声明与 `fun` 函数表达式、if/while/for/return/
  块语句、悬垂 else 归最近 if、语法错误带行列号定位(26 个单测)。
- [x] **M3 树求值器**:环境链实现词法作用域与块级遮蔽、闭包捕获定义时环境、
  一等函数与匿名函数、递归、if/while/for、return 非局部退出、
  原生函数(print/len/clock)、类型检查与运行时错误、REPL(括号不闭合自动续行)、
  脚本 CLI(26 个单测,含子进程集成)。
- [x] **M4 字节码 VM**:两遍编译(名字解析与捕获分析 → wordcode 代码生成,
  与 CPython 同款"操作码 + 操作数字"布局)、基于栈的虚拟机与函数调用帧、
  cell + 捕获链实现的 **upvalue 闭包**(跨层捕获、双闭包共享变量、
  局部命名函数自递归)、短路跳转、`--vm` 开关。
  测试采用**双后端对拍**:同一批程序在树求值器与 VM 上输出逐行一致(14 个单测)。
  树求值器保留为默认后端与语义参照。

## 语义要点

- 真值规则:只有 `nil` 和 `false` 为假,`0` 与空串为真(同 Lox,异于 Python)。
- `+` 只允许数字相加或两个字符串拼接;比较运算只允许数字。
- `true == 1` 为 `false`(bool 与数字不相等,严格区分类型)。
- `/` 遵循 Python 语义(总是浮点);`%` 取模,除以零报运行时错误。
