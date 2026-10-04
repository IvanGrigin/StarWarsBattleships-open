# Engine tests: heroes v3.3 (ADR-016) — hero draft, state v3 extension
# (heroes/objects/pending_reaction), reaction windows (luke/obi_wan), active
# abilities (vader/anakin/han/jango/boba), phasma passive, mines/bombs,
# errors (§6), legal_actions filtering (seeded_bots_skip_heroes) and the
# rng_counter == dice.size() invariant across effect dice.
extends "res://tools/test_base.gd"

const MatchEngine := preload("res://src/core/rules/match_engine.gd")
const CardStore := preload("res://src/core/data/card_store.gd")
const Canonical := preload("res://src/core/serialization/canonical.gd")
const RngScript := preload("res://src/core/rng/rng.gd")
const RandomLegal := preload("res://src/bots/policies/random_legal.gd")
const Playout := preload("res://src/bots/playout.gd")

# Parking cells for ships excluded from a scenario (all inside the radius-3
# board, ADR-015; none adjacent to the (0,0)/(0,-1) duel cells).
const PARKS: Array = [[2, -2], [-2, 2], [2, 0], [-2, 0]]


func _seat_ships(state: Dictionary, seat: String) -> Array:
	var out: Array = []
	for s: Dictionary in state.get("ships", []):
		if String(s.get("seat", "")) == seat:
			out.append(s)
	return out


func _by_id(state: Dictionary, instance_id: String) -> Dictionary:
	for s: Dictionary in state.get("ships", []):
		if String(s.get("id", "")) == instance_id:
			return s
	return {}


## First ship of `seat` whose type has no enabled special abilities (plain
## combat pipeline: no transform/revive/reroll/lucky-shot noise).
func _plain_ship(state: Dictionary, seat: String) -> Dictionary:
	var defs := CardStore.ships_ref()
	for s: Dictionary in state.get("ships", []):
		if String(s.get("seat", "")) != seat:
			continue
		var has_enabled := false
		for a: Dictionary in defs.get(String(s["type_id"]), {}).get("abilities", []):
			if bool(a.get("enabled", false)):
				has_enabled = true
				break
		if not has_enabled:
			return s
	return {}


## Parks every ship except the keepers so the test owns the board picture.
func _isolate(state: Dictionary, keep: Array) -> void:
	var park_index := 0
	for s: Dictionary in state.get("ships", []):
		if keep.has(String(s["id"])):
			continue
		var park: Array = PARKS[park_index % PARKS.size()]
		s["q"] = int(park[0])
		s["r"] = int(park[1])
		park_index += 1


## Replaces the drafted heroes with an explicit test-owned assignment.
func _set_heroes(state: Dictionary, a_hero: String, a_uses: int, b_hero: String,
		b_uses: int) -> void:
	state["heroes"] = {
		"A1": {"hero_id": a_hero, "uses_left": a_uses},
		"B1": {"hero_id": b_hero, "uses_left": b_uses},
	}


## Standard duel setup: plain A1 attacker at (0,0) facing 0, plain B1 defender
## at (0,-1) facing 0, everyone else parked. no_skip=false keeps the default
## seeded_bots_skip_heroes=true bot-parity mode. Returns {} when the seed has
## no plain duelists.
func _duel(seed_value: int, no_skip: bool = true) -> Dictionary:
	var created := MatchEngine.create_match({
		"seed": seed_value,
		"seeded_bots_skip_heroes": not no_skip,
	})
	if created.has("error"):
		return {}
	var state: Dictionary = created["state"]
	var attacker := _plain_ship(state, "A1")
	var defender := _plain_ship(state, "B1")
	if attacker.is_empty() or defender.is_empty():
		return {}
	_isolate(state, [String(attacker["id"]), String(defender["id"])])
	attacker["q"] = 0
	attacker["r"] = 0
	attacker["facing"] = 0
	attacker["hp"] = 20
	attacker["shield"] = 0
	defender["q"] = 0
	defender["r"] = -1
	defender["facing"] = 0
	defender["hp"] = 20
	defender["shield"] = 0
	return {"state": state, "attacker": attacker, "defender": defender,
			"seed": seed_value}


## Deterministic seed scan for a usable duel.
func _find_duel(start_seed: int, no_skip: bool = true) -> Dictionary:
	for seed_value in range(start_seed, start_seed + 400):
		var duel := _duel(seed_value, no_skip)
		if not duel.is_empty():
			return duel
	return {}


func _begin_and_attack(state: Dictionary, attacker: Dictionary,
		defender: Dictionary) -> Dictionary:
	var begin := MatchEngine.apply_command(state,
			{"type": "BeginActivation", "ship_instance_id": String(attacker["id"])})
	assert_true(bool(begin.get("ok", false)), "begin attacker activation")
	if not bool(begin.get("ok", false)):
		return begin
	return MatchEngine.apply_command(begin["state"],
			{"type": "DeclareAttack", "target_ship_instance_id": String(defender["id"])})


func _first_event(events: Array, type_name: String) -> Dictionary:
	for e: Dictionary in events:
		if String(e["type"]) == type_name:
			return e
	return {}


func _count_event(events: Array, type_name: String) -> int:
	var n := 0
	for e: Dictionary in events:
		if String(e["type"]) == type_name:
			n += 1
	return n


