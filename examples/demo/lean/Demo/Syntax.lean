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
  | lit : Nat → AExp
  | var : Var → AExp
  | add : AExp → AExp → AExp
  deriving Repr

/-- The free variables of an expression, read off its syntax.  Listed rather
than a set, so that no order structure has to be imported for it. -/
def AExp.fv : AExp → List Var
  | .lit _ => []
  | .var x => [x]
  | .add a b => a.fv ++ b.fv

/-- Boolean expressions: paper:def:bexp.  `BExp.tt` is the paper's `true`;
the name avoids the reserved one. -/
inductive BExp where
  | tt : BExp
  | le : AExp → AExp → BExp
  | not : BExp → BExp
  | and : BExp → BExp → BExp
  deriving Repr

/-- Commands: paper:def:cmd.

`whileDo` and `ite` rather than `while` and `if` because both of the obvious
names are reserved tokens in Lean 4. -/
inductive Cmd where
  | skip : Cmd
  | assign : Var → AExp → Cmd
  | seq : Cmd → Cmd → Cmd
  | ite : BExp → Cmd → Cmd → Cmd
  | whileDo : BExp → Cmd → Cmd
  deriving Repr

/-- A procedure declaration, in the sense of note, def:proc: formal parameters
and a body, and nothing else.

The core language of the paper has no call construct at all
(note, rem:no-calls), so this type is declared and never eliminated.  It is
here because the note's frame discipline is what the rest of the development
uses, and a declaration is what that discipline is about. -/
structure Proc where
  params : List Var
  body : Cmd

end Demo
