"""Kit params: the dict one step, or the preflight, sends its kit.

A name the kit receives has one of six origins: the point through `params`
(a knob, const or expr, or one element of a profile, split as <p>_0 ..
<p>_{N-1} for a kit that takes no lists), an earlier step's metric through
`params_from`, the study's settings for the kit, the step's `fixed` values,
and the step's stage template as `entry` (a kit of stage templates). The
keys of a setting the kit also receives as params (beamkit's deck_params)
count as names too.

This module is the one place that knows them:
  names()    every name a sender's kit receives, after the split, with every
             origin that produces it;
  problems() the rules on those names, run when a study loads;
  build()    the values at one point, one per name.

The rules (ADR-0003):
  1. One origin per name. Nothing overrides anything.
  2. A mapping (`params`, `params_from`) may not name what the kit reads
     itself (KitDecl.own_params, KitDecl.reserved_params), and must match
     the kit's name pattern when it has one.
  3. No '${...}' or personal user area inside a nested value
     (refuse_nested_paths, beside expand_artifact).

`study` is duck-typed: names() and problems() read `steps`, `preflight`,
`kits` and `profile_counts`; build() also reads `entry_template(step)` for a
kit of stage templates. Every fact about a kit comes from
kit_registry.KITS (a KeyError for an undeclared kit).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import kit_registry
import paths

ARTIFACT_TOKEN = "${ARTIFACT}/"
_PERSONAL = re.compile(r"^/exp/mu2e/(app|data)/users/[^/]+/")


def expand_artifact(value, where):
    """Only '${ARTIFACT}/' is supported; a bare personal user area is
    refused (it would run only for that account)."""
    if not isinstance(value, str):
        return value
    if value.startswith(ARTIFACT_TOKEN):
        return str(paths.artifact(value[len(ARTIFACT_TOKEN):]))
    if "${" in value:
        raise ValueError(f"{where}: unknown variable in {value!r}; the only "
                         f"supported token is '${{ARTIFACT}}/'")
    if _PERSONAL.match(value):
        raise ValueError(f"{where}: {value!r} hardcodes a personal user "
                         f"area; use '${{ARTIFACT}}/<rest-of-path>'")
    return value


def refuse_nested_paths(value, where) -> None:
    """Rule 3: a string nested inside a dict or list value may not hold
    '${' or a personal user area. Such a value is sent as it is, so an
    expanded local path would not exist on a grid worker; '${ARTIFACT}/'
    and user areas are allowed only as a whole setting or fixed value, which
    expand_artifact handles. A top-level string is not checked here."""
    def walk(v, path):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}[{k}]")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
        elif isinstance(v, str) and ("${" in v or _PERSONAL.match(v)):
            raise ValueError(
                f"{where}{path}: {v!r} is a path inside a nested value; "
                f"'${{ARTIFACT}}/' and user areas are allowed only as a "
                f"whole setting or fixed value")

    if isinstance(value, (dict, list)):
        walk(value, "")


@dataclass(frozen=True)
class Origin:
    kind: str              # "point" | "profile" | "params_from" | "setting"
                           # | "fixed" | "entry"
    ref: str               # the JSON key under the sender that produced it:
                           # "params.R", "params_from.r",
                           # "kits.toykit.function", "fixed.n", "entry"
    source: Optional[str]  # the knob/const/expr/profile name, or
                           # "<step>.<metric>"; None otherwise
    index: Optional[int]   # the profile element; None when not split


@dataclass(frozen=True)
class Sender:
    label: str                 # "step 'sob'" | "preflight"
    at: str                    # "evaluate.sob" | "preflight"
    kit: str
    params: Dict[str, str]
    params_from: Dict[str, str]    # {} for the preflight
    fixed: Dict[str, Any]          # {} for the preflight
    step: Optional[str]            # None for the preflight


def sender_of(step) -> Sender:
    return Sender(f"step {step.step!r}", f"evaluate.{step.step}", step.kit,
                  dict(step.params), dict(step.params_from), dict(step.fixed),
                  step.step)


def preflight_sender(study) -> Sender:
    pre = study.preflight
    if pre is None:
        raise ValueError("the study has no preflight")
    return Sender("preflight", "preflight", pre["kit"], dict(pre["params"]),
                  {}, {}, None)


def senders(study) -> Tuple[Sender, ...]:
    """The steps in order, then the preflight."""
    out = [sender_of(s) for s in study.steps]
    if study.preflight is not None:
        out.append(preflight_sender(study))
    return tuple(out)


def names(study, sender) -> Dict[str, Tuple[Origin, ...]]:
    """Every top-level name `sender`'s kit receives, with every origin that
    produces it, in the order the kit receives them: the params (a profile
    split in place unless the kit takes lists), params_from by name, the
    kit's settings, the fixed values, then entry. A clean study has one
    origin per name."""
    decl = kit_registry.KITS[sender.kit]
    counts = study.profile_counts
    out: Dict[str, List[Origin]] = {}

    def add(name, origin):
        out.setdefault(name, []).append(origin)

    for key, source in sender.params.items():
        ref = f"params.{key}"
        if source not in counts:
            add(key, Origin("point", ref, source, None))
        elif decl.accepts_lists:
            add(key, Origin("profile", ref, source, None))
        else:
            for i in range(counts[source]):
                add(f"{key}_{i}", Origin("profile", ref, source, i))
    for key in sorted(sender.params_from):
        add(key, Origin("params_from", f"params_from.{key}",
                        sender.params_from[key], None))
    for key in study.kits.get(sender.kit, {}):
        add(key, Origin("setting", f"kits.{sender.kit}.{key}", None, None))
    for key in sender.fixed:
        add(key, Origin("fixed", f"fixed.{key}", None, None))
    if decl.uses_entries and sender.step is not None:
        add("entry", Origin("entry", "entry", None, None))
    return {name: tuple(origins) for name, origins in out.items()}


def _says(o: Origin) -> str:
    """One origin in words, for a refusal."""
    if o.kind == "profile" and o.index is not None:
        return f"profile {o.source!r} element {o.index} ({o.ref})"
    if o.kind in ("point", "profile", "params_from"):
        return f"{o.ref} = {o.source!r}"
    if o.kind == "entry":
        return "the stage template (entry)"
    return o.ref        # a setting, a fixed value, a key inside a setting


def _clashes(study, sender, found) -> List[str]:
    """Rule 1 for one sender: every name with more than one origin,
    counting the keys of the kit's inner-params setting."""
    decl = kit_registry.KITS[sender.kit]
    inner = {}
    if decl.inner_params_setting is not None:
        value = study.kits.get(sender.kit, {}).get(decl.inner_params_setting)
        if isinstance(value, dict):
            inner = value
    out = []
    for name, origins in found.items():
        if name in inner:
            origins = origins + (Origin(
                "inner", f"kits.{sender.kit}.{decl.inner_params_setting}."
                f"{name}", None, None),)
        if len(origins) > 1:
            first, rest = origins[0], origins[1:]
            out.append(f"[{sender.at}.{first.ref}]: {_says(first)} sends "
                       f"{name!r}, also sent by "
                       f"{', '.join(_says(o) for o in rest)}; a param the "
                       f"kit receives has exactly one source")
    return out


