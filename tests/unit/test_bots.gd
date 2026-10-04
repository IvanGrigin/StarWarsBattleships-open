# Unit tests for src/bots: RandomLegal contract and full-match determinism
# through the shared Playout driver (same code path as the console/batch tools).
extends "res://tools/test_base.gd"

const MatchEngine := preload("res://src/core/rules/match_engine.gd")
const Canonical := preload("res://src/core/serialization/canonical.gd")
const RngScript := preload("res://src/core/rng/rng.gd")
const RandomLegal := preload("res://src/bots/policies/random_legal.gd")
const Playout := preload("res://src/bots/playout.gd")

func run() -> int:
	# Same per-seat factory as console_match/batch_sim: seed_bot = match_seed*K + seat_index.
	var factory: Callable = func(seat: String, seat_index: int, match_seed: int) -> Variant:
		return RandomLegal.new(RngScript.new(Playout.bot_seed(match_seed, seat_index)))

	section("RandomLegal picks members of a synthetic legal list")
	var bot := RandomLegal.new(RngScript.new(20260913))
	var synthetic: Array = [
		{"type": "BeginActivation", "ship_instance_id": "s0"},
		{"type": "Move", "dir": 3},
		{"type": "RotateLeft"},
		{"type": "RotateRight"},
		{"type": "DeclareAttack", "target_ship_instance_id": "x0"},
		{"type": "EndActivation"},
	]
	var seen := {}
	for i in 200:
		var choice := bot.choose_action({}, synthetic)
		assert_true(synthetic.has(choice), "draw %d is a member of legal" % i)
		seen[Canonical.to_canonical(choice)] = true
	assert_eq(seen.size(), synthetic.size(), "all 6 variants sampled over 200 draws")

	section("RandomLegal picks members of real legal_actions (200 choices)")
	# Matches have different lengths per seed (heroes, ADR-016, reshuffle the
	# draft stream), so the 200 choices may span several fresh matches.
	var created := MatchEngine.create_match({"seed": 1, "round_limit": 60})
	assert_true(not created.has("error"), "match created for seed 1")
	var state: Dictionary = created["state"]
	var used := 0
	var bots_seed := 1
	while used < 200:
		while used < 200 and not MatchEngine.is_terminal(state):
			var legal := MatchEngine.legal_actions(state)
			assert_true(legal.size() > 0, "legal actions non-empty mid-match")
			var cmd := bot.choose_action(state, legal)
			assert_true(legal.has(cmd), "choice %d belongs to the engine legal list" % used)
			var res := MatchEngine.apply_command(state, cmd)
			assert_true(bool(res.get("ok", false)), "engine accepts the chosen command")
			if not bool(res.get("ok", false)):
				break
			state = res["state"]
			used += 1
		if used >= 200:
			break
		bots_seed += 1
		assert_between(bots_seed, 1, 10, "200 choices reached within 10 seeds")
		if bots_seed > 10:
			break
		state = MatchEngine.create_match({"seed": bots_seed, "round_limit": 60})["state"]
	assert_eq(used, 200, "made exactly 200 choices in real matches")

	section("determinism: same (match_seed, bot seeds) -> same hash and commands")
	for match_seed: int in [7, 8]:
		var first := Playout.play({"seed": match_seed, "round_limit": 60}, factory)
		var second := Playout.play({"seed": match_seed, "round_limit": 60}, factory)
		assert_true(not first.has("error"), "seed %d: first playout completed" % match_seed)
		assert_true(not second.has("error"), "seed %d: second playout completed" % match_seed)
		assert_eq(MatchEngine.state_hash(first["state"]), MatchEngine.state_hash(second["state"]),
				"seed %d: identical final state hash" % match_seed)
		assert_eq(Canonical.to_canonical(first["commands"]), Canonical.to_canonical(second["commands"]),
				"seed %d: identical command list" % match_seed)

	section("smoke: 3 full matches through the console code path all end")
	for match_seed: int in [1, 2, 3]:
		var res := Playout.play({"seed": match_seed, "round_limit": 60}, factory)
		assert_true(not res.has("error"), "seed %d: no playout error" % match_seed)
		assert_eq(String(res["state"].get("phase", "")), "ended", "seed %d: match ended" % match_seed)
		var winner: Variant = res["state"].get("winner")
		assert_true(winner == null or winner == "A" or winner == "B",
				"seed %d: winner is A/B/null" % match_seed)
	return finish()
