import Demo.Syntax

/-!
# Semantics

Expression evaluation (paper:def:aeval) and the big-step relation
(paper:def:bigstep), plus the one frame property the paper's Hoare logic
borrows from the note.

Determinism of the big-step relation — the paper states it — is *not* here.
That is deliberate: a formalization is never finished, and a coverage view
that shows every paper item as green is a view with nothing to say.
-/

namespace Demo

/-- Evaluation of arithmetic expressions: clause 1 of the paper's definition,
paper:def:aeval:arith.  Total, because an expression has no side effect and cannot
fail. -/
def AExp.eval : AExp → Store → Nat
  | .lit n, _ => n
  | .var x, s => s x
  | .add a b, s => a.eval s + b.eval s

/-- Evaluation of boolean expressions — the other half, paper:def:aeval:bool.
The trailing dot there is sentence punctuation and not part of the clause. -/
def BExp.eval : BExp → Store → Bool
  | .tt, _ => true
  | .le a b, s => decide (a.eval s ≤ b.eval s)
  | .not b, s => !(b.eval s)
  | .and b c, s => b.eval s && c.eval s

/-- An expression only sees its own free variables: note, prop:agree-eval.

The note proves this for the paper's expressions, which is why the statement
lives in the note and the proof lives in the module that has both halves. -/
theorem AExp.eval_congr {s t : Store} :
    ∀ a : AExp, AgreeOn a.fv s t → a.eval s = a.eval t
  | .lit _, _ => rfl
  | .var x, h => h x (by simp [AExp.fv])
  | .add a b, h => by
      have ha : a.eval s = a.eval t := by
        refine AExp.eval_congr a ?_
        intro x hx
        exact h x (by simp [AExp.fv, hx])
      have hb : b.eval s = b.eval t := by
        refine AExp.eval_congr b ?_
        intro x hx
        exact h x (by simp [AExp.fv, hx])
      simp [AExp.eval, ha, hb]

/-! ## Big-step evaluation -/

/-- The big-step relation of paper:def:bigstep: `BigStep c s t` is the paper's
`⟨c, σ⟩ ⇓ τ`.  Non-termination is the absence of a derivation, which is all
partial correctness needs. -/
inductive BigStep : Cmd → Store → Store → Prop where
  | skip (s : Store) : BigStep Cmd.skip s s
  | assign (s : Store) (x : Var) (a : AExp) :
      BigStep (Cmd.assign x a) s (Store.update s x (a.eval s))
  | seq {c₁ c₂ : Cmd} {s t u : Store} :
      BigStep c₁ s t → BigStep c₂ t u → BigStep (Cmd.seq c₁ c₂) s u
  | iteTrue {b : BExp} {c₁ c₂ : Cmd} {s t : Store} :
      b.eval s = true → BigStep c₁ s t → BigStep (Cmd.ite b c₁ c₂) s t
  | iteFalse {b : BExp} {c₁ c₂ : Cmd} {s t : Store} :
      b.eval s = false → BigStep c₂ s t → BigStep (Cmd.ite b c₁ c₂) s t
  | whileFalse {b : BExp} {c : Cmd} {s : Store} :
      b.eval s = false → BigStep (Cmd.whileDo b c) s s
  | whileTrue {b : BExp} {c : Cmd} {s t u : Store} :
      b.eval s = true → BigStep c s t → BigStep (Cmd.whileDo b c) t u →
      BigStep (Cmd.whileDo b c) s u

section Examples

variable (x : Var) (a : AExp)

/-- An assignment run, spelled out: the store afterwards is the note's update
(note, def:update) at the value the expression takes beforehand. -/
theorem bigStep_assign_eq (s : Store) :
    BigStep (Cmd.assign x a) s (Store.update s x (a.eval s)) :=
  BigStep.assign s x a

end Examples

open BigStep in
/-- Two skips are one.  Written with the constructors unqualified, which is
what the `open ... in` above buys. -/
theorem bigStep_seq_skip (s : Store) :
    BigStep (Cmd.seq Cmd.skip Cmd.skip) s s :=
  seq (skip s) (skip s)

end Demo
