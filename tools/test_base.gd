# Minimal assertion base for headless unit tests.
# Test files extend this script and implement `func run() -> int` returning 0 on success.
extends RefCounted

var _failures: Array[String] = []
var _checks := 0
var _current := ""

func section(name: String) -> void:
	_current = name

func assert_true(cond: bool, msg: String = "expected true") -> void:
	_checks += 1
	if not cond:
		_failures.append("[%s] %s" % [_current, msg])

func assert_eq(actual: Variant, expected: Variant, msg: String = "values differ") -> void:
	_checks += 1
	if actual != expected:
		_failures.append("[%s] %s | expected=%s actual=%s" % [_current, msg, str(expected), str(actual)])

func assert_ne(actual: Variant, expected: Variant, msg: String = "values must differ") -> void:
	_checks += 1
	if actual == expected:
		_failures.append("[%s] %s | both=%s" % [_current, msg, str(actual)])

func assert_between(value: int, low: int, high: int, msg: String = "out of range") -> void:
	_checks += 1
	if value < low or value > high:
		_failures.append("[%s] %s | value=%d range=[%d,%d]" % [_current, msg, value, low, high])

## Call at the end of run(). Prints result and returns exit code.
func finish() -> int:
	if _failures.is_empty():
		print("PASS %s (%d checks)" % [get_script().resource_path.get_file(), _checks])
		return 0
	for f in _failures:
		printerr("FAIL %s" % f)
	print("FAILED %s (%d/%d checks failed)" % [get_script().resource_path.get_file(), _failures.size(), _checks])
	return 1