def problems(study) -> List[str]:
    """Every broken rule, per sender: rule 1, then rule 2, then the name
    pattern. The loader raises the first, prefixed with the file path."""
    out: List[str] = []
    for sender in senders(study):
        decl = kit_registry.KITS[sender.kit]
        out += _clashes(study, sender, names(study, sender))
        banned = set(decl.own_params) | set(decl.reserved_params)
        for part in ("params", "params_from"):
            for key in getattr(sender, part):
                if key in banned:
                    out.append(f"[{sender.at}.{part}.{key}]: a {sender.kit} "
                               f"setting, not a param to map; kit "
                               f"{sender.kit!r} or its worker sets it itself")
        if decl.param_name_pattern is not None:
            for part in ("params", "params_from"):
                bad = sorted(k for k in getattr(sender, part)
                             if not decl.param_name_pattern.fullmatch(k))
                if bad:
                    out.append(f"[{sender.at}.{part}]: {bad} cannot be "
                               f"{sender.kit} param names (letters, digits "
                               f"and _)")
    return out


def _metric(param, source, upstream) -> float:
    """The params_from value: the metric of an earlier step, read from that
    step's record as it is. A missing metric, or one that is not a finite
    number, is a ValueError: there is no default."""
    up, key = source.split(".", 1)
    metrics = upstream[up]["metrics"]
    if key not in metrics:
        raise ValueError(f"params_from {param}={source!r}: step {up!r} "
                         f"returned no metric {key!r} (it returned "
                         f"{sorted(metrics)})")
    value = metrics[key]
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError(f"params_from {param}={source!r}: step {up!r} "
                         f"returned {value!r}, not a finite number")
    return value


def build(study, sender, env, upstream) -> Dict[str, Any]:
    """The params `sender` sends at one point: `env` is the point's derived
    values, `upstream` {step: its record} (empty for the preflight). Each
    name's one origin is resolved, in names() order. A name with two
    origins is refused here too, so a study that skipped the loader cannot
    send an ambiguous value. A missing knob (KeyError) or a bad params_from
    metric (ValueError) fails the step, as before."""
    found = names(study, sender)
    clashes = _clashes(study, sender, found)
    if clashes:
        raise ValueError(f"{sender.label}: {clashes[0]}")
    out: Dict[str, Any] = {}
    for name, (o,) in found.items():
        if o.kind == "point":
            out[name] = env[o.source]
        elif o.kind == "profile":
            value = env[o.source]
            out[name] = list(value) if o.index is None else value[o.index]
        elif o.kind == "params_from":
            out[name] = _metric(name, o.source, upstream)
        elif o.kind == "setting":
            out[name] = study.kits[sender.kit][name]
        elif o.kind == "fixed":
            out[name] = expand_artifact(sender.fixed[name],
                                        f"{sender.label} fixed[{name}]")
        else:
            out[name] = study.entry_template(sender.step)
    return out


def kit_names(study, kit: str) -> FrozenSet[str]:
    """Every name the kit receives from any of the study's senders."""
    return frozenset(name for sender in senders(study) if sender.kit == kit
                     for name in names(study, sender))
