import Demo.Store

/-!
# Syntax of the toy language

The grammars of paper:sec:syntax, one inductive per production.  The paper
gives three of them (paper:def:aexp, paper:def:bexp, paper:def:cmd); the fourth
declaration here belongs to the note instead.

This module imports `Demo.Store` only for `Var`, which is enough to put it
*after* `Store` in import order and *last* alphabetically — the two orders
disagree about every module in this development, which is why the viewer does
not use the alphabetical one.
-/

namespace Demo

/-- Arithmetic expressions: paper:def:aexp. -/
inductive AExp where
  /-- paper:def:aexp:lit. -/
  | lit : Nat → AExp
  /-- paper:def:aexp:var. -/
  | var : Var → AExp
  /-- paper:def:aexp:add. -/
  | add : AExp → AExp → AExp
  deriving Repr

/-- The free variables of an expression, read off its syntax:
paper:def:aexp:fv, the one sentence of that definition that is not the
grammar.  Listed rather than a set, so that no order structure has to be
imported for it. -/
def AExp.fv : AExp → List Var
  | .lit _ => []
  | .var x => [x]
  | .add a b => a.fv ++ b.fv

/-- Boolean expressions: paper:def:bexp.  `BExp.tt` is the paper's `true`;
the name avoids the reserved one. -/
inductive BExp where
  /-- paper:def:bexp:tt -/
  | tt : BExp
  /-- paper:def:bexp:le -/
  | le : AExp → AExp → BExp
  /-- paper:def:bexp:not -/
  | not : BExp → BExp
  /-- paper:def:bexp:and -/
  | and : BExp → BExp → BExp
  deriving Repr

/-- Commands: paper:def:cmd.

`whileDo` and `ite` rather than `while` and `if` because both of the obvious
names are reserved tokens in Lean 4. -/
inductive Cmd where
  /-- paper:def:cmd:skip -/
  | skip : Cmd
  /-- paper:def:cmd:assign -/
  | assign : Var → AExp → Cmd
  /-- paper:def:cmd:seq -/
  | seq : Cmd → Cmd → Cmd
  /-- paper:def:cmd:ite -/
  | ite : BExp → Cmd → Cmd → Cmd
  /-- The loop: paper:def:cmd:while.  The band on the left is that production
  alone — the paper's grammar sets all five on one typeset line, so the
  rectangle comes from the marked build rather than from SyncTeX.  The band on
  the right is this constructor, not the datatype: a docstring on a member
  belongs to the member. -/
  | whileDo : BExp → Cmd → Cmd
  deriving Repr

/-- A procedure declaration, in the sense of note, def:proc: formal parameters
and a body, and nothing else.

The core language of the paper has no call construct at all
(note, rem:no-calls), so this type is declared and never eliminated.  It is
here because the note's frame discipline is what the rest of the development
uses, and a declaration is what that discipline is about. -/
structure Proc where
  /-- The formal parameters — the `x⃗` of note, def:proc:params.  The note
  carries no anchor by that name, so the path peels to the statement with
  `params` recorded: it links today, and sharpens by itself the day the note
  is annotated, with no edit here. -/
  params : List Var
  /-- The body — the `c` of note, def:proc:body.  Peels the same way. -/
  body : Cmd

end Demo
