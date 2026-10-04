# Headless test runner. Usage:
#   godot --headless --path . --script res://tools/run_tests.gd
# Discovers res://tests/**/test_*.gd, instantiates each and calls run().
# Exits with code 1 if any test file fails.
extends SceneTree

func _initialize() -> void:
	var test_paths: Array[String] = []
	_collect("res://tests", test_paths)
	test_paths.sort()
	if test_paths.is_empty():
		printerr("No test files found under res://tests")
		quit(1)
		return
	var failed: Array[String] = []
	var passed := 0
	for p in test_paths:
		var script: GDScript = load(p)
		if script == null:
			failed.append(p + " (load error)")
			continue
		var instance: Object = script.new()
		if not instance.has_method("run"):
			failed.append(p + " (missing run())")
			continue
		var code: int = instance.call("run")
		if code != 0:
			failed.append(p)
		else:
			passed += 1
	print("---")
	print("Tests: %d passed, %d failed" % [passed, failed.size()])
	for f in failed:
		printerr("FAILED FILE: " + f)
	quit(0 if failed.is_empty() else 1)

func _collect(dir_path: String, out: Array[String]) -> void:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return
	dir.list_dir_begin()
	var name := dir.get_next()
	while name != "":
		if dir.current_is_dir() and not name.begins_with("."):
			_collect(dir_path + "/" + name, out)
		elif name.begins_with("test_") and name.ends_with(".gd"):
			out.append(dir_path + "/" + name)
		name = dir.get_next()
	dir.list_dir_end()