func run() -> int:
	var hero_cards := CardStore.heroes()

	# ------------------------------------------------------------- data load
	section("card_store heroes(): 8 cards with abilities and uses")
	assert_eq(hero_cards.size(), 8, "8 hero cards loaded")
	var hero_ids: Array = hero_cards.keys()
	hero_ids.sort()
	assert_eq(hero_ids, ["anakin", "boba_fett", "darth_vader", "han_solo", "jango_fett",
			"luke", "obi_wan", "phasma"], "hero ids sorted")
	for hero_id: Variant in hero_ids:
		var card: Dictionary = hero_cards[hero_id]
		assert_true(card.has("display_name") and not String(card["display_name"]).is_empty(),
				"hero %s has a display name" % hero_id)
		assert_true(card.has("ability"), "hero %s has an ability" % hero_id)
	assert_eq(int(hero_cards["luke"]["ability"]["uses_per_match"]), 1, "luke 1 use")
	assert_eq(int(hero_cards["obi_wan"]["ability"]["uses_per_match"]), 2, "obi_wan 2 uses")
	assert_eq(int(hero_cards["phasma"]["ability"]["uses_per_match"]), 0, "phasma passive, 0 uses")

	# ---------------------------------------------------------------- draft
	section("hero draft: distinct heroes per seat, deterministic, card uses")
	for seed_value: int in [1, 2, 3, 42, 777]:
		var created := MatchEngine.create_match({"seed": seed_value})
		var state: Dictionary = created["state"]
		var heroes_state: Dictionary = state["heroes"]
		assert_eq(heroes_state.size(), 2, "seed %d: both seats hold a hero" % seed_value)
		assert_ne(String(heroes_state["A1"]["hero_id"]), String(heroes_state["B1"]["hero_id"]),
				"seed %d: distinct heroes (pool shrinks)" % seed_value)
		for seat: String in ["A1", "B1"]:
			var hero: Dictionary = heroes_state[seat]
			var card: Dictionary = hero_cards[String(hero["hero_id"])]
			assert_eq(int(hero["uses_left"]), int(card["ability"]["uses_per_match"]),
					"seed %d seat %s: uses_left from the card" % [seed_value, seat])
		var again := MatchEngine.create_match({"seed": seed_value})
		assert_eq(MatchEngine.state_hash(again["state"]), MatchEngine.state_hash(state),
				"seed %d: hero draft is seed-deterministic" % seed_value)
	var pool_pairs := {}
	for seed_value in range(1, 41):
		var heroes_state: Dictionary = MatchEngine.create_match(
				{"seed": seed_value})["state"]["heroes"]
		assert_ne(String(heroes_state["A1"]["hero_id"]), String(heroes_state["B1"]["hero_id"]),
				"seed %d: no hero reuse inside a match" % seed_value)
		var pair := "%s+%s" % [heroes_state["A1"]["hero_id"], heroes_state["B1"]["hero_id"]]
		pool_pairs[pair] = true
	assert_true(pool_pairs.size() >= 4, "different seeds deal different hero pairs")

	section("event journal: HeroDrafted after the fleet draft, before placements")
	var evts: Array = MatchEngine.create_match({"seed": 42})["events"]
	var last_ship_drafted := -1
	var first_hero_drafted := -1
	var first_ship_placed := -1
	for i in evts.size():
		match String(evts[i]["type"]):
			"ShipDrafted":
				last_ship_drafted = i
			"HeroDrafted":
				if first_hero_drafted < 0:
					first_hero_drafted = i
			"ShipPlaced":
				if first_ship_placed < 0:
					first_ship_placed = i
	assert_true(last_ship_drafted < first_hero_drafted and
			first_hero_drafted < first_ship_placed,
			"ShipDrafted* -> HeroDrafted* -> ShipPlaced*")
	var hero_event := _first_event(evts, "HeroDrafted")
	assert_true(hero_event.has("seat") and hero_event.has("hero_id"), "HeroDrafted fields")

	# ------------------------------------------------------------ state v4
	section("state v4: heroes, objects, pending_reaction, bot-parity flag")
	var fresh: Dictionary = MatchEngine.create_match({"seed": 42})["state"]
	assert_eq(int(fresh["version"]), 4, "state version 4")
	assert_eq((fresh["objects"] as Array).size(), 0, "objects starts empty")
	assert_true(fresh["pending_reaction"] == null, "pending_reaction starts null")
	assert_eq(bool(fresh["seeded_bots_skip_heroes"]), true,
			"seeded_bots_skip_heroes defaults to true")
	var open_cfg: Dictionary = MatchEngine.create_match(
			{"seed": 42, "seeded_bots_skip_heroes": false})["state"]
	assert_eq(bool(open_cfg["seeded_bots_skip_heroes"]), false,
			"seeded_bots_skip_heroes=false is taken from the config")

	section("legal_actions hides hero commands when seeded_bots_skip_heroes=true")
	var filtered := _find_duel(11, false)
	assert_true(not filtered.is_empty(), "filtered duel built")
	if filtered.is_empty():
		return finish()
	var stf: Dictionary = filtered["state"]
	_set_heroes(stf, "darth_vader", 1, "han_solo", 1)
	var begun_f := MatchEngine.apply_command(stf,
			{"type": "BeginActivation", "ship_instance_id": String(filtered["attacker"]["id"])})
	assert_true(bool(begun_f.get("ok", false)), "begin activation (skip=true)")
	var hero_legal := 0
	for action: Dictionary in MatchEngine.legal_actions(begun_f["state"]):
		if String(action["type"]) == "UseHeroAbility":
			hero_legal += 1
	assert_eq(hero_legal, 0, "no UseHeroAbility offered to seeded bots (skip=true)")

	# -------------------------------------------------------------- phasma
	section("phasma: attacker flat_bonus +1 (ADR-016 §3.1)")
	var base := _find_duel(1)
	assert_true(not base.is_empty(), "plain duel found for the phasma check")
	if not base.is_empty():
		var with_phasma := MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(base["state"]))
		_set_heroes(base["state"], "han_solo", 1, "han_solo", 1)
		_set_heroes(with_phasma, "phasma", 0, "han_solo", 1)
		var res_plain := _begin_and_attack(base["state"], base["attacker"], base["defender"])
		var res_phasma := _begin_and_attack(with_phasma,
				_by_id(with_phasma, String(base["attacker"]["id"])),
				_by_id(with_phasma, String(base["defender"]["id"])))
		assert_true(bool(res_plain.get("ok", false)) and bool(res_phasma.get("ok", false)),
				"both phasma-scenario attacks accepted")
		if bool(res_plain.get("ok", false)) and bool(res_phasma.get("ok", false)):
			var str_plain := {}
			var str_phasma := {}
			var def_plain := {}
			var def_phasma := {}
			for e: Dictionary in res_plain["events"]:
				if String(e["type"]) != "StrengthCalculated":
					continue
				if String(e["ship_instance_id"]) == String(base["attacker"]["id"]):
					str_plain = e
				else:
					def_plain = e
			for e: Dictionary in res_phasma["events"]:
				if String(e["type"]) != "StrengthCalculated":
					continue
				if String(e["ship_instance_id"]) == String(base["attacker"]["id"]):
					str_phasma = e
				else:
					def_phasma = e
			assert_eq(int(str_phasma["flat_bonus"]), 1, "phasma attacker flat_bonus 1")
			assert_eq(int(str_plain["flat_bonus"]), 0, "non-phasma attacker flat_bonus 0")
			assert_eq(int(str_phasma["total"]), int(str_plain["total"]) + 1,
					"phasma adds exactly +1 to the attacker total")
			assert_eq(int(def_phasma["total"]), int(def_plain["total"]),
					"phasma does not affect the defender side")
			assert_eq(Canonical.to_canonical(res_plain["state"]["dice"]),
					Canonical.to_canonical(res_phasma["state"]["dice"]),
					"phasma consumes no extra rng")

	# ---------------------------------------------------------------- luke
	section("luke: reaction window opens before the defender roll")
	var luke := _find_duel(23)
	assert_true(not luke.is_empty(), "luke duel built")
	if luke.is_empty():
		return finish()
	var stl: Dictionary = luke["state"]
	_set_heroes(stl, "luke", 1, "anakin", 1)
	var resl := _begin_and_attack(stl, luke["attacker"], luke["defender"])
	assert_true(bool(resl.get("ok", false)), "luke attack accepted")
	if not bool(resl.get("ok", false)):
		return finish()
	var evl: Array = resl["events"]
	var window := _first_event(evl, "ReactionWindow")
	assert_eq(String(window.get("kind", "")), "luke_flip", "luke window kind")
	assert_eq(String(window.get("seat", "")), "A1", "luke window seat A1")
	var pending: Dictionary = resl["state"]["pending_reaction"]
	assert_eq(String(pending["seat"]), "A1", "pending seat A1")
	assert_eq(String(pending["kind"]), "luke_flip", "pending kind")
	assert_eq((pending["faces"] as Array).size(), 2, "two attacker faces pending")
	assert_eq(String(resl["state"]["phase"]), "reaction", "phase reaction")
	assert_eq(_count_event(evl, "DieRolled"), 2, "only attacker dice rolled so far")
	assert_true(_first_event(evl, "StrengthCalculated").is_empty(),
			"no strength before the window closes")

	section("luke: window legal commands and the 1->6 ban")
	var legal_l := MatchEngine.legal_actions(resl["state"])
	var flips := 0
	var has_skip := false
	for action: Dictionary in legal_l:
		if String(action["type"]) == "SkipReaction":
			has_skip = true
		if String(action["type"]) == "UseHeroAbility":
			flips += 1
			assert_eq(String(action["ability_id"]), "precise_shot",
					"luke flip ability id from the hero card")
	assert_true(has_skip, "SkipReaction is legal in the window")
	assert_true(flips > 0, "flips are offered in the window")
	# Test-owned faces: die 0 shows a natural 1.
	resl["state"]["pending_reaction"]["faces"] = [1, 3]
	var hash_before := MatchEngine.state_hash(resl["state"])
	var banned := MatchEngine.apply_command(resl["state"],
			{"type": "UseHeroAbility", "ability_id": "precise_shot",
			"die_index": 0, "value": 6})
	assert_true(not bool(banned.get("ok", true)), "flip 1->6 is rejected")
	assert_eq(String(banned.get("error", "")), "bad_target", "1->6 error code")
	assert_eq(MatchEngine.state_hash(resl["state"]), hash_before,
			"rejected flip leaves the state untouched")
	var face_keep := MatchEngine.apply_command(resl["state"],
			{"type": "UseHeroAbility", "ability_id": "precise_shot",
			"die_index": 0, "value": 1})
	assert_true(not bool(face_keep.get("ok", true)), "flip to the same face is rejected")
	var bad_index := MatchEngine.apply_command(resl["state"],
			{"type": "UseHeroAbility", "ability_id": "precise_shot",
			"die_index": 5, "value": 2})
	assert_eq(String(bad_index.get("error", "")), "bad_target", "die_index out of range")

	section("luke: 1->5 flip resolves the combat with the new face")
	var flipped := MatchEngine.apply_command(resl["state"],
			{"type": "UseHeroAbility", "ability_id": "precise_shot",
			"die_index": 0, "value": 5})
	assert_true(bool(flipped.get("ok", false)), "flip 1->5 accepted")
	if bool(flipped.get("ok", false)):
		var evfl: Array = flipped["events"]
		assert_eq(String(_first_event(evfl, "AbilityUsed").get("hero_id", "")), "luke",
				"AbilityUsed by luke")
		var die_flip := _first_event(evfl, "DieFlipped")
		assert_eq(String(die_flip.get("role", "")), "attacker", "DieFlipped role attacker")
		assert_eq(int(die_flip.get("die_index", -1)), 0, "DieFlipped die_index")
		assert_eq(int(die_flip.get("from", -1)), 1, "DieFlipped from 1")
		assert_eq(int(die_flip.get("to", -1)), 5, "DieFlipped to 5")
		assert_eq(String(die_flip.get("by_hero", "")), "luke", "DieFlipped by_hero luke")
		var post: Dictionary = flipped["state"]
		assert_eq(String(post["phase"]), "activation", "window closed, phase activation")
		assert_true(post["pending_reaction"] == null, "pending_reaction cleared")
		assert_eq(int(post["heroes"]["A1"]["uses_left"]), 0, "luke use consumed")
		assert_eq(_count_event(evfl, "DieRolled"), 1, "defender die rolled on resume")
		var str_l := _first_event(evfl, "StrengthCalculated")
		assert_eq(str_l["dice"], [5, 3], "strength uses the flipped face")
		assert_eq(int(post["rng_counter"]), (post["dice"] as Array).size(),
				"flip consumes no rng (counter == dice log)")

	section("luke: SkipReaction keeps the use and the rolled faces")
	var skip_state := MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(stl))
	var res_skip := _begin_and_attack(skip_state,
			_by_id(skip_state, String(luke["attacker"]["id"])),
			_by_id(skip_state, String(luke["defender"]["id"])))
	assert_true(bool(res_skip.get("ok", false)), "skip-path attack accepted")
	if bool(res_skip.get("ok", false)):
		var rolled_faces: Array = res_skip["state"]["pending_reaction"]["faces"]
		var skipped := MatchEngine.apply_command(res_skip["state"], {"type": "SkipReaction"})
		assert_true(bool(skipped.get("ok", false)), "SkipReaction accepted")
		if bool(skipped.get("ok", false)):
			assert_eq(String(_first_event(skipped["events"], "ReactionSkipped").get("seat", "")),
					"A1", "ReactionSkipped by A1")
			assert_eq(int(skipped["state"]["heroes"]["A1"]["uses_left"]), 1,
					"skip does not consume the use")
			assert_eq(String(skipped["state"]["phase"]), "activation", "combat resolved")
			var str_s := _first_event(skipped["events"], "StrengthCalculated")
			assert_eq(str_s["dice"], rolled_faces, "skipped combat keeps the rolled faces")

	# -------------------------------------------------------------- obi_wan
	section("obi_wan: flips an attacker die, 6->1 forbidden, seat guard")
	var obi := _find_duel(29)
	assert_true(not obi.is_empty(), "obi_wan duel built")
	if obi.is_empty():
		return finish()
	var sto: Dictionary = obi["state"]
	_set_heroes(sto, "han_solo", 1, "obi_wan", 2)
	var reso := _begin_and_attack(sto, obi["attacker"], obi["defender"])
	assert_true(bool(reso.get("ok", false)), "obi_wan attack accepted")
	if not bool(reso.get("ok", false)):
		return finish()
	var window_o := _first_event(reso["events"], "ReactionWindow")
	assert_eq(String(window_o.get("kind", "")), "obi_wan_flip", "obi_wan window kind")
	assert_eq(String(window_o.get("seat", "")), "B1", "obi_wan window seat B1")
	assert_eq(String(reso["state"]["pending_reaction"]["seat"]), "B1", "pending seat B1")
	var wrong_seat := MatchEngine.apply_command(reso["state"],
			{"type": "SkipReaction", "seat": "A1"})
	assert_eq(String(wrong_seat.get("error", "")), "not_your_seat",
			"a non-window seat cannot act in the window")
	reso["state"]["pending_reaction"]["faces"] = [6, 2]
	var banned_o := MatchEngine.apply_command(reso["state"],
			{"type": "UseHeroAbility", "ability_id": "miss", "die_index": 0, "value": 1})
	assert_true(not bool(banned_o.get("ok", true)), "flip 6->1 is rejected")
	assert_eq(String(banned_o.get("error", "")), "bad_target", "6->1 error code")
	var flipped_o := MatchEngine.apply_command(reso["state"],
			{"type": "UseHeroAbility", "ability_id": "miss", "die_index": 0, "value": 3})
	assert_true(bool(flipped_o.get("ok", false)), "obi_wan flip 6->3 accepted")
	if bool(flipped_o.get("ok", false)):
		var die_flip_o := _first_event(flipped_o["events"], "DieFlipped")
		assert_eq(String(die_flip_o.get("by_hero", "")), "obi_wan", "flip by obi_wan")
		assert_eq(String(flipped_o["state"]["phase"]), "activation", "combat resolved")
		assert_eq(int(flipped_o["state"]["heroes"]["B1"]["uses_left"]), 1,
				"obi_wan 2 -> 1 uses")
		var str_o := _first_event(flipped_o["events"], "StrengthCalculated")
		assert_eq(str_o["dice"], [3, 2], "attacker strength uses the obi_wan-flipped die")

	section("luke + obi_wan: windows run sequentially (attacker first)")
	var both := _find_duel(31)
	assert_true(not both.is_empty(), "both-heroes duel built")
	if not both.is_empty():
		var stb: Dictionary = both["state"]
		_set_heroes(stb, "luke", 1, "obi_wan", 2)
		var resb := _begin_and_attack(stb, both["attacker"], both["defender"])
		assert_true(bool(resb.get("ok", false)), "both-heroes attack accepted")
		if bool(resb.get("ok", false)):
			assert_eq(String(resb["state"]["pending_reaction"]["kind"]), "luke_flip",
					"attacker window first")
			var skipb := MatchEngine.apply_command(resb["state"], {"type": "SkipReaction"})
			assert_true(bool(skipb.get("ok", false)), "luke skip accepted")
			if bool(skipb.get("ok", false)):
				var windows_b: Array = []
				for e: Dictionary in skipb["events"]:
					if String(e["type"]) == "ReactionWindow":
						windows_b.append(e)
				assert_eq(windows_b.size(), 1, "the obi_wan window opened in the same apply")
				assert_eq(String(windows_b[0]["kind"]), "obi_wan_flip", "second window kind")
				assert_eq(String(windows_b[0]["seat"]), "B1", "second window seat")
				assert_eq(String(skipb["state"]["phase"]), "reaction", "still in reaction")
				assert_eq(String(skipb["state"]["pending_reaction"]["seat"]), "B1",
						"pending moved to the defender")
				var skipb2 := MatchEngine.apply_command(skipb["state"], {"type": "SkipReaction"})
				assert_true(bool(skipb2.get("ok", false)), "obi_wan skip accepted")
				assert_eq(String(skipb2["state"]["phase"]), "activation", "combat done")
				assert_eq(_count_event(skipb2["events"], "DieRolled"), 1,
						"defender rolled after both windows")

	section("windows never open without luke/obi_wan; auto-skip in bot mode")
	var plain_duel := _find_duel(35)
	assert_true(not plain_duel.is_empty(), "plain duel built")
	if not plain_duel.is_empty():
		_set_heroes(plain_duel["state"], "anakin", 1, "jango_fett", 1)
		var resp := _begin_and_attack(plain_duel["state"], plain_duel["attacker"],
				plain_duel["defender"])
		assert_true(bool(resp.get("ok", false)), "no-window attack accepted")
		assert_true(_first_event(resp["events"], "ReactionWindow").is_empty(),
				"no window without the reaction heroes")
		assert_eq(String(resp["state"]["phase"]), "activation", "single-apply combat")
	var bot_duel := _find_duel(23, false)
	assert_true(not bot_duel.is_empty(), "bot-mode duel built")
	if not bot_duel.is_empty():
		_set_heroes(bot_duel["state"], "luke", 1, "obi_wan", 2)
		var resz := _begin_and_attack(bot_duel["state"], bot_duel["attacker"],
				bot_duel["defender"])
		assert_true(bool(resz.get("ok", false)), "bot-mode attack accepted")
		if bool(resz.get("ok", false)):
			var evz: Array = resz["events"]
			assert_eq(_count_event(evz, "ReactionWindow"), 2, "both windows announced")
			assert_eq(_count_event(evz, "ReactionSkipped"), 2, "both windows auto-skipped")
			assert_eq(String(resz["state"]["phase"]), "activation", "no pause in bot mode")
			assert_true(resz["state"]["pending_reaction"] == null, "no pending in bot mode")
			assert_eq(int(resz["state"]["heroes"]["A1"]["uses_left"]), 1,
					"auto-skip consumes no uses")

	# --------------------------------------------------------------- vader
	section("vader: force_attack at distance exactly 2")
	var vader := _find_duel(37)
	assert_true(not vader.is_empty(), "vader duel built")
	if vader.is_empty():
		return finish()
	var stv: Dictionary = vader["state"]
	_set_heroes(stv, "darth_vader", 1, "han_solo", 1)
	# Only the tuned target may stay alive on team B: every park cell sits at
	# distance 2 from (0,0) and would otherwise also be offered.
	for s: Dictionary in _seat_ships(stv, "B1"):
		if String(s["id"]) != String(vader["defender"]["id"]):
			s["alive"] = false
	var target: Dictionary = vader["defender"]
	target["q"] = 0
	target["r"] = -2 # distance 2 from (0,0), straight ray north
	var beginv := MatchEngine.apply_command(stv,
			{"type": "BeginActivation", "ship_instance_id": String(vader["attacker"]["id"])})
	assert_true(bool(beginv.get("ok", false)), "vader begins activation")
	var vader_offers := 0
	for action: Dictionary in MatchEngine.legal_actions(beginv["state"]):
		if String(action["type"]) == "UseHeroAbility" \
				and String(action.get("ability_id", "")) == "force_attack":
			vader_offers += 1
	assert_eq(vader_offers, 1, "force_attack offered for the distance-2 enemy")
	var resv := MatchEngine.apply_command(beginv["state"],
			{"type": "UseHeroAbility", "ability_id": "force_attack",
			"target_ship_instance_id": String(target["id"])})
	assert_true(bool(resv.get("ok", false)), "force_attack accepted at distance 2")
	if not bool(resv.get("ok", false)):
		return finish()
	var evv: Array = resv["events"]
	var used_v := _first_event(evv, "AbilityUsed")
	assert_eq(String(used_v.get("hero_id", "")), "darth_vader", "AbilityUsed by vader")
	assert_eq(String(used_v.get("ability_id", "")), "force_attack", "force_attack id")
	assert_true(not _first_event(evv, "AttackDeclared").is_empty(),
			"full regular combat resolved")
	var str_v := _first_event(evv, "StrengthCalculated")
	assert_eq(int(str_v["range_penalty"]), 0, "force_attack has no range penalty")
	assert_eq(int(str_v["sector_index"]), 0, "sectors follow the ray")
	assert_eq(int(resv["state"]["heroes"]["A1"]["uses_left"]), 0, "vader use consumed")
	assert_eq(bool(_by_id(resv["state"], String(vader["attacker"]["id"]))["attack_used"]),
			true, "force_attack counts as the activation attack")
	var dmg_v := _first_event(evv, "DamageApplied")
	assert_true(not dmg_v.is_empty(), "the distance-2 combat dealt damage")
	assert_eq(String(dmg_v.get("target_id", "")), String(target["id"]),
			"damage lands on the distance-2 target")
	var second := MatchEngine.apply_command(resv["state"],
			{"type": "UseHeroAbility", "ability_id": "force_attack",
			"target_ship_instance_id": String(target["id"])})
	assert_true(not bool(second.get("ok", true)), "second force_attack rejected")
	assert_eq(String(second.get("error", "")), "hero_no_uses", "hero_no_uses code")

	section("vader: not_in_range at distance 1 and 3, attack_used and hero gates")
	for dist in [1, 3]:
		var stv2: Dictionary = MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(stv))
		var tgt2 := _by_id(stv2, String(vader["defender"]["id"]))
		tgt2["q"] = 0
		tgt2["r"] = -dist
		var begin2 := MatchEngine.apply_command(stv2,
				{"type": "BeginActivation", "ship_instance_id": String(vader["attacker"]["id"])})
		assert_true(bool(begin2.get("ok", false)), "vader begins (dist %d)" % dist)
		var res2 := MatchEngine.apply_command(begin2["state"],
				{"type": "UseHeroAbility", "ability_id": "force_attack",
				"target_ship_instance_id": String(tgt2["id"])})
		assert_true(not bool(res2.get("ok", true)), "distance %d rejected" % dist)
		assert_eq(String(res2.get("error", "")), "not_in_range", "distance %d code" % dist)
	var stv3: Dictionary = MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(stv))
	_by_id(stv3, String(vader["attacker"]["id"]))["attack_used"] = true
	var begin3 := MatchEngine.apply_command(stv3,
			{"type": "BeginActivation", "ship_instance_id": String(vader["attacker"]["id"])})
	var res3 := MatchEngine.apply_command(begin3["state"],
			{"type": "UseHeroAbility", "ability_id": "force_attack",
			"target_ship_instance_id": String(vader["defender"]["id"])})
	assert_true(not bool(res3.get("ok", true)), "force_attack after a spent attack rejected")
	assert_eq(String(res3.get("error", "")), "attack_used", "attack_used gate")
	var res4 := MatchEngine.apply_command(begin3["state"],
			{"type": "UseHeroAbility", "ability_id": "hyperjump", "q": 0, "r": 0})
	assert_eq(String(res4.get("error", "")), "not_your_hero",
			"an ability the seat's hero does not own is not_your_hero")
	# Dead/distant attacker-ship gates: no active ship at all.
	var res5 := MatchEngine.apply_command(stv,
			{"type": "UseHeroAbility", "ability_id": "force_attack",
			"target_ship_instance_id": String(vader["defender"]["id"])})
	assert_eq(String(res5.get("error", "")), "bad_phase_for_ability",
			"ability without an active ship rejected")

	# -------------------------------------------------------------- anakin
	section("anakin: force_push any ship, facing kept, occupied/out_of_board/bad dir")
	var anakin := _find_duel(41)
	assert_true(not anakin.is_empty(), "anakin duel built")
	if anakin.is_empty():
		return finish()
	var sta: Dictionary = anakin["state"]
	_set_heroes(sta, "anakin", 1, "han_solo", 1)
	var mate := {}
	for s: Dictionary in _seat_ships(sta, "A1"):
		if String(s["id"]) != String(anakin["attacker"]["id"]):
			mate = s
			break
	mate["q"] = 3
	mate["r"] = 0 # edge cell: dir 2 (SE) from here leaves the board
	mate["facing"] = 3
	var begina := MatchEngine.apply_command(sta,
			{"type": "BeginActivation", "ship_instance_id": String(anakin["attacker"]["id"])})
	assert_true(bool(begina.get("ok", false)), "anakin begins activation")
	var bad_dir := MatchEngine.apply_command(begina["state"],
			{"type": "UseHeroAbility", "ability_id": "force_push",
			"ship_instance_id": String(mate["id"]), "dir": 9})
	assert_eq(String(bad_dir.get("error", "")), "bad_direction", "bad_direction code")
	var out_edge := MatchEngine.apply_command(begina["state"],
			{"type": "UseHeroAbility", "ability_id": "force_push",
			"ship_instance_id": String(mate["id"]), "dir": 2}) # (3,0)+(1,0)=(4,0)
	assert_eq(String(out_edge.get("error", "")), "out_of_board", "out_of_board code")
	var push_blocked := MatchEngine.apply_command(begina["state"],
			{"type": "UseHeroAbility", "ability_id": "force_push",
			"ship_instance_id": String(anakin["defender"]["id"]), "dir": 3}) # (0,-1)->(0,0): attacker
	assert_eq(String(push_blocked.get("error", "")), "occupied_cell", "occupied_cell code")
	var no_target := MatchEngine.apply_command(begina["state"],
			{"type": "UseHeroAbility", "ability_id": "force_push",
			"ship_instance_id": "no_such_ship", "dir": 0})
	assert_eq(String(no_target.get("error", "")), "bad_target", "bad_target for an unknown ship")
	# Successful pushes: the own squadmate north (a park cell would be occupied),
	# then the enemy would follow — but the use is already spent.
	var push_mate := MatchEngine.apply_command(begina["state"],
			{"type": "UseHeroAbility", "ability_id": "force_push",
			"ship_instance_id": String(mate["id"]), "dir": 0}) # (3,0)->(3,-1)
	assert_true(bool(push_mate.get("ok", false)), "push own ship accepted")
	if bool(push_mate.get("ok", false)):
		var moved := _by_id(push_mate["state"], String(mate["id"]))
		assert_eq(int(moved["q"]), 3, "mate moved to q=3")
		assert_eq(int(moved["r"]), -1, "mate moved to r=-1")
		assert_eq(int(moved["facing"]), 3, "orientation preserved")
		assert_eq(_count_event(push_mate["events"], "ShipMoved"), 1, "ShipMoved emitted")
		assert_eq(int(push_mate["state"]["heroes"]["A1"]["uses_left"]), 0, "use consumed")
	var push_enemy := MatchEngine.apply_command(push_mate["state"],
			{"type": "UseHeroAbility", "ability_id": "force_push",
			"ship_instance_id": String(anakin["defender"]["id"]), "dir": 0}) # (0,-1)->(0,-2)
	assert_true(not bool(push_enemy.get("ok", true)), "second use in the match rejected")
	assert_eq(String(push_enemy.get("error", "")), "hero_no_uses", "hero_no_uses after the push")

	# ----------------------------------------------------------------- han
	section("han: hyperjump zeroes charges, too_close_to_enemy")
	var han := _find_duel(43)
	assert_true(not han.is_empty(), "han duel built")
	if han.is_empty():
		return finish()
	var sth: Dictionary = han["state"]
	_set_heroes(sth, "han_solo", 1, "han_solo", 1)
	_by_id(sth, String(han["attacker"]["id"]))["charges"] = 0
	var beginh := MatchEngine.apply_command(sth,
			{"type": "BeginActivation", "ship_instance_id": String(han["attacker"]["id"])})
	assert_true(bool(beginh.get("ok", false)), "han begins activation")
	var no_charge := MatchEngine.apply_command(beginh["state"],
			{"type": "UseHeroAbility", "ability_id": "hyperjump", "q": 0, "r": 2})
	assert_eq(String(no_charge.get("error", "")), "no_charges", "no_charges at 0 charges")
	var sth2: Dictionary = MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(sth))
	_by_id(sth2, String(han["attacker"]["id"]))["charges"] = 3
	var beginh2 := MatchEngine.apply_command(sth2,
			{"type": "BeginActivation", "ship_instance_id": String(han["attacker"]["id"])})
	# (0,-1) holds the living defender: (1,-1) neighbors it -> too close;
	# (0,2) is free and far from every parked ship.
	var too_close := MatchEngine.apply_command(beginh2["state"],
			{"type": "UseHeroAbility", "ability_id": "hyperjump", "q": 1, "r": -1})
	assert_eq(String(too_close.get("error", "")), "too_close_to_enemy",
			"cell neighboring an enemy rejected")
	var occupied := MatchEngine.apply_command(beginh2["state"],
			{"type": "UseHeroAbility", "ability_id": "hyperjump", "q": 0, "r": -1})
	assert_eq(String(occupied.get("error", "")), "occupied_cell", "occupied target cell")
	var out_board := MatchEngine.apply_command(beginh2["state"],
			{"type": "UseHeroAbility", "ability_id": "hyperjump", "q": 0, "r": 9})
	assert_eq(String(out_board.get("error", "")), "out_of_board", "off-board jump target")
	var jump := MatchEngine.apply_command(beginh2["state"],
			{"type": "UseHeroAbility", "ability_id": "hyperjump", "q": 0, "r": 2})
	assert_true(bool(jump.get("ok", false)), "hyperjump accepted")
	if bool(jump.get("ok", false)):
		var jumped := _by_id(jump["state"], String(han["attacker"]["id"]))
		assert_eq(int(jumped["q"]), 0, "jumped to q=0")
		assert_eq(int(jumped["r"]), 2, "jumped to r=2")
		assert_eq(int(jumped["charges"]), 0, "charges zeroed by the jump")
		assert_eq(int(jumped["spent_round"]), 3,
				"hyperjump zeroing counts as spent charges (v3.5, ADR-018)")
		assert_eq(int(jumped["facing"]), 0, "orientation preserved")
		assert_eq(String(_first_event(jump["events"], "ChargeSpent").get("reason", "")),
				"hyperjump", "ChargeSpent reason hyperjump")
		assert_eq(_count_event(jump["events"], "ShipMoved"), 1, "ShipMoved emitted")
		assert_eq(int(jump["state"]["heroes"]["A1"]["uses_left"]), 0, "use consumed")

	# --------------------------------------------------------------- jango
	section("jango: mine placement, no trigger on standing ships")
	var jango := _find_duel(47)
	assert_true(not jango.is_empty(), "jango duel built")
	if jango.is_empty():
		return finish()
	var stj: Dictionary = jango["state"]
	_set_heroes(stj, "jango_fett", 1, "jango_fett", 1)
	# Park a B1 ship right next to the mine cell: standing ships never trigger.
	var bystander: Dictionary = _seat_ships(stj, "B1")[1]
	bystander["q"] = 1
	bystander["r"] = 0
	var beginj := MatchEngine.apply_command(stj,
			{"type": "BeginActivation", "ship_instance_id": String(jango["attacker"]["id"])})
	assert_true(bool(beginj.get("ok", false)), "jango begins activation")
	var place := MatchEngine.apply_command(beginj["state"],
			{"type": "UseHeroAbility", "ability_id": "place_mine"})
	assert_true(bool(place.get("ok", false)), "place_mine accepted")
	if not bool(place.get("ok", false)):
		return finish()
	var placed := _first_event(place["events"], "MinePlaced")
	assert_eq(String(placed.get("seat", "")), "A1", "MinePlaced seat")
	assert_eq(int(placed.get("q", 99)), 0, "MinePlaced at the active ship cell q")
	assert_eq(int(placed.get("r", 99)), 0, "MinePlaced at the active ship cell r")
	assert_eq((place["state"]["objects"] as Array).size(), 1, "one object in state")
	assert_eq(String((place["state"]["objects"][0] as Dictionary)["kind"]), "mine",
			"object kind mine")
	assert_true(_first_event(place["events"], "MineTriggered").is_empty(),
			"standing ships (incl. the neighbor at (1,0)) do not trigger the mine")
	assert_eq(int(place["state"]["heroes"]["A1"]["uses_left"]), 0, "use consumed")

	section("jango: a ship entering a neighbor cell detonates the mine (1xd4)")
	var mine_state: Dictionary = place["state"]
	var victim := _by_id(mine_state, String(jango["defender"]["id"]))
	victim["q"] = 0
	victim["r"] = -2
	victim["facing"] = 0 # north: the step dir 3 to (0,-1), which neighbors the
	# mine at (0,0), is a BACKWARD move — mines trigger on entry from any
	# direction (v3.4 ADR-017; ADR-016 §5)
	victim["charges"] = 2
	victim["shield"] = 1
	victim["hp"] = 20
	var endj := MatchEngine.apply_command(mine_state, {"type": "EndActivation"})
	assert_true(bool(endj.get("ok", false)), "jango ends activation")
	var begin_victim := MatchEngine.apply_command(endj["state"],
			{"type": "BeginActivation", "ship_instance_id": String(victim["id"])})
	assert_true(bool(begin_victim.get("ok", false)), "victim begins activation")
	var move_victim := MatchEngine.apply_command(begin_victim["state"],
			{"type": "Move", "dir": 3})
	assert_true(bool(move_victim.get("ok", false)), "victim moves toward the mine (backward)")
	if not bool(move_victim.get("ok", false)):
		return finish()
	assert_eq(int(_by_id(move_victim["state"], String(victim["id"]))["facing"]), 0,
			"the entering move keeps facing")
	var evm: Array = move_victim["events"]
	var d4 := _first_event(evm, "DieRolled")
	assert_eq(int(d4.get("sides", 0)), 4, "mine rolls a d4")
	assert_eq(String(d4.get("role", "")), "effect", "effect dice role")
	var dmg := _first_event(evm, "DamageApplied")
	assert_eq(String(dmg.get("target_id", "")), String(victim["id"]),
			"mine damage hits the mover")
	assert_eq(int(dmg.get("shield_damage", -1)), mini(1, int(d4["value"])),
			"shield absorbs first")
	assert_eq(int(dmg.get("hull_damage", -1)), int(d4["value"]) - int(dmg["shield_damage"]),
			"hull takes the rest")
	var trig := _first_event(evm, "MineTriggered")
	assert_eq(String(trig.get("seat", "")), "A1", "MineTriggered owner seat")
	assert_eq(String(trig.get("target_id", "")), String(victim["id"]), "MineTriggered target")
	assert_eq(int(trig.get("r", 99)), 0, "MineTriggered at the mine cell")
	assert_true(not _first_event(evm, "ObjectRemoved").is_empty(), "ObjectRemoved after the blast")
	assert_eq((move_victim["state"]["objects"] as Array).size(), 0, "the mine is gone")
	assert_eq(int(move_victim["state"]["rng_counter"]),
			(move_victim["state"]["dice"] as Array).size(),
			"rng_counter == dice.size() after the effect die")

	section("jango: lethal mine blast runs the destruction pipeline")
	var stj3: Dictionary = MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(stj))
	var beginj3 := MatchEngine.apply_command(stj3,
			{"type": "BeginActivation", "ship_instance_id": String(jango["attacker"]["id"])})
	var place3 := MatchEngine.apply_command(beginj3["state"],
			{"type": "UseHeroAbility", "ability_id": "place_mine"})
	assert_true(bool(place3.get("ok", false)), "lethal-scenario mine placed")
	var mine_state3: Dictionary = place3["state"]
	var victim3 := _by_id(mine_state3, String(jango["defender"]["id"]))
	victim3["q"] = 0
	victim3["r"] = -2 # (0,-1) is adjacent to the mine at (0,0); the mine cell
	# itself is blocked by the mine owner, so the trigger is the neighbor entry
	victim3["facing"] = 0 # backward entry again (dir 3), any direction triggers
	victim3["charges"] = 2
	victim3["hp"] = 1
	victim3["shield"] = 0
	var endj3 := MatchEngine.apply_command(mine_state3, {"type": "EndActivation"})
	assert_true(bool(endj3.get("ok", false)), "jango ends activation (lethal scenario)")
	var begin_v3 := MatchEngine.apply_command(endj3["state"],
			{"type": "BeginActivation", "ship_instance_id": String(victim3["id"])})
	assert_true(bool(begin_v3.get("ok", false)), "victim begins next to the mine")
	var move_v3 := MatchEngine.apply_command(begin_v3["state"], {"type": "Move", "dir": 3})
	assert_true(bool(move_v3.get("ok", false)), "victim drives onto the mine")
	if bool(move_v3.get("ok", false)):
		var died := _first_event(move_v3["events"], "ShipDestroyed")
		var revived := _first_event(move_v3["events"], "ShipRevived")
		assert_true(not died.is_empty() or not revived.is_empty(),
				"hp<=0 resolved by the regular destruction pipeline")
		if not revived.is_empty():
			assert_eq(int(_by_id(move_v3["state"], String(victim3["id"]))["hp"]),
					int(revived["hp"]), "revive d4 hp stored")
			assert_eq(String(revived["ship_instance_id"]), String(victim3["id"]),
					"revive id")
		if not died.is_empty():
			assert_eq(bool(_by_id(move_v3["state"], String(victim3["id"]))["alive"]),
					false, "victim stays dead")
		assert_eq(int(move_v3["state"]["rng_counter"]),
				(move_v3["state"]["dice"] as Array).size(),
				"rng invariant after the destruction dice")

	section("jango: lateral entry detonates the mine too (any direction, v3.4)")
	var stj4: Dictionary = MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(stj))
	var beginj4 := MatchEngine.apply_command(stj4,
			{"type": "BeginActivation", "ship_instance_id": String(jango["attacker"]["id"])})
	assert_true(bool(beginj4.get("ok", false)), "jango begins activation (lateral scenario)")
	var place4 := MatchEngine.apply_command(beginj4["state"],
			{"type": "UseHeroAbility", "ability_id": "place_mine"})
	assert_true(bool(place4.get("ok", false)), "lateral-scenario mine placed")
	var mine_state4: Dictionary = place4["state"]
	var victim4 := _by_id(mine_state4, String(jango["defender"]["id"]))
	victim4["q"] = -1
	victim4["r"] = -1
	victim4["facing"] = 0
	victim4["charges"] = 1
	victim4["hp"] = 20
	victim4["shield"] = 0
	var endj4 := MatchEngine.apply_command(mine_state4, {"type": "EndActivation"})
	assert_true(bool(endj4.get("ok", false)), "jango ends activation (lateral scenario)")
	var begin_v4 := MatchEngine.apply_command(endj4["state"],
			{"type": "BeginActivation", "ship_instance_id": String(victim4["id"])})
	assert_true(bool(begin_v4.get("ok", false)), "victim begins west of the trigger cell")
	var move_v4 := MatchEngine.apply_command(begin_v4["state"], {"type": "Move", "dir": 2})
	assert_true(bool(move_v4.get("ok", false)), "sideways Move dir 2 accepted")
	assert_eq(_count_event(move_v4["events"], "MineTriggered"), 1,
			"entry from the west flank triggers the mine")
	assert_eq((move_v4["state"]["objects"] as Array).size(), 0, "the mine is consumed")

	# ---------------------------------------------------------------- boba
	section("boba: bomb drift, despawn after 3 shifts")
	var boba := _find_duel(53)
	assert_true(not boba.is_empty(), "boba duel built")
	if boba.is_empty():
		return finish()
	var stbb: Dictionary = boba["state"]
	_set_heroes(stbb, "boba_fett", 1, "boba_fett", 1)
	var beginbb := MatchEngine.apply_command(stbb,
			{"type": "BeginActivation", "ship_instance_id": String(boba["attacker"]["id"])})
	assert_true(bool(beginbb.get("ok", false)), "boba begins activation")
	var placed_bomb := MatchEngine.apply_command(beginbb["state"],
			{"type": "UseHeroAbility", "ability_id": "place_bomb", "dir": 3})
	assert_true(bool(placed_bomb.get("ok", false)), "place_bomb accepted")
	if not bool(placed_bomb.get("ok", false)):
		return finish()
	var placed_ev := _first_event(placed_bomb["events"], "BombPlaced")
	assert_eq(int(placed_ev.get("dir", -1)), 3, "BombPlaced dir")
	var bomb: Dictionary = placed_bomb["state"]["objects"][0]
	assert_eq(int(bomb["moves_left"]), 3, "bomb starts with 3 shifts")
	# First drift at the end of the very activation that placed the bomb.
	var end1 := MatchEngine.apply_command(placed_bomb["state"], {"type": "EndActivation"})
	assert_true(bool(end1.get("ok", false)), "boba ends activation")
	var moved1 := _first_event(end1["events"], "BombMoved")
	assert_eq(int(moved1.get("from_q", 99)), 0, "drift from q")
	assert_eq(int(moved1.get("from_r", 99)), 0, "drift from r")
	assert_eq(int(moved1.get("to_r", 99)), 1, "drift one cell along dir 3 (S)")
	assert_eq(int((end1["state"]["objects"][0] as Dictionary)["moves_left"]), 2,
			"moves_left 3 -> 2")
	# Shifts 2 and 3 happen at the end of the next A1 activations; the third
	# shift disperses the charge (despawn, no explosion).
	var cur: Dictionary = end1["state"]
	var drifts := 1
	var removed := false
	var guard := 0
	while drifts < 3 and guard < 40:
		guard += 1
		var idle := ""
		for s: Dictionary in cur["ships"]:
			if String(s["seat"]) == String(cur["active_seat"]) and bool(s["alive"]) \
					and not bool(s["activated"]):
				idle = String(s["id"])
				break
		if idle.is_empty():
			break
		var b2 := MatchEngine.apply_command(cur,
				{"type": "BeginActivation", "ship_instance_id": idle})
		assert_true(bool(b2.get("ok", false)), "cycle begin %s" % idle)
		cur = b2["state"]
		var is_owner_seat := String(cur["active_seat"]) == "A1"
		var e2 := MatchEngine.apply_command(cur, {"type": "EndActivation"})
		assert_true(bool(e2.get("ok", false)), "cycle end %s" % idle)
		cur = e2["state"]
		if is_owner_seat:
			drifts += 1
		for e: Dictionary in e2["events"]:
			if String(e["type"]) == "ObjectRemoved":
				removed = true
	assert_eq(drifts, 3, "exactly three shifts happened")
	assert_true(removed, "the bomb despawned after the third shift")
	assert_eq((cur["objects"] as Array).size(), 0, "objects empty after despawn")

	section("boba: despawn off the board")
	var stbb2: Dictionary = MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(stbb))
	var b2n := MatchEngine.apply_command(stbb2,
			{"type": "BeginActivation", "ship_instance_id": String(boba["attacker"]["id"])})
	assert_true(bool(b2n.get("ok", false)), "boba begins (edge scenario)")
	_by_id(b2n["state"], String(boba["attacker"]["id"]))["q"] = 0
	_by_id(b2n["state"], String(boba["attacker"]["id"]))["r"] = -3
	var place_north := MatchEngine.apply_command(b2n["state"],
			{"type": "UseHeroAbility", "ability_id": "place_bomb", "dir": 0})
	assert_true(bool(place_north.get("ok", false)), "edge bomb placed")
	var end_north := MatchEngine.apply_command(place_north["state"], {"type": "EndActivation"})
	var off_ev := _first_event(end_north["events"], "ObjectRemoved")
	assert_eq(String(off_ev.get("kind", "")), "bomb", "bomb despawn kind")
	assert_eq(int(off_ev.get("r", 99)), -3, "despawn reported at the last on-board cell")
	assert_true(_first_event(end_north["events"], "BombMoved").is_empty(),
			"no BombMoved for an off-board drift")
	assert_eq((end_north["state"]["objects"] as Array).size(), 0, "objects empty")

	section("boba: explosion in the destination cell, shield first")
	var stbb3: Dictionary = MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(stbb))
	var mate3: Dictionary = _seat_ships(stbb3, "A1")[1]
	mate3["q"] = 0
	mate3["r"] = 1 # directly south of the placing ship: the drift lands here
	mate3["hp"] = 20
	mate3["shield"] = 1
	var b3 := MatchEngine.apply_command(stbb3,
			{"type": "BeginActivation", "ship_instance_id": String(boba["attacker"]["id"])})
	var place_b3 := MatchEngine.apply_command(b3["state"],
			{"type": "UseHeroAbility", "ability_id": "place_bomb", "dir": 3})
	assert_true(bool(place_b3.get("ok", false)), "bomb placed over the mate")
	var end3 := MatchEngine.apply_command(place_b3["state"], {"type": "EndActivation"})
	var ev3: Array = end3["events"]
	var moved3 := _first_event(ev3, "BombMoved")
	assert_eq(int(moved3.get("to_r", 99)), 1, "bomb drifted onto the mate cell")
	var d43 := _first_event(ev3, "DieRolled")
	assert_eq(int(d43.get("sides", 0)), 4, "bomb rolls a d4")
	assert_eq(String(d43.get("role", "")), "effect", "bomb die role effect")
	var dmg3 := _first_event(ev3, "DamageApplied")
	assert_eq(String(dmg3.get("target_id", "")), String(mate3["id"]),
			"explosion hits the ship in the destination cell")
	assert_eq(int(dmg3.get("shield_damage", -1)), mini(1, int(d43["value"])),
			"shield absorbs first")
	var trig3 := _first_event(ev3, "BombTriggered")
	assert_eq(String(trig3.get("target_id", "")), String(mate3["id"]), "BombTriggered target")
	assert_true(not _first_event(ev3, "ObjectRemoved").is_empty(), "bomb removed")
	assert_eq(int(end3["state"]["rng_counter"]), (end3["state"]["dice"] as Array).size(),
			"rng invariant after the bomb blast")

	section("boba: bad_direction")
	var boba_dir := _find_duel(57)
	assert_true(not boba_dir.is_empty(), "boba dir duel built")
	if not boba_dir.is_empty():
		var stbd: Dictionary = boba_dir["state"]
		_set_heroes(stbd, "boba_fett", 1, "boba_fett", 1)
		var beginbd := MatchEngine.apply_command(stbd,
				{"type": "BeginActivation", "ship_instance_id": String(boba_dir["attacker"]["id"])})
		var bad_bomb := MatchEngine.apply_command(beginbd["state"],
				{"type": "UseHeroAbility", "ability_id": "place_bomb", "dir": 6})
		assert_eq(String(bad_bomb.get("error", "")), "bad_direction", "bad_direction code")
		var bad_push := MatchEngine.apply_command(beginbd["state"],
				{"type": "UseHeroAbility", "ability_id": "force_push",
				"ship_instance_id": String(boba_dir["attacker"]["id"]), "dir": 0})
		assert_eq(String(bad_push.get("error", "")), "not_your_hero",
				"boba cannot force_push")

	# ------------------------------------------------- invariants/snapshot
	section("snapshot round-trips with heroes, objects and pending_reaction")
	var snap_duel := _find_duel(23)
	assert_true(not snap_duel.is_empty(), "snapshot duel built")
	if not snap_duel.is_empty():
		var sts: Dictionary = snap_duel["state"]
		_set_heroes(sts, "jango_fett", 1, "obi_wan", 2)
		var begins := MatchEngine.apply_command(sts,
				{"type": "BeginActivation", "ship_instance_id": String(snap_duel["attacker"]["id"])})
		var placed_s := MatchEngine.apply_command(begins["state"],
				{"type": "UseHeroAbility", "ability_id": "place_mine"})
		assert_true(bool(placed_s.get("ok", false)), "mine placed for the snapshot check")
		var with_object: Dictionary = placed_s["state"]
		var restored_obj := MatchEngine.restore_snapshot(MatchEngine.snapshot_bytes(with_object))
		assert_eq(MatchEngine.state_hash(restored_obj), MatchEngine.state_hash(with_object),
				"objects survive a snapshot round-trip")
		var atk_s := MatchEngine.apply_command(with_object,
				{"type": "DeclareAttack", "target_ship_instance_id": String(snap_duel["defender"]["id"])})
		assert_true(bool(atk_s.get("ok", false)), "attack opens the obi_wan window")
		if bool(atk_s.get("ok", false)):
			assert_eq(String(atk_s["state"]["phase"]), "reaction", "window open pre-snapshot")
			var restored_win := MatchEngine.restore_snapshot(
					MatchEngine.snapshot_bytes(atk_s["state"]))
			assert_eq(MatchEngine.state_hash(restored_win), MatchEngine.state_hash(atk_s["state"]),
					"pending_reaction survives a snapshot round-trip")
			var cont_a := MatchEngine.apply_command(atk_s["state"], {"type": "SkipReaction"})
			var cont_b := MatchEngine.apply_command(restored_win, {"type": "SkipReaction"})
			assert_eq(MatchEngine.state_hash(cont_b["state"]),
					MatchEngine.state_hash(cont_a["state"]),
					"restored window continues identically")

	section("wrong-phase guards around the window")
	var guard_duel := _find_duel(23)
	if not guard_duel.is_empty():
		var stg: Dictionary = guard_duel["state"]
		_set_heroes(stg, "luke", 1, "obi_wan", 2)
		var stray_skip := MatchEngine.apply_command(stg, {"type": "SkipReaction"})
		assert_eq(String(stray_skip.get("error", "")), "wrong_phase",
				"SkipReaction without a window rejected")
		var resg := _begin_and_attack(stg, guard_duel["attacker"], guard_duel["defender"])
		if bool(resg.get("ok", false)) and String(resg["state"]["phase"]) == "reaction":
			var wrong := MatchEngine.apply_command(resg["state"], {"type": "EndActivation"})
			assert_eq(String(wrong.get("error", "")), "wrong_phase",
					"activation commands are rejected in a window")
			var resolved := MatchEngine.apply_command(resg["state"], {"type": "SkipReaction"})
			assert_true(bool(resolved.get("ok", false)), "window resolved by skip")

	# -------------------------------------------------------- seeded bots
	section("seeded bots (skip=true): no hero commands, windows auto-skip")
	var bot_factory := func(seat: String, seat_index: int, match_seed: int) -> Variant:
		return RandomLegal.new(RngScript.new(Playout.bot_seed(match_seed, seat_index)))
	for match_seed: int in [1, 42, 5077]:
		var played: Dictionary = Playout.play({"seed": match_seed, "round_limit": 60}, bot_factory)
		assert_true(not played.has("error"), "seed %d: playout finished" % match_seed)
		assert_eq(String(played["state"].get("phase", "")), "ended",
				"seed %d: match ended" % match_seed)
		var hero_cmds := 0
		for cmd: Dictionary in played["commands"]:
			if String(cmd["type"]) == "UseHeroAbility" or String(cmd["type"]) == "SkipReaction":
				hero_cmds += 1
		assert_eq(hero_cmds, 0, "seed %d: bots never send hero commands" % match_seed)
		var window_balance := 0
		for e: Dictionary in played["events"]:
			if String(e["type"]) == "ReactionWindow":
				window_balance += 1
			if String(e["type"]) == "ReactionSkipped":
				window_balance -= 1
		assert_eq(window_balance, 0, "seed %d: every window was auto-skipped" % match_seed)
		assert_true(played["state"]["pending_reaction"] == null,
				"seed %d: no pending window at the end" % match_seed)
		assert_eq(int(played["state"]["rng_counter"]), (played["state"]["dice"] as Array).size(),
				"seed %d: rng invariant over the whole match" % match_seed)
		assert_eq((played["state"]["heroes"] as Dictionary).size(), 2,
				"seed %d: heroes traveled with the state" % match_seed)

	return finish()
