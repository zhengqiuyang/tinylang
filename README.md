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

## 里程碑

- [x] **M1 词法分析器**:手写 scanner。双引号字符串(`\n \t \" \\` 转义)、
  行注释与块注释、int/float 数字、关键字表、所有运算符的最长匹配、
  行列号错误定位(15 个单测)。
- [ ] M2 Pratt 解析器 → AST(优先级、结合性、调用、函数表达式)
- [ ] M3 树求值器:词法作用域、闭包、if/while/for、return
- [ ] M4(可选)字节码 VM
