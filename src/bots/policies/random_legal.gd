# BotPolicy (core-api §10). GDScript has no interfaces: the contract is duck
# typing, every bot in src/bots/** honors it:
#
#   func _init(rng) -> void
#       rng: an instance of src/core/rng/rng.gd, injected by the caller.
#       Between matches a NEW Rng with its own seed must be created; the bot
#       seed is part of the run configuration and of the report.
#
#   func choose_action(state: Dictionary, legal: Array) -> Dictionary
#       Returns exactly ONE element of `legal` (the output of
#       MatchEngine.legal_actions). The bot never invents commands and never
#       mutates `state`. During the activation phase `legal` is never empty;
#       if it is empty anyway (terminal state) the bot returns {}.
#
# RandomLegal: uniform random legal action, no other dependencies.
extends RefCounted

const Rng := preload("res://src/core/rng/rng.gd")

var _rng: Rng


func _init(rng: Rng) -> void:
	_rng = rng


func choose_action(_state: Dictionary, legal: Array) -> Dictionary:
	if legal.is_empty():
		return {}
	return legal[_rng.next_below(legal.size())]
